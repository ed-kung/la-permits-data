"""Data repair for Anaheim (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Anaheim DATA is an Accela Citizen Access scrape. Nearly all rows share
the same top-level keys (``status``, ``date``, ``tasks``, ``inspections``,
``more_details``, ``search_data``, …). Content variants (used as
INFERRED_SCHEMA) differ by which dated workflow events are present:

  - accela_tasks_full:   Permit Issuance / Issued plus a finalization
                         event (Final Inspection Complete, Final CO,
                         Closure / Closed, Closed - Picked Up)
  - accela_tasks_issued: Issued event present; no finalization event
  - accela_tasks:        other dated task events only
  - accela_shell:        tasks present but no dated events
  - accela_partial:      missing inspections / conditions / fees_details
  - unknown / missing

Canonical mappings:
  - DATA.status (else Issued / Finaled task marks) → STATUS_NORMALIZED
  - DATA.date / search_data['Application Date']    → FILE_DATE
  - Permit Issuance / Issued; else (Approved only)
    Closure / Closed                               → PERMIT_DATE
  - Inspection(s) / Final Inspection Complete;
    Certificate of Occupancy / Final CO Issued;
    Closure / Closed; Revision Status /
    Closed - Picked Up                             → FINAL_DATE

Known issues repaired:
  - STATUS_NORMALIZED was derived from STATUS_ORIGINAL (portal search
    status), which is stale vs DATA.status on ~14 rows (e.g. Finaled
    labeled Active; Issued / Approved labeled In Review). Remap from
    DATA.status. Fill 2 null statuses (Issued → Active; PAD → In Review).
  - PERMIT_DATE missing for Issued / Approved Active rows that have an
    Issued event or Closure / Closed approval close → FILLED.
  - FINAL_DATE missing for Final / Finaled rows with finalization events
    (including 9 Finaled-as-Active rows after status FIX) → FILLED.
  - A few FINAL_DATE values disagree with the latest finalization event
    by 1–several days → FIXED.

Not repairable / left as-is:
  - FILE_DATE already matches DATA.date / Application Date for all
    sample rows.
  - Most legacy Finaled / Closed shells lack Issued or finalization
    events → PERMIT_DATE / FINAL_DATE stay missing.
  - Development Project / Planning Approved rows without Closure or
    Issued events have no approval date in DATA → PERMIT_DATE stays
    missing.
"""

from __future__ import annotations

import json
import math
from typing import Optional

import numpy as np
import pandas as pd


# ── Helpers ──────────────────────────────────────────────────────────────────

def _is_missing(data) -> bool:
    if data is None:
        return True
    if isinstance(data, float) and math.isnan(data):
        return True
    return False


def _safe_parse(data) -> Optional[dict]:
    if _is_missing(data):
        return None
    if isinstance(data, str):
        return json.loads(data)
    return data


def _safe_to_datetime(val):
    """Parse a date value, returning pd.NaT on failure."""
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return pd.NaT
    if isinstance(val, str) and not str(val).strip():
        return pd.NaT
    if isinstance(val, str) and val.strip().upper() == "TBD":
        return pd.NaT
    try:
        dt = pd.to_datetime(val)
    except (ValueError, TypeError):
        return pd.NaT
    if dt is pd.NaT or pd.isna(dt):
        return pd.NaT
    if getattr(dt, "tzinfo", None) is not None:
        dt = dt.tz_convert("UTC").tz_localize(None)
    return dt


def _dates_equal(a, b) -> bool:
    """Compare two datelike values at calendar-day resolution."""
    da = _safe_to_datetime(a)
    db = _safe_to_datetime(b)
    if da is pd.NaT or db is pd.NaT:
        return False
    return da.normalize() == db.normalize()


def _event_field(event: dict, *names: str):
    """Read an event field, tolerating leading/trailing spaces in keys."""
    targets = {n.strip() for n in names}
    for k, v in event.items():
        if isinstance(k, str) and k.strip() in targets:
            return v
    return None


def _iter_tasks(tasks: list):
    for t in tasks or []:
        if not isinstance(t, dict):
            continue
        yield t
        for st in t.get("subtasks") or []:
            if isinstance(st, dict):
                yield st


def _event_dates(tasks: list, task_names, marked_as):
    """Collect event dates for matching task name(s) and Marked-as value(s)."""
    if isinstance(task_names, str):
        task_names = {task_names}
    if isinstance(marked_as, str):
        marked_as = {marked_as}
    dates = []
    for t in _iter_tasks(tasks):
        if t.get("name") not in task_names:
            continue
        for e in t.get("events") or []:
            if not isinstance(e, dict):
                continue
            marked = _event_field(e, "Marked as")
            if marked not in marked_as:
                continue
            dt = _safe_to_datetime(_event_field(e, "on"))
            if dt is not pd.NaT:
                dates.append(dt)
    return dates


def _first_event_date(tasks: list, task_names, marked_as):
    dates = _event_dates(tasks, task_names, marked_as)
    return min(dates) if dates else pd.NaT


def _latest_event_date(tasks: list, task_names, marked_as):
    dates = _event_dates(tasks, task_names, marked_as)
    return max(dates) if dates else pd.NaT


def _all_marked_as(tasks: list) -> set:
    marks = set()
    for t in _iter_tasks(tasks):
        for e in t.get("events") or []:
            if isinstance(e, dict):
                m = _event_field(e, "Marked as")
                if m:
                    marks.add(m)
    return marks


def _has_dated_events(d: dict) -> bool:
    for t in _iter_tasks(d.get("tasks") or []):
        for e in t.get("events") or []:
            if not isinstance(e, dict):
                continue
            if _safe_to_datetime(_event_field(e, "on")) is not pd.NaT:
                return True
    return False


def _has_issued_event(d: dict) -> bool:
    return _first_event_date(
        d.get("tasks") or [], "Permit Issuance", "Issued"
    ) is not pd.NaT


def _has_finalization_event(d: dict) -> bool:
    return _final_date_from_data(d) is not pd.NaT


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())
    if "tasks" not in keys or "status" not in keys:
        return "unknown"

    partial_missing = not {"inspections", "conditions", "fees_details"} <= keys
    if partial_missing:
        return "accela_partial"

    has_events = _has_dated_events(data_dict)
    if not has_events:
        return "accela_shell"

    has_issued = _has_issued_event(data_dict)
    has_final = _has_finalization_event(data_dict)
    if has_issued and has_final:
        return "accela_tasks_full"
    if has_issued:
        return "accela_tasks_issued"
    return "accela_tasks"


# ── Status mapping ──────────────────────────────────────────────────────────

_STATUS_MAP = {
    # Final
    "Finaled": "Final",
    "Closed": "Final",
    "Case Closed": "Final",
    "Complete": "Final",
    "Adopted": "Final",
    # Active — issued / approved
    "Issued": "Active",
    "Approved": "Active",
    # In Review — application / plan check / pre-issuance
    "Plan Review": "In Review",
    "Received": "In Review",
    "In Review": "In Review",
    "Ready to Issue": "In Review",
    "On Hold": "In Review",
    "Incomplete Submittal": "In Review",
    "PAD": "In Review",
    # Inactive
    "Expired": "Inactive",
    "Terminated": "Inactive",
}


def _expected_status(d: dict) -> Optional[str]:
    """Map DATA.status → STATUS_NORMALIZED; fall back to task marks."""
    raw = d.get("status")
    if isinstance(raw, str) and raw.strip():
        mapped = _STATUS_MAP.get(raw.strip())
        if mapped is not None:
            return mapped

    marks = _all_marked_as(d.get("tasks") or [])
    if "Final Inspection Complete" in marks or "Final CO Issued" in marks:
        return "Final"
    if "Closed" in marks or "Closed - Picked Up" in marks:
        return "Final"
    if "Issued" in marks:
        return "Active"
    if marks:
        return "In Review"
    return None


def _file_date_from_data(d: dict):
    file_date = _safe_to_datetime(d.get("date"))
    if file_date is not pd.NaT:
        return file_date
    sd = d.get("search_data")
    if isinstance(sd, dict):
        return _safe_to_datetime(sd.get("Application Date"))
    return pd.NaT


def _issued_date(tasks: list):
    """Earliest Permit Issuance / Issued date."""
    return _first_event_date(tasks, "Permit Issuance", "Issued")


def _approval_date(tasks: list):
    """Planning / entitlement approval close date (no building issuance)."""
    closed = _latest_event_date(tasks, "Closure", "Closed")
    if closed is not pd.NaT:
        return closed
    completed = _latest_event_date(tasks, "Review Coordination", "Completed")
    if completed is not pd.NaT:
        return completed
    return pd.NaT


def _permit_date_from_data(d: dict):
    tasks = d.get("tasks") or []
    issued = _issued_date(tasks)
    if issued is not pd.NaT:
        return issued
    # Approved entitlements often close without a Permit Issuance task.
    if d.get("status") == "Approved":
        return _approval_date(tasks)
    return pd.NaT


def _final_date_from_data(d: dict):
    """Best available finaling / closure / sign-off date."""
    tasks = d.get("tasks") or []
    candidates = []

    for task_names, marks in (
        ({"Inspection", "Inspections"}, {"Final Inspection Complete"}),
        ({"Certificate of Occupancy"}, {"Final CO Issued"}),
        ({"Closure"}, {"Closed"}),
        ({"Revision Status"}, {"Closed - Picked Up"}),
    ):
        dt = _latest_event_date(tasks, task_names, marks)
        if dt is not pd.NaT:
            candidates.append(dt)

    return max(candidates) if candidates else pd.NaT


# ── Repair logic ────────────────────────────────────────────────────────────

def _repair_record(row, d: dict, repairs: dict):
    # -- STATUS_NORMALIZED --
    current_status = row["STATUS_NORMALIZED"]
    expected = _expected_status(d)
    if expected is not None:
        if pd.isna(current_status):
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"
        elif current_status != expected:
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FIXED"

    effective_status = repairs.get("STATUS_NORMALIZED", current_status)

    # -- FILE_DATE --
    file_date = _file_date_from_data(d)
    if file_date is not pd.NaT:
        if pd.isna(row["FILE_DATE"]):
            repairs["FILE_DATE"] = file_date
            repairs["FILE_DATE_FLAG"] = "FILLED"
        elif not _dates_equal(row["FILE_DATE"], file_date):
            repairs["FILE_DATE"] = file_date
            repairs["FILE_DATE_FLAG"] = "FIXED"

    # -- PERMIT_DATE --
    permit_date = _permit_date_from_data(d)
    if permit_date is not pd.NaT:
        if pd.isna(row["PERMIT_DATE"]):
            if effective_status in ("Active", "Final"):
                repairs["PERMIT_DATE"] = permit_date
                repairs["PERMIT_DATE_FLAG"] = "FILLED"
        elif not _dates_equal(row["PERMIT_DATE"], permit_date):
            # Only overwrite when we have a clear Issued date that disagrees.
            issued = _issued_date(d.get("tasks") or [])
            if issued is not pd.NaT and _dates_equal(permit_date, issued):
                repairs["PERMIT_DATE"] = permit_date
                repairs["PERMIT_DATE_FLAG"] = "FIXED"

    # -- FINAL_DATE --
    if effective_status == "Final":
        final_date = _final_date_from_data(d)
        if final_date is not pd.NaT:
            if pd.isna(row["FINAL_DATE"]):
                repairs["FINAL_DATE"] = final_date
                repairs["FINAL_DATE_FLAG"] = "FILLED"
            elif not _dates_equal(row["FINAL_DATE"], final_date):
                repairs["FINAL_DATE"] = final_date
                repairs["FINAL_DATE_FLAG"] = "FIXED"
    elif not pd.isna(row["FINAL_DATE"]):
        repairs["FINAL_DATE"] = pd.NaT
        repairs["FINAL_DATE_FLAG"] = "FIXED"


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Anaheim permit records using information from the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Anaheim".  Must contain
        columns STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, FINAL_DATE,
        and DATA.

    Returns
    -------
    pd.DataFrame
        Copy of *df* with corrected field values, an INFERRED_SCHEMA column
        naming the DATA JSON sub-schema identified for each record, and new
        flag columns: STATUS_NORMALIZED_FLAG, FILE_DATE_FLAG,
        PERMIT_DATE_FLAG, FINAL_DATE_FLAG.  Flag values are "FILLED"
        (was missing, now populated) or "FIXED" (had an incorrect value,
        now corrected).
    """
    out = df.copy()

    flag_cols = [
        "STATUS_NORMALIZED_FLAG",
        "FILE_DATE_FLAG",
        "PERMIT_DATE_FLAG",
        "FINAL_DATE_FLAG",
    ]
    for col in flag_cols:
        out[col] = pd.Series(np.nan, index=out.index, dtype=object)
    out["INFERRED_SCHEMA"] = pd.Series(np.nan, index=out.index, dtype=object)

    for idx in out.index:
        row = out.loc[idx]
        d = _safe_parse(row["DATA"])
        schema = _classify_schema(d)
        out.at[idx, "INFERRED_SCHEMA"] = schema
        if d is None:
            continue

        repairs: dict = {}
        _repair_record(row, d, repairs)

        for key, value in repairs.items():
            out.at[idx, key] = value

    return out


# ── CLI: run standalone to preview repair stats ─────────────────────────────

if __name__ == "__main__":
    import os
    from dotenv import load_dotenv, find_dotenv

    load_dotenv(find_dotenv())
    MY_DATA_PATH = os.getenv("MY_DATA_PATH")
    filepath = os.path.join(
        MY_DATA_PATH, "processed_data", "permits_ca_sample.parquet"
    )
    df = pd.read_parquet(filepath)
    city = df[df["JURISDICTION"] == "Anaheim"].copy()

    print(f"Anaheim records: {len(city):,}\n")

    repaired = data_repair(city)

    print("INFERRED_SCHEMA:")
    for s, c in repaired["INFERRED_SCHEMA"].value_counts(dropna=False).items():
        print(f"  {str(s):30s}: {c:>4,}")
    print()

    for field in ["STATUS_NORMALIZED", "FILE_DATE", "PERMIT_DATE", "FINAL_DATE"]:
        flag_col = f"{field}_FLAG"
        n_filled = (repaired[flag_col] == "FILLED").sum()
        n_fixed = (repaired[flag_col] == "FIXED").sum()
        print(f"{field}:")
        print(f"  FILLED: {n_filled:>4,}   FIXED: {n_fixed:>4,}")

        before_missing = city[field].isna().sum()
        after_missing = repaired[field].isna().sum()
        print(
            f"  Missing before: {before_missing:>4,}   "
            f"Missing after: {after_missing:>4,}"
        )
        print()

    print("STATUS_NORMALIZED distribution:")
    print("  Before:")
    for s, c in city["STATUS_NORMALIZED"].value_counts(dropna=False).items():
        print(f"    {str(s):15s}: {c:>4,}")
    print("  After:")
    for s, c in repaired["STATUS_NORMALIZED"].value_counts(dropna=False).items():
        print(f"    {str(s):15s}: {c:>4,}")

    print("\nPERMIT_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["PERMIT_DATE"].notna().sum()
        pct = n_has / len(sub) if len(sub) else 0.0
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({pct:.1%})")

    print("\nFINAL_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FINAL_DATE"].notna().sum()
        pct = n_has / len(sub) if len(sub) else 0.0
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({pct:.1%})")

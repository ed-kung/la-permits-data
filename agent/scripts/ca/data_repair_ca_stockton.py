"""Data repair for Stockton (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Stockton DATA is an Accela Citizen Access scrape. Nearly all rows share
the same top-level keys (``status``, ``date``, ``tasks``, ``inspections``,
``more_details``, ``search_data``, …). Content variants (used as
INFERRED_SCHEMA) differ by which date sources are populated:

  - accela_tasks:            dated workflow events under ``tasks``
  - accela_tasks_and_master: task events plus legacy ``PERMIT MASTER``
                             fields in ``more_details``
  - accela_legacy_master:    empty task shells; dates only in
                             ``PERMIT MASTER`` (pre-~2015 migrations)
  - accela_shell:            tasks present but no dated events and no
                             usable PERMIT MASTER dates
  - accela_partial:          missing inspections / conditions / fees keys
  - unknown / missing

Canonical mappings:
  - DATA.status (else task Marked-as)     → STATUS_NORMALIZED
  - DATA.date / search_data['Date']       → FILE_DATE
  - Ready to Issue|Application Review|
    Application Submittal / Issued|
    Re-Issued; else PERMIT MASTER
    Permit Issue Date / Last Reissue Date → PERMIT_DATE
  - Inspections / Finaled; Closed / Closed;
    else PERMIT MASTER Permit Status Date → FINAL_DATE

Known issues repaired:
  - Estimate / expired / Finaled / Issued / etc. mis-normalized statuses
    (~28 FIXED) and 5 null-status Over Time Inspection Request rows
    FILLED from task marks (Approved → Active, Void → Inactive).
  - PERMIT_DATE missing for most Active/Final rows despite Issued events
    or PERMIT MASTER Issue / Reissue dates → FILLED.
  - FINAL_DATE missing for Final rows with Finaled / Closed events or
    legacy Permit Status Date → FILLED.
  - Spurious FINAL_DATE on Active (Issued / Final Pending) rows → cleared.

Not repairable / left as-is:
  - FILE_DATE already matches DATA.date for all sample rows.
  - Hundreds of legacy Finaled shells have empty task events and no
    PERMIT MASTER dates → PERMIT_DATE / FINAL_DATE stay missing.
  - Finaled rows whose only completion mark is Inspections / Final
    Pending keep the existing FINAL_DATE (best available proxy; no
    Finaled event or Status Date).
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


def _walk_leaves(obj, path: str = ""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _walk_leaves(v, f"{path}.{k}" if path else str(k))
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk_leaves(v, f"{path}[]")
    else:
        yield path, obj


def _more_details_field(d: dict, field_substr: str):
    """First non-empty more_details leaf whose path contains *field_substr*."""
    md = d.get("more_details")
    if not isinstance(md, dict):
        return None
    needle = field_substr.lower()
    for path, val in _walk_leaves(md):
        if needle not in path.lower():
            continue
        if val is None:
            continue
        if isinstance(val, str) and not val.strip():
            continue
        return val
    return None


def _has_permit_master_dates(d: dict) -> bool:
    for field in (
        "Permit Issue Date",
        "Permit Last Reissue Date",
        "Permit Status Date",
    ):
        if _more_details_field(d, field) is not None:
            return True
    return False


def _has_dated_events(d: dict) -> bool:
    for t in _iter_tasks(d.get("tasks") or []):
        for e in t.get("events") or []:
            if not isinstance(e, dict):
                continue
            if _safe_to_datetime(_event_field(e, "on")) is not pd.NaT:
                return True
    return False


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())
    if "tasks" not in keys or "status" not in keys:
        return "unknown"

    partial_missing = not {"inspections", "conditions", "fees_details"} <= keys
    has_events = _has_dated_events(data_dict)
    has_master = _has_permit_master_dates(data_dict)

    if partial_missing:
        return "accela_partial"
    if has_events and has_master:
        return "accela_tasks_and_master"
    if has_events:
        return "accela_tasks"
    if has_master:
        return "accela_legacy_master"
    return "accela_shell"


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


# ── Status mapping ──────────────────────────────────────────────────────────

_STATUS_MAP = {
    # Final
    "Finaled": "Final",
    "Closed": "Final",
    # Active — issued / approved / awaiting final
    "Issued": "Active",
    "Re-Issued": "Active",
    "Approved": "Active",
    "Final Pending": "Active",
    # In Review — application / plan check / pre-issuance
    "Applied": "In Review",
    "Pending Review": "In Review",
    "Ready to Issue": "In Review",
    "Resubmittal Required": "In Review",
    "Scheduled": "In Review",
    "Estimate": "In Review",
    "Template": "In Review",
    # Inactive
    "Expired Permit": "Inactive",
    "Permit Expired": "Inactive",
    "Expired Application": "Inactive",
    "Application Expired": "Inactive",
    "Void": "Inactive",
    "Withdrawn": "Inactive",
}


def _expected_status(d: dict) -> Optional[str]:
    """Map DATA.status → STATUS_NORMALIZED; fall back to task marks."""
    raw = d.get("status")
    if isinstance(raw, str) and raw.strip():
        return _STATUS_MAP.get(raw.strip())

    marks = _all_marked_as(d.get("tasks") or [])
    if "Void" in marks:
        return "Inactive"
    if "Withdrawn" in marks:
        return "Inactive"
    if "Finaled" in marks or "Closed" in marks:
        return "Final"
    if "Issued" in marks or "Re-Issued" in marks or "Approved" in marks:
        return "Active"
    if marks:
        return "In Review"
    return None


def _issued_date(tasks: list):
    """Earliest issuance date, preferring Ready to Issue / Issued."""
    preferred = _first_event_date(
        tasks, "Ready to Issue", {"Issued", "Re-Issued"}
    )
    if preferred is not pd.NaT:
        return preferred

    for task_name in (
        "Application Review",
        "Application Submittal",
        "Processing",
    ):
        dt = _first_event_date(tasks, task_name, {"Issued", "Re-Issued"})
        if dt is not pd.NaT:
            return dt

    # Any Issued / Re-Issued mark elsewhere
    dates = []
    for t in _iter_tasks(tasks):
        for e in t.get("events") or []:
            if not isinstance(e, dict):
                continue
            if _event_field(e, "Marked as") not in {"Issued", "Re-Issued"}:
                continue
            dt = _safe_to_datetime(_event_field(e, "on"))
            if dt is not pd.NaT:
                dates.append(dt)
    return min(dates) if dates else pd.NaT


def _canonical_issued_date(tasks: list):
    """Strict Ready to Issue issuance date used for FIXED checks."""
    return _first_event_date(tasks, "Ready to Issue", {"Issued", "Re-Issued"})


def _permit_date_from_master(d: dict):
    issue = _safe_to_datetime(_more_details_field(d, "Permit Issue Date"))
    if issue is not pd.NaT:
        return issue
    return _safe_to_datetime(_more_details_field(d, "Permit Last Reissue Date"))


def _final_date_from_data(d: dict):
    """Best available finaling / closure date."""
    tasks = d.get("tasks") or []

    finaled = _latest_event_date(tasks, "Inspections", "Finaled")
    if finaled is not pd.NaT:
        return finaled

    closed = _latest_event_date(tasks, "Closed", "Closed")
    if closed is not pd.NaT:
        return closed

    co = _latest_event_date(
        tasks, "Certificate of Occupancy", "C of O Issued"
    )
    if co is not pd.NaT:
        return co

    # Legacy PERMIT MASTER Status Date for closed / finaled records.
    status_date = _safe_to_datetime(
        _more_details_field(d, "Permit Status Date")
    )
    if status_date is pd.NaT:
        return pd.NaT

    raw_status = d.get("status")
    code = _more_details_field(d, "Permit Status Code")
    code_s = str(code).strip().upper() if code is not None else ""
    if raw_status in {"Finaled", "Closed"} or code_s in {"CL", "FI"}:
        return status_date

    return pd.NaT


def _file_date_from_data(d: dict):
    file_date = _safe_to_datetime(d.get("date"))
    if file_date is not pd.NaT:
        return file_date
    sd = d.get("search_data")
    if isinstance(sd, dict):
        return _safe_to_datetime(sd.get("Date"))
    return pd.NaT


# ── Repair logic ────────────────────────────────────────────────────────────

def _repair_record(row, d: dict, repairs: dict):
    tasks = d.get("tasks") or []

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
    issued = _issued_date(tasks)
    if issued is pd.NaT:
        issued = _permit_date_from_master(d)

    canonical = _canonical_issued_date(tasks)
    if not pd.isna(row["PERMIT_DATE"]):
        if (
            canonical is not pd.NaT
            and not _dates_equal(row["PERMIT_DATE"], canonical)
        ):
            repairs["PERMIT_DATE"] = canonical
            repairs["PERMIT_DATE_FLAG"] = "FIXED"
    elif effective_status in ("Active", "Final") and issued is not pd.NaT:
        repairs["PERMIT_DATE"] = issued
        repairs["PERMIT_DATE_FLAG"] = "FILLED"

    # -- FINAL_DATE --
    if effective_status == "Final":
        final_date = _final_date_from_data(d)
        if final_date is not pd.NaT:
            if pd.isna(row["FINAL_DATE"]):
                repairs["FINAL_DATE"] = final_date
                repairs["FINAL_DATE_FLAG"] = "FILLED"
            elif not _dates_equal(row["FINAL_DATE"], final_date):
                # Only overwrite when we have a stronger source than the
                # existing value (Finaled / Closed / Status Date). Leave
                # Final Pending proxies alone when no stronger source.
                repairs["FINAL_DATE"] = final_date
                repairs["FINAL_DATE_FLAG"] = "FIXED"
    elif not pd.isna(row["FINAL_DATE"]):
        repairs["FINAL_DATE"] = pd.NaT
        repairs["FINAL_DATE_FLAG"] = "FIXED"


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Stockton permit records using information from the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Stockton".  Must contain
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
    city = df[df["JURISDICTION"] == "Stockton"].copy()

    print(f"Stockton records: {len(city):,}\n")

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

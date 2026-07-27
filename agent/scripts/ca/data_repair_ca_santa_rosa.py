"""Data repair for Santa Rosa (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Santa Rosa DATA is an Accela Citizen Access scrape. Nearly all rows share
the same top-level keys (``status``, ``date``, ``tasks``, ``inspections``,
``more_details``, ``search_data``, …). Content variants (used as
INFERRED_SCHEMA) differ by which date sources are populated:

  - accela_tasks:   dated workflow events under ``tasks``
  - accela_shell:   tasks present but no dated events
  - accela_partial: missing inspections / conditions / fees keys
  - unknown / missing

Canonical mappings:
  - DATA.status                              → STATUS_NORMALIZED
  - DATA.date / search_data['Date']          → FILE_DATE
  - Permit Issuance / Issued                 → PERMIT_DATE
  - Closed / Close; else Inspections /
    Inspections Complete                     → FINAL_DATE

Known issues repaired:
  - STATUS_NORMALIZED derived from stale STATUS_ORIGINAL while DATA.status
    had already moved (Finaled→Active, Issued→In Review, Withdrawn→Active).
  - PERMIT_DATE missing on Issued rows that were mis-labeled In Review.
  - FINAL_DATE missing on Finaled rows whose STATUS_NORMALIZED was Active;
    FINAL_DATE set to earliest Inspections Complete when a later Close
    exists; spurious FINAL_DATE on Active (Issued) rows.

Not repairable / left as-is:
  - FILE_DATE already matches DATA.date for all sample rows.
  - A handful of Finaled rows have Inspections/Closed marked TBD only —
    FINAL_DATE stays missing.
  - Active ``Approved`` row with no Permit Issuance / Issued event —
    PERMIT_DATE stays missing.
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

    if not {"inspections", "conditions", "fees_details"} <= keys:
        return "accela_partial"
    if _has_dated_events(data_dict):
        return "accela_tasks"
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


# ── Status mapping ──────────────────────────────────────────────────────────

_STATUS_MAP = {
    # Final
    "Finaled": "Final",
    # Active — issued / approved / deferred issuance
    "Issued": "Active",
    "Issued - Deferred": "Active",
    "Approved": "Active",
    # In Review — application / plan check / pre-issuance
    "In Plan Review": "In Review",
    "Waiting for Applicant": "In Review",
    "Plan Review Approved": "In Review",
    "Pending": "In Review",
    "Plans Received": "In Review",
    "Applied": "In Review",
    "Open": "In Review",
    # Inactive
    "Expired": "Inactive",
    "Withdrawn": "Inactive",
    "Expired Plan Review": "Inactive",
}


def _expected_status(d: dict) -> Optional[str]:
    """Map DATA.status → STATUS_NORMALIZED."""
    raw = d.get("status")
    if isinstance(raw, str) and raw.strip():
        return _STATUS_MAP.get(raw.strip())
    return None


def _issued_date(tasks: list):
    """Earliest Permit Issuance / Issued date."""
    issued = _first_event_date(tasks, "Permit Issuance", "Issued")
    if issued is not pd.NaT:
        return issued
    # Rare revision re-issuance on the same task
    return _first_event_date(tasks, "Permit Issuance", "Revision Issued")


def _final_date_from_data(d: dict):
    """Best available finaling / closure date.

    Prefer Closed / Close (workflow closure). Fall back to Inspections /
    Inspections Complete when no Close date exists.
    """
    tasks = d.get("tasks") or []

    closed = _latest_event_date(tasks, "Closed", "Close")
    if closed is not pd.NaT:
        return closed

    # Occasional alternate closure task name
    closed_alt = _latest_event_date(tasks, "Closure", "Close")
    if closed_alt is not pd.NaT:
        return closed_alt

    insp = _latest_event_date(tasks, "Inspections", "Inspections Complete")
    if insp is not pd.NaT:
        return insp

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
    if not pd.isna(row["PERMIT_DATE"]):
        if issued is not pd.NaT and not _dates_equal(row["PERMIT_DATE"], issued):
            repairs["PERMIT_DATE"] = issued
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
                repairs["FINAL_DATE"] = final_date
                repairs["FINAL_DATE_FLAG"] = "FIXED"
    elif not pd.isna(row["FINAL_DATE"]):
        repairs["FINAL_DATE"] = pd.NaT
        repairs["FINAL_DATE_FLAG"] = "FIXED"


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Santa Rosa permit records using information from the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Santa Rosa".  Must contain
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
    city = df[df["JURISDICTION"] == "Santa Rosa"].copy()

    print(f"Santa Rosa records: {len(city):,}\n")

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

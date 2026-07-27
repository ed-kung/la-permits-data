"""Data repair for Concord (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Concord DATA is an Accela Citizen Access scrape. All rows share the same
top-level keys (``status``, ``date``, ``tasks``, ``inspections``,
``more_details``, ``search_data``, …). Content variants (used as
INFERRED_SCHEMA) differ by which date sources are populated:

  - accela_tasks:              dated workflow events under ``tasks``
  - accela_shell_inspections:  empty task shells; Passed FINAL*
                               inspections carry Status Date
  - accela_shell:              no dated task events and no usable
                               FINAL inspection dates
  - unknown / missing

Canonical mappings:
  - DATA.status (Accepted+Issued → Active) → STATUS_NORMALIZED
  - DATA.date / search_data['Date Submitted'] → FILE_DATE
  - Permit Issuance|Issuance / Issued|Reissued|
    Annual Issued|Permit Reissued           → PERMIT_DATE
  - Closed / Finaled|Closed; Close /
    Completed; Permit Issuance|CBO|BIS /
    Closed; else Passed FINAL* insp
    Status Date; else Inspection / Complete → FINAL_DATE

Known issues repaired:
  - Unmapped planning statuses (Project Approved, Incomple, Project
    Denied, Project Closeout) left STATUS_NORMALIZED null → FILLED.
  - Mis-normalized Accepted / Expired / Finaled / Canceled / Issued
    rows → FIXED (notably Accepted+Issued wrongly In Review/Inactive).
  - PERMIT_DATE set to Pending Issue instead of Issued → FIXED;
    missing Issued dates on Active/Final → FILLED.
  - FINAL_DATE set to Inspection Complete when Closed/Finaled exists
    → FIXED to Finaled; missing finals filled from Closed / Close /
    Completed / FINAL* inspections; spurious finals on non-Final
    cleared.

Not repairable / left as-is:
  - FILE_DATE already matches DATA.date for all sample rows.
  - Hundreds of Accela shells (esp. pre-~2013 Finaled) have empty
    task events and no FINAL inspections → PERMIT_DATE / FINAL_DATE
    stay missing.
  - Active Approved / planning rows pending issuance have no Issued
    mark → PERMIT_DATE stays missing.
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


def _passed_final_inspection_dates(d: dict) -> list:
    """Status Dates from Passed inspections whose title contains 'final'."""
    dates = []
    for item in d.get("inspections") or []:
        if not isinstance(item, dict):
            continue
        title = str(item.get("Title") or "")
        if "final" not in title.lower():
            continue
        if str(item.get("Status") or "").lower() != "passed":
            continue
        dt = _safe_to_datetime(item.get("Status Date"))
        if dt is not pd.NaT:
            dates.append(dt)
    return dates


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())
    if "tasks" not in keys or "status" not in keys:
        return "unknown"

    if _has_dated_events(data_dict):
        return "accela_tasks"
    if _passed_final_inspection_dates(data_dict):
        return "accela_shell_inspections"
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
                    marks.add(str(m).strip())
    return marks


def _has_issued_mark(tasks: list) -> bool:
    issued_marks = {
        "Issued",
        "Reissued",
        "Re-Issued",
        "Annual Issued",
        "Permit Reissued",
    }
    return bool(_all_marked_as(tasks) & issued_marks)


# ── Status mapping ──────────────────────────────────────────────────────────

_STATUS_MAP = {
    # Final
    "Finaled": "Final",
    "Closed": "Final",
    "Completed": "Final",
    "Project Closed": "Final",
    "Project Closeout": "Final",
    # Active — issued / approved / awaiting final
    "Issued": "Active",
    "Approved": "Active",
    "Active": "Active",
    "Renewed": "Active",
    "Reissued": "Active",
    "PreFinaled": "Active",
    "Project Approved": "Active",
    "Accepted": "Active",  # post-issuance open status in Concord Accela
    # In Review — application / plan check / pre-issuance
    "Applied": "In Review",
    "Submitted": "In Review",
    "Opened": "In Review",
    "Created": "In Review",
    "Completeness Review": "In Review",
    "Incomplete": "In Review",
    "Incomple": "In Review",
    "Corrections Required": "In Review",
    # Inactive
    "Canceled": "Inactive",
    "Cancel": "Inactive",
    "Expired": "Inactive",
    "Permit Withdrawn": "Inactive",
    "Voided": "Inactive",
    "Void": "Inactive",
    "ApplCanceled": "Inactive",
    "Inactive": "Inactive",
    "Application Withdrawn": "Inactive",
    "Revoked": "Inactive",
    "ApprExpired": "Inactive",
    "ApplExpired": "Inactive",
    "Withdrawn": "Inactive",
    "Project Denied": "Inactive",
}


def _expected_status(d: dict) -> Optional[str]:
    """Map DATA.status → STATUS_NORMALIZED; fall back to task marks."""
    raw = d.get("status")
    tasks = d.get("tasks") or []

    if isinstance(raw, str) and raw.strip():
        raw = raw.strip()
        # Accepted without an Issued mark is usually a legacy shell
        # (often Encroachment) still awaiting a clear lifecycle — treat
        # as In Review rather than Active.
        if raw == "Accepted" and not _has_issued_mark(tasks):
            return "In Review"
        mapped = _STATUS_MAP.get(raw)
        if mapped is not None:
            return mapped

    marks = _all_marked_as(tasks)
    if marks & {"Void", "Voided", "Canceled", "Withdrawn"}:
        return "Inactive"
    if marks & {"Finaled", "Closed", "Completed"}:
        return "Final"
    if marks & {"Issued", "Reissued", "Re-Issued", "Annual Issued", "Permit Reissued"}:
        return "Active"
    if marks & {"Approved"}:
        return "Active"
    if marks:
        return "In Review"
    return None


def _issued_date(tasks: list):
    """Earliest true issuance date (not Pending Issue)."""
    issuance_tasks = {"Permit Issuance", "Issuance"}
    issued_marks = {
        "Issued",
        "Reissued",
        "Re-Issued",
        "Annual Issued",
    }

    preferred = _first_event_date(tasks, issuance_tasks, issued_marks)
    if preferred is not pd.NaT:
        return preferred

    # Reissue admin path
    reissue = _first_event_date(
        tasks,
        {
            "BLD - Permit Expiration Admin",
            "BLD - Permit Expiration Admin - Reissue",
        },
        {"Permit Reissued", "Permit Renewed"},
    )
    if reissue is not pd.NaT:
        return reissue

    # Any Issued-like mark elsewhere
    dates = []
    for t in _iter_tasks(tasks):
        for e in t.get("events") or []:
            if not isinstance(e, dict):
                continue
            if _event_field(e, "Marked as") not in issued_marks:
                continue
            dt = _safe_to_datetime(_event_field(e, "on"))
            if dt is not pd.NaT:
                dates.append(dt)
    return min(dates) if dates else pd.NaT


def _canonical_issued_date(tasks: list):
    """Strict Permit Issuance / Issuance Issued date used for FIXED checks."""
    return _first_event_date(
        tasks,
        {"Permit Issuance", "Issuance"},
        {"Issued", "Reissued", "Re-Issued", "Annual Issued"},
    )


def _workflow_close_date(tasks: list):
    """Closure date from Closed / Close / Project Closeout workflow tasks."""
    finaled = _latest_event_date(tasks, "Closed", "Finaled")
    if finaled is not pd.NaT:
        return finaled

    closed = _latest_event_date(
        tasks, {"Closed", "Close"}, {"Closed", "Completed", "Complete"}
    )
    if closed is not pd.NaT:
        return closed

    closeout = _latest_event_date(
        tasks,
        {"Project Closeout", "Project Completion"},
        {"Closed", "Completed", "Complete", "Finaled"},
    )
    if closeout is not pd.NaT:
        return closeout

    return pd.NaT


def _alt_close_date(tasks: list):
    """Secondary close marks used on annual / enforcement / levy records."""
    issuance_closed = _latest_event_date(
        tasks, {"Permit Issuance", "Issuance"}, "Closed"
    )
    if issuance_closed is not pd.NaT:
        return issuance_closed

    review_closed = _latest_event_date(
        tasks, {"CBO Review", "BIS Review"}, "Closed"
    )
    if review_closed is not pd.NaT:
        return review_closed

    investigation = _latest_event_date(tasks, "Investigation", "Completed")
    if investigation is not pd.NaT:
        return investigation

    return pd.NaT


def _final_date_from_data(d: dict):
    """Best available finaling / closure date."""
    tasks = d.get("tasks") or []

    strong = _workflow_close_date(tasks)
    if strong is not pd.NaT:
        return strong

    alt = _alt_close_date(tasks)
    if alt is not pd.NaT:
        return alt

    insp_final = _passed_final_inspection_dates(d)
    if insp_final:
        return max(insp_final)

    # Weaker proxy: workflow Inspection / Complete
    insp_complete = _latest_event_date(tasks, "Inspection", "Complete")
    if insp_complete is not pd.NaT:
        return insp_complete

    return pd.NaT


def _strong_final_date(d: dict):
    """Final date strong enough to overwrite Inspection Complete proxies."""
    tasks = d.get("tasks") or []

    strong = _workflow_close_date(tasks)
    if strong is not pd.NaT:
        return strong

    return _alt_close_date(tasks)

def _file_date_from_data(d: dict):
    file_date = _safe_to_datetime(d.get("date"))
    if file_date is not pd.NaT:
        return file_date
    sd = d.get("search_data")
    if isinstance(sd, dict):
        for key in ("Date Submitted", "Date"):
            dt = _safe_to_datetime(sd.get(key))
            if dt is not pd.NaT:
                return dt
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
        strong = _strong_final_date(d)
        if strong is not pd.NaT:
            if pd.isna(row["FINAL_DATE"]):
                repairs["FINAL_DATE"] = strong
                repairs["FINAL_DATE_FLAG"] = "FILLED"
            elif not _dates_equal(row["FINAL_DATE"], strong):
                repairs["FINAL_DATE"] = strong
                repairs["FINAL_DATE_FLAG"] = "FIXED"
        elif pd.isna(row["FINAL_DATE"]):
            final_date = _final_date_from_data(d)
            if final_date is not pd.NaT:
                repairs["FINAL_DATE"] = final_date
                repairs["FINAL_DATE_FLAG"] = "FILLED"
    elif not pd.isna(row["FINAL_DATE"]):
        repairs["FINAL_DATE"] = pd.NaT
        repairs["FINAL_DATE_FLAG"] = "FIXED"


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Concord permit records using information from the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Concord".  Must contain
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
    city = df[df["JURISDICTION"] == "Concord"].copy()

    print(f"Concord records: {len(city):,}\n")

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

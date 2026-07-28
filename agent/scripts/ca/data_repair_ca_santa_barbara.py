"""Data repair for Santa Barbara (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Santa Barbara DATA is an Accela Citizen Access scrape. Content variants
(recorded in INFERRED_SCHEMA):

  - accela_full:     dated workflow events plus inspections / conditions /
                     fees_details blocks
  - accela_tasks:    dated workflow events under ``tasks`` (no full blocks)
  - accela_shell:    task shells present but no dated events (Issued /
                     Completed status with empty Permit Issuance / Closed)
  - accela_minimal:  address / contacts / details present, tasks empty/null
                     (common on Historic Permits / older Completed rows)
  - search_only:     only ``search_data``
  - unknown / missing

Canonical mappings:
  - DATA.status / search_data['Status']              → STATUS_NORMALIZED
  - DATA.date / search_data['Date']; else earliest
    Application Submittal accepted event             → FILE_DATE
  - Permit Issuance Marked as Issued                 → PERMIT_DATE
  - Latest among Closed Marked as Closed*, Inspection Final Inspection
    Complete, and passed final-titled inspections    → FINAL_DATE

Known issues repaired:
  - STATUS_NORMALIZED null for Documents Received, Corrections Incomplete,
    Responses Required → FILLED as In Review. Hold Placed On Record was
    Inactive → FIXED to In Review.
  - FILE_DATE already matches DATA.date / search_data.Date for every
    parseable row; one test record has a non-date ``date`` dict and no
    search Date → left missing.
  - PERMIT_DATE matches Issued when both present; Fees Paid (In Review)
    incorrectly carried a PERMIT_DATE from Fees Paid / Fees Due → cleared.
    Active/Final Issued/Completed shells without dated Issued events cannot
    be filled from DATA.
  - FINAL_DATE often used the first Final Inspection Complete rather than
    the latest Closed / FI mark when records were reopened → FIXED; a few
    Final rows with inspections but no Closed/FI task dates → FILLED from
    passed final inspections.

Not repairable / left as-is:
  - Vast majority of Completed / Issued Historic Permits and older shells
    have no dated tasks, KEY DATES, or inspections → PERMIT_DATE /
    FINAL_DATE stay missing.
  - Active Permit Issued rows whose Permit Issuance task has empty events
    (or no tasks list) → PERMIT_DATE stays missing.
  - Blank DATA.status / search Status (temp record) → STATUS stays null.
  - Test record BLD2016-11111 with malformed date dict → FILE_DATE stays
    missing.
"""

from __future__ import annotations

import json
import math
from typing import Optional

import numpy as np
import pandas as pd


_MIN_YEAR = 1990
_MAX_YEAR = 2035


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
    """Parse a date value as UTC, returning pd.NaT on failure."""
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return pd.NaT
    if isinstance(val, dict):
        return pd.NaT
    if isinstance(val, str):
        s = val.strip()
        if not s or s.upper() in {"TBD", "N/A", "NA", "NONE", "NULL"}:
            return pd.NaT
    try:
        dt = pd.to_datetime(val, utc=True, errors="coerce")
    except (ValueError, TypeError):
        return pd.NaT
    if dt is pd.NaT or pd.isna(dt):
        return pd.NaT
    year = int(dt.year)
    if year < _MIN_YEAR or year > _MAX_YEAR:
        return pd.NaT
    return dt


def _dates_equal(a, b) -> bool:
    da = _safe_to_datetime(a)
    db = _safe_to_datetime(b)
    if da is pd.NaT or db is pd.NaT:
        return False
    return da.date() == db.date()


def _event_field(event: dict, *names: str):
    """Read an Accela event field; keys are often padded with spaces."""
    normalized = {k.strip(): v for k, v in event.items() if isinstance(k, str)}
    for name in names:
        if name.strip() in normalized:
            return normalized[name.strip()]
    return None


def _event_status(event: dict):
    return _event_field(event, "Marked as", "status", "Status")


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
    if "status" not in keys and "search_data" not in keys:
        return "unknown"

    tasks = data_dict.get("tasks") or []
    has_tasks = isinstance(tasks, list) and len(tasks) > 0

    if _has_dated_events(data_dict):
        if {"inspections", "conditions", "fees_details"} <= keys:
            return "accela_full"
        return "accela_tasks"

    if has_tasks:
        return "accela_shell"

    if keys <= {"search_data"} or keys == {"search_data"}:
        return "search_only"

    return "accela_minimal"


def _event_dates(tasks: list, task_names, statuses):
    if isinstance(task_names, str):
        task_names = {task_names}
    if isinstance(statuses, str):
        statuses = {statuses}
    statuses_l = {s.lower() for s in statuses}
    dates = []
    for t in _iter_tasks(tasks):
        if t.get("name") not in task_names:
            continue
        for e in t.get("events") or []:
            if not isinstance(e, dict):
                continue
            mark = _event_status(e)
            if not isinstance(mark, str) or mark.strip().lower() not in statuses_l:
                continue
            dt = _safe_to_datetime(_event_field(e, "on"))
            if dt is not pd.NaT:
                dates.append(dt)
    return dates


def _first_event_date(tasks: list, task_names, statuses):
    dates = _event_dates(tasks, task_names, statuses)
    return min(dates) if dates else pd.NaT


def _latest_event_date(tasks: list, task_names, statuses):
    dates = _event_dates(tasks, task_names, statuses)
    return max(dates) if dates else pd.NaT


def _latest_closed_date(tasks: list):
    """Latest Closed-task mark whose status starts with 'Closed'."""
    dates = []
    for t in _iter_tasks(tasks):
        if t.get("name") != "Closed":
            continue
        for e in t.get("events") or []:
            if not isinstance(e, dict):
                continue
            mark = _event_status(e)
            if not isinstance(mark, str):
                continue
            if not mark.strip().lower().startswith("closed"):
                continue
            dt = _safe_to_datetime(_event_field(e, "on"))
            if dt is not pd.NaT:
                dates.append(dt)
    return max(dates) if dates else pd.NaT


# ── Status mapping ──────────────────────────────────────────────────────────

# DATA.status (exact, then case-insensitive) → STATUS_NORMALIZED
_STATUS_MAP = {
    # Final
    "Completed": "Final",
    "Complete": "Final",
    "Finaled": "Final",
    "Closed": "Final",
    # Active (issued / under construction / approved mod with permit)
    "Issued": "Active",
    "Permit Issued": "Active",
    "Code Mod Approved": "Active",
    # Inactive
    "Permit Expired": "Inactive",
    "Application Withdrawn": "Inactive",
    "Application Expired": "Inactive",
    "Voided": "Inactive",
    "Void": "Inactive",
    "Permit Canceled": "Inactive",
    "Code Mod Denied": "Inactive",
    "Application Denied": "Inactive",
    "Permit On Hold": "Inactive",
    # In Review (pre-issuance / applicant action / holds)
    "Returned to Applicant": "In Review",
    "Plan Review": "In Review",
    "Waiting on Applicant": "In Review",
    "Application Incomplete": "In Review",
    "Application Received": "In Review",
    "Warning Letter Sent": "In Review",
    "Corrections Required": "In Review",
    "Corrections Incomplete": "In Review",
    "Fees Paid": "In Review",
    "Plans Returned To Applicant": "In Review",
    "Resubmittal Received": "In Review",
    "Documents Received": "In Review",
    "Responses Required": "In Review",
    "Hold Placed On Record": "In Review",
}


_ISSUE_TASKS = {"Permit Issuance"}
_ISSUE_MARKS = {"Issued", "Permit Issued"}

_FINAL_INSP_MARKS = {"Final Inspection Complete", "Closed"}

_SUBMIT_TASKS = {"Application Submittal"}
_SUBMIT_MARKS = {
    "Accepted - Plan Review Req",
    "Accepted - Plan Review Not Req",
    "Ready to Issue",
    "Files Received",
}


def _raw_status(d: dict) -> Optional[str]:
    raw = d.get("status")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    sd = d.get("search_data")
    if isinstance(sd, dict):
        sd_status = sd.get("Status")
        if isinstance(sd_status, str) and sd_status.strip():
            return sd_status.strip()
    return None


def _expected_status(d: dict) -> Optional[str]:
    raw = _raw_status(d)
    if raw is None:
        return None
    mapped = _STATUS_MAP.get(raw)
    if mapped is None:
        for k, v in _STATUS_MAP.items():
            if k.lower() == raw.lower():
                mapped = v
                break
    return mapped


def _file_date_from_data(d: dict):
    """Application / opened date from Accela top-level date or search_data."""
    top = _safe_to_datetime(d.get("date"))
    if top is not pd.NaT:
        return top

    sd = d.get("search_data")
    if isinstance(sd, dict):
        for key in ("Date", "Opened Date", "Submitted Date", "Application Date"):
            opened = _safe_to_datetime(sd.get(key))
            if opened is not pd.NaT:
                return opened

    tasks = d.get("tasks") or []
    return _first_event_date(tasks, _SUBMIT_TASKS, _SUBMIT_MARKS)


def _permit_date_from_data(d: dict):
    """Earliest true issuance date (Permit Issuance / Issued)."""
    tasks = d.get("tasks") or []
    return _first_event_date(tasks, _ISSUE_TASKS, _ISSUE_MARKS)


def _has_issuance_evidence(d: dict) -> bool:
    return _permit_date_from_data(d) is not pd.NaT


def _final_date_from_inspections(d: dict):
    """Latest final-titled inspection with an approved/pass status."""
    dates = []
    ok = {"approved", "passed", "pass", "complete", "completed", "done", "final"}
    for item in d.get("inspections") or []:
        if not isinstance(item, dict):
            continue
        title = str(item.get("Title") or "")
        if "FINAL" not in title.upper():
            continue
        st = item.get("Status")
        if not isinstance(st, str) or st.strip().lower() not in ok:
            continue
        dt = _safe_to_datetime(item.get("Status Date") or item.get("Last Update Date"))
        if dt is not pd.NaT:
            dates.append(dt)
    return max(dates) if dates else pd.NaT


def _final_date_from_data(d: dict):
    """Best available finaling / sign-off date.

    Takes the latest among Closed marks, Final Inspection Complete task
    events, and passed final-titled inspections. Preferring Closed alone
    is wrong when a record was closed early and later received a Final
    Inspection Complete without a new Closed mark.
    """
    tasks = d.get("tasks") or []
    cands = [
        c
        for c in (
            _latest_closed_date(tasks),
            _latest_event_date(
                tasks, {"Inspection", "Inspections"}, _FINAL_INSP_MARKS
            ),
            _final_date_from_inspections(d),
        )
        if c is not pd.NaT
    ]
    return max(cands) if cands else pd.NaT


# ── Per-record repair logic ─────────────────────────────────────────────────

def _repair_record(row, d: dict, repairs: dict):
    current_status = row["STATUS_NORMALIZED"]
    expected = _expected_status(d)

    # -- STATUS_NORMALIZED --
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
    issued = _permit_date_from_data(d)
    current_permit = row["PERMIT_DATE"]
    if not pd.isna(current_permit):
        if issued is not pd.NaT and not _dates_equal(current_permit, issued):
            repairs["PERMIT_DATE"] = issued
            repairs["PERMIT_DATE_FLAG"] = "FIXED"
        elif effective_status == "In Review" and not _has_issuance_evidence(d):
            repairs["PERMIT_DATE"] = pd.NaT
            repairs["PERMIT_DATE_FLAG"] = "FIXED"
    elif effective_status in ("Active", "Final") and issued is not pd.NaT:
        repairs["PERMIT_DATE"] = issued
        repairs["PERMIT_DATE_FLAG"] = "FILLED"

    # -- FINAL_DATE --
    current_final = row["FINAL_DATE"]
    if effective_status == "Final":
        final_date = _final_date_from_data(d)
        if final_date is not pd.NaT:
            if pd.isna(current_final):
                repairs["FINAL_DATE"] = final_date
                repairs["FINAL_DATE_FLAG"] = "FILLED"
            elif not _dates_equal(current_final, final_date):
                repairs["FINAL_DATE"] = final_date
                repairs["FINAL_DATE_FLAG"] = "FIXED"
    elif not pd.isna(current_final):
        repairs["FINAL_DATE"] = pd.NaT
        repairs["FINAL_DATE_FLAG"] = "FIXED"


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Santa Barbara permit records using information from the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Santa Barbara".  Must contain
        columns STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, FINAL_DATE,
        and DATA.

    Returns
    -------
    pd.DataFrame
        Copy of *df* with corrected field values, an INFERRED_SCHEMA column
        naming the DATA JSON schema identified for each record, and new
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

    for col in ("FILE_DATE", "PERMIT_DATE", "FINAL_DATE"):
        if col in out.columns:
            out[col] = pd.to_datetime(out[col], utc=True, errors="coerce")

    return out


# ── CLI: run standalone to preview repair stats ─────────────────────────────

if __name__ == "__main__":
    import os
    from pathlib import Path

    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[3] / ".env")
    MY_DATA_PATH = os.getenv("MY_DATA_PATH")
    AGENT_DATA_PATH = os.getenv("AGENT_DATA_PATH")
    filepath = os.path.join(
        MY_DATA_PATH, "processed_data", "permits_ca_sample.parquet"
    )
    df = pd.read_parquet(filepath)
    city = df[(df["JURISDICTION"] == "Santa Barbara") & (df["STATE"] == "CA")].copy()

    print(f"Santa Barbara records: {len(city):,}\n")

    repaired = data_repair(city)

    print("INFERRED_SCHEMA:")
    print(repaired["INFERRED_SCHEMA"].value_counts(dropna=False).to_string())
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
        n = len(sub)
        pct = n_has / n if n else 0.0
        print(f"  {status:15s}: {n_has:>4,} / {n:>4,} ({pct:.1%})")

    print("\nFINAL_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FINAL_DATE"].notna().sum()
        n = len(sub)
        pct = n_has / n if n else 0.0
        print(f"  {status:15s}: {n_has:>4,} / {n:>4,} ({pct:.1%})")

    print("\nFILE_DATE coverage (after repair):")
    n_has = repaired["FILE_DATE"].notna().sum()
    print(f"  {n_has:>4,} / {len(repaired):>4,} ({n_has / len(repaired):.1%})")

    fd = pd.to_datetime(repaired["FILE_DATE"], utc=True, errors="coerce")
    pd_ = pd.to_datetime(repaired["PERMIT_DATE"], utc=True, errors="coerce")
    ff = pd.to_datetime(repaired["FINAL_DATE"], utc=True, errors="coerce")
    both_fp = fd.notna() & pd_.notna()
    both_pf = pd_.notna() & ff.notna()
    print("\nChronology inversions:")
    print(f"  FILE > PERMIT: {(both_fp & (fd.dt.normalize() > pd_.dt.normalize())).sum()}")
    print(f"  PERMIT > FINAL: {(both_pf & (pd_.dt.normalize() > ff.dt.normalize())).sum()}")

    if AGENT_DATA_PATH:
        out_path = os.path.join(AGENT_DATA_PATH, "santa_barbara_repaired_sample.parquet")
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote repaired sample → {out_path}")

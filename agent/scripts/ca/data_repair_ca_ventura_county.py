"""Data repair for Ventura County (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Ventura County DATA is an Accela Citizen Access scrape. Sample rows share
the same top-level keys (``status``, ``date``, ``tasks``, ``inspections``,
``search_data``, ``more_details``, …). Content variants (INFERRED_SCHEMA):

  - accela_tasks: dated workflow events under ``tasks``
  - accela_shell: task shells present but no dated events
                  (common on older converted / estimate records)
  - unknown / missing

Canonical mappings:
  - DATA.status / search_data['Status'] (+ workflow upgrade)
                                                      → STATUS_NORMALIZED
  - DATA.date / search_data['Date']                   → FILE_DATE
  - Plans Approved|Issued; Permit Issuance|Issued*;
    Permit Status|Issued; Application Submittal|
    Issued / OTC - No Plan Check; Plan Check|
    Approved OTC*; Permit Issuance|To Be Billed       → PERMIT_DATE
  - Inspections|Work Complete / Finaled / …;
    else Close|Closed / Certificate of Occupancy      → FINAL_DATE

Known issues repaired:
  - Estimate incorrectly mapped to Final → FIXED to In Review.
  - Approved (planning / plan-check approval, no issuance)
    incorrectly mapped to Active → FIXED to In Review.
  - Unmapped review / billing / enforcement statuses left null
    → FILLED (In Review / Active / Inactive as appropriate).
  - Issued / Inspection Pending rows that already carry
    Work Complete / Finaled / Close marks → FIXED to Final.
  - FILE_DATE already matches DATA.date for every sample row;
    no changes expected unless a future mismatch appears.
  - Active/Final missing PERMIT_DATE when an issuance mark exists
    (Plans Approved Issued, OTC fire systems, PE To Be Billed,
    Permit Status Issued, …) → FILLED.
  - Final missing FINAL_DATE when Work Complete / Finaled / Close
    marks exist → FILLED (prefer inspection final over admin Close).
  - Spurious FINAL_DATE on non-Final rows → cleared (FIXED),
    except when status is upgraded to Final first.

Not repairable from DATA:
  - ~114 Public Records / blank-status shells with empty Status →
    STATUS_NORMALIZED stays missing.
  - Many Active/Final Accela shells (and Estimate / Approved
    planning records) lack issuance marks → PERMIT_DATE stays
    missing.
  - Final rows with no Work Complete / Close / Finaled events →
    FINAL_DATE stays missing.
"""

from __future__ import annotations

import json
import math
from typing import Optional

import numpy as np
import pandas as pd


_MIN_YEAR = 1900
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
    """Parse a date value, returning pd.NaT on failure or implausible year."""
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return pd.NaT
    if isinstance(val, dict):
        return pd.NaT
    if isinstance(val, str):
        s = val.strip()
        if not s or s.upper() == "TBD":
            return pd.NaT
    try:
        dt = pd.to_datetime(val, errors="coerce")
    except (ValueError, TypeError):
        return pd.NaT
    if dt is pd.NaT or pd.isna(dt):
        return pd.NaT
    if getattr(dt, "tzinfo", None) is not None:
        dt = dt.tz_convert("UTC").tz_localize(None)
    year = int(dt.year)
    if year < _MIN_YEAR or year > _MAX_YEAR:
        return pd.NaT
    return dt


def _dates_equal(a, b) -> bool:
    da = _safe_to_datetime(a)
    db = _safe_to_datetime(b)
    if da is pd.NaT or db is pd.NaT:
        return False
    return da.normalize() == db.normalize()


def _event_field(event: dict, *names: str):
    """Read an event field by *names* priority (first match wins)."""
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
    has_events = _has_dated_events(data_dict)

    if has_events:
        return "accela_tasks"
    if has_tasks:
        return "accela_shell"
    return "accela_search_only"


def _event_dates(tasks: list, task_names, statuses):
    """Collect event dates for matching task name(s) and status value(s)."""
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


# ── Status mapping ──────────────────────────────────────────────────────────

_STATUS_MAP = {
    # Final
    "Closed": "Final",
    "Final": "Final",
    "Case Closed": "Final",
    "Completed": "Final",
    "Certified": "Final",
    "Abated": "Final",
    # Active
    "Issued": "Active",
    "Permit Issued": "Active",
    "Inspection Pending": "Active",
    "Approved OTC": "Active",
    # In Review — includes values previously mis-mapped
    "Estimate": "In Review",
    "Approved": "In Review",
    "Applied": "In Review",
    "Application Needs Information": "In Review",
    "Application In Review": "In Review",
    "Application Pending Review": "In Review",
    "Application Pending": "In Review",
    "Application Submitted": "In Review",
    "Plans Approved": "In Review",
    "In Plan Review": "In Review",
    "In Plan Check": "In Review",
    "Plan Check In Progress": "In Review",
    "In Check": "In Review",
    "Emailed": "In Review",
    "Reviewed": "In Review",
    "Submitted": "In Review",
    "Submittal In Progress": "In Review",
    "Submittal in Progress": "In Review",
    "Payment Required": "In Review",
    "Fees Invoiced": "In Review",
    "Fees Due - Ready": "In Review",
    "To Be Billed": "In Review",
    "Final Payment Due": "In Review",
    "Picked Up": "In Review",
    "Pre-Approval": "In Review",
    "Completeness Rev In Progress": "In Review",
    "In Progress": "In Review",
    "In Review": "In Review",
    "In Review-CSG": "In Review",
    "Correction Notice": "In Review",
    "Corrections Required": "In Review",
    "Out For Corrections": "In Review",
    "Incomplete": "In Review",
    "Insufficient": "In Review",
    "Quote Given": "In Review",
    "Assign Checker": "In Review",
    "Applicant Notified": "In Review",
    "Open": "In Review",
    "Report Review": "In Review",
    "Manager Review": "In Review",
    "Pending Signature": "In Review",
    "In Legal Lot Determination": "In Review",
    "Ship/Deliver/Pickup": "In Review",
    "Awaiting Information": "In Review",
    "Re-Submittal 1": "In Review",
    "Re-submittal 1": "In Review",
    "Re-Submittal 3": "In Review",
    "NOV/NOI": "Active",
    # Inactive
    "Expired": "Inactive",
    "Void": "Inactive",
    "Withdrawn": "Inactive",
    "Exempt": "Inactive",
}

_FINAL_INSPECTION_MARKS = {
    "Work Complete",
    "Work Complete - C of O Needed",
    "Finaled",
    "Final",
    "Completed",
    "No Inspection Required",
}

_FINAL_CLOSE_MARKS = {
    "Closed",
    "Close",
    "Complete",
    "Completed",
    "Finaled",
}

_FINAL_CLOSE_TASKS = {
    "Close",
    "Closed",
    "Closure",
    "Finalization",
    "Case Close Out",
    "Permit Closure",
}

_ISSUANCE_RULES = (
    # (task_names, mark_set, label)
    ({"Plans Approved"}, {"Issued"}, "PlansApproved|Issued"),
    (
        {"Permit Issuance", "Issuance", "Permit Issued"},
        {"Issued", "Permit Issued", "Clearance Issued"},
        "PermitIssuance|Issued",
    ),
    ({"Permit Status"}, {"Issued"}, "PermitStatus|Issued"),
    ({"Application Submittal"}, {"Issued"}, "AppSubmittal|Issued"),
    (
        {"Plan Check"},
        {"Approved OTC", "Approved OTC - No Inspection", "Issued"},
        "PlanCheck|OTC",
    ),
    (
        {"Application Submittal"},
        {"OTC - No Plan Check"},
        "AppSubmittal|OTC",
    ),
    (
        {"Permit Issuance", "Issuance"},
        {"To Be Billed"},
        "PermitIssuance|ToBeBilled",
    ),
)


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


def _map_raw_status(raw: str) -> Optional[str]:
    mapped = _STATUS_MAP.get(raw)
    if mapped is not None:
        return mapped
    for k, v in _STATUS_MAP.items():
        if k.lower() == raw.lower():
            return v
    return None


def _has_final_evidence(d: dict) -> bool:
    tasks = d.get("tasks") or []
    if _event_dates(tasks, {"Inspections", "Inspection"}, _FINAL_INSPECTION_MARKS):
        return True
    if _event_dates(tasks, _FINAL_CLOSE_TASKS, _FINAL_CLOSE_MARKS):
        return True
    if _event_dates(tasks, {"Certificate of Occupancy"}, {"Complete", "Completed"}):
        return True
    if _event_dates(tasks, {"License Status"}, {"Closed"}):
        return True
    return False


def _expected_status(d: dict) -> Optional[str]:
    """Map DATA.status → STATUS_NORMALIZED, upgrading on final workflow marks."""
    raw = _raw_status(d)
    mapped = _map_raw_status(raw) if raw else None

    # Terminal inactive statuses are not upgraded by close marks.
    if mapped == "Inactive":
        return mapped

    if _has_final_evidence(d):
        return "Final"

    return mapped


def _file_date_from_data(d: dict):
    """Application / opened date from Accela top-level date."""
    top = _safe_to_datetime(d.get("date"))
    if top is not pd.NaT:
        return top

    sd = d.get("search_data")
    if isinstance(sd, dict):
        for key in ("Date", "Submitted Date", "Date Opened", "Application Date"):
            opened = _safe_to_datetime(sd.get(key))
            if opened is not pd.NaT:
                return opened
    return pd.NaT


def _permit_date_from_data(d: dict, allow_otc_plan_check: bool = True):
    """Earliest true issuance / OTC-issuance date from workflow tasks."""
    tasks = d.get("tasks") or []
    for task_names, marks, label in _ISSUANCE_RULES:
        if label == "PlanCheck|OTC" and not allow_otc_plan_check:
            continue
        dates = _event_dates(tasks, task_names, marks)
        if dates:
            return min(dates)
    return pd.NaT


def _has_issuance_evidence(d: dict) -> bool:
    return _permit_date_from_data(d, allow_otc_plan_check=True) is not pd.NaT


def _final_date_from_data(d: dict, on_or_after=None):
    """Best finaling / sign-off date.

    Prefer inspection Work Complete / Finaled over administrative Close,
    which can lag days or years after the true final.
    """
    tasks = d.get("tasks") or []
    candidates = []

    insp = _event_dates(tasks, {"Inspections", "Inspection"}, _FINAL_INSPECTION_MARKS)
    if insp:
        candidates.append(max(insp))

    coo = _event_dates(tasks, {"Certificate of Occupancy"}, {"Complete", "Completed"})
    if coo:
        candidates.append(max(coo))

    if not candidates:
        close = _event_dates(tasks, _FINAL_CLOSE_TASKS, _FINAL_CLOSE_MARKS)
        if close:
            candidates.append(max(close))
        lic = _event_dates(tasks, {"License Status"}, {"Closed"})
        if lic:
            candidates.append(max(lic))

    if not candidates:
        return pd.NaT

    floor = _safe_to_datetime(on_or_after)
    if floor is not pd.NaT:
        filtered = [dt for dt in candidates if dt.normalize() >= floor.normalize()]
        if filtered:
            candidates = filtered
    return max(candidates)


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
    # Plan Check Approved OTC is only treated as issuance for Active/Final
    # (e.g. FPS Approved OTC). Plans Approved + OTC plan-check stays In Review.
    allow_otc = effective_status in ("Active", "Final")
    issued = _permit_date_from_data(d, allow_otc_plan_check=allow_otc)
    current_permit = row["PERMIT_DATE"]
    if not pd.isna(current_permit):
        if issued is not pd.NaT and not _dates_equal(current_permit, issued):
            repairs["PERMIT_DATE"] = issued
            repairs["PERMIT_DATE_FLAG"] = "FIXED"
        elif (
            effective_status == "In Review"
            and not _has_issuance_evidence(d)
        ):
            repairs["PERMIT_DATE"] = pd.NaT
            repairs["PERMIT_DATE_FLAG"] = "FIXED"
    elif effective_status in ("Active", "Final") and issued is not pd.NaT:
        repairs["PERMIT_DATE"] = issued
        repairs["PERMIT_DATE_FLAG"] = "FILLED"

    # -- FINAL_DATE --
    if effective_status == "Final":
        permit_for_final = repairs.get("PERMIT_DATE", row["PERMIT_DATE"])
        final_date = _final_date_from_data(d, on_or_after=permit_for_final)
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
    Ventura County permit records using the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Ventura County".  Must
        contain columns STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE,
        FINAL_DATE, and DATA.

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
    from dotenv import load_dotenv

    load_dotenv("/Users/ekung/projects/la-permits-data/.env")
    MY_DATA_PATH = os.getenv("MY_DATA_PATH")
    AGENT_DATA_PATH = os.getenv("AGENT_DATA_PATH")
    filepath = os.path.join(
        MY_DATA_PATH, "processed_data", "permits_ca_sample.parquet"
    )
    df = pd.read_parquet(filepath)
    vc = df[df["JURISDICTION"] == "Ventura County"].copy()

    print(f"Ventura County records: {len(vc):,}\n")

    repaired = data_repair(vc)

    print("INFERRED_SCHEMA:")
    print(repaired["INFERRED_SCHEMA"].value_counts(dropna=False).to_string())
    print()

    for field in ["STATUS_NORMALIZED", "FILE_DATE", "PERMIT_DATE", "FINAL_DATE"]:
        flag_col = f"{field}_FLAG"
        n_filled = (repaired[flag_col] == "FILLED").sum()
        n_fixed = (repaired[flag_col] == "FIXED").sum()
        print(f"{field}:")
        print(f"  FILLED: {n_filled:>4,}   FIXED: {n_fixed:>4,}")

        before_missing = vc[field].isna().sum()
        after_missing = repaired[field].isna().sum()
        print(
            f"  Missing before: {before_missing:>4,}   "
            f"Missing after: {after_missing:>4,}"
        )
        print()

    print("STATUS_NORMALIZED distribution:")
    print("  Before:")
    for s, c in vc["STATUS_NORMALIZED"].value_counts(dropna=False).items():
        print(f"    {str(s):15s}: {c:>4,}")
    print("  After:")
    for s, c in repaired["STATUS_NORMALIZED"].value_counts(dropna=False).items():
        print(f"    {str(s):15s}: {c:>4,}")

    print("\nFINAL_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FINAL_DATE"].notna().sum()
        print(
            f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} "
            f"({n_has / len(sub) if len(sub) else 0:.1%})"
        )

    print("\nPERMIT_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["PERMIT_DATE"].notna().sum()
        print(
            f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} "
            f"({n_has / len(sub) if len(sub) else 0:.1%})"
        )

    print("\nFILE_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FILE_DATE"].notna().sum()
        print(
            f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} "
            f"({n_has / len(sub) if len(sub) else 0:.1%})"
        )

    # Chronology checks
    bad_pf = bad_fp = 0
    for idx in repaired.index:
        f = _safe_to_datetime(repaired.at[idx, "FILE_DATE"])
        p = _safe_to_datetime(repaired.at[idx, "PERMIT_DATE"])
        fin = _safe_to_datetime(repaired.at[idx, "FINAL_DATE"])
        if f is not pd.NaT and p is not pd.NaT and p.normalize() < f.normalize():
            bad_pf += 1
        if p is not pd.NaT and fin is not pd.NaT and fin.normalize() < p.normalize():
            bad_fp += 1
    print(f"\nChronology: PERMIT<FILE={bad_pf}  FINAL<PERMIT={bad_fp}")

    if AGENT_DATA_PATH:
        out_path = os.path.join(
            AGENT_DATA_PATH, "ventura_county_repaired_sample.parquet"
        )
        to_write = repaired.copy()
        for col in ("FILE_DATE", "PERMIT_DATE", "FINAL_DATE"):
            to_write[col] = pd.to_datetime(to_write[col], errors="coerce")
        to_write.to_parquet(out_path, index=False)
        print(f"\nWrote repaired sample → {out_path}")

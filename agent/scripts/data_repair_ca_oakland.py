"""Data repair for Oakland (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Oakland DATA is an Accela Citizen Access scrape. All sample rows share the
same top-level key set; INFERRED_SCHEMA distinguishes workflow richness:

  - tasks_inspections: non-empty tasks + non-empty inspections
  - tasks_only:        non-empty tasks, no inspections
  - inspections_only:  inspections present, no usable tasks
  - header_only:       status/date/search_data only (empty workflows)

Canonical mappings:
  - DATA.status                              → STATUS_NORMALIZED
  - DATA.date / search_data['File Date']     → FILE_DATE
  - Permit Issuance / Issued*                → PERMIT_DATE
      (fallback: Application Intake OTC issuance;
       Application Intake|Zoning Review|Closure / Approved
       for Approved / planning-style records)
  - Inspection / Final* (latest)             → FINAL_DATE
      (fallback: inspections titled Final* with Pass/APPROVED;
       Certificate of Occupancy / Issued; Closure / Closed)

Known issues repaired:
  - 88 STATUS_NORMALIZED gaps for code-enforcement / specialty statuses
    that were never mapped from DATA.status → FILLED.
  - ~47 PERMIT_DATE values that used Permit Issuance / Ready to Issue*
    instead of the later Issued event → FIXED.
  - Missing FINAL_DATE on Final rows with final inspection history
    (especially pre-2014 Accela migration shells) → FILLED.
  - Spurious FINAL_DATE on non-Final rows → cleared (FIXED).

Not repairable / left as-is:
  - FILE_DATE already matches DATA.date for all sample rows.
  - Many Active/Final rows (esp. pre-2014 and Permit Issued with TBD
    Permit Issuance events) have no dated issuance event → PERMIT_DATE
    stays missing.
  - Final rows with no Inspection/Final* task and no Final* inspection
    result → FINAL_DATE stays missing.
  - 9 rows with blank DATA.status → STATUS_NORMALIZED stays missing.
"""

import json
import math
import re
from typing import Optional

import pandas as pd
import numpy as np


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
    if val is None or (isinstance(val, str) and not str(val).strip()):
        return pd.NaT
    if str(val).strip() == "TBD":
        return pd.NaT
    try:
        return pd.to_datetime(val)
    except (ValueError, TypeError):
        return pd.NaT


def _dates_equal(a, b) -> bool:
    """Compare two datelike values at calendar-day resolution."""
    da = _safe_to_datetime(a)
    db = _safe_to_datetime(b)
    if da is pd.NaT or db is pd.NaT:
        return False
    return da.normalize() == db.normalize()


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())
    if "status" not in keys and "date" not in keys and "search_data" not in keys:
        return "unknown"

    tasks = data_dict.get("tasks") or []
    inspections = data_dict.get("inspections") or []
    has_tasks = isinstance(tasks, list) and len(tasks) > 0
    has_insp = isinstance(inspections, list) and len(inspections) > 0

    if has_tasks and has_insp:
        return "tasks_inspections"
    if has_tasks:
        return "tasks_only"
    if has_insp:
        return "inspections_only"
    return "header_only"


def _event_field(event: dict, *names: str):
    """Read an event field, tolerating leading/trailing spaces in keys."""
    targets = {n.strip().lower() for n in names}
    for k, v in event.items():
        if isinstance(k, str) and k.strip().lower() in targets:
            return v
    return None


def _event_dates(tasks: list, task_name: str, marked_pred) -> list:
    """Return all datetimes for task_name events matching marked_pred(marked)."""
    dates = []
    for t in tasks or []:
        if not isinstance(t, dict) or t.get("name") != task_name:
            continue
        for e in t.get("events") or []:
            if not isinstance(e, dict):
                continue
            marked = _event_field(e, "Marked as")
            marked = (marked or "").strip() if isinstance(marked, str) else marked
            if not marked_pred(marked):
                continue
            on_val = _event_field(e, "on")
            dt = _safe_to_datetime(on_val)
            if dt is not pd.NaT:
                dates.append(dt)
    return dates


# ── Status mapping ──────────────────────────────────────────────────────────

# DATA.status (title case as scraped) → STATUS_NORMALIZED.
# Lookup is case-insensitive via _map_status.
_STATUS_MAP = {
    # Final
    "Final": "Final",
    "Complete": "Final",
    "Closed": "Final",
    "Closed - Property Sold": "Final",
    "Certificate Issued": "Final",
    "Inspection Final": "Final",
    "Completed Cert Received": "Final",
    "Compliant": "Final",
    "Fully Executed": "Final",
    "In Compliance": "Final",
    "ACA Registered": "Final",
    "No Violation Found": "Final",
    "CL-Insp-NoViolFound": "Final",
    # Active
    "Permit Issued": "Active",
    "Approved": "Active",
    "Issued": "Active",
    "Inspections - In Progress": "Active",
    "OTC Issuance": "Active",
    "Reinstated": "Active",
    "Report Ready for Pick Up": "Active",
    "Report Ready For Pick Up": "Active",
    "Paid-Ready for Inspection": "Active",
    "Ready for Building": "Active",
    # Inactive
    "Expired": "Inactive",
    "Permit Expired": "Inactive",
    "Abated": "Inactive",
    "Abated - by Owner": "Inactive",
    "Abated - Self Certified": "Inactive",
    "CL-Insp-Abated": "Inactive",
    "Application Inactive": "Inactive",
    "Withdrawn": "Inactive",
    "Withdraw": "Inactive",
    "Cancelled": "Inactive",
    "Void": "Inactive",
    "Permit Inactive": "Inactive",
    "Non-Actionable": "Inactive",
    "Denied": "Inactive",
    "Revoked": "Inactive",
    "Refund": "Inactive",
    "Non Compliance": "Inactive",
    "Discussion Only": "Inactive",
    "Counter Discussion Only": "Inactive",
    "Deregistered": "Inactive",
    "Not Creekside": "Inactive",
    # In Review
    "Created": "In Review",
    "Referred": "In Review",
    "Referred - Planning": "In Review",
    "Referred to FPB": "In Review",
    "Application Approved": "In Review",
    "On Hold": "In Review",
    "Open": "In Review",
    "TBD": "In Review",
    "Assigned": "In Review",
    "Assigned to Planner": "In Review",
    "Pending": "In Review",
    "Filed": "In Review",
    "Under Review": "In Review",
    "OTC Fees Due": "In Review",
    "OTC FEES DUE": "In Review",
    "Application Accepted": "In Review",
    "Application Submitted": "In Review",
    "Approved OTC": "In Review",
    "Completed - Fees Due": "In Review",
    "Final Check - On Hold": "In Review",
    "In Review": "In Review",
    "Intake - Completed": "In Review",
    "Intake - On Hold": "In Review",
    "Intake-On Hold": "In Review",
    "No Response": "In Review",
    "On Hold - Fee Due": "In Review",
    "On Hold - Field Check Pending": "In Review",
    "Payment Received": "In Review",
    "Pending - Document Uploaded": "In Review",
    "Pending-Document Uploaded": "In Review",
    "Pending - Incomplete": "In Review",
    "Plan Review": "In Review",
    "Plan Review In Progress": "In Review",
    "Plan Routing - Completed": "In Review",
    "Ready to Issue": "In Review",
    "Ready to Issue - Fee Due": "In Review",
    "Ready to Issue - Fees Due": "In Review",
    "Received": "In Review",
    "Registered": "In Review",
    "Review - In Progress": "In Review",
    "Review - In progress": "In Review",
    "Review - On Hold": "In Review",
    "Routing - Completed": "In Review",
    "Scheduled Appointment": "In Review",
    "Submitted": "In Review",
    # Code enforcement / specialty (mostly missing before repair)
    "Initial Inspection": "In Review",
    "Initial Inspection Pending": "In Review",
    "Violation Verified": "In Review",
    "Pending Investigation": "In Review",
    "Notice of Violation Sent": "In Review",
    "OP-Insp-VioVeri": "In Review",
    "OP-Insp-Not Abated": "In Review",
    "OP-1stInsp-NOVSent": "In Review",
    "OP-Case Intake - IntakeComp": "In Review",
    "OP-CouttesyLtr-CourtesyLtrSent": "In Review",
    "Courtesy Letter Sent": "In Review",
    "Notice to Register Sent": "In Review",
    "Engineer Review Required": "In Review",
    "Minor Engineer of Day Review": "In Review",
    "Building Incomplete": "In Review",
    "Yellow Tag": "In Review",
}

_STATUS_MAP_LOWER = {k.casefold(): v for k, v in _STATUS_MAP.items()}


def _map_status(data_status: Optional[str]) -> Optional[str]:
    if not data_status or not isinstance(data_status, str):
        return None
    key = data_status.strip()
    if not key:
        return None
    return _STATUS_MAP_LOWER.get(key.casefold())


_ISSUED_MARKED = {
    "Issued",
    "Permit Issued",
    "Issued/Inspection Required",
}

_OTC_ISSUANCE_MARKED = {
    "OTC Issuance",
    "Approved OTC",
    "OTC Approved",
}

_FINAL_INSPECTION_PASS = {
    "pass",
    "approved",
    "partial approval",
}


def _is_issued_marked(m) -> bool:
    return isinstance(m, str) and m.strip() in _ISSUED_MARKED


def _is_ready_to_issue_marked(m) -> bool:
    if not isinstance(m, str):
        return False
    s = m.strip().casefold()
    return "ready" in s and "issue" in s


def _is_final_task_marked(m) -> bool:
    if not isinstance(m, str):
        return False
    return m.strip().casefold().startswith("final")


def _permit_date_from_tasks(tasks: list, data_status: Optional[str]):
    """Earliest canonical issuance / approval date from workflow tasks."""
    dates = _event_dates(tasks, "Permit Issuance", _is_issued_marked)
    if dates:
        return min(dates)

    dates = _event_dates(
        tasks, "Application Intake", lambda m: m in _OTC_ISSUANCE_MARKED
    )
    if dates:
        return min(dates)

    # Planning / discretionary "Approved" records often never hit Permit Issuance.
    if data_status and data_status.strip().casefold() in {
        "approved",
        "fully executed",
        "aca registered",
    }:
        for task_name, pred in (
            ("Application Intake", lambda m: m == "Approved"),
            ("Zoning Review", lambda m: isinstance(m, str) and m.startswith("Approved")),
            (
                "Closure",
                lambda m: m in ("Paid and Approved", "Approved", "Paid and Complete"),
            ),
        ):
            dates = _event_dates(tasks, task_name, pred)
            if dates:
                return min(dates)

    return pd.NaT


def _final_date_from_inspections(inspections: list):
    """Latest Final* inspection with a passing / approved result."""
    dates = []
    for insp in inspections or []:
        if not isinstance(insp, dict):
            continue
        title = str(insp.get("Title") or "")
        # Titles look like "Final Building (...)" or "FINAL ELECTRICAL ..."
        if not re.search(r"\bfinal\b", title, flags=re.IGNORECASE):
            continue
        status = str(insp.get("Status") or "").strip().casefold()
        if status not in _FINAL_INSPECTION_PASS:
            continue
        dt = _safe_to_datetime(insp.get("Status Date") or insp.get("Last Update Date"))
        if dt is not pd.NaT:
            dates.append(dt)
    return max(dates) if dates else pd.NaT


def _final_date_from_data(tasks: list, inspections: list, data_status: Optional[str]):
    """Latest completion / sign-off date from tasks and inspections."""
    finals = _event_dates(tasks, "Inspection", _is_final_task_marked)
    if finals:
        return max(finals)

    insp_final = _final_date_from_inspections(inspections)
    if insp_final is not pd.NaT:
        return insp_final

    cos = _event_dates(tasks, "Certificate of Occupancy", lambda m: m == "Issued")
    if cos:
        return max(cos)

    closed = _event_dates(
        tasks,
        "Closure",
        lambda m: isinstance(m, str)
        and m.strip().casefold() in {"closed", "paid and complete"},
    )
    if closed:
        return max(closed)

    # Some Complete / Closed rows only stamp Final Check / Approved.
    if data_status and data_status.strip().casefold() in {
        "complete",
        "closed",
        "inspection final",
        "certificate issued",
        "completed cert received",
    }:
        fc = _event_dates(
            tasks,
            "Final Check",
            lambda m: m in ("Approved", "Final Check Complete", "Final Check Completed"),
        )
        if fc:
            return max(fc)

    return pd.NaT


# ── Per-schema repair logic ─────────────────────────────────────────────────

def _repair_accela(row, d: dict, repairs: dict):
    """Repair an Accela Citizen Access Oakland record."""
    tasks = d.get("tasks") or []
    inspections = d.get("inspections") or []
    data_status = d.get("status")
    if isinstance(data_status, str):
        data_status = data_status.strip() or None
    else:
        data_status = None
    if data_status is None:
        sd = d.get("search_data") if isinstance(d.get("search_data"), dict) else {}
        sd_status = sd.get("Status")
        if isinstance(sd_status, str) and sd_status.strip():
            data_status = sd_status.strip()

    # -- STATUS_NORMALIZED --
    current_status = row["STATUS_NORMALIZED"]
    expected = _map_status(data_status)
    if expected is not None:
        if pd.isna(current_status):
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"
        elif current_status != expected:
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FIXED"

    effective_status = repairs.get("STATUS_NORMALIZED", current_status)

    # -- FILE_DATE --
    file_src = _safe_to_datetime(d.get("date"))
    if file_src is pd.NaT:
        sd = d.get("search_data") if isinstance(d.get("search_data"), dict) else {}
        file_src = _safe_to_datetime(sd.get("File Date") or sd.get("Date"))
    if file_src is not pd.NaT:
        if pd.isna(row["FILE_DATE"]):
            repairs["FILE_DATE"] = file_src
            repairs["FILE_DATE_FLAG"] = "FILLED"
        elif not _dates_equal(row["FILE_DATE"], file_src):
            repairs["FILE_DATE"] = file_src
            repairs["FILE_DATE_FLAG"] = "FIXED"

    # -- PERMIT_DATE --
    issued = _permit_date_from_tasks(tasks, data_status)
    if issued is not pd.NaT:
        if pd.isna(row["PERMIT_DATE"]):
            if effective_status in ("Active", "Final"):
                repairs["PERMIT_DATE"] = issued
                repairs["PERMIT_DATE_FLAG"] = "FILLED"
        elif not _dates_equal(row["PERMIT_DATE"], issued):
            repairs["PERMIT_DATE"] = issued
            repairs["PERMIT_DATE_FLAG"] = "FIXED"

    # -- FINAL_DATE --
    final = _final_date_from_data(tasks, inspections, data_status)
    current_final = row["FINAL_DATE"]

    if effective_status == "Final":
        if final is not pd.NaT:
            if pd.isna(current_final):
                repairs["FINAL_DATE"] = final
                repairs["FINAL_DATE_FLAG"] = "FILLED"
            elif not _dates_equal(current_final, final):
                repairs["FINAL_DATE"] = final
                repairs["FINAL_DATE_FLAG"] = "FIXED"
    elif not pd.isna(current_final):
        # Spurious FINAL_DATE on non-Final rows.
        repairs["FINAL_DATE"] = pd.NaT
        repairs["FINAL_DATE_FLAG"] = "FIXED"


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Oakland permit records using information from the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Oakland".  Must contain
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
        if schema in (
            "tasks_inspections",
            "tasks_only",
            "inspections_only",
            "header_only",
        ):
            _repair_accela(row, d, repairs)

        for key, value in repairs.items():
            if key in ("FILE_DATE", "PERMIT_DATE", "FINAL_DATE") and value is not pd.NaT and not pd.isna(value):
                value = _safe_to_datetime(value)
                if value is not pd.NaT:
                    value = value.normalize()
            out.at[idx, key] = value

    # Normalize date columns for consistent dtypes (parquet-safe).
    for col in ("FILE_DATE", "PERMIT_DATE", "FINAL_DATE"):
        out[col] = pd.to_datetime(out[col], errors="coerce")

    return out


# ── CLI: run standalone to preview repair stats ─────────────────────────────

if __name__ == "__main__":
    import os
    from dotenv import load_dotenv

    load_dotenv("/Users/ekung/projects/la-permits-data/.env")
    MY_DATA_PATH = os.getenv("MY_DATA_PATH")
    AGENT_DATA_PATH = os.getenv("AGENT_DATA_PATH")
    filepath = os.path.join(MY_DATA_PATH, "processed_data", "permits_ca_sample.parquet")
    df = pd.read_parquet(filepath)
    city = df[(df["JURISDICTION"] == "Oakland") & (df["STATE"] == "CA")].copy()

    print(f"Oakland records: {len(city):,}\n")

    repaired = data_repair(city)

    if AGENT_DATA_PATH:
        out_path = os.path.join(
            AGENT_DATA_PATH, "processed_data", "permits_ca_oakland_repaired.parquet"
        )
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        repaired.to_parquet(out_path, index=False)
        print(f"Wrote {out_path}\n")

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
        print(f"  Missing before: {before_missing:>4,}   Missing after: {after_missing:>4,}")
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
    print(f"  {n_has:>4,} / {len(repaired):>4,} ({n_has/len(repaired):.1%})")

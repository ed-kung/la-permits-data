"""Data repair for San Joaquin County (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

San Joaquin County DATA has two schemas:

  - tasks_full: Accela Citizen Access scrape with top-level keys
                ``tasks``, ``status``, ``date``, ``search_data``,
                ``inspections``, etc. (n≈1,744)
  - flat_legacy: flatter Accela export with ``Status``, ``Initialized``,
                 ``Issued``, ``Last Inspection``, etc. (n≈255)

Canonical mappings (tasks_full):
  - DATA.status                                      → STATUS_NORMALIZED
  - DATA.date / search_data['Date']                  → FILE_DATE
  - Permit Issuance|License Issuance / Issued        → PERMIT_DATE
      (fallback for Release records: Application Intake / Clearance Approved)
  - Inspection / Permit Complete|Final Inspection Complete,
    Application Review / Completed,
    Final Review / Released,
    Processing|Permit|Incident|License Status / Closed,
    Reviews / Completed No Inspection Required,
    Final*-titled approved inspections[].Status Date → FINAL_DATE (latest)

Canonical mappings (flat_legacy):
  - DATA.Status                                      → STATUS_NORMALIZED
  - DATA.Initialized                                 → FILE_DATE
  - DATA.Issued                                      → PERMIT_DATE
  - date prefix of DATA['Last Inspection']           → FINAL_DATE

Known issues repaired:
  - Many Accela statuses never mapped upstream (Active billable, Closed -
    Released, Mailed, Inactive non-billable, Billing Complete, etc.) →
    FILLED.
  - Closed - Permit Issued labeled Active → FIXED to Final.
  - FINAL_DATE often set to Final Inspection Complete when a later
    Permit Complete exists → FIXED to latest completion.
  - Spurious FINAL_DATE on Active Inspection Phase rows (sourced from
    Releases Complete / Complete) → cleared.
  - Missing FINAL_DATE filled from Permit Complete / Final Inspection
    Complete events, Application Review Completed, Final Review Released,
    Closed status marks, and Final-titled approved inspections.
  - Flat Finals missing FINAL_DATE when Last Inspection carries a date →
    FILLED.

Not repairable / left as-is:
  - FILE_DATE already matches DATA.date / Initialized for all sample rows.
  - NONE / UNKNOWN STATUS historical shells stay unmapped.
  - Hundreds of Active/Final Accela rows (esp. legacy Closed - Complete /
    FINISHED and Environmental Health Active billable) have no dated
    Issued or completion event → PERMIT_DATE / FINAL_DATE stay missing.
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
    """Parse a date value, returning pd.NaT on failure / TBD."""
    if val is None or (isinstance(val, str) and not str(val).strip()):
        return pd.NaT
    if str(val).strip().upper() == "TBD":
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
    if "tasks" in keys and "status" in keys:
        return "tasks_full"
    if "Status" in keys and "Initialized" in keys:
        return "flat_legacy"
    return "unknown"


def _event_field(event: dict, *names: str):
    """Read an event field, tolerating leading/trailing spaces in keys."""
    targets = {n.strip() for n in names}
    for k, v in event.items():
        if isinstance(k, str) and k.strip() in targets:
            return v
    return None


def _iter_task_nodes(tasks: list):
    """Yield (task_name, task_dict) for top-level tasks and subtasks."""
    for t in tasks or []:
        if not isinstance(t, dict):
            continue
        yield (t.get("name") or "").strip(), t
        for st in t.get("subtasks") or []:
            if isinstance(st, dict):
                yield (st.get("name") or "").strip(), st


def _event_dates(tasks: list, task_names, marked_pred) -> list:
    """Return datetimes for matching task events (Marked as + on)."""
    if isinstance(task_names, str):
        task_names = {task_names}
    else:
        task_names = set(task_names)
    dates = []
    for name, t in _iter_task_nodes(tasks):
        if name not in task_names:
            continue
        for e in t.get("events") or []:
            if not isinstance(e, dict):
                continue
            marked = _event_field(e, "Marked as")
            marked = (marked or "").strip() if isinstance(marked, str) else marked
            if not marked_pred(marked):
                continue
            dt = _safe_to_datetime(_event_field(e, "on"))
            if dt is not pd.NaT:
                dates.append(dt)
    return dates


# ── Status mapping ──────────────────────────────────────────────────────────

# Accela DATA.status (Title Case as scraped; lookup is case-insensitive)
_ACCELA_STATUS_MAP = {
    # Final
    "Closed - Complete": "Final",
    "FINISHED": "Final",
    "Closed": "Final",
    "Compliant": "Final",
    "Final Inspection Complete": "Final",
    "Closed - Issued": "Final",
    "Closed - Released": "Final",
    "Closed - Permit Issued": "Final",
    "Billing Complete": "Final",
    "Other Approved Class": "Final",
    "EHD Class Comp": "Final",
    # Active
    "Active": "Active",
    "ACTIVE": "Active",
    "Permit Issued": "Active",
    "Issued": "Active",
    "Inspection Phase": "Active",
    "Active, billable": "Active",
    "Active, exempt from billing": "Active",
    "Diversion Plan Approved": "Active",
    # Inactive
    "Inactive": "Inactive",
    "Void": "Inactive",
    "Expired": "Inactive",
    "Closed - Withdrawn": "Inactive",
    "CANCELED": "Inactive",
    "Canceled": "Inactive",
    "Cancelled": "Inactive",
    "Denied": "Inactive",
    "Inactive, non-billable": "Inactive",
    "Inactive code": "Inactive",
    "Closed - Entered in Error": "Inactive",
    "Closed - Initiated in Error": "Inactive",
    # In Review
    "In Review": "In Review",
    "Fees Paid": "In Review",
    "Pending": "In Review",
    "Open": "In Review",
    "SCHEDULED": "In Review",
    "Scheduled": "In Review",
    "Referred": "In Review",
    "Additional Info Required": "In Review",
    "Paid": "In Review",
    "IN PROGRESS": "In Review",
    "In Progress": "In Review",
    "Fees Due": "In Review",
    "Mailed": "In Review",
    "Certified Mailed": "In Review",
    "Certified and Regular Mail": "In Review",
    "Planning Pre-Review": "In Review",
}

_ACCELA_STATUS_MAP_LOWER = {k.lower(): v for k, v in _ACCELA_STATUS_MAP.items()}

# Flat legacy DATA.Status
_FLAT_STATUS_MAP = {
    "FINAL": "Final",
    "ISSUED": "Active",
    "EXPIRED": "Inactive",
    "WITHDRWN": "Inactive",
    "PENDING": "In Review",
    "EXP/NOCV": "Inactive",
    "COR/REQ": "In Review",
}

_FLAT_STATUS_MAP_LOWER = {k.lower(): v for k, v in _FLAT_STATUS_MAP.items()}


def _map_accela_status(data_status: Optional[str]) -> Optional[str]:
    if not data_status or not isinstance(data_status, str):
        return None
    key = data_status.strip()
    if not key:
        return None
    return _ACCELA_STATUS_MAP.get(key) or _ACCELA_STATUS_MAP_LOWER.get(key.lower())


def _map_flat_status(data_status: Optional[str]) -> Optional[str]:
    if not data_status or not isinstance(data_status, str):
        return None
    key = data_status.strip()
    if not key:
        return None
    return _FLAT_STATUS_MAP.get(key) or _FLAT_STATUS_MAP_LOWER.get(key.lower())


_ISSUED_MARKS = {"Issued", "Re-issued", "Re-Issued"}


def _is_issue_mark(marked: Optional[str]) -> bool:
    if not marked or not isinstance(marked, str):
        return False
    return marked.strip() in _ISSUED_MARKS


def _is_final_mark(task_name: str, marked: Optional[str]) -> bool:
    """True when (task, Marked as) indicates permit completion / finaling."""
    if not marked or not isinstance(marked, str):
        return False
    m = marked.strip()
    if task_name == "Inspection" and m in (
        "Permit Complete",
        "Final Inspection Complete",
    ):
        return True
    if task_name == "Application Review" and m == "Completed":
        return True
    if task_name == "Final Review" and m == "Released":
        return True
    if task_name == "Reviews" and m == "Completed No Inspection Required":
        return True
    if task_name in (
        "Processing Record",
        "Permit Status",
        "Incident Status",
        "License Status",
        "Permit Issuance",
    ) and m == "Closed":
        return True
    return False


def _permit_date_from_tasks(tasks: list):
    """Earliest true issuance date; Release fallback = Clearance Approved."""
    dates = _event_dates(
        tasks, ["Permit Issuance", "License Issuance"], _is_issue_mark
    )
    if dates:
        return min(dates)
    # Release workflow: clearance approval is the decision/issuance step.
    cleared = _event_dates(
        tasks, "Application Intake", lambda m: m == "Clearance Approved"
    )
    if cleared:
        return min(cleared)
    return pd.NaT


def _final_date_from_inspections(inspections: list):
    """Latest Status Date from Final-titled approved inspections."""
    dates = []
    for insp in inspections or []:
        if not isinstance(insp, dict):
            continue
        title = insp.get("Title") or ""
        status = (insp.get("Status") or "").strip().lower()
        if status not in ("approved", "passed", "complete", "completed"):
            continue
        if not re.search(
            r"\bfinal\b|building permit final|building approvals final",
            title,
            re.I,
        ):
            continue
        dt = _safe_to_datetime(insp.get("Status Date"))
        if dt is not pd.NaT:
            dates.append(dt)
    return max(dates) if dates else pd.NaT


def _final_date_from_tasks(tasks: list):
    """Latest completion / finaling workflow date from tasks."""
    dates = []
    for name, t in _iter_task_nodes(tasks):
        for e in t.get("events") or []:
            if not isinstance(e, dict):
                continue
            marked = _event_field(e, "Marked as")
            marked = (marked or "").strip() if isinstance(marked, str) else marked
            if not _is_final_mark(name, marked):
                continue
            dt = _safe_to_datetime(_event_field(e, "on"))
            if dt is not pd.NaT:
                dates.append(dt)
    return max(dates) if dates else pd.NaT


def _final_date_from_data(d: dict):
    """Latest FINAL_DATE candidate across tasks and inspections."""
    candidates = []
    task_final = _final_date_from_tasks(d.get("tasks") or [])
    if task_final is not pd.NaT:
        candidates.append(task_final)
    insp_final = _final_date_from_inspections(d.get("inspections") or [])
    if insp_final is not pd.NaT:
        candidates.append(insp_final)
    return max(candidates) if candidates else pd.NaT


def _parse_last_inspection_date(val) -> pd.Timestamp:
    """Parse 'MM/DD/YYYY: Approved (...)' Last Inspection strings."""
    if val is None or (isinstance(val, str) and not str(val).strip()):
        return pd.NaT
    m = re.match(r"^(\d{1,2}/\d{1,2}/\d{4})", str(val).strip())
    if not m:
        return pd.NaT
    return _safe_to_datetime(m.group(1))


# ── Per-record repair logic ─────────────────────────────────────────────────

def _repair_tasks(row, d: dict, repairs: dict):
    """Repair a tasks_full (Accela Citizen Access) record."""
    tasks = d.get("tasks") or []
    data_status = d.get("status")
    if isinstance(data_status, str):
        data_status = data_status.strip() or None
    else:
        data_status = None

    # -- STATUS_NORMALIZED --
    current_status = row["STATUS_NORMALIZED"]
    expected = _map_accela_status(data_status)
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
        file_src = _safe_to_datetime(sd.get("Created Date") or sd.get("Date"))
    if file_src is not pd.NaT:
        if pd.isna(row["FILE_DATE"]):
            repairs["FILE_DATE"] = file_src
            repairs["FILE_DATE_FLAG"] = "FILLED"
        elif not _dates_equal(row["FILE_DATE"], file_src):
            repairs["FILE_DATE"] = file_src
            repairs["FILE_DATE_FLAG"] = "FIXED"

    # -- PERMIT_DATE --
    issued = _permit_date_from_tasks(tasks)
    if issued is not pd.NaT:
        if pd.isna(row["PERMIT_DATE"]):
            if effective_status in ("Active", "Final"):
                repairs["PERMIT_DATE"] = issued
                repairs["PERMIT_DATE_FLAG"] = "FILLED"
        elif not _dates_equal(row["PERMIT_DATE"], issued):
            repairs["PERMIT_DATE"] = issued
            repairs["PERMIT_DATE_FLAG"] = "FIXED"

    # -- FINAL_DATE --
    final = _final_date_from_data(d)
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
        # Spurious FINAL_DATE on non-Final (e.g. Inspection Phase using
        # Releases Complete / Complete).
        repairs["FINAL_DATE"] = pd.NaT
        repairs["FINAL_DATE_FLAG"] = "FIXED"


def _repair_flat(row, d: dict, repairs: dict):
    """Repair a flat_legacy Accela export record."""
    data_status = d.get("Status")
    if isinstance(data_status, str):
        data_status = data_status.strip() or None
    else:
        data_status = None

    # -- STATUS_NORMALIZED --
    current_status = row["STATUS_NORMALIZED"]
    expected = _map_flat_status(data_status)
    if expected is not None:
        if pd.isna(current_status):
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"
        elif current_status != expected:
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FIXED"

    effective_status = repairs.get("STATUS_NORMALIZED", current_status)

    # -- FILE_DATE --
    file_src = _safe_to_datetime(d.get("Initialized"))
    if file_src is not pd.NaT:
        if pd.isna(row["FILE_DATE"]):
            repairs["FILE_DATE"] = file_src
            repairs["FILE_DATE_FLAG"] = "FILLED"
        elif not _dates_equal(row["FILE_DATE"], file_src):
            repairs["FILE_DATE"] = file_src
            repairs["FILE_DATE_FLAG"] = "FIXED"

    # -- PERMIT_DATE --
    issued = _safe_to_datetime(d.get("Issued"))
    if issued is not pd.NaT:
        if pd.isna(row["PERMIT_DATE"]):
            if effective_status in ("Active", "Final"):
                repairs["PERMIT_DATE"] = issued
                repairs["PERMIT_DATE_FLAG"] = "FILLED"
        elif not _dates_equal(row["PERMIT_DATE"], issued):
            repairs["PERMIT_DATE"] = issued
            repairs["PERMIT_DATE_FLAG"] = "FIXED"

    # -- FINAL_DATE --
    final = _parse_last_inspection_date(d.get("Last Inspection"))
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
        repairs["FINAL_DATE"] = pd.NaT
        repairs["FINAL_DATE_FLAG"] = "FIXED"


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    San Joaquin County permit records using information from the raw DATA
    JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "San Joaquin County".  Must
        contain columns STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE,
        FINAL_DATE, and DATA.

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
        if schema == "tasks_full":
            _repair_tasks(row, d, repairs)
        elif schema == "flat_legacy":
            _repair_flat(row, d, repairs)

        for key, value in repairs.items():
            out.at[idx, key] = value

    # Normalize date columns for parquet (mixed date/Timestamp → datetime64).
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
    filepath = os.path.join(
        MY_DATA_PATH, "processed_data", "permits_ca_sample.parquet"
    )
    df = pd.read_parquet(filepath)
    city = df[
        (df["JURISDICTION"] == "San Joaquin County") & (df["STATE"] == "CA")
    ].copy()

    print(f"San Joaquin County records: {len(city):,}\n")

    repaired = data_repair(city)

    if AGENT_DATA_PATH:
        out_path = os.path.join(
            AGENT_DATA_PATH,
            "processed_data",
            "permits_ca_san_joaquin_county_repaired.parquet",
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

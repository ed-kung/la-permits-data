"""Data repair for San Bernardino County (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

San Bernardino County DATA is a single Accela Citizen Access "tasks"
schema (all sample rows share the same top-level keys: date, status,
tasks, inspections, search_data, details, contacts, fees_details, etc.).

Task event keys have leading/trailing spaces ('Marked as ', ' on '),
same as Downey / other Accela portals.

Canonical fields:
  - DATA.status                         → STATUS_NORMALIZED
  - DATA.date                           → FILE_DATE
  - Permit Issuance / Issued task event → PERMIT_DATE
      (fallback: Application Review / Issued)
  - Inspections / Inspection Final or Complete task event,
    else inspection Status Date (Final / Pass),
    else Closure / Project Closure / Job Closure / Recordation
                                        → FINAL_DATE

Known issues repaired:
  - STATUS_NORMALIZED missing for Part 1/2 Approved, Approved with
    Comments, Contractor Info Required, Waiver Denied, blank status,
    and one Issued row → FILLED from DATA.status.
  - Stale STATUS_ORIGINAL-derived labels vs current DATA.status
    (e.g. Issued→Active while DATA.status is Final; Issued labeled
    In Review; Inspection Required labeled Final) → FIXED.
  - PERMIT_DATE set to Ready to Issue (or other Permit Issuance
    intermediate dates) instead of Issued → FIXED to Issued.
  - Active/Final rows missing PERMIT_DATE despite an Issued event →
    FILLED.
  - Final rows missing FINAL_DATE with a usable finaling / closure
    event or Final/Pass inspection → FILLED.
  - Spurious FINAL_DATE on non-Final rows (mostly Issued with a Final
    inspection while DATA.status remains Issued) → cleared (FIXED).

Not repairable from DATA:
  - FILE_DATE already matches DATA.date for every sample row.
  - ~400 Active/Final rows (Approved, Active, Complete, Closed,
    Recorded, etc.) have no Permit Issuance / Issued event →
    PERMIT_DATE stays missing.
  - ~140 Final rows (mostly Complete / Closed addressing and fire
    annual records, plus some Final without inspections) lack a
    usable finaling date → FINAL_DATE stays missing.
"""

import json
import math
from typing import Optional

import pandas as pd
import numpy as np


# Plausible calendar-year range for permit dates in this jurisdiction.
_MIN_YEAR = 1980
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
    if val is None or (isinstance(val, str) and not str(val).strip()):
        return pd.NaT
    if isinstance(val, str) and val.strip().upper() == "TBD":
        return pd.NaT
    try:
        dt = pd.to_datetime(val)
    except (ValueError, TypeError):
        return pd.NaT
    if dt is pd.NaT or pd.isna(dt):
        return pd.NaT
    year = int(dt.year)
    if year < _MIN_YEAR or year > _MAX_YEAR:
        return pd.NaT
    return dt


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())
    if "tasks" in keys and "status" in keys:
        return "tasks"
    if "search_data" in keys and "status" in keys:
        return "search_data"
    return "unknown"


def _event_field(event: dict, *names: str):
    """Read an event field, tolerating leading/trailing spaces in keys."""
    targets = {n.strip() for n in names}
    for k, v in event.items():
        if isinstance(k, str) and k.strip() in targets:
            return v
    return None


def _event_dates(tasks: list, task_name: str, marked_as: str):
    """All dates for task_name + marked_as events."""
    dates = []
    for t in tasks or []:
        if not isinstance(t, dict):
            continue
        if t.get("name") != task_name:
            continue
        for e in t.get("events") or []:
            if not isinstance(e, dict):
                continue
            if _event_field(e, "Marked as") != marked_as:
                continue
            dt = _safe_to_datetime(_event_field(e, "on"))
            if dt is not pd.NaT:
                dates.append(dt)
    return dates


def _first_event_date(tasks: list, task_name: str, marked_as: str):
    dates = _event_dates(tasks, task_name, marked_as)
    return min(dates) if dates else pd.NaT


def _latest_event_date(tasks: list, task_name: str, marked_as: str):
    dates = _event_dates(tasks, task_name, marked_as)
    return max(dates) if dates else pd.NaT


def _issued_date(tasks: list):
    """Earliest Permit Issuance / Issued; fallback Application Review / Issued."""
    issued = _first_event_date(tasks, "Permit Issuance", "Issued")
    if issued is not pd.NaT:
        return issued
    return _first_event_date(tasks, "Application Review", "Issued")


def _latest_inspection_status_date(inspections: list, statuses: set):
    """Latest Status Date among inspections whose Status is in *statuses*."""
    best = None
    wanted = {s.lower() for s in statuses}
    for insp in inspections or []:
        if not isinstance(insp, dict):
            continue
        st = str(insp.get("Status") or "").strip().lower()
        if st not in wanted:
            continue
        dt = _safe_to_datetime(insp.get("Status Date") or insp.get("Last Update Date"))
        if dt is not pd.NaT and (best is None or dt > best):
            best = dt
    return best if best is not None else pd.NaT


def _final_date_from_data(tasks: list, inspections: list):
    """Best available finaling / completion / recordation date."""
    # Prefer explicit inspection-workflow Final markers.
    for task_name in ("Inspections", "Inspection"):
        dt = _latest_event_date(tasks, task_name, "Final")
        if dt is not pd.NaT:
            return dt
    for task_name in ("Inspections", "Inspection"):
        dt = _latest_event_date(tasks, task_name, "Complete")
        if dt is not pd.NaT:
            return dt

    dt = _latest_inspection_status_date(inspections, {"Final"})
    if dt is not pd.NaT:
        return dt

    # Closure / recordation for Complete / Closed / Recorded Accela types.
    for task_name, marked_as in (
        ("Closure", "Closed - Complete"),
        ("Job Closure", "Closed - Complete"),
        ("Project Closure", "Complete"),
        ("Closure", "Complete"),
        ("Recordation", "Recorded"),
    ):
        dt = _latest_event_date(tasks, task_name, marked_as)
        if dt is not pd.NaT:
            return dt

    # Weaker fallback: passed final-style inspections.
    return _latest_inspection_status_date(
        inspections,
        {
            "Pass",
            "No Violations - Pass",
            "Corrected Violations - Pass",
            "Pass with Corrections",
        },
    )


# ── Status mapping ──────────────────────────────────────────────────────────

# DATA.status (Title Case, as stored) → STATUS_NORMALIZED
_STATUS_MAP = {
    # Final
    "Final": "Final",
    "Finaled": "Final",
    "Complete": "Final",
    "Closed": "Final",
    "Closed - Final": "Final",
    "Recorded": "Final",
    # Active — issued / approved / in construction / inspection phase
    "Issued": "Active",
    "Approved": "Active",
    "Active": "Active",
    "Delinquent": "Active",
    "Inspection Complete": "Active",
    "Inspection Required": "Active",
    # Inactive
    "Withdrawn": "Inactive",
    "Closed - Withdrawn": "Inactive",
    "Void": "Inactive",
    "Expired": "Inactive",
    "Abandoned": "Inactive",
    "Denied": "Inactive",
    "Waiver Denied": "Inactive",
    "No Review Required": "Inactive",
    # In Review — application / plan check / pre-issuance
    "Submitted": "In Review",
    "In Review": "In Review",
    "Awaiting Client Reply": "In Review",
    "Accepted": "In Review",
    "Filed": "In Review",
    "Paid": "In Review",
    "Processing": "In Review",
    "Fees Invoiced": "In Review",
    "Pending Issuance": "In Review",
    "Report Approved": "In Review",
    "Returned": "In Review",
    "Revision Submitted": "In Review",
    "Revisions Required": "In Review",
    "Received": "In Review",
    "In Progress": "In Review",
    "Suspended": "In Review",
    "Open": "In Review",
    "Contractor Info Required": "In Review",
    # Partial / conditional approvals — still pre-issuance workflow
    "Approved with Conditions": "In Review",
    "Approved with Comments": "In Review",
    "Part 1 Approved": "In Review",
    "Part 2 Approved": "In Review",
    "Part 2 Ready for Review": "In Review",
}


# ── Repair logic ────────────────────────────────────────────────────────────

def _repair_tasks(row, d: dict, repairs: dict):
    """Repair a tasks-schema (Accela Citizen Access) record."""
    tasks = d.get("tasks") or []
    inspections = d.get("inspections") or []
    data_status = d.get("status")
    if isinstance(data_status, str) and not data_status.strip():
        data_status = None

    # -- STATUS_NORMALIZED --
    current_status = row["STATUS_NORMALIZED"]
    if data_status is None:
        expected = "In Review"
    else:
        expected = _STATUS_MAP.get(data_status)

    if expected is not None:
        if pd.isna(current_status):
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"
        elif current_status != expected:
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FIXED"

    effective_status = repairs.get("STATUS_NORMALIZED", current_status)

    # -- FILE_DATE --
    # Already complete and equal to DATA.date for all sample records.

    # -- PERMIT_DATE --
    issued = _issued_date(tasks)

    if not pd.isna(row["PERMIT_DATE"]):
        current_pd = _safe_to_datetime(row["PERMIT_DATE"])
        if issued is not pd.NaT and current_pd is not pd.NaT:
            if current_pd.normalize() != issued.normalize():
                repairs["PERMIT_DATE"] = issued
                repairs["PERMIT_DATE_FLAG"] = "FIXED"
    elif effective_status in ("Active", "Final") and issued is not pd.NaT:
        repairs["PERMIT_DATE"] = issued
        repairs["PERMIT_DATE_FLAG"] = "FILLED"

    # -- FINAL_DATE --
    if effective_status == "Final":
        final_date = _final_date_from_data(tasks, inspections)
        if final_date is not pd.NaT:
            if pd.isna(row["FINAL_DATE"]):
                repairs["FINAL_DATE"] = final_date
                repairs["FINAL_DATE_FLAG"] = "FILLED"
            else:
                current_fd = _safe_to_datetime(row["FINAL_DATE"])
                if (
                    current_fd is pd.NaT
                    or current_fd.normalize() != final_date.normalize()
                ):
                    repairs["FINAL_DATE"] = final_date
                    repairs["FINAL_DATE_FLAG"] = "FIXED"
    elif not pd.isna(row["FINAL_DATE"]):
        # Spurious FINAL_DATE on non-Final records (common for Issued rows
        # that already have a Final inspection while status remains Issued).
        repairs["FINAL_DATE"] = pd.NaT
        repairs["FINAL_DATE_FLAG"] = "FIXED"


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    San Bernardino County permit records using the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "San Bernardino County".
        Must contain columns STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE,
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

        if schema == "tasks":
            _repair_tasks(row, d, repairs)

        for key, value in repairs.items():
            out.at[idx, key] = value

    # Clearing FINAL_DATE with pd.NaT can upcast the column to object;
    # coerce date fields back to datetime for consistent downstream use.
    for col in ("FILE_DATE", "PERMIT_DATE", "FINAL_DATE"):
        if col in out.columns:
            out[col] = pd.to_datetime(out[col], errors="coerce")

    return out


# ── CLI: run standalone to preview repair stats ─────────────────────────────

if __name__ == "__main__":
    import os
    from dotenv import load_dotenv

    load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".env"))
    # Fallback: repo-root .env relative to cwd
    if not os.getenv("MY_DATA_PATH"):
        load_dotenv(".env")

    MY_DATA_PATH = os.getenv("MY_DATA_PATH")
    filepath = os.path.join(MY_DATA_PATH, "processed_data", "permits_ca_sample.parquet")
    df = pd.read_parquet(filepath)
    sbc = df[df["JURISDICTION"] == "San Bernardino County"].copy()

    print(f"San Bernardino County records: {len(sbc):,}\n")

    repaired = data_repair(sbc)

    print("INFERRED_SCHEMA:")
    for s, c in repaired["INFERRED_SCHEMA"].value_counts(dropna=False).items():
        print(f"  {str(s):20s}: {c:>4,}")
    print()

    for field in ["STATUS_NORMALIZED", "FILE_DATE", "PERMIT_DATE", "FINAL_DATE"]:
        flag_col = f"{field}_FLAG"
        n_filled = (repaired[flag_col] == "FILLED").sum()
        n_fixed = (repaired[flag_col] == "FIXED").sum()
        print(f"{field}:")
        print(f"  FILLED: {n_filled:>4,}   FIXED: {n_fixed:>4,}")

        before_missing = sbc[field].isna().sum()
        after_missing = repaired[field].isna().sum()
        print(f"  Missing before: {before_missing:>4,}   Missing after: {after_missing:>4,}")
        print()

    print("STATUS_NORMALIZED distribution:")
    print("  Before:")
    for s, c in sbc["STATUS_NORMALIZED"].value_counts(dropna=False).items():
        print(f"    {str(s):15s}: {c:>4,}")
    print("  After:")
    for s, c in repaired["STATUS_NORMALIZED"].value_counts(dropna=False).items():
        print(f"    {str(s):15s}: {c:>4,}")

    print("\nFINAL_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        if len(sub) == 0:
            continue
        n_has = sub["FINAL_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({n_has / len(sub):.1%})")

    print("\nPERMIT_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        if len(sub) == 0:
            continue
        n_has = sub["PERMIT_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({n_has / len(sub):.1%})")

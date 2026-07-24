"""Data repair for Downey permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

The Downey DATA column uses a single Accela Citizen Access "tasks" schema
with top-level keys date, status, tasks, inspections, search_data, etc.

Task event keys have leading/trailing spaces ('Marked as ', ' on ')
unlike some other Accela cities.

Known issues repaired:
  - STATUS_NORMALIZED derived from stale STATUS_ORIGINAL while DATA.status
    was updated (e.g. STATUS_ORIGINAL="permit issued" but DATA.status=
    "Closed"/"Finaled") → FIXED to match DATA.status (12 records).
  - STATUS_NORMALIZED missing when DATA.status is None/'' → FILLED as
    In Review (5 records).
  - PERMIT_DATE mismatches Permit Issuance / Issued task event → FIXED
    (10 records).
  - PERMIT_DATE missing for Active/Final records with OTC Approval task
    events but empty Permit Issuance events (post-~2023 Accela scrape
    gap) → FILLED from OTC Approval / OTC Review Approved (252 records).
  - FINAL_DATE missing for Final records → FILLED from Inspection task
    finals events, Closed/Closed, or Building Final approved inspections
    (116 records).

FILE_DATE is already complete and matches DATA.date for all records.
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
    if val is None or (isinstance(val, str) and not val.strip()):
        return pd.NaT
    try:
        return pd.to_datetime(val)
    except (ValueError, TypeError):
        return pd.NaT


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())
    if "tasks" in keys:
        return "tasks"
    if "search_data" in keys and "status" in keys:
        return "search_data"
    return "unknown"


def _event_field(event: dict, *names: str):
    """Read an event field, tolerating leading/trailing spaces in keys."""
    targets = {n.strip() for n in names}
    for k, v in event.items():
        if k.strip() in targets:
            return v
    return None


def _first_event_date(tasks: list, task_name: str, marked_as: str):
    """Return the date of the first event matching task_name + marked_as."""
    for t in tasks:
        if t.get("name") != task_name:
            continue
        for e in t.get("events") or []:
            if _event_field(e, "Marked as") != marked_as:
                continue
            on_val = _event_field(e, "on")
            if on_val and str(on_val).strip() and str(on_val).strip() != "TBD":
                return _safe_to_datetime(on_val)
    return pd.NaT


def _strip_insp_code(title: str) -> str:
    """Strip leading numeric inspection codes, e.g. '195 Building Final'."""
    return re.sub(r"^\d+\s+", "", (title or "").strip().lower())


def _latest_building_final_approved(inspections: list):
    """Latest Approved Building Final / Final inspection Status Date."""
    best = None
    for insp in inspections or []:
        if insp.get("Status") != "Approved":
            continue
        title = _strip_insp_code(insp.get("Title") or "")
        if title not in ("final", "building final") and not title.endswith(
            "building final"
        ):
            continue
        dt = _safe_to_datetime(
            insp.get("Status Date") or insp.get("Last Update Date")
        )
        if dt is not pd.NaT and (best is None or dt > best):
            best = dt
    return best if best is not None else pd.NaT


def _latest_any_final_approved(inspections: list):
    """Latest Approved inspection whose title contains 'final' (not rough)."""
    best = None
    for insp in inspections or []:
        if insp.get("Status") != "Approved":
            continue
        title = _strip_insp_code(insp.get("Title") or "")
        if "final" not in title or "rough" in title:
            continue
        dt = _safe_to_datetime(
            insp.get("Status Date") or insp.get("Last Update Date")
        )
        if dt is not pd.NaT and (best is None or dt > best):
            best = dt
    return best if best is not None else pd.NaT


def _otc_approval_date(tasks: list):
    """OTC Approval / OTC Review Approved date from early workflow tasks."""
    for task_name in (
        "Application Submittal",
        "Preliminary Plan Review",
        "Plans Distribution",
    ):
        for marked_as in ("OTC Approval", "OTC Review Approved"):
            dt = _first_event_date(tasks, task_name, marked_as)
            if dt is not pd.NaT:
                return dt
    return pd.NaT


# ── Status mapping ──────────────────────────────────────────────────────────

_STATUS_MAP = {
    # Final
    "Closed": "Final",
    "Permit Closed": "Final",
    "Final Issued": "Final",
    "Finaled": "Final",
    "Final Inspection Complete": "Final",
    "Temp C of O Issued": "Final",
    # Active
    "Permit Issued": "Active",
    "Inspections In Process": "Active",
    # Inactive
    "Expired": "Inactive",
    "Withdrawn": "Inactive",
    "Permit Expired": "Inactive",
    "Permit Voided": "Inactive",
    "Plan Check Expired": "Inactive",
    "Project Cancelled": "Inactive",
    "Permit Archived": "Inactive",
    # In Review
    "In Progress": "In Review",
    "Contact Notified": "In Review",
    "Ready to Issue": "In Review",
    "Incomplete Submittal": "In Review",
    "Applied": "In Review",
    "Out for Corrections": "In Review",
    "Submitted": "In Review",
    "1st Plan Check": "In Review",
    "2nd Plan Check": "In Review",
    "Fees Due": "In Review",
    "Revision Complete": "In Review",
    "Pending": "In Review",
    "Corrections Picked Up": "In Review",
    "Corrections Required": "In Review",
    "Awaiting Plans": "In Review",
    "Routed for Review": "In Review",
}

_ISSUED_LIKE_STATUSES = {
    "Permit Issued",
    "Inspections In Process",
    "Closed",
    "Permit Closed",
    "Final Issued",
    "Finaled",
    "Final Inspection Complete",
    "Temp C of O Issued",
}


# ── Repair logic ────────────────────────────────────────────────────────────

def _repair_tasks(row, d: dict, repairs: dict):
    """Repair a tasks-schema (Accela Citizen Access) record."""
    tasks = d.get("tasks") or []
    inspections = d.get("inspections") or []
    data_status = d.get("status")
    # Treat blank string the same as missing
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
    # Already complete and equal to DATA.date for all Downey sample records.

    # -- PERMIT_DATE --
    issued = _first_event_date(tasks, "Permit Issuance", "Issued")

    if not pd.isna(row["PERMIT_DATE"]):
        current_pd = _safe_to_datetime(row["PERMIT_DATE"])
        if issued is not pd.NaT and current_pd is not pd.NaT:
            if current_pd.normalize() != issued.normalize():
                repairs["PERMIT_DATE"] = issued
                repairs["PERMIT_DATE_FLAG"] = "FIXED"
    elif effective_status in ("Active", "Final"):
        if issued is not pd.NaT:
            repairs["PERMIT_DATE"] = issued
            repairs["PERMIT_DATE_FLAG"] = "FILLED"
        else:
            # Post-~2023 Accela scrapes often omit Permit Issuance events
            # even when status is Permit Issued. OTC Approval is a strong
            # proxy (historically agrees with Issued ~95% of the time).
            otc = _otc_approval_date(tasks)
            if otc is not pd.NaT and data_status in _ISSUED_LIKE_STATUSES:
                repairs["PERMIT_DATE"] = otc
                repairs["PERMIT_DATE_FLAG"] = "FILLED"

    # -- FINAL_DATE --
    if pd.isna(row["FINAL_DATE"]) and effective_status == "Final":
        final_date = pd.NaT
        # Prefer Inspection-task finals markers (matches upstream derivation)
        for marked_as in (
            "Finals Complete No CofO Req",
            "Finals Complete",
            "Finaled",
        ):
            final_date = _first_event_date(tasks, "Inspection", marked_as)
            if final_date is not pd.NaT:
                break
        if final_date is pd.NaT:
            final_date = _first_event_date(tasks, "Closed", "Closed")
        if final_date is pd.NaT:
            final_date = _first_event_date(
                tasks, "Certificate of Occupancy", "Issued"
            )
        if final_date is pd.NaT:
            final_date = _latest_building_final_approved(inspections)
        if final_date is pd.NaT:
            final_date = _latest_any_final_approved(inspections)
        if final_date is not pd.NaT:
            repairs["FINAL_DATE"] = final_date
            repairs["FINAL_DATE_FLAG"] = "FILLED"


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Downey permit records using information from the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Downey".  Must contain
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

        if schema == "tasks":
            _repair_tasks(row, d, repairs)

        for key, value in repairs.items():
            out.at[idx, key] = value

    return out


# ── CLI: run standalone to preview repair stats ─────────────────────────────

if __name__ == "__main__":
    import os
    from dotenv import load_dotenv

    load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))
    MY_DATA_PATH = os.getenv("MY_DATA_PATH")
    filepath = os.path.join(MY_DATA_PATH, "processed_data", "permits_la_sample.parquet")
    df = pd.read_parquet(filepath)
    downey = df[df["JURISDICTION"] == "Downey"].copy()

    print(f"Downey records: {len(downey):,}\n")

    repaired = data_repair(downey)

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

        before_missing = downey[field].isna().sum()
        after_missing = repaired[field].isna().sum()
        print(f"  Missing before: {before_missing:>4,}   Missing after: {after_missing:>4,}")
        print()

    print("STATUS_NORMALIZED distribution:")
    print("  Before:")
    for s, c in downey["STATUS_NORMALIZED"].value_counts(dropna=False).items():
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
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({n_has/len(sub):.1%})")

    print("\nPERMIT_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        if len(sub) == 0:
            continue
        n_has = sub["PERMIT_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({n_has/len(sub):.1%})")

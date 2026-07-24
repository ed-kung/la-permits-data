"""Data repair for Lancaster permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

The Lancaster DATA column has two sub-schemas:

  - tasks:  Accela Citizen Access records with top-level keys 'tasks',
            'date', 'status', 'inspections', 'search_data', etc.  Status
            and workflow dates live in DATA.status and task events
            (Permit Issuance / Issued; Inspection / Final Inspection
            Complete or Final Inspection).

  - search_data_only: listing scrape with only 'search_data'.  Status is
            empty and no workflow dates are available, so STATUS /
            PERMIT / FINAL cannot be filled from DATA.

Known issues repaired:
  - STATUS_NORMALIZED missing for unmapped DATA.status values
    ("Final Inspection Completed", "Preliminary Review",
    "Approve(d) on Another Record", "1st Plan Check Out") and blank
    status on tasks-schema rows (→ In Review).
  - Spurious FINAL_DATE on non-Final records, typically Active/Issued
    Encroachment rows whose "Final Inspection" event was treated as a
    finaling date while DATA.status remained Issued (29), plus one
    Ready to Issue row with Final Inspection Complete (1).
  - PERMIT_DATE filled from Permit Issuance / Issued when present; for a
    few specialty Active rows with no issuance event, from approval
    proxies (Engineering Review / Approved; Senior Analyst Review /
    Accepted). ~700 Finaled rows are 2005–2009 Accela migrations with
    empty task events and a bogus 01/09/2016 fee stamp — unfillable.
  - FINAL_DATE filled from Inspection finals events when missing for
    Final records.

FILE_DATE is already complete and matches DATA.date (or search_data
Submission Date) for all records.
"""

import json
import math
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
    if "search_data" in keys and "tasks" not in keys and "status" not in keys:
        return "search_data_only"
    return "unknown"


def _first_event_date(tasks: list, task_name: str, marked_as: str):
    """Return the date of the first event matching task_name + marked_as."""
    for t in tasks or []:
        if t.get("name") != task_name:
            continue
        for e in t.get("events") or []:
            if e.get("Marked as") != marked_as:
                continue
            on_val = e.get("on", "")
            if on_val and str(on_val).strip() and str(on_val).strip() != "TBD":
                return _safe_to_datetime(on_val)
    return pd.NaT


def _approval_proxy_date(tasks: list, data_status: str):
    """Issuance proxy when Permit Issuance / Issued is absent.

    Used only for specialty Active statuses where Accela never records a
    separate Permit Issuance event:
      - status Approved → Engineering Review / Approved (e.g. geotech reports)
      - status Issued with Senior Analyst Review / Accepted (e.g. Impact Fee Credit)
    """
    if data_status == "Approved":
        return _first_event_date(tasks, "Engineering Review", "Approved")
    if data_status == "Issued":
        return _first_event_date(tasks, "Senior Analyst Review", "Accepted")
    return pd.NaT


# ── Status mapping ──────────────────────────────────────────────────────────

_STATUS_MAP = {
    # Final
    "Finaled": "Final",
    "Closed - Complete": "Final",
    "Final Inspection Completed": "Final",
    # Active
    "Issued": "Active",
    "Approved": "Active",
    "Construction": "Active",
    "Inspection Phase": "Active",
    # Inactive
    "Expired": "Inactive",
    "Denied": "Inactive",
    "Application Denied": "Inactive",
    "Void": "Inactive",
    "Abandoned": "Inactive",
    "Permit Not Required": "Inactive",
    # Approved via a different record — this record was never issued
    "Approved on Another Record": "Inactive",
    "Approve on Another Record": "Inactive",
    # In Review
    "Submitted": "In Review",
    "Plan Review": "In Review",
    "Incomplete Submittal": "In Review",
    "Revisions Required": "In Review",
    "Revisions Received": "In Review",
    "Ready to Issue": "In Review",
    "Preliminary Review": "In Review",
    "Pending": "In Review",
    "Stop Work": "In Review",
    "1st Plan Check Out": "In Review",
}


# ── Per-schema repair logic ─────────────────────────────────────────────────

def _repair_tasks(row, d: dict, repairs: dict):
    """Repair a tasks-schema record."""
    tasks = d.get("tasks") or []
    data_status = (d.get("status") or "").strip()

    # -- STATUS_NORMALIZED --
    current_status = row["STATUS_NORMALIZED"]
    expected = None
    if data_status and data_status in _STATUS_MAP:
        expected = _STATUS_MAP[data_status]
    elif not data_status:
        # Blank Accela status with an early-stage workflow → In Review
        expected = "In Review"

    if expected is not None:
        if pd.isna(current_status):
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"
        elif current_status != expected:
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FIXED"

    effective_status = repairs.get("STATUS_NORMALIZED", current_status)

    # -- FILE_DATE -- (already complete; matches DATA.date)

    # -- PERMIT_DATE --
    issued = _first_event_date(tasks, "Permit Issuance", "Issued")
    if not pd.isna(row["PERMIT_DATE"]):
        current_pd = _safe_to_datetime(row["PERMIT_DATE"])
        if issued is not pd.NaT and current_pd is not pd.NaT:
            if current_pd.normalize() != issued.normalize():
                repairs["PERMIT_DATE"] = issued
                repairs["PERMIT_DATE_FLAG"] = "FIXED"
    elif effective_status in ("Active", "Final"):
        permit_date = issued
        if permit_date is pd.NaT:
            permit_date = _approval_proxy_date(tasks, data_status)
        if permit_date is not pd.NaT:
            repairs["PERMIT_DATE"] = permit_date
            repairs["PERMIT_DATE_FLAG"] = "FILLED"

    # -- FINAL_DATE --
    if effective_status == "Final":
        final_date = _first_event_date(
            tasks, "Inspection", "Final Inspection Complete"
        )
        if final_date is pd.NaT:
            # Some Finaled encroachment/utility rows only have
            # "Final Inspection" (not "... Complete").
            final_date = _first_event_date(tasks, "Inspection", "Final Inspection")

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
        # Spurious FINAL_DATE on non-Final records.  Common for Issued
        # Encroachment Utilities rows that have a "Final Inspection"
        # event while DATA.status remains Issued (sometimes later
        # Reissued).
        repairs["FINAL_DATE"] = pd.NaT
        repairs["FINAL_DATE_FLAG"] = "FIXED"


def _repair_search_data_only(row, d: dict, repairs: dict):
    """search_data_only rows have empty Status and no workflow dates."""
    del row, d, repairs  # explicitly unused


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Lancaster permit records using information from the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Lancaster".  Must contain
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
        elif schema == "search_data_only":
            _repair_search_data_only(row, d, repairs)

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
    lancaster = df[df["JURISDICTION"] == "Lancaster"].copy()

    print(f"Lancaster records: {len(lancaster):,}\n")

    repaired = data_repair(lancaster)

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

        before_missing = lancaster[field].isna().sum()
        after_missing = repaired[field].isna().sum()
        print(f"  Missing before: {before_missing:>4,}   Missing after: {after_missing:>4,}")
        print()

    print("STATUS_NORMALIZED distribution:")
    print("  Before:")
    for s, c in lancaster["STATUS_NORMALIZED"].value_counts(dropna=False).items():
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

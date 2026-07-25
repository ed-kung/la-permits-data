"""Data repair for Culver City permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

The Culver City DATA column has two sub-schemas:

  - tasks:  Rich workflow data with top-level keys 'tasks', 'date', 'status',
            etc.  Status, permit-issuance, and finaling dates are embedded in
            the tasks list as events (e.g. "Permit Issuance / Issued",
            "Inspection / Finaled", "Closed / Finaled", "CO Issuance / CO
            Issued").

  - flat:   Structured record with keys 'RecordStatus', 'DateOpened',
            'StatusDate', 'PermitType', etc.  StatusDate holds the date of
            the current status (e.g. for 'Issued' records, it is the
            issuance date; for 'Finaled' records, the finaled date).
            However, many flat records have empty StatusDate, leaving no
            source for missing dates.

Known issues repaired:
  - STATUS_NORMALIZED missing for "Corrections Sent - EDR" records (→ In Review).
  - PERMIT_DATE incorrectly set to the CO Issuance date instead of the
    Permit Issuance date (5 records).
  - PERMIT_DATE missing for Active/Final records that have a "Permit
    Issuance / Issued" task event (274 records).
  - FINAL_DATE missing for Final records that have a "Closed / Finaled" or
    "CO Issuance" task event (267 records).
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
    if "tasks" in keys and data_dict["tasks"]:
        return "tasks"
    if "RecordStatus" in keys:
        return "flat"
    if "search_data" in keys:
        return "search_data_only"
    return "unknown"


def _first_event_date(tasks: list, task_name: str, marked_as: str) -> pd.Timestamp:
    """Return the date of the first event matching task_name + marked_as."""
    for t in tasks:
        if t.get("name") != task_name:
            continue
        for e in t.get("events", []):
            if e.get("Marked as") != marked_as:
                continue
            on_val = e.get("on", "")
            if on_val and on_val != "TBD":
                return _safe_to_datetime(on_val)
        break
    return pd.NaT


def _any_event_date(tasks: list, task_name: str, marked_as_contains: str) -> pd.Timestamp:
    """Return the date of the first event where Marked-as contains a substring."""
    for t in tasks:
        if t.get("name") != task_name:
            continue
        for e in t.get("events", []):
            ma = e.get("Marked as", "")
            if marked_as_contains not in ma:
                continue
            on_val = e.get("on", "")
            if on_val and on_val != "TBD":
                return _safe_to_datetime(on_val)
        break
    return pd.NaT


# ── Status mapping ──────────────────────────────────────────────────────────

_TASKS_STATUS_MAP = {
    "Finaled": "Final",
    "Final": "Final",
    "Closed": "Final",
    "Issued": "Active",
    "Approved": "Active",
    "Void": "Inactive",
    "Withdrawn": "Inactive",
    "Expired": "Inactive",
    "Applied": "In Review",
    "Applied - OTC": "In Review",
    "Open": "In Review",
    "In Plan Check": "In Review",
    "Plans Picked Up": "In Review",
    "Not Approved": "In Review",
    "Notice Sent": "In Review",
    "Corrections Sent - EDR": "In Review",
    "Application Incomplete": "In Review",
    "Resubmittal Received": "In Review",
    "Revision Resub In Plan Check": "In Review",
}


# ── Per-schema repair logic ─────────────────────────────────────────────────

def _repair_tasks(row, d: dict, repairs: dict):
    """Repair a tasks-schema record."""
    tasks = d.get("tasks", [])
    data_status = d.get("status")

    # -- STATUS_NORMALIZED --
    current_status = row["STATUS_NORMALIZED"]
    if data_status and data_status in _TASKS_STATUS_MAP:
        expected = _TASKS_STATUS_MAP[data_status]
        if pd.isna(current_status):
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"
        elif current_status != expected:
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FIXED"

    effective_status = repairs.get("STATUS_NORMALIZED", current_status)

    # -- FILE_DATE -- (no repairs needed; all populated and correct)

    # -- PERMIT_DATE --
    first_issued = _first_event_date(tasks, "Permit Issuance", "Issued")
    co_date = _any_event_date(tasks, "CO Issuance", "Issued")

    if not pd.isna(row["PERMIT_DATE"]):
        current_pd = _safe_to_datetime(row["PERMIT_DATE"])
        if first_issued is not pd.NaT and current_pd != first_issued:
            if co_date is not pd.NaT and current_pd == co_date:
                repairs["PERMIT_DATE"] = first_issued
                repairs["PERMIT_DATE_FLAG"] = "FIXED"
    elif effective_status in ("Active", "Final"):
        if first_issued is not pd.NaT:
            repairs["PERMIT_DATE"] = first_issued
            repairs["PERMIT_DATE_FLAG"] = "FILLED"

    # -- FINAL_DATE --
    if pd.isna(row["FINAL_DATE"]) and effective_status == "Final":
        finaled_date = _first_event_date(tasks, "Inspection", "Finaled")
        if finaled_date is pd.NaT:
            finaled_date = _first_event_date(tasks, "Closed", "Finaled")
        if finaled_date is pd.NaT and co_date is not pd.NaT:
            finaled_date = co_date
        if finaled_date is not pd.NaT:
            repairs["FINAL_DATE"] = finaled_date
            repairs["FINAL_DATE_FLAG"] = "FILLED"


def _repair_flat(row, d: dict, repairs: dict):
    """Repair a flat-schema record.

    The flat schema's StatusDate field is the primary date source, but it is
    empty for most records that have missing dates, so repairs are limited.
    """
    record_status = d.get("RecordStatus", "")
    status_date_str = d.get("StatusDate", "").strip()
    status_date = _safe_to_datetime(status_date_str) if status_date_str else pd.NaT

    # -- STATUS_NORMALIZED -- (already correct from upstream mapping)

    current_status = row["STATUS_NORMALIZED"]
    effective_status = current_status

    # -- FILE_DATE -- (no repairs needed)

    # -- PERMIT_DATE --
    if pd.isna(row["PERMIT_DATE"]) and effective_status in ("Active", "Final"):
        if record_status in ("Issued", "Approved") and status_date is not pd.NaT:
            repairs["PERMIT_DATE"] = status_date
            repairs["PERMIT_DATE_FLAG"] = "FILLED"

    # -- FINAL_DATE --
    if pd.isna(row["FINAL_DATE"]) and effective_status == "Final":
        if record_status in ("Finaled", "Final", "Closed") and status_date is not pd.NaT:
            repairs["FINAL_DATE"] = status_date
            repairs["FINAL_DATE_FLAG"] = "FILLED"


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Culver City permit records using information from the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Culver City".  Must contain
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
        elif schema == "flat":
            _repair_flat(row, d, repairs)

        for key, value in repairs.items():
            out.at[idx, key] = value

    return out


# ── CLI: run standalone to preview repair stats ─────────────────────────────

if __name__ == "__main__":
    import os
    from dotenv import load_dotenv, find_dotenv

    load_dotenv(find_dotenv())
    MY_DATA_PATH = os.getenv("MY_DATA_PATH")
    filepath = os.path.join(MY_DATA_PATH, "processed_data", "permits_la_sample.parquet")
    df = pd.read_parquet(filepath)
    cc = df[df["JURISDICTION"] == "Culver City"].copy()

    print(f"Culver City records: {len(cc):,}\n")

    repaired = data_repair(cc)

    for field in ["STATUS_NORMALIZED", "FILE_DATE", "PERMIT_DATE", "FINAL_DATE"]:
        flag_col = f"{field}_FLAG"
        n_filled = (repaired[flag_col] == "FILLED").sum()
        n_fixed = (repaired[flag_col] == "FIXED").sum()
        print(f"{field}:")
        print(f"  FILLED: {n_filled:>4,}   FIXED: {n_fixed:>4,}")

        before_missing = cc[field].isna().sum()
        after_missing = repaired[field].isna().sum()
        print(f"  Missing before: {before_missing:>4,}   Missing after: {after_missing:>4,}")
        print()

    print("STATUS_NORMALIZED distribution:")
    print("  Before:")
    for s, c in cc["STATUS_NORMALIZED"].value_counts(dropna=False).items():
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

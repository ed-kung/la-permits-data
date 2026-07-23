"""Data repair for Burbank permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column.  Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

The Burbank DATA column is a flat JSON with consistent keys:
    Address, Permit #, Sub Type, Completed, Inspection, Issue Date,
    Description, Permit Type, Applied Date, Permit Status,
    People Information

Key field mappings from DATA → normalised columns:
    Permit Status → STATUS_NORMALIZED
    Applied Date  → FILE_DATE
    Issue Date    → PERMIT_DATE
    Completed     → FINAL_DATE

Issues found:
    STATUS_NORMALIZED
    -  "Admin Completed" was mapped to "In Review"; should be "Final"
       (123 records, all have a Completed date).
    -  "Archived" was mapped to "In Review"; should be "Inactive"
       (21 records, no further activity).
    -  "Department Clearance" left as NaN for 2 records and incorrectly
       set to "Active" for 1 record where STATUS_ORIGINAL diverged from
       the raw Permit Status; should be "In Review".
    -  1 record has STATUS_ORIGINAL = "issued" but DATA Permit Status =
       "Final" (status updated in source after initial ingest); current
       STATUS_NORMALIZED = "Active" should be "Final".

    FILE_DATE
    -  10 records missing, but Applied Date is also empty in DATA for
       all 10 — cannot be filled.

    PERMIT_DATE
    -  No records where PERMIT_DATE is missing but Issue Date is present
       in DATA (unfillable from DATA alone).

    FINAL_DATE
    -  1 record (the "issued"→"Final" mismatch above) has Completed in
       DATA but missing FINAL_DATE; fillable after status correction.
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


# ── Status mapping ──────────────────────────────────────────────────────────

_STATUS_MAP = {
    "Active": "Active",
    "Admin Completed": "Final",
    "Admin Pending": "In Review",
    "Approved": "Active",
    "Archived": "Inactive",
    "Calendar Year Expired": "Inactive",
    "Cancelled": "Inactive",
    "Certificate of Occupancy": "Final",
    "Closed": "Final",
    "Complete": "Final",
    "Denied Without Prejudice": "Inactive",
    "Department Clearance": "In Review",
    "Exempt": "In Review",
    "Expired": "Inactive",
    "Final": "Final",
    "Fiscal Yr Expired": "Inactive",
    "H/O Inspection Required": "Active",
    "In Process": "In Review",
    "Inactive": "Inactive",
    "Issued": "Active",
    "Out of Business": "Inactive",
    "PC App w/ Sign-offs": "In Review",
    "PC Approved": "In Review",
    "PC Cancelled": "Inactive",
    "PC Expired": "Inactive",
    "PC Submitted": "In Review",
    "Paid - Pending Approval": "In Review",
    "Paid / Current": "Active",
    "Pending": "In Review",
    "Pending Renewal": "In Review",
    "Permit Cancelled": "Inactive",
    "Permit Expired": "Inactive",
    "Permit Final": "Final",
    "Permit Issued": "Active",
    "Permit Ready": "Active",
    "Projectdox": "In Review",
    "RTS Inspection Required": "Active",
    "Submitted": "In Review",
    "Withdrawn": "Inactive",
    "Withdrawn / Cancel": "Inactive",
}


# ── Per-record repair logic ─────────────────────────────────────────────────

def _repair_record(row, d: dict, repairs: dict):
    """Repair a single Burbank record."""
    permit_status = d.get("Permit Status", "").strip()
    current_status = row["STATUS_NORMALIZED"]

    # -- STATUS_NORMALIZED --
    expected = _STATUS_MAP.get(permit_status)
    if expected is not None:
        if pd.isna(current_status):
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"
        elif current_status != expected:
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FIXED"

    effective_status = repairs.get("STATUS_NORMALIZED", current_status)

    # -- FILE_DATE --
    if pd.isna(row["FILE_DATE"]):
        applied = _safe_to_datetime(d.get("Applied Date"))
        if applied is not pd.NaT:
            repairs["FILE_DATE"] = applied
            repairs["FILE_DATE_FLAG"] = "FILLED"

    # -- PERMIT_DATE --
    if pd.isna(row["PERMIT_DATE"]) and effective_status in ("Active", "Final"):
        issue = _safe_to_datetime(d.get("Issue Date"))
        if issue is not pd.NaT:
            repairs["PERMIT_DATE"] = issue
            repairs["PERMIT_DATE_FLAG"] = "FILLED"

    # -- FINAL_DATE --
    if pd.isna(row["FINAL_DATE"]) and effective_status == "Final":
        completed = _safe_to_datetime(d.get("Completed"))
        if completed is not pd.NaT:
            repairs["FINAL_DATE"] = completed
            repairs["FINAL_DATE_FLAG"] = "FILLED"


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Burbank permit records using information from the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Burbank".  Must contain
        columns STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, FINAL_DATE,
        and DATA.

    Returns
    -------
    pd.DataFrame
        Copy of *df* with corrected field values and new flag columns:
        STATUS_NORMALIZED_FLAG, FILE_DATE_FLAG, PERMIT_DATE_FLAG,
        FINAL_DATE_FLAG.  Flag values are "FILLED" (was missing, now
        populated) or "FIXED" (had an incorrect value, now corrected).
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

    for idx in out.index:
        row = out.loc[idx]
        d = _safe_parse(row["DATA"])
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
    filepath = os.path.join(MY_DATA_PATH, "processed_data", "permits_la_sample.parquet")
    df = pd.read_parquet(filepath)
    bur = df[df["JURISDICTION"] == "Burbank"].copy()

    print(f"Burbank records: {len(bur):,}\n")

    repaired = data_repair(bur)

    for field in ["STATUS_NORMALIZED", "FILE_DATE", "PERMIT_DATE", "FINAL_DATE"]:
        flag_col = f"{field}_FLAG"
        n_filled = (repaired[flag_col] == "FILLED").sum()
        n_fixed = (repaired[flag_col] == "FIXED").sum()
        print(f"{field}:")
        print(f"  FILLED: {n_filled:>4,}   FIXED: {n_fixed:>4,}")

        before_missing = bur[field].isna().sum()
        after_missing = repaired[field].isna().sum()
        print(f"  Missing before: {before_missing:>4,}   Missing after: {after_missing:>4,}")
        print()

    print("STATUS_NORMALIZED distribution:")
    print("  Before:")
    for s, c in bur["STATUS_NORMALIZED"].value_counts(dropna=False).items():
        print(f"    {str(s):15s}: {c:>4,}")
    print("  After:")
    for s, c in repaired["STATUS_NORMALIZED"].value_counts(dropna=False).items():
        print(f"    {str(s):15s}: {c:>4,}")

    print("\nFINAL_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FINAL_DATE"].notna().sum()
        if len(sub) > 0:
            print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({n_has/len(sub):.1%})")

    print("\nPERMIT_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["PERMIT_DATE"].notna().sum()
        if len(sub) > 0:
            print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({n_has/len(sub):.1%})")

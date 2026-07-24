"""Data repair for Calabasas permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

The Calabasas DATA column has a consistent schema with two key sections:
  - "Build Status": text status (e.g. "Permit Finaled", "Issued",
    "Expired: <date>", or None for recently-scraped records)
  - "My Project": dict with date fields "Submitted", "Issued", "Closed",
    "Approved", "Created" (values are date strings or " - -" when absent)

Root causes of data issues:
  1. STATUS_NORMALIZED is NaN for 396 records. For 96 of these, Build Status
     in DATA maps to a known status but was not propagated. For the remaining
     300, Build Status is None (recent scrapes) and status must be inferred
     from My Project date availability.
  2. STATUS_NORMALIZED is incorrect for 8 records where the permit status
     changed after the initial data load (e.g. Active permits that were later
     finaled or expired).
  3. FILE_DATE is sourced from My Project.Submitted. One record (idx 11525)
     was incorrectly set to Created instead of Submitted.
  4. PERMIT_DATE and FINAL_DATE are missing for some Active/Final records
     where My Project.Issued or My Project.Closed are available in DATA.
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
    if val is None or (isinstance(val, str) and val.strip() in ("", "- -")):
        return pd.NaT
    try:
        return pd.to_datetime(val)
    except (ValueError, TypeError):
        return pd.NaT


def _safe_to_date(val):
    """Parse a date value, returning None on failure."""
    dt = _safe_to_datetime(val)
    if dt is pd.NaT:
        return None
    return dt.date()


# ── Status mapping ───────────────────────────────────────────────────────────

_BUILD_STATUS_MAP = {
    "permit finaled": "Final",
    "issued": "Active",
    "reinstated permit - issued": "Active",
    "plan check expired": "Inactive",
    "planning approved*": "In Review",
    "application documents accepted": "In Review",
    "application is submitted": "In Review",
    "application is submitted and fees are ready for payment": "In Review",
    "permit application routed to review": "In Review",
    "required submittal items received and may have pending fees (plng)": "In Review",
    "ready": "In Review",
    "ready to issue -  pending fee collection": "In Review",
    "ready to issue - pending fee collection": "In Review",
    "returned to applicant": "In Review",
}


def _status_from_build_status(build_status: Optional[str]) -> Optional[str]:
    """Map a Build Status string to STATUS_NORMALIZED."""
    if build_status is None:
        return None
    bs = build_status.strip().lower()
    if bs.startswith("expired"):
        return "Inactive"
    return _BUILD_STATUS_MAP.get(bs)


def _status_from_my_project(mp: dict) -> Optional[str]:
    """Infer STATUS_NORMALIZED from My Project date availability."""
    has_closed = _safe_to_date(mp.get("Closed")) is not None
    has_issued = _safe_to_date(mp.get("Issued")) is not None
    has_submitted = _safe_to_date(mp.get("Submitted")) is not None

    if has_closed:
        return "Final"
    if has_issued:
        return "Active"
    if has_submitted:
        return "In Review"
    return None


# ── Per-record repair logic ─────────────────────────────────────────────────

def _repair_record(row, d: dict, repairs: dict):
    """Populate *repairs* dict with corrected values for a single record."""
    mp = d.get("My Project", {})
    build_status = d.get("Build Status")

    # -- STATUS_NORMALIZED --
    expected_status = _status_from_build_status(build_status)
    if expected_status is None and build_status is None:
        expected_status = _status_from_my_project(mp)

    current_status = row["STATUS_NORMALIZED"]

    if expected_status is not None:
        if pd.isna(current_status):
            repairs["STATUS_NORMALIZED"] = expected_status
            repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"
        elif current_status != expected_status:
            repairs["STATUS_NORMALIZED"] = expected_status
            repairs["STATUS_NORMALIZED_FLAG"] = "FIXED"

    effective_status = repairs.get("STATUS_NORMALIZED", current_status)

    # -- FILE_DATE --
    submitted_dt = _safe_to_date(mp.get("Submitted"))

    if pd.isna(row["FILE_DATE"]):
        if submitted_dt is not None:
            repairs["FILE_DATE"] = pd.Timestamp(submitted_dt)
            repairs["FILE_DATE_FLAG"] = "FILLED"
    else:
        current_fd = _safe_to_date(row["FILE_DATE"])
        if submitted_dt is not None and current_fd is not None and current_fd != submitted_dt:
            repairs["FILE_DATE"] = pd.Timestamp(submitted_dt)
            repairs["FILE_DATE_FLAG"] = "FIXED"

    # -- PERMIT_DATE --
    issued_dt = _safe_to_date(mp.get("Issued"))

    if pd.isna(row["PERMIT_DATE"]) and effective_status in ("Active", "Final"):
        if issued_dt is not None:
            repairs["PERMIT_DATE"] = pd.Timestamp(issued_dt)
            repairs["PERMIT_DATE_FLAG"] = "FILLED"

    # -- FINAL_DATE --
    closed_dt = _safe_to_date(mp.get("Closed"))

    if pd.isna(row["FINAL_DATE"]) and effective_status == "Final":
        if closed_dt is not None:
            repairs["FINAL_DATE"] = pd.Timestamp(closed_dt)
            repairs["FINAL_DATE_FLAG"] = "FILLED"


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Calabasas permit records using information from the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Calabasas".  Must contain
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
    cal = df[df["JURISDICTION"] == "Calabasas"].copy()

    print(f"Calabasas records: {len(cal):,}\n")

    repaired = data_repair(cal)

    for field in ["STATUS_NORMALIZED", "FILE_DATE", "PERMIT_DATE", "FINAL_DATE"]:
        flag_col = f"{field}_FLAG"
        n_filled = (repaired[flag_col] == "FILLED").sum()
        n_fixed = (repaired[flag_col] == "FIXED").sum()
        print(f"{field}:")
        print(f"  FILLED: {n_filled:>4,}   FIXED: {n_fixed:>4,}")

        before_missing = cal[field].isna().sum()
        after_missing = repaired[field].isna().sum()
        print(f"  Missing before: {before_missing:>4,}   Missing after: {after_missing:>4,}")
        print()

    print("STATUS_NORMALIZED distribution:")
    print("  Before:")
    for s, c in cal["STATUS_NORMALIZED"].value_counts(dropna=False).items():
        print(f"    {str(s):15s}: {c:>4,}")
    print("  After:")
    for s, c in repaired["STATUS_NORMALIZED"].value_counts(dropna=False).items():
        print(f"    {str(s):15s}: {c:>4,}")

    print("\nFINAL_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FINAL_DATE"].notna().sum()
        n_total = len(sub) if len(sub) > 0 else 1
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({n_has/n_total:.1%})")

    print("\nPERMIT_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["PERMIT_DATE"].notna().sum()
        n_total = len(sub) if len(sub) > 0 else 1
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({n_has/n_total:.1%})")

"""Data repair for Azusa (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Azusa DATA is a single flat portal schema (all sample rows share the same
top-level keys). Canonical fields:

  - System Status              → STATUS_NORMALIZED
  - Data Details['App. Date']  → FILE_DATE
  - Data Details['Issue Date'] → PERMIT_DATE
  - Data Details['Final Date'] → FINAL_DATE

``Data Details['Expire Date']`` is a permit-validity window, not a
finaling / completion date.

Known issues repaired:
  - STATUS_NORMALIZED: 9 Estimate rows mapped to Final (pre-issuance,
    no Issue/Final dates) → In Review; 1 B.L. HOLD missing → In Review;
    14 rows where STATUS_ORIGINAL is stale vs System Status (trust
    System Status).
  - FINAL_DATE was populated from Expire Date for ~1,745 sample rows
    instead of Final Date (only 3 rows correctly matched Final Date,
    and those happened to equal Expire). Overwrite with Final Date when
    present; clear Expire-derived values when Final Date is absent or
    status is not Final.

Not repairable from DATA:
  - 33 Final / Completed rows have empty Final Date (legacy Completed
    Building History / trades, plus some Final rows). Expire Date is not
    used as a proxy.
  - 13 Final / Completed rows also lack Issue Date (mostly Completed
    legacy); PERMIT_DATE left null.
"""

import json
import math
from datetime import date, datetime
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


def _safe_to_datetime_raw(val):
    """Parse a date with no year gate (used to detect Expire-derived values)."""
    if val is None or (isinstance(val, str) and not str(val).strip()):
        return pd.NaT
    try:
        dt = pd.to_datetime(val)
    except (ValueError, TypeError):
        return pd.NaT
    if dt is pd.NaT or pd.isna(dt):
        return pd.NaT
    return dt


def _as_date(val) -> Optional[date]:
    """Normalize a datelike value to datetime.date."""
    if _is_missing(val):
        return None
    if isinstance(val, date) and not isinstance(val, datetime):
        return val
    dt = _safe_to_datetime_raw(val)
    if dt is pd.NaT:
        return None
    return dt.date()


def _dates_equal(a, b) -> bool:
    """Compare two datelike values at calendar-day resolution."""
    da = _as_date(a)
    db = _as_date(b)
    if da is None or db is None:
        return False
    return da == db


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())
    if {"System Status", "Data Details"}.issubset(keys):
        return "system_status_data_details"
    return "unknown"


def _data_details(d: dict) -> dict:
    dd = d.get("Data Details")
    return dd if isinstance(dd, dict) else {}


# ── Status mapping ──────────────────────────────────────────────────────────

# System Status (as in DATA) → STATUS_NORMALIZED
_STATUS_MAP = {
    "Final": "Final",
    "Completed": "Final",
    "Issued": "Active",
    "Open": "In Review",
    "Estimate": "In Review",
    "Hold": "In Review",
    "B.L. HOLD": "In Review",
    "Expired": "Inactive",
    "Void": "Inactive",
    "Canceled": "Inactive",
}


# ── Per-record repair logic ─────────────────────────────────────────────────

def _repair_record(row, d: dict, repairs: dict):
    """Populate *repairs* with corrected values for a single Azusa record."""
    dd = _data_details(d)
    raw_status = d.get("System Status")
    if isinstance(raw_status, str):
        raw_status = raw_status.strip() or None
    expected = _STATUS_MAP.get(raw_status) if raw_status else None

    # -- STATUS_NORMALIZED --
    current_status = row["STATUS_NORMALIZED"]
    if expected is not None:
        if pd.isna(current_status):
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"
        elif current_status != expected:
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FIXED"

    effective_status = repairs.get("STATUS_NORMALIZED", current_status)

    app = _safe_to_datetime(dd.get("App. Date"))
    issue = _safe_to_datetime(dd.get("Issue Date"))
    final = _safe_to_datetime(dd.get("Final Date"))
    expire_raw = _safe_to_datetime_raw(dd.get("Expire Date"))

    # -- FILE_DATE (application / App. Date) --
    if app is not pd.NaT:
        app_date = app.date()
        if pd.isna(row["FILE_DATE"]):
            repairs["FILE_DATE"] = app_date
            repairs["FILE_DATE_FLAG"] = "FILLED"
        elif not _dates_equal(row["FILE_DATE"], app_date):
            repairs["FILE_DATE"] = app_date
            repairs["FILE_DATE_FLAG"] = "FIXED"

    # -- PERMIT_DATE (issuance / Issue Date) --
    if not pd.isna(row["PERMIT_DATE"]):
        if issue is not pd.NaT and not _dates_equal(row["PERMIT_DATE"], issue):
            repairs["PERMIT_DATE"] = issue.date()
            repairs["PERMIT_DATE_FLAG"] = "FIXED"
    elif effective_status in ("Active", "Final") and issue is not pd.NaT:
        repairs["PERMIT_DATE"] = issue.date()
        repairs["PERMIT_DATE_FLAG"] = "FILLED"

    # -- FINAL_DATE (finaled / Final Date; NOT Expire Date) --
    current_final = row["FINAL_DATE"]
    expire_derived = (
        not pd.isna(current_final)
        and expire_raw is not pd.NaT
        and _dates_equal(current_final, expire_raw)
        and (final is pd.NaT or not _dates_equal(current_final, final))
    )

    if effective_status == "Final":
        if final is not pd.NaT:
            final_date = final.date()
            if pd.isna(current_final):
                repairs["FINAL_DATE"] = final_date
                repairs["FINAL_DATE_FLAG"] = "FILLED"
            elif not _dates_equal(current_final, final_date):
                repairs["FINAL_DATE"] = final_date
                repairs["FINAL_DATE_FLAG"] = "FIXED"
        elif expire_derived:
            # No true Final Date; existing value is the validity window.
            repairs["FINAL_DATE"] = pd.NaT
            repairs["FINAL_DATE_FLAG"] = "FIXED"
    elif not pd.isna(current_final):
        # Spurious FINAL_DATE on non-Final rows (almost always Expire Date).
        repairs["FINAL_DATE"] = pd.NaT
        repairs["FINAL_DATE_FLAG"] = "FIXED"


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Azusa permit records using information from the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Azusa".  Must contain
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

    return out


# ── CLI: run standalone to preview repair stats ─────────────────────────────

if __name__ == "__main__":
    import os
    from dotenv import load_dotenv

    load_dotenv("/Users/ekung/projects/la-permits-data/.env")
    MY_DATA_PATH = os.getenv("MY_DATA_PATH")
    filepath = os.path.join(MY_DATA_PATH, "processed_data", "permits_la_sample.parquet")
    df = pd.read_parquet(filepath)
    azusa = df[(df["JURISDICTION"] == "Azusa") & (df["STATE"] == "CA")].copy()

    print(f"Azusa records: {len(azusa):,}\n")

    repaired = data_repair(azusa)

    print("INFERRED_SCHEMA:")
    print(repaired["INFERRED_SCHEMA"].value_counts(dropna=False).to_string())
    print()

    for field in ["STATUS_NORMALIZED", "FILE_DATE", "PERMIT_DATE", "FINAL_DATE"]:
        flag_col = f"{field}_FLAG"
        n_filled = (repaired[flag_col] == "FILLED").sum()
        n_fixed = (repaired[flag_col] == "FIXED").sum()
        print(f"{field}:")
        print(f"  FILLED: {n_filled:>4,}   FIXED: {n_fixed:>4,}")

        before_missing = azusa[field].isna().sum()
        after_missing = repaired[field].isna().sum()
        print(f"  Missing before: {before_missing:>4,}   Missing after: {after_missing:>4,}")
        print()

    print("STATUS_NORMALIZED distribution:")
    print("  Before:")
    for s, c in azusa["STATUS_NORMALIZED"].value_counts(dropna=False).items():
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

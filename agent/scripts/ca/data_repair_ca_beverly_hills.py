"""Data repair for Beverly Hills (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Beverly Hills DATA is a single portal schema (all sample rows share the
same top-level keys: Permit, activity, apn, archive, custom, divisions,
lso, people). Canonical fields:

  - activity.STATUS / Permit.STATUS (always equal) → STATUS_NORMALIZED
  - activity['APPLIED DATE']                       → FILE_DATE
  - activity['ISSUED DATE'] / Permit.ISSUED        → PERMIT_DATE
  - activity['FINAL DATE']                         → FINAL_DATE

``activity['PERMIT EXPIRATION DATE']`` is a permit-validity window, not
a finaling / completion date.

Known issues repaired:
  - STATUS_NORMALIZED missing for 25 unmapped raw statuses (RTI, Plan
    Review Withdrawn, Permanent, Garage Sale, etc.), plus 7 rows where
    raw STATUS is Final but STATUS_NORMALIZED was left Active.
  - FILE_DATE missing when APPLIED DATE is empty; fill from APPLIED
    DATE, else START DATE when available.
  - PERMIT_DATE missing for Active/Final rows that have ISSUED DATE.
  - FINAL_DATE was populated from PERMIT EXPIRATION DATE for ~1,421
    sample rows instead of FINAL DATE. Overwrite with FINAL DATE when
    present; clear Expire-derived / spurious values when FINAL DATE is
    absent or status is not Final.

Not repairable from DATA:
  - FILE_DATE gaps with no APPLIED DATE and no START DATE.
  - Active/Final PERMIT_DATE gaps with empty ISSUED DATE (mostly
    Approved / pre-issuance, plus some Final legacy rows).
  - Final rows with empty FINAL DATE (no true finaling date in DATA;
    expiration is not used as a proxy).
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
    if {"Permit", "activity"}.issubset(keys):
        return "permit_activity"
    return "unknown"


# ── Status mapping ──────────────────────────────────────────────────────────

# activity.STATUS / Permit.STATUS → STATUS_NORMALIZED
_STATUS_MAP = {
    "Final": "Final",
    "Issued": "Active",
    "Approved": "Active",
    "Approved For Garage Sale": "Active",
    "Permanent": "Final",
    "Withdrawn": "Inactive",
    "Plan Review Withdrawn": "Inactive",
    "Permit Ready to Issue (RTI)": "In Review",
    "Permit Approved": "In Review",
    "Investigation Pending": "In Review",
}


# ── Per-record repair logic ─────────────────────────────────────────────────

def _repair_record(row, d: dict, repairs: dict):
    """Populate *repairs* with corrected values for a single Beverly Hills record."""
    activity = d.get("activity") if isinstance(d.get("activity"), dict) else {}
    permit = d.get("Permit") if isinstance(d.get("Permit"), dict) else {}

    raw_status = activity.get("STATUS") or permit.get("STATUS")
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

    applied = _safe_to_datetime(activity.get("APPLIED DATE"))
    start = _safe_to_datetime(activity.get("START DATE"))
    issued = _safe_to_datetime(activity.get("ISSUED DATE"))
    if issued is pd.NaT:
        issued = _safe_to_datetime(permit.get("ISSUED"))
    final = _safe_to_datetime(activity.get("FINAL DATE"))
    expire_raw = _safe_to_datetime_raw(activity.get("PERMIT EXPIRATION DATE"))

    # -- FILE_DATE (application / APPLIED DATE; START DATE fallback) --
    file_src = applied if applied is not pd.NaT else start
    if file_src is not pd.NaT:
        file_date = file_src.date()
        if pd.isna(row["FILE_DATE"]):
            repairs["FILE_DATE"] = file_date
            repairs["FILE_DATE_FLAG"] = "FILLED"
        elif not _dates_equal(row["FILE_DATE"], file_date) and applied is not pd.NaT:
            # Only overwrite mismatches from the canonical APPLIED DATE.
            repairs["FILE_DATE"] = file_date
            repairs["FILE_DATE_FLAG"] = "FIXED"

    # -- PERMIT_DATE (issuance / ISSUED DATE) --
    if not pd.isna(row["PERMIT_DATE"]):
        if issued is not pd.NaT and not _dates_equal(row["PERMIT_DATE"], issued):
            repairs["PERMIT_DATE"] = issued.date()
            repairs["PERMIT_DATE_FLAG"] = "FIXED"
    elif effective_status in ("Active", "Final") and issued is not pd.NaT:
        repairs["PERMIT_DATE"] = issued.date()
        repairs["PERMIT_DATE_FLAG"] = "FILLED"

    # -- FINAL_DATE (finaled / FINAL DATE; NOT PERMIT EXPIRATION DATE) --
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
            # No true FINAL DATE; existing value is the validity window.
            repairs["FINAL_DATE"] = pd.NaT
            repairs["FINAL_DATE_FLAG"] = "FIXED"
    elif not pd.isna(current_final):
        # Spurious FINAL_DATE on non-Final rows (almost always expiration).
        repairs["FINAL_DATE"] = pd.NaT
        repairs["FINAL_DATE_FLAG"] = "FIXED"


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Beverly Hills permit records using information from the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Beverly Hills".  Must contain
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
    bh = df[(df["JURISDICTION"] == "Beverly Hills") & (df["STATE"] == "CA")].copy()

    print(f"Beverly Hills records: {len(bh):,}\n")

    repaired = data_repair(bh)

    print("INFERRED_SCHEMA:")
    print(repaired["INFERRED_SCHEMA"].value_counts(dropna=False).to_string())
    print()

    for field in ["STATUS_NORMALIZED", "FILE_DATE", "PERMIT_DATE", "FINAL_DATE"]:
        flag_col = f"{field}_FLAG"
        n_filled = (repaired[flag_col] == "FILLED").sum()
        n_fixed = (repaired[flag_col] == "FIXED").sum()
        print(f"{field}:")
        print(f"  FILLED: {n_filled:>4,}   FIXED: {n_fixed:>4,}")

        before_missing = bh[field].isna().sum()
        after_missing = repaired[field].isna().sum()
        print(f"  Missing before: {before_missing:>4,}   Missing after: {after_missing:>4,}")
        print()

    print("STATUS_NORMALIZED distribution:")
    print("  Before:")
    for s, c in bh["STATUS_NORMALIZED"].value_counts(dropna=False).items():
        print(f"    {str(s):15s}: {c:>4,}")
    print("  After:")
    for s, c in repaired["STATUS_NORMALIZED"].value_counts(dropna=False).items():
        print(f"    {str(s):15s}: {c:>4,}")

    print("\nFILE_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FILE_DATE"].notna().sum()
        n = len(sub)
        pct = n_has / n if n else 0.0
        print(f"  {status:15s}: {n_has:>4,} / {n:>4,} ({pct:.1%})")

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

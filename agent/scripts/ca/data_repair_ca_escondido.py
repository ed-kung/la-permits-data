"""Data repair for Escondido (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Escondido DATA is a flat civic-portal scrape. All sample rows share the
same top-level keys:

  Address, Applicant/Owner/Contractor, Applied, Parcel,
  Permit Description, Permit Number, Permit Type, Status,
  license number

Canonical mappings:
  - Status   → STATUS_NORMALIZED
  - Applied  → FILE_DATE

There is **no** issuance, approval, finaled, or sign-off date in DATA,
so PERMIT_DATE and FINAL_DATE cannot be recovered from the payload.

Content variants (INFERRED_SCHEMA):

  - portal_issued:        Status == ISSUED, Applied present
  - portal_finaled:       Status in {FINALED, CLOSED}, Applied present
  - portal_in_review:     pre-issuance Status with Applied present
  - portal_inactive:      Status == N/A, Applied present
  - portal_no_applied:    Applied blank / unparseable
  - missing

Known issues repaired:
  - Null STATUS_NORMALIZED on PRE-INTAKE / PAYMNT_DU / PLAN_APPR
    shells (142 rows) → FILLED as In Review.

Not repairable / left as-is:
  - FILE_DATE already matches Applied whenever Applied is parseable
    (1,921/1,921). 79 shells have blank Applied → FILE_DATE stays
    missing.
  - PERMIT_DATE is null for every row; DATA has no Issue/Issued date.
  - FINAL_DATE is null for every row; DATA has no Finaled/Closed date.
  - Existing STATUS_NORMALIZED values already match the Status map
    (ISSUED→Active, FINALED/CLOSED→Final, PENDING/REVIEW/INCOMPLETE/
    HOLD→In Review, N/A→Inactive); no FIXED status repairs.
"""

from __future__ import annotations

import json
import math
from typing import Optional

import numpy as np
import pandas as pd


_MIN_YEAR = 1990
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
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return pd.NaT
    if isinstance(val, str) and not str(val).strip():
        return pd.NaT
    try:
        dt = pd.to_datetime(val, errors="coerce")
    except (ValueError, TypeError):
        return pd.NaT
    if dt is pd.NaT or pd.isna(dt):
        return pd.NaT
    dt = pd.Timestamp(dt)
    if getattr(dt, "tzinfo", None) is not None:
        dt = dt.tz_convert("UTC").tz_localize(None)
    year = int(dt.year)
    if year < _MIN_YEAR or year > _MAX_YEAR:
        return pd.NaT
    return dt


def _dates_equal(a, b) -> bool:
    da = _safe_to_datetime(a)
    db = _safe_to_datetime(b)
    if da is pd.NaT or db is pd.NaT or pd.isna(da) or pd.isna(db):
        return False
    return da.normalize() == db.normalize()


def _raw_status(d: dict) -> str:
    s = d.get("Status")
    if s is None or (isinstance(s, float) and math.isnan(s)):
        return ""
    return str(s).strip()


def _applied_date(d: dict):
    return _safe_to_datetime(d.get("Applied"))


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())
    if "Status" not in keys and "Applied" not in keys:
        return "unknown"

    applied = _applied_date(data_dict)
    if applied is pd.NaT:
        return "portal_no_applied"

    status = _raw_status(data_dict).upper()
    if status == "ISSUED":
        return "portal_issued"
    if status in {"FINALED", "CLOSED"}:
        return "portal_finaled"
    if status == "N/A":
        return "portal_inactive"
    return "portal_in_review"


# ── Status mapping ──────────────────────────────────────────────────────────

# DATA.Status (uppercased as observed in the sample)
_STATUS_MAP = {
    # Final
    "FINALED": "Final",
    "CLOSED": "Final",
    # Active
    "ISSUED": "Active",
    # In Review (pre-issuance / workflow)
    "PENDING": "In Review",
    "REVIEW": "In Review",
    "INCOMPLETE": "In Review",
    "HOLD": "In Review",
    "PRE-INTAKE": "In Review",
    "PAYMNT_DU": "In Review",  # truncated "Payment Due"
    "PLAN_APPR": "In Review",  # truncated "Plan Approved"
    # Inactive
    "N/A": "Inactive",
}


def _expected_status(d: dict) -> Optional[str]:
    raw = _raw_status(d)
    if not raw:
        return None
    return _STATUS_MAP.get(raw.upper())


# ── Per-record repair ───────────────────────────────────────────────────────

def _repair_row(row, d: dict, repairs: dict) -> None:
    """Repair one Escondido record in-place into *repairs*."""
    expected = _expected_status(d)
    current_status = row["STATUS_NORMALIZED"]

    # -- STATUS_NORMALIZED --
    if expected is not None:
        if pd.isna(current_status):
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"
        elif current_status != expected:
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FIXED"

    # -- FILE_DATE --
    applied = _applied_date(d)
    if applied is not pd.NaT:
        if pd.isna(row["FILE_DATE"]):
            repairs["FILE_DATE"] = applied
            repairs["FILE_DATE_FLAG"] = "FILLED"
        elif not _dates_equal(row["FILE_DATE"], applied):
            repairs["FILE_DATE"] = applied
            repairs["FILE_DATE_FLAG"] = "FIXED"

    # -- PERMIT_DATE / FINAL_DATE --
    # Escondido DATA exposes no issuance or finaled stamps. Leave as-is.


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Escondido permit records using information from the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Escondido".  Must contain
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
        _repair_row(row, d, repairs)

        for key, value in repairs.items():
            out.at[idx, key] = value

    return out


# ── CLI: run standalone to preview repair stats ─────────────────────────────

if __name__ == "__main__":
    import os
    from dotenv import load_dotenv, find_dotenv

    load_dotenv(find_dotenv())
    MY_DATA_PATH = os.getenv("MY_DATA_PATH")
    filepath = os.path.join(
        MY_DATA_PATH, "processed_data", "permits_ca_sample.parquet"
    )
    df = pd.read_parquet(filepath)
    city = df[df["JURISDICTION"] == "Escondido"].copy()

    print(f"Escondido records: {len(city):,}\n")

    repaired = data_repair(city)

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
        pct = (n_has / n) if n else 0.0
        print(f"  {status:15s}: {n_has:>4,} / {n:>4,} ({pct:.1%})")

    print("\nFINAL_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FINAL_DATE"].notna().sum()
        n = len(sub)
        pct = (n_has / n) if n else 0.0
        print(f"  {status:15s}: {n_has:>4,} / {n:>4,} ({pct:.1%})")

    print("\nFILE_DATE coverage after repair:")
    n_has = repaired["FILE_DATE"].notna().sum()
    print(f"  {n_has:>4,} / {len(repaired):>4,} ({n_has/len(repaired):.1%})")

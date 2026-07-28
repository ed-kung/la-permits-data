"""Data repair for Santa Cruz County (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Santa Cruz County DATA is a flat county portal payload. All sample rows
share the same top-level keys: ``APN``, ``Review``, ``Issued Date``,
``Expiration Date``, ``Application Date``, ``Master Permit No``,
``Primary Applicant``, ``Application Number``, ``Application Status``,
``Project Description``. Canonical fields:

  - Application Status                        → STATUS_NORMALIZED
  - Application Date                          → FILE_DATE
  - Issued Date (when not "Not Yet Issued")   → PERMIT_DATE
  - (no finaled / completion date in DATA)    → FINAL_DATE unavailable

Content variants (same keys; differ by which dates are populated):

  - flat_app_issued:     Application Date + Issued Date present
  - flat_app_not_issued: Application Date present, Issued blank /
                         "Not Yet Issued"
  - flat_issued_no_app:  Issued Date present, Application Date blank
  - flat_empty_dates:    neither Application nor Issued usable
  - unknown / missing

Known issues repaired:
  - STATUS_NORMALIZED / STATUS_ORIGINAL entirely null in the sample
    → FILLED from Application Status.
  - FILE_DATE entirely null → FILLED from Application Date.
  - PERMIT_DATE entirely null on Active/Final → FILLED from Issued Date
    when parseable.

Not repairable from DATA:
  - No finaled / signoff / completion timestamp exists in the payload
    (``Review[].Last Rev`` is plan-review activity, typically on or
    before issuance) → FINAL_DATE stays missing for all Final rows.
  - ~27 Complete rows and other Active/Final shells with
    ``Issued Date`` = "Not Yet Issued" → PERMIT_DATE stays missing.
  - 7 rows lack Application Date → FILE_DATE stays missing.
"""

from __future__ import annotations

import json
import math
from typing import Optional

import numpy as np
import pandas as pd


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
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return pd.NaT
    if isinstance(val, str):
        s = val.strip()
        if not s or s.lower() in {"not yet issued", "tbd", "n/a", "none"}:
            return pd.NaT
    try:
        dt = pd.to_datetime(val, errors="coerce")
    except (ValueError, TypeError):
        return pd.NaT
    if dt is pd.NaT or pd.isna(dt):
        return pd.NaT
    if getattr(dt, "tzinfo", None) is not None:
        dt = dt.tz_convert("UTC").tz_localize(None)
    year = int(dt.year)
    if year < _MIN_YEAR or year > _MAX_YEAR:
        return pd.NaT
    return dt


def _dates_equal(a, b) -> bool:
    da = _safe_to_datetime(a)
    db = _safe_to_datetime(b)
    if da is pd.NaT or db is pd.NaT:
        return False
    return da.normalize() == db.normalize()


def _is_blank(val) -> bool:
    if val is None:
        return True
    if isinstance(val, float) and math.isnan(val):
        return True
    if isinstance(val, str) and not val.strip():
        return True
    return False


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())
    if "Application Status" not in keys and "Application Date" not in keys:
        return "unknown"

    has_app = _safe_to_datetime(data_dict.get("Application Date")) is not pd.NaT
    has_iss = _safe_to_datetime(data_dict.get("Issued Date")) is not pd.NaT

    if has_app and has_iss:
        return "flat_app_issued"
    if has_app and not has_iss:
        return "flat_app_not_issued"
    if has_iss and not has_app:
        return "flat_issued_no_app"
    return "flat_empty_dates"


# ── Status mapping ───────────────────────────────────────────────────────────

# Application Status → STATUS_NORMALIZED
_STATUS_MAP = {
    "Complete": "Final",
    "Inspections": "Active",
    "Prior to Final": "Active",
    "Issue Children Permit": "Active",
    "Ready to Issue": "In Review",
    "Resubmittal": "In Review",
    "Routing": "In Review",
    "Waiting on MasterApp": "In Review",
    "Collect Fees": "In Review",
    "Consolidation-Evaluation": "In Review",
    "VOID": "Inactive",
    "Withdrawn": "Inactive",
    "Surrender": "Inactive",
}


def _expected_status(d: dict) -> Optional[str]:
    raw = d.get("Application Status")
    if _is_blank(raw):
        return None
    return _STATUS_MAP.get(str(raw).strip())


def _application_date(d: dict):
    return _safe_to_datetime(d.get("Application Date"))


def _issued_date(d: dict):
    return _safe_to_datetime(d.get("Issued Date"))


# ── Per-record repair logic ─────────────────────────────────────────────────

def _repair_record(row, d: dict, repairs: dict):
    current_status = row["STATUS_NORMALIZED"]
    expected = _expected_status(d)

    # -- STATUS_NORMALIZED --
    if expected is not None:
        if pd.isna(current_status):
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"
        elif current_status != expected:
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FIXED"

    effective_status = repairs.get("STATUS_NORMALIZED", current_status)

    # -- FILE_DATE --
    app_dt = _application_date(d)
    if app_dt is not pd.NaT:
        if pd.isna(row["FILE_DATE"]):
            repairs["FILE_DATE"] = app_dt
            repairs["FILE_DATE_FLAG"] = "FILLED"
        elif not _dates_equal(row["FILE_DATE"], app_dt):
            repairs["FILE_DATE"] = app_dt
            repairs["FILE_DATE_FLAG"] = "FIXED"

    # -- PERMIT_DATE --
    iss_dt = _issued_date(d)
    if effective_status in ("Active", "Final"):
        if iss_dt is not pd.NaT:
            if pd.isna(row["PERMIT_DATE"]):
                repairs["PERMIT_DATE"] = iss_dt
                repairs["PERMIT_DATE_FLAG"] = "FILLED"
            elif not _dates_equal(row["PERMIT_DATE"], iss_dt):
                repairs["PERMIT_DATE"] = iss_dt
                repairs["PERMIT_DATE_FLAG"] = "FIXED"
    elif not pd.isna(row["PERMIT_DATE"]) and effective_status in ("In Review",):
        # In Review should not carry an issuance date when DATA says
        # Not Yet Issued; clear spurious values if present.
        if iss_dt is pd.NaT:
            repairs["PERMIT_DATE"] = pd.NaT
            repairs["PERMIT_DATE_FLAG"] = "FIXED"

    # -- FINAL_DATE --
    # No finaled / completion / signoff field exists in this DATA schema.
    # Leave FINAL_DATE untouched (typically null).


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Santa Cruz County permit records using information from the raw DATA
    JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Santa Cruz County".  Must
        contain columns STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE,
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
    filepath = os.path.join(MY_DATA_PATH, "processed_data", "permits_ca_sample.parquet")
    df = pd.read_parquet(filepath)
    scc = df[df["JURISDICTION"] == "Santa Cruz County"].copy()

    print(f"Santa Cruz County records: {len(scc):,}\n")

    repaired = data_repair(scc)

    print("INFERRED_SCHEMA:")
    for s, c in repaired["INFERRED_SCHEMA"].value_counts(dropna=False).items():
        print(f"  {str(s):30s}: {c:>4,}")
    print()

    for field in ["STATUS_NORMALIZED", "FILE_DATE", "PERMIT_DATE", "FINAL_DATE"]:
        flag_col = f"{field}_FLAG"
        n_filled = (repaired[flag_col] == "FILLED").sum()
        n_fixed = (repaired[flag_col] == "FIXED").sum()
        print(f"{field}:")
        print(f"  FILLED: {n_filled:>4,}   FIXED: {n_fixed:>4,}")

        before_missing = scc[field].isna().sum()
        after_missing = repaired[field].isna().sum()
        print(f"  Missing before: {before_missing:>4,}   Missing after: {after_missing:>4,}")
        print()

    print("STATUS_NORMALIZED distribution:")
    print("  Before:")
    for s, c in scc["STATUS_NORMALIZED"].value_counts(dropna=False).items():
        print(f"    {str(s):15s}: {c:>4,}")
    print("  After:")
    for s, c in repaired["STATUS_NORMALIZED"].value_counts(dropna=False).items():
        print(f"    {str(s):15s}: {c:>4,}")

    print("\nFINAL_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FINAL_DATE"].notna().sum()
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

    print("\nFILE_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FILE_DATE"].notna().sum()
        n = len(sub)
        pct = n_has / n if n else 0.0
        print(f"  {status:15s}: {n_has:>4,} / {n:>4,} ({pct:.1%})")

    # Chronology checks
    print("\nChronology issues after repair:")
    file_dt = pd.to_datetime(repaired["FILE_DATE"], errors="coerce")
    permit_dt = pd.to_datetime(repaired["PERMIT_DATE"], errors="coerce")
    final_dt = pd.to_datetime(repaired["FINAL_DATE"], errors="coerce")
    n_pf = ((permit_dt.notna()) & (file_dt.notna()) & (permit_dt < file_dt)).sum()
    n_fp = ((final_dt.notna()) & (permit_dt.notna()) & (final_dt < permit_dt)).sum()
    print(f"  PERMIT < FILE: {n_pf}")
    print(f"  FINAL < PERMIT: {n_fp}")

"""Data repair for El Segundo (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

El Segundo DATA is a single flat portal schema (all sample rows share the
same top-level keys: contacts, fees, inspections, permit_info,
search_data, site_info). Canonical fields:

  - permit_info.PermitStatus       → STATUS_NORMALIZED
  - permit_info.PermitAppliedDate  → FILE_DATE
      (search_data.Application is identical when present)
  - permit_info.PermitIssuedDate   → PERMIT_DATE
      (fallback: PermitApprovedDate; search_data.Issued matches Issued)
  - permit_info.PermitFinaledDate  → FINAL_DATE

``PermitExpirationDate`` is a permit-validity window, not a finaling /
completion date. Inspections are null for all sample rows.

Known issues repaired:
  - STATUS_NORMALIZED is null for APPLICATION GENERATED (4 sample rows)
    → In Review.
  - 15 rows have PermitFinaledDate but STATUS_NORMALIZED is Active
    (ISSUED/APPROVED) or Inactive (EXPIRED/WITHDRAWN) → Final.
  - PERMIT_DATE missing on Active/Final when Issued is empty but
    Approved is present → fill from PermitApprovedDate.

Not repairable from DATA:
  - 10 rows (SUBMITTED/WITHDRAWN) have empty Applied/Application dates.
  - 25 FINALED rows lack PermitFinaledDate; Expiration is not used as
    a proxy.
  - Some Active/Final rows lack both Issued and Approved dates.
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


def _as_date(val) -> Optional[date]:
    """Normalize a datelike value to datetime.date."""
    if _is_missing(val):
        return None
    if isinstance(val, date) and not isinstance(val, datetime):
        return val
    if isinstance(val, pd.Timestamp):
        if pd.isna(val):
            return None
        return val.date()
    dt = _safe_to_datetime(val)
    if dt is pd.NaT or pd.isna(dt):
        return None
    return dt.date()


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())
    if {"permit_info", "search_data"}.issubset(keys):
        return "permit_info_search_data"
    return "unknown"


# ── Status mapping ──────────────────────────────────────────────────────────

# permit_info.PermitStatus (uppercased) → STATUS_NORMALIZED
_STATUS_MAP = {
    "FINALED": "Final",
    "ISSUED": "Active",
    "APPROVED": "Active",
    "SUBMITTED": "In Review",
    "APPLIED": "In Review",
    "PC FEES DUE": "In Review",
    "APPLICATION GENERATED": "In Review",
    "EXPIRED": "Inactive",
    "PERMIT EXP": "Inactive",
    "WITHDRAWN": "Inactive",
    "CANCELLED": "Inactive",
}


def _permit_info(d: dict) -> dict:
    pi = d.get("permit_info")
    return pi if isinstance(pi, dict) else {}


def _search_data(d: dict) -> dict:
    sd = d.get("search_data")
    return sd if isinstance(sd, dict) else {}


def _derive_status(pi: dict) -> Optional[str]:
    """Map PermitStatus to STATUS_NORMALIZED; prefer Final when finaled."""
    raw = pi.get("PermitStatus")
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        status = None
    else:
        status = _STATUS_MAP.get(str(raw).strip().upper())

    # A populated finaled date is stronger evidence of completion than a
    # stale ISSUED / EXPIRED / WITHDRAWN portal label.
    if _as_date(pi.get("PermitFinaledDate")) is not None:
        return "Final"
    return status


def _preferred_file_date(pi: dict, sd: dict) -> Optional[date]:
    applied = _as_date(pi.get("PermitAppliedDate"))
    if applied is not None:
        return applied
    return _as_date(sd.get("Application"))


def _preferred_permit_date(pi: dict, sd: dict) -> Optional[date]:
    issued = _as_date(pi.get("PermitIssuedDate"))
    if issued is not None:
        return issued
    issued_sd = _as_date(sd.get("Issued"))
    if issued_sd is not None:
        return issued_sd
    return _as_date(pi.get("PermitApprovedDate"))


def _preferred_final_date(pi: dict) -> Optional[date]:
    return _as_date(pi.get("PermitFinaledDate"))


# ── Per-record repair logic ─────────────────────────────────────────────────

def _repair_record(row, d: dict, repairs: dict):
    """Populate *repairs* with corrected values for a single El Segundo record."""
    pi = _permit_info(d)
    sd = _search_data(d)

    # -- STATUS_NORMALIZED --
    current_status = row["STATUS_NORMALIZED"]
    expected = _derive_status(pi)
    if expected is not None:
        if pd.isna(current_status):
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"
        elif current_status != expected:
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FIXED"

    effective_status = repairs.get("STATUS_NORMALIZED", current_status)

    # -- FILE_DATE --
    preferred_fd = _preferred_file_date(pi, sd)
    current_fd = _as_date(row["FILE_DATE"])
    if preferred_fd is not None:
        if current_fd is None:
            repairs["FILE_DATE"] = pd.Timestamp(preferred_fd)
            repairs["FILE_DATE_FLAG"] = "FILLED"
        elif current_fd != preferred_fd:
            repairs["FILE_DATE"] = pd.Timestamp(preferred_fd)
            repairs["FILE_DATE_FLAG"] = "FIXED"

    # -- PERMIT_DATE --
    preferred_pd = _preferred_permit_date(pi, sd)
    current_pd = _as_date(row["PERMIT_DATE"])
    if preferred_pd is not None:
        if current_pd is None:
            if effective_status in ("Active", "Final"):
                repairs["PERMIT_DATE"] = pd.Timestamp(preferred_pd)
                repairs["PERMIT_DATE_FLAG"] = "FILLED"
        elif current_pd != preferred_pd:
            repairs["PERMIT_DATE"] = pd.Timestamp(preferred_pd)
            repairs["PERMIT_DATE_FLAG"] = "FIXED"

    # -- FINAL_DATE --
    preferred_final = _preferred_final_date(pi)
    current_final = _as_date(row["FINAL_DATE"])
    if preferred_final is not None:
        if current_final is None:
            if effective_status == "Final":
                repairs["FINAL_DATE"] = pd.Timestamp(preferred_final)
                repairs["FINAL_DATE_FLAG"] = "FILLED"
        elif current_final != preferred_final:
            repairs["FINAL_DATE"] = pd.Timestamp(preferred_final)
            repairs["FINAL_DATE_FLAG"] = "FIXED"
    elif current_final is not None and effective_status != "Final":
        # Clear final dates on non-Final rows when DATA has no FinaledDate
        # (should be rare after status override for finaled rows).
        repairs["FINAL_DATE"] = pd.NaT
        repairs["FINAL_DATE_FLAG"] = "FIXED"


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    El Segundo permit records using information from the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "El Segundo".  Must contain
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
    city = df[(df["JURISDICTION"] == "El Segundo") & (df["STATE"] == "CA")].copy()

    print(f"El Segundo records: {len(city):,}\n")

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
        pct = n_has / n if n else 0.0
        print(f"  {status:15s}: {n_has:>4,} / {n:>4,} ({pct:.1%})")

    print("\nFINAL_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FINAL_DATE"].notna().sum()
        n = len(sub)
        pct = n_has / n if n else 0.0
        print(f"  {status:15s}: {n_has:>4,} / {n:>4,} ({pct:.1%})")

    print("\nFILE_DATE coverage (after repair):")
    n_has = repaired["FILE_DATE"].notna().sum()
    print(f"  {n_has:>4,} / {len(repaired):>4,} ({n_has/len(repaired):.1%})")

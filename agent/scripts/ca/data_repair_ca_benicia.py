"""Data repair for Benicia (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Benicia DATA is a CitizenServe / SmartGov-style payload with top-level
keys ``main``, ``extra``, and ``location``. Content variants
(INFERRED_SCHEMA):

  - past_building_accela_dates: migrated Accela building row with
    Status and/or issuance/final ASI dates (28084 / 28061)
  - past_building_file_only: migrated building row with File Date only
  - past_public_works_accela_dates: migrated PW row with Status and/or
    29411 status date
  - past_public_works_file_only: migrated PW row with File Date only
  - past_business / past_planning / past_fire / past_enforcement:
    other Accela migrations (no usable permit/final dates)
  - citizenserve_with_status: modern form with Permit Status /
    Current Permit Status / Status
  - citizenserve_modern: modern form without status fields
  - unknown / missing

Canonical mappings:
  - main.status (0/1/2/-1), refined by Accela/form Status fields
                                                      → STATUS_NORMALIZED
  - main.dateSubmitted (else dateCreated / File Date) → FILE_DATE
  - extra['28084'] when Accela Status is Issued/Finaled
    extra['29411'] when Accela Status is Issued
    extra['28084'] when Status absent but 28082=COMPLETE
                                                      → PERMIT_DATE
  - extra['28061'] when Accela Status is Finaled
    extra['29411'] when Accela Status is Finaled (PW)
    max(* Date Completed) on modern Final rows        → FINAL_DATE

Known issues repaired:
  - FILE_DATE was taken from main.dateCreated. When dateSubmitted
    falls on a later calendar day (52 sample rows), overwrite with
    the submittal date.
  - Past Record Accela Status Expired/Withdrawn left as Final because
    main.status=2 (complete) → FIXED to Inactive.
  - Past Record Accela Status Issued left as Final → FIXED to Active.
  - Modern Active rows with in-review form statuses (Need More
    Information, Correction List Generated, Payment Pending, …)
    → FIXED to In Review.
  - Modern Expired/Declined form status left as Active
    → FIXED to Inactive.
  - PERMIT_DATE / FINAL_DATE universally missing; fill from Accela
    ASI dates and (rarely) modern Date Completed fields.
  - When Finaled building ASI dates are inverted (28084 after 28061),
    skip 28084 as PERMIT_DATE but still use 28061 as FINAL_DATE.

Not repairable from DATA:
  - Vast majority of Past Record rows lack Accela Status and ASI
    issue/final dates → PERMIT_DATE / FINAL_DATE stay missing.
  - Modern CitizenServe forms generally carry no issuance or
    finaling timestamp.
  - Business / Planning past records have no usable permit/final
    dates (only File Date equivalents).
"""

from __future__ import annotations

import json
import math
import re
from datetime import date, datetime
from typing import Optional

import numpy as np
import pandas as pd


_MIN_YEAR = 1900
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
    if isinstance(val, dict):
        return pd.NaT
    if isinstance(val, str):
        s = val.strip()
        if not s or s.upper() == "TBD":
            return pd.NaT
    try:
        dt = pd.to_datetime(val, errors="coerce")
    except (ValueError, TypeError):
        return pd.NaT
    if pd.isna(dt):
        return pd.NaT
    year = int(dt.year)
    if year < _MIN_YEAR or year > _MAX_YEAR:
        return pd.NaT
    return dt


def _utc_date(val) -> Optional[date]:
    """Parse a timestamp and return its UTC calendar date."""
    if val is None or (isinstance(val, str) and not val.strip()):
        return None
    try:
        ts = pd.to_datetime(val, utc=True, errors="coerce")
    except (ValueError, TypeError):
        return None
    if pd.isna(ts):
        return None
    year = int(ts.year)
    if year < _MIN_YEAR or year > _MAX_YEAR:
        return None
    return ts.date()


def _as_date(val) -> Optional[date]:
    """Normalize a FILE_DATE-like value to datetime.date."""
    if _is_missing(val):
        return None
    if isinstance(val, date) and not isinstance(val, datetime):
        return val
    dt = _safe_to_datetime(val)
    if dt is pd.NaT:
        return None
    if getattr(dt, "tzinfo", None) is not None:
        dt = dt.tz_convert("UTC") if hasattr(dt, "tz_convert") else dt
        return dt.date()
    return dt.date()


def _is_past_record(main: dict) -> bool:
    rtype = main.get("recordTypeName") or ""
    return rtype.startswith("Past Record")


def _accela_raw_status(extra: dict) -> Optional[str]:
    """Prefer Accela Status, then modern Permit Status fields."""
    for key in ("Status", "Permit Status", "Current Permit Status"):
        val = extra.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return None


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())
    if not {"main", "extra", "location"}.issubset(keys):
        if "main" in keys:
            return "main_only"
        return "unknown"

    main = data_dict.get("main") or {}
    extra = data_dict.get("extra") or {}
    if not isinstance(main, dict):
        main = {}
    if not isinstance(extra, dict):
        extra = {}

    rtype = main.get("recordTypeName") or ""
    prefix = main.get("prefix") or ""
    has_accela_status = bool(_accela_raw_status(extra))
    has_bldg_dates = "28084" in extra or "28061" in extra
    has_pw_dates = "29411" in extra

    if rtype.startswith("Past Record - Building") or prefix.startswith("PBLD"):
        if has_accela_status or has_bldg_dates:
            return "past_building_accela_dates"
        return "past_building_file_only"
    if rtype.startswith("Past Record - Business") or prefix.startswith("PBUS"):
        return "past_business"
    if rtype.startswith("Past Record - Public Works") or prefix.startswith("PPW"):
        if has_accela_status or has_pw_dates:
            return "past_public_works_accela_dates"
        return "past_public_works_file_only"
    if rtype.startswith("Past Record - Planning") or prefix.startswith("PPLN"):
        return "past_planning"
    if rtype.startswith("Past Record - Fire"):
        return "past_fire"
    if rtype.startswith("Past Record - Enforcement"):
        return "past_enforcement"
    if has_accela_status:
        return "citizenserve_with_status"
    return "citizenserve_modern"


# ── Status mapping ──────────────────────────────────────────────────────────

# main.status (int) → STATUS_NORMALIZED
_STATUS_CODE_MAP = {
    0: "In Review",  # draft
    1: "Active",     # active
    2: "Final",      # complete
    -1: "Inactive",  # stopped
}

# Accela / form status text → STATUS_NORMALIZED
_ACCELA_STATUS_MAP = {
    "finaled": "Final",
    "closed": "Final",
    "issued": "Active",
    "ready to issue": "Active",
    "expired": "Inactive",
    "withdrawn": "Inactive",
    "declined": "Inactive",
    "in review": "In Review",
    "submitted": "In Review",
    "correction list generated": "In Review",
    "need more information": "In Review",
    "payment pending": "In Review",
    "awaiting applicant response": "In Review",
    "courtesy notice sent": "In Review",
}


def _status_from_main(main: dict) -> Optional[str]:
    status = main.get("status")
    if status is None:
        return None
    try:
        code = int(status)
    except (TypeError, ValueError):
        return None
    return _STATUS_CODE_MAP.get(code)


def _derive_status(main: dict, extra: dict) -> Optional[str]:
    """Derive STATUS_NORMALIZED from CitizenServe + Accela/form status.

    Past Record migrations set main.status=2 (complete) indiscriminately,
    so Accela Status in extra is authoritative when present. Modern
    CitizenServe rows trust main.status, with narrow overrides for clear
    Inactive / still-in-review form statuses.
    """
    base = _status_from_main(main)
    raw = _accela_raw_status(extra)
    if not raw:
        return base
    mapped = _ACCELA_STATUS_MAP.get(raw.lower())
    if mapped is None:
        return base

    if _is_past_record(main):
        return mapped

    if mapped == "Inactive":
        return "Inactive"
    if base == "Active" and mapped == "In Review":
        return "In Review"
    if base == "Inactive" and mapped == "Final":
        return "Final"
    # Do not demote Final→Active on stale Permit Status=Issued
    return base


def _preferred_file_date(main: dict, extra: dict) -> Optional[date]:
    """Application/submittal date: dateSubmitted, else dateCreated, else File Date."""
    submitted = _utc_date(main.get("dateSubmitted"))
    if submitted is not None:
        return submitted
    created = _utc_date(main.get("dateCreated"))
    if created is not None:
        return created
    file_date = _safe_to_datetime(extra.get("File Date"))
    if file_date is not pd.NaT:
        return file_date.date()
    return None


def _modern_final_date(extra: dict):
    """Latest non-empty '* Date Completed' form field, if any."""
    dates = []
    for key, val in extra.items():
        if not re.search(r"Date Completed", str(key)):
            continue
        dt = _safe_to_datetime(val)
        if dt is not pd.NaT:
            dates.append(dt)
    if not dates:
        return pd.NaT
    return max(dates)


def _permit_date_from_extra(extra: dict, raw_status: Optional[str]):
    """Issuance date from Accela ASI fields when status supports it.

    For Finaled building rows, ``28084`` is treated as issuance only when it
    does not fall after ``28061`` (completion). A handful of migrated rows
    invert that order; those ``28084`` values are skipped as unreliable.
    """
    status_l = (raw_status or "").lower()
    d84 = _safe_to_datetime(extra.get("28084"))
    d61 = _safe_to_datetime(extra.get("28061"))
    d29411 = _safe_to_datetime(extra.get("29411"))

    if status_l in ("issued", "finaled"):
        if d84 is not pd.NaT:
            if status_l == "finaled" and d61 is not pd.NaT:
                if d84.normalize() > d61.normalize():
                    d84 = pd.NaT
            if d84 is not pd.NaT:
                return d84
        # Public Works Issued uses 29411 as the post-file status/issue date
        if status_l == "issued" and d29411 is not pd.NaT:
            return d29411

    # Migrated building rows marked COMPLETE without Accela Status
    if not raw_status and extra.get("28082") == "COMPLETE" and d84 is not pd.NaT:
        return d84

    return pd.NaT


def _final_date_from_extra(extra: dict, raw_status: Optional[str], effective_status: str):
    """Finaling date from Accela ASI or modern Date Completed fields."""
    status_l = (raw_status or "").lower()
    d61 = _safe_to_datetime(extra.get("28061"))
    d84 = _safe_to_datetime(extra.get("28084"))
    d29411 = _safe_to_datetime(extra.get("29411"))

    if status_l == "finaled":
        # Building: 28061 is completion; 28084 is issuance (do not reuse)
        if d61 is not pd.NaT:
            return d61
        # Public Works Finaled: 29411 is the final status date
        if d84 is pd.NaT and d29411 is not pd.NaT:
            return d29411

    if effective_status == "Final":
        modern = _modern_final_date(extra)
        if modern is not pd.NaT:
            return modern

    return pd.NaT


# ── Per-record repair logic ─────────────────────────────────────────────────

def _repair_record(row, d: dict, repairs: dict):
    """Populate *repairs* with corrected values for a single Benicia record."""
    main = d.get("main") or {}
    extra = d.get("extra") or {}
    if not isinstance(main, dict):
        main = {}
    if not isinstance(extra, dict):
        extra = {}

    raw_status = _accela_raw_status(extra)

    # -- STATUS_NORMALIZED --
    current_status = row["STATUS_NORMALIZED"]
    expected = _derive_status(main, extra)
    if expected is not None:
        if pd.isna(current_status):
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"
        elif current_status != expected:
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FIXED"

    effective_status = repairs.get("STATUS_NORMALIZED", current_status)

    # -- FILE_DATE --
    preferred = _preferred_file_date(main, extra)
    current_fd = _as_date(row["FILE_DATE"])
    if preferred is not None:
        if current_fd is None:
            repairs["FILE_DATE"] = pd.Timestamp(preferred)
            repairs["FILE_DATE_FLAG"] = "FILLED"
        elif current_fd != preferred:
            repairs["FILE_DATE"] = pd.Timestamp(preferred)
            repairs["FILE_DATE_FLAG"] = "FIXED"

    # -- PERMIT_DATE --
    permit_dt = _permit_date_from_extra(extra, raw_status)
    if permit_dt is not pd.NaT:
        if pd.isna(row["PERMIT_DATE"]):
            repairs["PERMIT_DATE"] = permit_dt
            repairs["PERMIT_DATE_FLAG"] = "FILLED"
        else:
            cur_pd = _safe_to_datetime(row["PERMIT_DATE"])
            if cur_pd is pd.NaT or cur_pd.normalize() != permit_dt.normalize():
                repairs["PERMIT_DATE"] = permit_dt
                repairs["PERMIT_DATE_FLAG"] = "FIXED"

    # -- FINAL_DATE --
    final_dt = _final_date_from_extra(extra, raw_status, effective_status)
    if final_dt is not pd.NaT:
        if pd.isna(row["FINAL_DATE"]):
            repairs["FINAL_DATE"] = final_dt
            repairs["FINAL_DATE_FLAG"] = "FILLED"
        else:
            cur_fd_final = _safe_to_datetime(row["FINAL_DATE"])
            if cur_fd_final is pd.NaT or cur_fd_final.normalize() != final_dt.normalize():
                repairs["FINAL_DATE"] = final_dt
                repairs["FINAL_DATE_FLAG"] = "FIXED"


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Benicia permit records using information from the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Benicia".  Must contain
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
    filepath = os.path.join(MY_DATA_PATH, "processed_data", "permits_ca_sample.parquet")
    df = pd.read_parquet(filepath)
    benicia = df[(df["JURISDICTION"] == "Benicia") & (df["STATE"] == "CA")].copy()

    print(f"Benicia records: {len(benicia):,}\n")

    repaired = data_repair(benicia)

    print("INFERRED_SCHEMA:")
    print(repaired["INFERRED_SCHEMA"].value_counts(dropna=False).to_string())
    print()

    for field in ["STATUS_NORMALIZED", "FILE_DATE", "PERMIT_DATE", "FINAL_DATE"]:
        flag_col = f"{field}_FLAG"
        n_filled = (repaired[flag_col] == "FILLED").sum()
        n_fixed = (repaired[flag_col] == "FIXED").sum()
        print(f"{field}:")
        print(f"  FILLED: {n_filled:>4,}   FIXED: {n_fixed:>4,}")

        before_missing = benicia[field].isna().sum()
        after_missing = repaired[field].isna().sum()
        print(f"  Missing before: {before_missing:>4,}   Missing after: {after_missing:>4,}")
        print()

    print("STATUS_NORMALIZED distribution:")
    print("  Before:")
    for s, c in benicia["STATUS_NORMALIZED"].value_counts(dropna=False).items():
        print(f"    {str(s):15s}: {c:>4,}")
    print("  After:")
    for s, c in repaired["STATUS_NORMALIZED"].value_counts(dropna=False).items():
        print(f"    {str(s):15s}: {c:>4,}")

    print("\nStatus transitions (before → after):")
    mask = repaired["STATUS_NORMALIZED_FLAG"].notna()
    if mask.any():
        transitions = (
            pd.DataFrame({
                "before": benicia.loc[mask, "STATUS_NORMALIZED"].astype(str),
                "after": repaired.loc[mask, "STATUS_NORMALIZED"].astype(str),
            })
            .value_counts()
            .reset_index(name="n")
        )
        for _, trow in transitions.iterrows():
            print(f"  {trow['before']:15s} → {trow['after']:15s}: {trow['n']:>4,}")

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

    print("\nFILE_DATE coverage:", f"{repaired['FILE_DATE'].notna().mean():.1%}")

    # Chronology checks
    pdf = repaired.copy()
    pdf["_fd"] = pd.to_datetime(pdf["FILE_DATE"], errors="coerce")
    pdf["_pd"] = pd.to_datetime(pdf["PERMIT_DATE"], errors="coerce")
    pdf["_fid"] = pd.to_datetime(pdf["FINAL_DATE"], errors="coerce")
    both_fp = pdf["_fd"].notna() & pdf["_pd"].notna()
    both_pf = pdf["_pd"].notna() & pdf["_fid"].notna()
    print("\nChronology:")
    print(f"  PERMIT_DATE < FILE_DATE: {(pdf.loc[both_fp, '_pd'].dt.normalize() < pdf.loc[both_fp, '_fd'].dt.normalize()).sum()}")
    print(f"  FINAL_DATE < PERMIT_DATE: {(pdf.loc[both_pf, '_fid'].dt.normalize() < pdf.loc[both_pf, '_pd'].dt.normalize()).sum()}")
    print(f"  FINAL_DATE < FILE_DATE: {(pdf['_fid'].notna() & pdf['_fd'].notna() & (pdf['_fid'].dt.normalize() < pdf['_fd'].dt.normalize())).sum()}")

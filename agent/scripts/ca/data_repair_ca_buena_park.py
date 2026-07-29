"""Data repair for Buena Park (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Buena Park DATA is a CitizenServe / OpenGov-style payload with top-level
keys ``main``, ``extra``, and ``location``. Content variants
(INFERRED_SCHEMA):

  - citizenserve_finaled_dates: parseable extra['Date Finaled']
  - citizenserve_issued_dates:  parseable extra['Date Issued'], no finaled
  - citizenserve_status_form:   extra Status and/or Date Applied only
  - citizenserve_form_other:    other form fields (CE, planning, …)
  - citizenserve_empty_extra:   empty extra dict
  - unknown / missing

Canonical mappings:
  - main.status (0/1/2/-1), refined by extra['Status'] and date evidence
                                                      → STATUS_NORMALIZED
  - main.dateSubmitted (else dateCreated / Date Applied)
                                                      → FILE_DATE
  - extra['Date Issued'] (skip when after Date Finaled)
                                                      → PERMIT_DATE
  - extra['Date Finaled'] when effective status is Final
                                                      → FINAL_DATE

Known issues repaired:
  - FILE_DATE was taken from main.dateCreated. When dateSubmitted falls
    on a later calendar day → FIXED to the submittal date.
  - Active rows with extra Status FINALED (and Date Finaled) left Active
    → FIXED to Final.
  - Active rows with PLAN CHECK / DUE / APPLIED / PAID / INVEST and no
    Date Issued left Active → FIXED to In Review.
  - Active/Final rows with EXPIRED / CANCELED / VOID → FIXED to Inactive.
  - Final rows with ISSUED / APPROVED and no Date Finaled → FIXED to Active.
  - In Review rows with ISSUED (or Date Issued) → FIXED to Active.
  - PERMIT_DATE / FINAL_DATE universally missing; fill from Date Issued /
    Date Finaled when present.

Not repairable from DATA:
  - Majority of CitizenServe forms (CE, planning inquiries, modern
    building shells) lack Date Issued / Date Finaled → dates stay missing.
  - One FINALED row has Date Finaled before Date Issued; PERMIT_DATE is
    skipped as unreliable, FINAL_DATE is still filled.
"""

from __future__ import annotations

import json
import math
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
    if getattr(dt, "tzinfo", None) is not None:
        dt = dt.tz_convert("UTC").tz_localize(None)
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
    if dt is pd.NaT or pd.isna(dt):
        return None
    if getattr(dt, "tzinfo", None) is not None:
        dt = dt.tz_convert("UTC") if hasattr(dt, "tz_convert") else dt
        return dt.date()
    return dt.date()


def _extra_status_raw(extra: dict) -> Optional[str]:
    val = extra.get("Status")
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

    extra = data_dict.get("extra") or {}
    if not isinstance(extra, dict):
        extra = {}
    if not extra:
        return "citizenserve_empty_extra"

    has_finaled = _safe_to_datetime(extra.get("Date Finaled")) is not pd.NaT
    has_issued = _safe_to_datetime(extra.get("Date Issued")) is not pd.NaT
    has_applied = _safe_to_datetime(extra.get("Date Applied")) is not pd.NaT
    has_status = _extra_status_raw(extra) is not None

    if has_finaled:
        return "citizenserve_finaled_dates"
    if has_issued:
        return "citizenserve_issued_dates"
    if has_status or has_applied:
        return "citizenserve_status_form"
    return "citizenserve_form_other"


# ── Status mapping ──────────────────────────────────────────────────────────

# main.status (int) → STATUS_NORMALIZED
_STATUS_CODE_MAP = {
    0: "In Review",  # draft
    1: "Active",     # active
    2: "Final",      # complete
    -1: "Inactive",  # stopped
}

# extra['Status'] (uppercased) → STATUS_NORMALIZED
_EXTRA_STATUS_MAP = {
    "FINALED": "Final",
    "ISSUED": "Active",
    "APPROVED": "Active",
    "RENEWAL": "Active",
    "EXPIRED": "Inactive",
    "CANCELED": "Inactive",
    "VOID": "Inactive",
    "PLAN CHECK": "In Review",
    "DUE": "In Review",
    "APPLIED": "In Review",
    "PAID": "In Review",
    "INVEST": "In Review",
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
    """Derive STATUS_NORMALIZED from CitizenServe main.status + form status.

    ``main.status`` is the portal lifecycle code and matches STATUS_ORIGINAL
    (draft/active/complete/stopped). When ``extra['Status']`` or issuance /
    finaling dates contradict that code, prefer the richer form evidence:
    Date Finaled / FINALED → Final; EXPIRED/CANCELED/VOID → Inactive;
    ISSUED/APPROVED demotes stale Final shells without a finaled date;
    in-review form labels demote Active only when no Date Issued exists.
    """
    base = _status_from_main(main)
    raw = _extra_status_raw(extra)
    mapped = _EXTRA_STATUS_MAP.get(raw.upper()) if raw else None
    date_finaled = _safe_to_datetime(extra.get("Date Finaled"))
    date_issued = _safe_to_datetime(extra.get("Date Issued"))
    has_finaled = date_finaled is not pd.NaT and not pd.isna(date_finaled)
    has_issued = date_issued is not pd.NaT and not pd.isna(date_issued)

    if has_finaled and mapped != "Inactive":
        return "Final"
    if mapped == "Inactive":
        return "Inactive"
    if mapped == "Final":
        return "Final"
    if mapped == "Active":
        if base == "Final" and not has_finaled:
            return "Active"
        if base in ("In Review", "Active", None) or (
            isinstance(base, float) and pd.isna(base)
        ):
            return "Active"
        return base
    if mapped == "In Review":
        # Issuance date outweighs a stale plan-check / fee label.
        if has_issued and base in ("Active", "Final"):
            return "Final" if has_finaled else "Active"
        if base == "Active":
            return "In Review"
        # DUE/PAID on complete BLDG Miscellaneous rows are fee labels.
        if base == "Final":
            return "Final"
        return base or "In Review"

    if has_finaled:
        return "Final"
    if has_issued and base == "In Review":
        return "Active"
    return base


def _preferred_file_date(main: dict, extra: dict) -> Optional[date]:
    """Application/submittal date: dateSubmitted, else dateCreated, else Date Applied."""
    submitted = _utc_date(main.get("dateSubmitted"))
    if submitted is not None:
        return submitted
    created = _utc_date(main.get("dateCreated"))
    if created is not None:
        return created
    applied = _safe_to_datetime(extra.get("Date Applied"))
    if applied is not pd.NaT and not pd.isna(applied):
        return applied.date()
    return None


def _permit_date_from_extra(extra: dict):
    """Issuance date from Date Issued; skip when it falls after Date Finaled."""
    issued = _safe_to_datetime(extra.get("Date Issued"))
    if issued is pd.NaT or pd.isna(issued):
        return pd.NaT
    finaled = _safe_to_datetime(extra.get("Date Finaled"))
    if finaled is not pd.NaT and not pd.isna(finaled):
        if issued.normalize() > finaled.normalize():
            return pd.NaT
    return issued


def _final_date_from_extra(extra: dict, effective_status):
    """Finaling date from Date Finaled when status is Final."""
    if effective_status != "Final":
        return pd.NaT
    return _safe_to_datetime(extra.get("Date Finaled"))


# ── Per-record repair logic ─────────────────────────────────────────────────

def _repair_record(row, d: dict, repairs: dict):
    """Populate *repairs* with corrected values for a single Buena Park record."""
    main = d.get("main") or {}
    extra = d.get("extra") or {}
    if not isinstance(main, dict):
        main = {}
    if not isinstance(extra, dict):
        extra = {}

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
    permit_dt = _permit_date_from_extra(extra)
    if permit_dt is not pd.NaT and not pd.isna(permit_dt):
        if pd.isna(row["PERMIT_DATE"]):
            repairs["PERMIT_DATE"] = permit_dt
            repairs["PERMIT_DATE_FLAG"] = "FILLED"
        else:
            cur_pd = _safe_to_datetime(row["PERMIT_DATE"])
            if cur_pd is pd.NaT or pd.isna(cur_pd) or cur_pd.normalize() != permit_dt.normalize():
                repairs["PERMIT_DATE"] = permit_dt
                repairs["PERMIT_DATE_FLAG"] = "FIXED"

    # -- FINAL_DATE --
    final_dt = _final_date_from_extra(extra, effective_status)
    if final_dt is not pd.NaT and not pd.isna(final_dt):
        if pd.isna(row["FINAL_DATE"]):
            repairs["FINAL_DATE"] = final_dt
            repairs["FINAL_DATE_FLAG"] = "FILLED"
        else:
            cur_fd_final = _safe_to_datetime(row["FINAL_DATE"])
            if (
                cur_fd_final is pd.NaT
                or pd.isna(cur_fd_final)
                or cur_fd_final.normalize() != final_dt.normalize()
            ):
                repairs["FINAL_DATE"] = final_dt
                repairs["FINAL_DATE_FLAG"] = "FIXED"


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Buena Park permit records using information from the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Buena Park".  Must contain
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
    buena_park = df[(df["JURISDICTION"] == "Buena Park") & (df["STATE"] == "CA")].copy()

    print(f"Buena Park records: {len(buena_park):,}\n")

    repaired = data_repair(buena_park)

    print("INFERRED_SCHEMA:")
    print(repaired["INFERRED_SCHEMA"].value_counts(dropna=False).to_string())
    print()

    for field in ["STATUS_NORMALIZED", "FILE_DATE", "PERMIT_DATE", "FINAL_DATE"]:
        flag_col = f"{field}_FLAG"
        n_filled = (repaired[flag_col] == "FILLED").sum()
        n_fixed = (repaired[flag_col] == "FIXED").sum()
        print(f"{field}:")
        print(f"  FILLED: {n_filled:>4,}   FIXED: {n_fixed:>4,}")

        before_missing = buena_park[field].isna().sum()
        after_missing = repaired[field].isna().sum()
        print(f"  Missing before: {before_missing:>4,}   Missing after: {after_missing:>4,}")
        print()

    print("STATUS_NORMALIZED distribution:")
    print("  Before:")
    for s, c in buena_park["STATUS_NORMALIZED"].value_counts(dropna=False).items():
        print(f"    {str(s):15s}: {c:>4,}")
    print("  After:")
    for s, c in repaired["STATUS_NORMALIZED"].value_counts(dropna=False).items():
        print(f"    {str(s):15s}: {c:>4,}")

    print("\nStatus transitions (before → after):")
    mask = repaired["STATUS_NORMALIZED_FLAG"].notna()
    if mask.any():
        transitions = (
            pd.DataFrame({
                "before": buena_park.loc[mask, "STATUS_NORMALIZED"].astype(str),
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

    pdf = repaired.copy()
    pdf["_fd"] = pd.to_datetime(pdf["FILE_DATE"], errors="coerce")
    pdf["_pd"] = pd.to_datetime(pdf["PERMIT_DATE"], errors="coerce")
    pdf["_fid"] = pd.to_datetime(pdf["FINAL_DATE"], errors="coerce")
    both_fp = pdf["_fd"].notna() & pdf["_pd"].notna()
    both_pf = pdf["_pd"].notna() & pdf["_fid"].notna()
    print("\nChronology:")
    print(
        f"  PERMIT_DATE < FILE_DATE: "
        f"{(pdf.loc[both_fp, '_pd'].dt.normalize() < pdf.loc[both_fp, '_fd'].dt.normalize()).sum()}"
    )
    print(
        f"  FINAL_DATE < PERMIT_DATE: "
        f"{(pdf.loc[both_pf, '_fid'].dt.normalize() < pdf.loc[both_pf, '_pd'].dt.normalize()).sum()}"
    )
    print(
        f"  FINAL_DATE < FILE_DATE: "
        f"{(pdf['_fid'].notna() & pdf['_fd'].notna() & (pdf['_fid'].dt.normalize() < pdf['_fd'].dt.normalize())).sum()}"
    )

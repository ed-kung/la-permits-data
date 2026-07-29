"""Data repair for Cypress (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Cypress DATA is a CitizenServe / OpenGov-style payload with top-level
keys ``main``, ``extra``, and ``location``. Content variants
(INFERRED_SCHEMA):

  - citizenserve_inspection_final: parseable extra['Inspection Final Date']
  - citizenserve_building_trade:   building / trade / ADU / TI / tract forms
  - citizenserve_solar:            solar / SolarAPP+ forms
  - citizenserve_debris:           Construction Debris Disposal (C&D)
  - citizenserve_public_works:     Public Works forms
  - citizenserve_daily_activity:   Building and Safety Daily Activity
  - citizenserve_transport:        transportation / oversize parking
  - citizenserve_records_request:  Request a Copy of a Building Permit
  - citizenserve_fog:              Fats, Oils, and Grease (FOG)
  - citizenserve_stormwater:       stormwater quality / requirements
  - citizenserve_numeric_legacy:   mostly numeric OpenGov field IDs
  - citizenserve_form_other:       other named form fields
  - empty_extra / unknown / missing

Canonical mappings:
  - main.status (0/1/2/-1) → STATUS_NORMALIZED
  - main.dateSubmitted (else dateCreated) → FILE_DATE
  - (none reliable) → PERMIT_DATE
  - extra['Inspection Final Date'] when effective status is Final
                                                      → FINAL_DATE

Known issues repaired:
  - STATUS_NORMALIZED was derived from STATUS_ORIGINAL (active / draft /
    complete / stopped), which can lag the live numeric main.status.
    11 sample rows have status=2 (complete) still labeled Active → FIXED.
  - FILE_DATE was taken from main.dateCreated. When dateSubmitted falls
    on a later calendar day → FIXED to the submittal date.
  - FINAL_DATE universally missing; fill from Inspection Final Date on
    Final Tenant Improvement rows when present.

Not repairable from DATA:
  - No Date Issued / Date Finaled / Accela-style Status fields (unlike
    Buena Park). expirationDate is a validity window (~180/365 days after
    an unobserved issue stamp). lastUpdatedDate reflects later edits.
    Unlabeled numeric ASI dates (26368 / 26796) and TCO Expiration Date
    track temporary CO / form stamps, not issuance or finaling — do not
    use as PERMIT_DATE / FINAL_DATE.
  - Public Works / Transportation extra['Date'] mirrors applicant
    submittal, not approval.
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
        if not s or s.upper() in {"TBD", "NULL", "NONE", "N/A", "NA"}:
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
    if val is None or (isinstance(val, str) and not str(val).strip()):
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


def _main(d: dict) -> dict:
    main = d.get("main")
    return main if isinstance(main, dict) else {}


def _extra(d: dict) -> dict:
    extra = d.get("extra")
    return extra if isinstance(extra, dict) else {}


# ── Schema classification ───────────────────────────────────────────────────

_BUILDING_TRADE_FRAGMENTS = (
    "building",
    "electrical",
    "plumbing",
    "mechanical",
    "reroof",
    "roof",
    "water heater",
    "heating",
    "air conditioning",
    "pool",
    "spa",
    "patio",
    "window",
    "skylight",
    "adu",
    "accessory dwelling",
    "tenant improvement",
    "tract",
    "block wall",
    "demolition",
    "charging station",
    "remodel",
)


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    if not isinstance(data_dict, dict) or "main" not in data_dict:
        return "unknown"

    extra = _extra(data_dict)
    if not extra:
        return "empty_extra"

    main = _main(data_dict)
    rt = (main.get("recordTypeName") or "").strip().lower()
    keys = list(extra.keys())

    if _safe_to_datetime(extra.get("Inspection Final Date")) is not pd.NaT:
        return "citizenserve_inspection_final"

    if "solarapp" in rt or "solar" in rt:
        return "citizenserve_solar"
    if "debris" in rt or "c&d" in rt:
        return "citizenserve_debris"
    if "daily activity" in rt:
        return "citizenserve_daily_activity"
    if "public works" in rt:
        return "citizenserve_public_works"
    if "transport" in rt or "oversize" in rt or "parking permit" in rt:
        return "citizenserve_transport"
    if "request a copy" in rt:
        return "citizenserve_records_request"
    if "fog" in rt or "fats" in rt or "grease" in rt:
        return "citizenserve_fog"
    if "stormwater" in rt:
        return "citizenserve_stormwater"
    if any(frag in rt for frag in _BUILDING_TRADE_FRAGMENTS):
        return "citizenserve_building_trade"

    n_numeric = sum(1 for k in keys if isinstance(k, str) and k.isdigit())
    if keys and n_numeric >= max(1, len(keys) // 2):
        return "citizenserve_numeric_legacy"

    return "citizenserve_form_other"


# ── Status mapping ──────────────────────────────────────────────────────────

# main.status (int) → STATUS_NORMALIZED
_STATUS_CODE_MAP = {
    0: "In Review",  # draft
    1: "Active",     # active
    2: "Final",      # complete
    -1: "Inactive",  # stopped
}


def _derive_status(main: dict) -> Optional[str]:
    """Map CitizenServe portal lifecycle code to STATUS_NORMALIZED.

    Cypress has no Accela-style extra Status / Date Issued / Date Finaled
    fields to refine against. Prefer live ``main.status`` over lagged
    STATUS_ORIGINAL strings.
    """
    status = main.get("status")
    if status is None:
        return None
    try:
        code = int(status)
    except (TypeError, ValueError):
        return None
    return _STATUS_CODE_MAP.get(code)


def _preferred_file_date(main: dict) -> Optional[date]:
    """Application/submittal date: dateSubmitted, else dateCreated."""
    submitted = _utc_date(main.get("dateSubmitted"))
    if submitted is not None:
        return submitted
    return _utc_date(main.get("dateCreated"))


def _final_date_from_extra(extra: dict, effective_status):
    """Finaling date from Inspection Final Date when status is Final."""
    if effective_status != "Final":
        return pd.NaT
    return _safe_to_datetime(extra.get("Inspection Final Date"))


# ── Per-record repair logic ─────────────────────────────────────────────────

def _repair_record(row, d: dict, repairs: dict):
    """Populate *repairs* with corrected values for a single Cypress record."""
    main = _main(d)
    extra = _extra(d)

    # -- STATUS_NORMALIZED --
    current_status = row["STATUS_NORMALIZED"]
    expected = _derive_status(main)
    if expected is not None:
        if pd.isna(current_status):
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"
        elif current_status != expected:
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FIXED"

    effective_status = repairs.get("STATUS_NORMALIZED", current_status)

    # -- FILE_DATE --
    preferred = _preferred_file_date(main)
    current_fd = _as_date(row["FILE_DATE"])
    if preferred is not None:
        if current_fd is None:
            repairs["FILE_DATE"] = pd.Timestamp(preferred)
            repairs["FILE_DATE_FLAG"] = "FILLED"
        elif current_fd != preferred:
            repairs["FILE_DATE"] = pd.Timestamp(preferred)
            repairs["FILE_DATE_FLAG"] = "FIXED"

    # -- PERMIT_DATE --
    # No reliable issuance/approval timestamp in DATA; leave as-is.

    # -- FINAL_DATE --
    final_dt = _final_date_from_extra(extra, effective_status)
    if final_dt is not pd.NaT and not pd.isna(final_dt):
        if pd.isna(row["FINAL_DATE"]):
            repairs["FINAL_DATE"] = final_dt
            repairs["FINAL_DATE_FLAG"] = "FILLED"
        else:
            cur_final = _safe_to_datetime(row["FINAL_DATE"])
            if (
                cur_final is pd.NaT
                or pd.isna(cur_final)
                or cur_final.normalize() != final_dt.normalize()
            ):
                repairs["FINAL_DATE"] = final_dt
                repairs["FINAL_DATE_FLAG"] = "FIXED"
    elif (
        effective_status != "Final"
        and not pd.isna(row["FINAL_DATE"])
    ):
        repairs["FINAL_DATE"] = pd.NaT
        repairs["FINAL_DATE_FLAG"] = "FIXED"


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Cypress permit records using information from the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Cypress".  Must contain
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
    AGENT_DATA_PATH = os.getenv("AGENT_DATA_PATH")
    filepath = os.path.join(MY_DATA_PATH, "processed_data", "permits_ca_sample.parquet")
    df = pd.read_parquet(filepath)
    cypress = df[(df["JURISDICTION"] == "Cypress") & (df["STATE"] == "CA")].copy()

    print(f"Cypress records: {len(cypress):,}\n")

    repaired = data_repair(cypress)

    print("INFERRED_SCHEMA:")
    print(repaired["INFERRED_SCHEMA"].value_counts(dropna=False).to_string())
    print()

    for field in ["STATUS_NORMALIZED", "FILE_DATE", "PERMIT_DATE", "FINAL_DATE"]:
        flag_col = f"{field}_FLAG"
        n_filled = (repaired[flag_col] == "FILLED").sum()
        n_fixed = (repaired[flag_col] == "FIXED").sum()
        print(f"{field}:")
        print(f"  FILLED: {n_filled:>4,}   FIXED: {n_fixed:>4,}")

        before_missing = cypress[field].isna().sum()
        after_missing = repaired[field].isna().sum()
        print(f"  Missing before: {before_missing:>4,}   Missing after: {after_missing:>4,}")
        print()

    print("STATUS_NORMALIZED distribution:")
    print("  Before:")
    for s, c in cypress["STATUS_NORMALIZED"].value_counts(dropna=False).items():
        print(f"    {str(s):15s}: {c:>4,}")
    print("  After:")
    for s, c in repaired["STATUS_NORMALIZED"].value_counts(dropna=False).items():
        print(f"    {str(s):15s}: {c:>4,}")

    # Status transitions
    transitions = {}
    for idx in cypress.index:
        before = cypress.at[idx, "STATUS_NORMALIZED"]
        after = repaired.at[idx, "STATUS_NORMALIZED"]
        if before != after:
            key = (str(before), str(after))
            transitions[key] = transitions.get(key, 0) + 1
    if transitions:
        print("\nStatus transitions (FIXED):")
        for (b, a), n in sorted(transitions.items(), key=lambda x: -x[1]):
            print(f"  {b} → {a}: {n}")

    print("\nFILE_DATE coverage:")
    n_has = repaired["FILE_DATE"].notna().sum()
    print(f"  {n_has:,} / {len(repaired):,} ({n_has / len(repaired):.1%})")

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

    # Chronology checks
    rep = repaired.copy()
    for col in ["FILE_DATE", "PERMIT_DATE", "FINAL_DATE"]:
        rep[col] = pd.to_datetime(rep[col], errors="coerce")
    both_pf = rep["PERMIT_DATE"].notna() & rep["FILE_DATE"].notna()
    both_fp = rep["FINAL_DATE"].notna() & rep["PERMIT_DATE"].notna()
    print(f"\nPERMIT_DATE < FILE_DATE: {(rep.loc[both_pf, 'PERMIT_DATE'] < rep.loc[both_pf, 'FILE_DATE']).sum()}")
    print(f"FINAL_DATE < PERMIT_DATE: {(rep.loc[both_fp, 'FINAL_DATE'] < rep.loc[both_fp, 'PERMIT_DATE']).sum()}")

    if AGENT_DATA_PATH:
        out_dir = os.path.join(AGENT_DATA_PATH, "repaired")
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, "permits_ca_cypress_repaired.parquet")
        for col in ["FILE_DATE", "PERMIT_DATE", "FINAL_DATE"]:
            repaired[col] = pd.to_datetime(repaired[col], errors="coerce")
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote {out_path}")

"""Data repair for Avenal (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Avenal DATA is an OpenGov / SmartGov-style payload with top-level keys
``main``, ``extra``, and ``location``.  ``extra`` content varies by
record type (used as INFERRED_SCHEMA):

  - business_license_form:  business license fields
                            (Type of Business, Start Date of Business …)
  - building_form:          named building fields (Type of Construction, …)
  - building_numeric:       Building / trade permits with numeric OpenGov IDs
  - encroachment_form:      encroachment fields
                            (Type of Encroachment, Acceptance of Conditions, …)
  - solar_form:             SolarAPP+ permit fields
  - temporary_event_form:   temporary use / special-event applications
  - planning_form:          Uniform Application / variance / lot-line fields
  - code_enforcement_form:  code-enforcement complaint / violation fields
  - numeric_legacy:         other numeric OpenGov field IDs
  - other_form / empty_extra / unknown / missing

Canonical mappings:
  - main.status (-1/0/1/2) → STATUS_NORMALIZED
  - main.dateSubmitted (else dateCreated) → FILE_DATE
  - (none) → PERMIT_DATE
  - (none) → FINAL_DATE

Known issues repaired:
  - STATUS_NORMALIZED was derived from STATUS_ORIGINAL (active / draft /
    complete / stopped), which can lag the live numeric main.status.
    49 sample rows disagree (mostly status=2 complete still labeled
    Active, and status=1 active still labeled Final) → FIXED to the
    code map.
  - FILE_DATE was taken from dateCreated; when dateSubmitted falls on a
    later calendar day (209 rows) → FIXED to the submittal date.

Not repairable / left as-is:
  - PERMIT_DATE and FINAL_DATE are universally missing.  No issuance or
    finaling timestamps exist in main or extra.  Form dates (Clerk Date,
    business start, expirations, acceptance-of-conditions) and
    lastUpdatedDate are not safe proxies for approval or finaling.
"""

from __future__ import annotations

import json
import math
from datetime import date, datetime
from typing import Optional

import numpy as np
import pandas as pd


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
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return pd.NaT
    if isinstance(val, str) and not str(val).strip():
        return pd.NaT
    try:
        return pd.to_datetime(val)
    except (ValueError, TypeError):
        return pd.NaT


def _utc_date(val) -> Optional[date]:
    """Parse a timestamp and return its UTC calendar date."""
    if val is None or (isinstance(val, str) and not str(val).strip()):
        return None
    try:
        ts = pd.to_datetime(val, utc=True)
    except (ValueError, TypeError):
        return None
    if pd.isna(ts):
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
        return dt.tz_convert("UTC").date()
    return dt.date()


def _main(d: dict) -> dict:
    main = d.get("main")
    return main if isinstance(main, dict) else {}


def _extra(d: dict) -> dict:
    extra = d.get("extra")
    return extra if isinstance(extra, dict) else {}


# ── Schema classification ───────────────────────────────────────────────────

_BUILDING_RT_FRAGMENTS = (
    "building",
    "electrical",
    "plumbing",
    "mechanical",
    "roof",
    "demolition",
    "certificate of occupancy",
)

_PLANNING_RT_FRAGMENTS = (
    "uniform application",
    "lot line",
    "variance",
)


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    if not isinstance(data_dict, dict) or "main" not in data_dict:
        return "unknown"

    extra = _extra(data_dict)
    if not extra:
        return "empty_extra"

    keys = set(extra.keys())
    main = _main(data_dict)
    rt = (main.get("recordTypeName") or "").strip().lower()

    if (
        "Start Date of Business in Avenal" in keys
        or "Type of Business" in keys
        or "Business Name " in keys
    ):
        return "business_license_form"
    if "Type of Construction" in keys or "Description of Work" in keys:
        return "building_form"
    if (
        "Type of Encroachment" in keys
        or "Date of Acceptance of Conditions:" in keys
        or "Complete Description of All Proposed Work:" in keys
        or "Current Permit Status" in keys
    ):
        return "encroachment_form"
    if "SolarAPP+ Approval ID" in keys or "solarapp" in rt:
        return "solar_form"
    if (
        "Description of Violation:" in keys
        or "code enforcement" in rt
    ):
        return "code_enforcement_form"
    if (
        "temporary permit" in rt
        or "temporary use" in rt
        or "special events" in rt
    ):
        return "temporary_event_form"
    if any(frag in rt for frag in _PLANNING_RT_FRAGMENTS):
        return "planning_form"
    if any(isinstance(k, str) and k.isdigit() for k in keys):
        if any(frag in rt for frag in _BUILDING_RT_FRAGMENTS):
            return "building_numeric"
        return "numeric_legacy"
    return "other_form"


# ── Status mapping ──────────────────────────────────────────────────────────

# main.status (int) → STATUS_NORMALIZED
_STATUS_CODE_MAP = {
    0: "In Review",   # draft
    1: "Active",      # active
    2: "Final",       # complete
    -1: "Inactive",   # stopped
}


def _derive_status(main: dict) -> Optional[str]:
    status = main.get("status")
    if status is None:
        return None
    try:
        code = int(status)
    except (TypeError, ValueError):
        return None
    return _STATUS_CODE_MAP.get(code)


def _preferred_file_date(main: dict) -> Optional[date]:
    """Application/submittal date: prefer dateSubmitted, else dateCreated."""
    submitted = _utc_date(main.get("dateSubmitted"))
    if submitted is not None:
        return submitted
    return _utc_date(main.get("dateCreated"))


# ── Per-record repair logic ─────────────────────────────────────────────────

def _repair_record(row, d: dict, repairs: dict):
    """Populate *repairs* with corrected values for a single Avenal record."""
    main = _main(d)

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
    # No issuance/approval date in DATA; leave as-is.

    # -- FINAL_DATE --
    # No finaling/completion/signoff date in DATA; leave as-is.


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Avenal permit records using information from the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Avenal".  Must contain
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
    avenal = df[(df["JURISDICTION"] == "Avenal") & (df["STATE"] == "CA")].copy()

    print(f"Avenal records: {len(avenal):,}\n")

    repaired = data_repair(avenal)

    print("INFERRED_SCHEMA:")
    print(repaired["INFERRED_SCHEMA"].value_counts(dropna=False).to_string())
    print()

    for field in ["STATUS_NORMALIZED", "FILE_DATE", "PERMIT_DATE", "FINAL_DATE"]:
        flag_col = f"{field}_FLAG"
        n_filled = (repaired[flag_col] == "FILLED").sum()
        n_fixed = (repaired[flag_col] == "FIXED").sum()
        print(f"{field}:")
        print(f"  FILLED: {n_filled:>4,}   FIXED: {n_fixed:>4,}")

        before_missing = avenal[field].isna().sum()
        after_missing = repaired[field].isna().sum()
        print(f"  Missing before: {before_missing:>4,}   Missing after: {after_missing:>4,}")
        print()

    print("STATUS_NORMALIZED distribution:")
    print("  Before:")
    for s, c in avenal["STATUS_NORMALIZED"].value_counts(dropna=False).items():
        print(f"    {str(s):15s}: {c:>4,}")
    print("  After:")
    for s, c in repaired["STATUS_NORMALIZED"].value_counts(dropna=False).items():
        print(f"    {str(s):15s}: {c:>4,}")

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

    final_sub = repaired[repaired["STATUS_NORMALIZED"] == "Final"]
    print(f"\nFinal still missing PERMIT_DATE: {final_sub['PERMIT_DATE'].isna().sum()}")
    print(f"Final still missing FINAL_DATE:  {final_sub['FINAL_DATE'].isna().sum()}")

    if AGENT_DATA_PATH:
        out_dir = os.path.join(AGENT_DATA_PATH, "repaired")
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, "permits_ca_avenal_repaired.parquet")
        for col in ["FILE_DATE", "PERMIT_DATE", "FINAL_DATE"]:
            repaired[col] = pd.to_datetime(repaired[col], errors="coerce")
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote {out_path}")

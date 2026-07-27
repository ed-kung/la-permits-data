"""Data repair for Arvin (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Arvin DATA is an OpenGov / SmartGov-style payload with top-level keys
``main``, ``extra``, and ``location``.  ``extra`` content varies by
record type (used as INFERRED_SCHEMA):

  - building_form:          building permit form fields
                            (Description of Work, Type of Construction, …);
                            may also carry numeric OpenGov field IDs
  - encroachment_form:      encroachment / grading fields
                            (Requested Start Date:, Current Permit Status, …)
  - planning_form:          Master Planning / site-development fields
                            (Zoning District, Site Plan Fee, …)
  - code_enforcement_form:  code-enforcement workflow fields
  - numeric_legacy:         numeric OpenGov field IDs without named forms
  - other_form / empty_extra / unknown / missing

Canonical mappings:
  - main.status (-1/0/1/2) → STATUS_NORMALIZED
  - main.dateSubmitted (else dateCreated) → FILE_DATE
  - (none) → PERMIT_DATE
  - (none) → FINAL_DATE

Known issues repaired:
  - STATUS_NORMALIZED was derived from STATUS_ORIGINAL (active / draft /
    complete / stopped), which can lag the live numeric main.status.
    36 sample rows disagree (mostly status=2 complete still labeled
    Active) → FIXED to the code map.
  - FILE_DATE was taken from dateCreated; when dateSubmitted falls on a
    later calendar day (53 rows) → FIXED to the submittal date.

Not repairable / left as-is:
  - PERMIT_DATE and FINAL_DATE are universally missing.  No issuance or
    finaling timestamps exist in main or extra.  expirationDate is a
    validity window (~1 year after an internal event), and
    lastUpdatedDate reflects later edits — neither is a safe proxy.
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

def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    if not isinstance(data_dict, dict) or "main" not in data_dict:
        return "unknown"

    extra = _extra(data_dict)
    if not extra:
        return "empty_extra"

    keys = set(extra.keys())
    # Named form signatures first — building forms also carry numeric IDs.
    if "Description of Work" in keys or "Type of Construction" in keys:
        return "building_form"
    if (
        "Requested Start Date:" in keys
        or "Requested Completion Date:" in keys
        or "Complete Description of All Proposed Work:" in keys
        or "Current Permit Status" in keys
    ):
        return "encroachment_form"
    if "Close Out Violation (no futher steps needed in workflow)" in keys:
        return "code_enforcement_form"
    if (
        "Site Plan Fee" in keys
        or "Proposed Project" in keys
        or "Zoning District" in keys
    ):
        return "planning_form"
    if any(isinstance(k, str) and k.isdigit() for k in keys):
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
    """Populate *repairs* with corrected values for a single Arvin record."""
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
    Arvin permit records using information from the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Arvin".  Must contain
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
    arvin = df[(df["JURISDICTION"] == "Arvin") & (df["STATE"] == "CA")].copy()

    print(f"Arvin records: {len(arvin):,}\n")

    repaired = data_repair(arvin)

    print("INFERRED_SCHEMA:")
    print(repaired["INFERRED_SCHEMA"].value_counts(dropna=False).to_string())
    print()

    for field in ["STATUS_NORMALIZED", "FILE_DATE", "PERMIT_DATE", "FINAL_DATE"]:
        flag_col = f"{field}_FLAG"
        n_filled = (repaired[flag_col] == "FILLED").sum()
        n_fixed = (repaired[flag_col] == "FIXED").sum()
        print(f"{field}:")
        print(f"  FILLED: {n_filled:>4,}   FIXED: {n_fixed:>4,}")

        before_missing = arvin[field].isna().sum()
        after_missing = repaired[field].isna().sum()
        print(f"  Missing before: {before_missing:>4,}   Missing after: {after_missing:>4,}")
        print()

    print("STATUS_NORMALIZED distribution:")
    print("  Before:")
    for s, c in arvin["STATUS_NORMALIZED"].value_counts(dropna=False).items():
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
        out_path = os.path.join(AGENT_DATA_PATH, "arvin_repaired_sample.parquet")
        for col in ["FILE_DATE", "PERMIT_DATE", "FINAL_DATE"]:
            repaired[col] = pd.to_datetime(repaired[col], errors="coerce")
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote {out_path}")

"""Data repair for Seminole County (FL) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Seminole County DATA is a sparse city/county portal payload with a single
key-set schema on every sample row:

  - fees_detail: top-level keys fees / detail / fees_total

Canonical fields (all under detail):

  - Application          → STATUS_NORMALIZED
  - Application Date     → FILE_DATE

There are no Issue Date, Permit Date, C.O. / completion, or inspection
arrays in DATA, so PERMIT_DATE and FINAL_DATE cannot be recovered.

Application values observed:
  - PERMIT COMPLETE / CLOSED / CERTIFICATE OF OCCUPANCY /
    CERTIFICATE OF COMPLETION → Final
  - PERMIT ISSUED → Active
  - IN PLAN CHECK / ON HOLD / APPROVED / IN APPROVAL → In Review
  - VOIDED → Inactive

INFERRED_SCHEMA further suffixes fees_detail by Application family
(complete / closed / co / cc / issued / plan_check / on_hold /
approved / in_approval / voided).

Known issues repaired:
  - STATUS_NORMALIZED (and STATUS_ORIGINAL) are null for every row —
    upstream never mapped detail.Application. All 2,001 rows are
    FILLED from Application.

Not repairable from DATA:
  - FILE_DATE already equals Application Date for every row.
  - No issuance or finalization timestamp → PERMIT_DATE and
    FINAL_DATE stay missing (including all Active / Final rows).
"""

from __future__ import annotations

import json
import math
import re
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
        try:
            parsed = json.loads(data)
        except (json.JSONDecodeError, TypeError):
            return None
        return parsed if isinstance(parsed, dict) else None
    return data if isinstance(data, dict) else None


def _safe_to_datetime(val):
    """Parse a date value, returning pd.NaT on failure / blanks / OOR."""
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return pd.NaT
    if isinstance(val, dict):
        return pd.NaT
    if isinstance(val, str):
        s = val.strip()
        if not s or s.upper() in {
            "TBD", "NULL", "NONE", "N/A", "NA", "NAN",
            "00/00/0000", "0/0/0000",
        }:
            return pd.NaT
    try:
        dt = pd.to_datetime(val, errors="coerce")
    except (ValueError, TypeError, OverflowError):
        return pd.NaT
    if pd.isna(dt):
        return pd.NaT
    year = int(dt.year)
    if year < _MIN_YEAR or year > _MAX_YEAR:
        return pd.NaT
    return dt


def _dates_equal(a, b) -> bool:
    """Compare two datelike values at calendar-day resolution."""
    da = _safe_to_datetime(a)
    db = _safe_to_datetime(b)
    if da is pd.NaT or db is pd.NaT:
        return False
    return da.normalize() == db.normalize()


def _detail(d: dict) -> dict:
    detail = d.get("detail")
    return detail if isinstance(detail, dict) else {}


# ── Status mapping ───────────────────────────────────────────────────────────

_STATUS_MAP = {
    "PERMIT COMPLETE": "Final",
    "CLOSED": "Final",
    "CERTIFICATE OF OCCUPANCY": "Final",
    "CERTIFICATE OF COMPLETION": "Final",
    "PERMIT ISSUED": "Active",
    "IN PLAN CHECK": "In Review",
    "ON HOLD": "In Review",
    # Plans/application approved but not yet issued (distinct from PERMIT ISSUED).
    "APPROVED": "In Review",
    "IN APPROVAL": "In Review",
    "VOIDED": "Inactive",
}

_SCHEMA_SUFFIX = {
    "PERMIT COMPLETE": "complete",
    "CLOSED": "closed",
    "CERTIFICATE OF OCCUPANCY": "co",
    "CERTIFICATE OF COMPLETION": "cc",
    "PERMIT ISSUED": "issued",
    "IN PLAN CHECK": "plan_check",
    "ON HOLD": "on_hold",
    "APPROVED": "approved",
    "IN APPROVAL": "in_approval",
    "VOIDED": "voided",
}


def _map_status(raw: Optional[str]) -> Optional[str]:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    expected = _STATUS_MAP.get(text)
    if expected is not None:
        return expected
    return _STATUS_MAP.get(text.upper())


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())
    if not ({"fees", "detail", "fees_total"} <= keys):
        return "unknown"
    app = str(_detail(data_dict).get("Application") or "").strip().upper()
    suffix = _SCHEMA_SUFFIX.get(app)
    if suffix is None:
        slug = re.sub(r"[^a-z0-9]+", "_", app.lower()).strip("_") or "other"
        return f"fees_detail_{slug}"
    return f"fees_detail_{suffix}"


def _apply_status(repairs: dict, current, expected: Optional[str]) -> Optional[str]:
    """Apply expected STATUS_NORMALIZED; return effective status."""
    if expected is None:
        if pd.isna(current):
            return None
        return current

    if pd.isna(current):
        repairs["STATUS_NORMALIZED"] = expected
        repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"
    elif current != expected:
        repairs["STATUS_NORMALIZED"] = expected
        repairs["STATUS_NORMALIZED_FLAG"] = "FIXED"

    return repairs.get("STATUS_NORMALIZED", current)


def _apply_date(repairs: dict, row, field: str, candidate) -> None:
    """Fill or fix *field* from *candidate* datetime (pd.NaT = no candidate)."""
    cand = _safe_to_datetime(candidate)
    if cand is pd.NaT:
        return

    current = row[field]
    if pd.isna(current):
        repairs[field] = cand
        repairs[f"{field}_FLAG"] = "FILLED"
    elif not _dates_equal(current, cand):
        repairs[field] = cand
        repairs[f"{field}_FLAG"] = "FIXED"


# ── Per-schema repair logic ─────────────────────────────────────────────────

def _repair_fees_detail(row, d: dict, repairs: dict) -> None:
    """Repair a fees_detail record."""
    detail = _detail(d)
    expected = _map_status(detail.get("Application"))
    effective_status = _apply_status(repairs, row["STATUS_NORMALIZED"], expected)

    # FILE_DATE ← Application Date (already correct for all sample rows).
    _apply_date(repairs, row, "FILE_DATE", detail.get("Application Date"))

    # No Issue Date / finalization / inspection history in this schema.
    # Leave PERMIT_DATE and FINAL_DATE unchanged (all missing in sample).
    _ = effective_status


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Seminole County permit records using information from the raw DATA JSON.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Seminole County".  Must
        contain columns STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE,
        FINAL_DATE, and DATA.

    Returns
    -------
    pd.DataFrame
        Copy of *df* with corrected field values, an INFERRED_SCHEMA
        column naming the DATA JSON sub-schema identified for each
        record, and flag columns: STATUS_NORMALIZED_FLAG, FILE_DATE_FLAG,
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

        if schema.startswith("fees_detail"):
            _repair_fees_detail(row, d, repairs)

        for key, value in repairs.items():
            out.at[idx, key] = value

    for col in ("FILE_DATE", "PERMIT_DATE", "FINAL_DATE"):
        out[col] = pd.to_datetime(out[col], errors="coerce")

    return out


# ── CLI: run standalone to preview repair stats ─────────────────────────────

if __name__ == "__main__":
    import os
    from dotenv import load_dotenv, find_dotenv

    load_dotenv(find_dotenv())
    MY_DATA_PATH = os.getenv("MY_DATA_PATH")
    AGENT_DATA_PATH = os.getenv("AGENT_DATA_PATH")
    filepath = os.path.join(MY_DATA_PATH, "processed_data", "permits_fl_sample.parquet")
    df = pd.read_parquet(filepath)
    sc = df[df["JURISDICTION"] == "Seminole County"].copy()

    print(f"Seminole County records: {len(sc):,}\n")

    repaired = data_repair(sc)

    print("INFERRED_SCHEMA:")
    print(repaired["INFERRED_SCHEMA"].value_counts(dropna=False).to_string())
    print()

    for field in ["STATUS_NORMALIZED", "FILE_DATE", "PERMIT_DATE", "FINAL_DATE"]:
        flag_col = f"{field}_FLAG"
        n_filled = (repaired[flag_col] == "FILLED").sum()
        n_fixed = (repaired[flag_col] == "FIXED").sum()
        print(f"{field}:")
        print(f"  FILLED: {n_filled:>4,}   FIXED: {n_fixed:>4,}")

        before_missing = sc[field].isna().sum()
        after_missing = repaired[field].isna().sum()
        print(f"  Missing before: {before_missing:>4,}   Missing after: {after_missing:>4,}")
        print()

    print("STATUS_NORMALIZED distribution:")
    print("  Before:")
    for s, c in sc["STATUS_NORMALIZED"].value_counts(dropna=False).items():
        print(f"    {str(s):15s}: {c:>4,}")
    print("  After:")
    for s, c in repaired["STATUS_NORMALIZED"].value_counts(dropna=False).items():
        print(f"    {str(s):15s}: {c:>4,}")

    print("\nFILE_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FILE_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({n_has/len(sub) if len(sub) else 0:.1%})")

    print("\nPERMIT_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["PERMIT_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({n_has/len(sub) if len(sub) else 0:.1%})")

    print("\nFINAL_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FINAL_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({n_has/len(sub) if len(sub) else 0:.1%})")

    # Sanity: every Application maps; FILE_DATE still matches Application Date
    n_unmapped = 0
    n_file_mismatch = 0
    for idx in repaired.index:
        d = _safe_parse(repaired.at[idx, "DATA"]) or {}
        detail = _detail(d)
        if _map_status(detail.get("Application")) is None:
            n_unmapped += 1
        app = _safe_to_datetime(detail.get("Application Date"))
        if app is not pd.NaT and not _dates_equal(repaired.at[idx, "FILE_DATE"], app):
            n_file_mismatch += 1

    print(f"\nUnmapped Application values: {n_unmapped}")
    print(f"FILE_DATE != Application Date after repair: {n_file_mismatch}")

    if AGENT_DATA_PATH:
        out_path = os.path.join(AGENT_DATA_PATH, "seminole_county_repaired_sample.parquet")
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote {out_path}")

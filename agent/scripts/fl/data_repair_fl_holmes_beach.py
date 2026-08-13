"""Data repair for Holmes Beach (FL) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Holmes Beach DATA is a flat city-portal export (same family as Anna
Maria). Key names vary slightly across rows:

  - flat_hash_wd:     Permit# + Issue Date + Work Description
  - flat_space_wd:    Permit # + Issue Date + Work Description
  - flat_hash:        Permit# + Issue Date (no Work Description)
  - flat_space:       Permit # + Issue Date (no Work Description)
  - flat_minimal:     no Issue Date (mostly shifted receipting shells)

Canonical mappings:
  - Status (or shifted Sub Type / Permit Type) → STATUS_NORMALIZED
  - Issue Date (when a real MM/DD/YYYY date)   → PERMIT_DATE
  - No application / finalization date         → FILE_DATE / FINAL_DATE
    cannot be populated from DATA

Known issues repaired:
  - STATUS_NORMALIZED null for Renew (parking) → FILLED as Active.
  - STATUS_NORMALIZED null on City of Holmes Beach Receipts rows where
    Status holds a payee / memo and Sub Type holds the real status
    (Under Review / Complete) → FILLED from the shifted field.
  - STATUS_NORMALIZED null when Status is free text (land-use memo,
    copy/Copies) but Sub Type or Permit Type is a known status token
    → FILLED.
  - Stale STATUS_ORIGINAL lagging DATA.Status (issued→Closed,
    expired/under review→Issued) → FIXED.

Not repairable / left as-is:
  - FILE_DATE always missing; DATA has no application/submittal date.
  - FINAL_DATE always missing; Closed exposes no completion / finaled
    timestamp (Issue Date is issuance, not finalization).
  - PERMIT_DATE missing when Issue Date holds non-date text (work
    descriptions, receipt memos, denial notes) — cannot invent an
    issuance date.
"""

from __future__ import annotations

import json
import math
import re
from typing import Optional

import numpy as np
import pandas as pd


# ── Helpers ──────────────────────────────────────────────────────────────────

_DATE_RE = re.compile(r"^\d{1,2}/\d{1,2}/\d{2,4}$")


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
    """Parse a date value, returning pd.NaT on failure / non-date text."""
    if val is None or (isinstance(val, str) and not str(val).strip()):
        return pd.NaT
    if not isinstance(val, str) and pd.isna(val):
        return pd.NaT
    text = str(val).strip()
    if text.upper() in ("TBD", "NONE", "N/A", "NA", "00/00/0000", "0/0/0000"):
        return pd.NaT
    # Portal often puts descriptions into Issue Date; only accept
    # calendar-shaped values, not free text that happens to contain digits.
    if _DATE_RE.match(text):
        try:
            return pd.to_datetime(text, errors="raise")
        except (ValueError, TypeError, OverflowError):
            return pd.NaT
    # Allow short ISO-like stamps; reject long free text.
    if len(text) > 30:
        return pd.NaT
    try:
        return pd.to_datetime(text, errors="raise")
    except (ValueError, TypeError, OverflowError):
        return pd.NaT


def _dates_equal(a, b) -> bool:
    """Compare two datelike values at calendar-day resolution."""
    da = _safe_to_datetime(a)
    db = _safe_to_datetime(b)
    if da is pd.NaT or db is pd.NaT:
        return False
    return da.normalize() == db.normalize()


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())
    has_issue = "Issue Date" in keys
    has_wd = "Work Description" in keys
    has_hash = "Permit#" in keys
    has_space = "Permit #" in keys

    if not has_issue:
        return "flat_minimal"
    if has_wd and has_hash:
        return "flat_hash_wd"
    if has_wd and has_space:
        return "flat_space_wd"
    if has_hash:
        return "flat_hash"
    if has_space:
        return "flat_space"
    return "unknown"


def _lookup_status(raw_status: Optional[str], status_map: dict) -> Optional[str]:
    if raw_status is None:
        return None
    expected = status_map.get(raw_status)
    if expected is not None:
        return expected
    raw_norm = str(raw_status).strip()
    if not raw_norm:
        return None
    expected = status_map.get(raw_norm)
    if expected is not None:
        return expected
    for k, v in status_map.items():
        if k.lower() == raw_norm.lower():
            return v
    return None


def _apply_status(repairs: dict, current, raw_status: Optional[str], status_map: dict):
    """Map raw status → STATUS_NORMALIZED; return effective status."""
    expected = _lookup_status(raw_status, status_map)
    if expected is None:
        return current if not (isinstance(current, float) and pd.isna(current)) else None

    if pd.isna(current):
        repairs["STATUS_NORMALIZED"] = expected
        repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"
    elif current != expected:
        repairs["STATUS_NORMALIZED"] = expected
        repairs["STATUS_NORMALIZED_FLAG"] = "FIXED"

    return repairs.get("STATUS_NORMALIZED", current)


def _apply_date(repairs: dict, row, field: str, candidate, *, allow_fill: bool = True) -> None:
    """Fill or fix *field* from *candidate* datetime (pd.NaT = no candidate)."""
    cand = _safe_to_datetime(candidate)
    if cand is pd.NaT:
        return

    current = row[field]
    if pd.isna(current):
        if allow_fill:
            repairs[field] = cand
            repairs[f"{field}_FLAG"] = "FILLED"
    elif not _dates_equal(current, cand):
        repairs[field] = cand
        repairs[f"{field}_FLAG"] = "FIXED"


def _resolve_raw_status(d: dict) -> Optional[str]:
    """Return the best raw status token from a (possibly shifted) row."""
    status = d.get("Status")
    if isinstance(status, str):
        status = status.strip() or None
    if _lookup_status(status, _STATUS_MAP) is not None:
        return status

    # Receipting / polluted Status: real status often lands in Sub Type
    # (Under Review / Complete) or, rarely, Permit Type.
    for key in ("Sub Type", "Permit Type"):
        cand = d.get(key)
        if isinstance(cand, str):
            cand = cand.strip() or None
        if _lookup_status(cand, _STATUS_MAP) is not None:
            return cand
    return status


# ── Status maps ──────────────────────────────────────────────────────────────

# DATA.Status (Title Case in portal) → STATUS_NORMALIZED
_STATUS_MAP = {
    # Final / completed
    "Closed": "Final",
    "Completed": "Final",
    "Complete": "Final",
    # Active / issued
    "Issued": "Active",
    "Approved": "Active",
    "Renew": "Active",
    # In review / pre-issuance
    "Online Application Received": "In Review",
    "Under Review": "In Review",
    "Incomplete Application": "In Review",
    # Inactive / closed without completion
    "Denied": "Inactive",
    "Void": "Inactive",
    "Expired": "Inactive",
}


# ── Per-schema repair logic ─────────────────────────────────────────────────

def _repair_record(row, d: dict, repairs: dict) -> None:
    """Repair a Holmes Beach flat-portal record."""
    raw_status = _resolve_raw_status(d)

    effective_status = _apply_status(
        repairs, row["STATUS_NORMALIZED"], raw_status, _STATUS_MAP
    )

    # FILE_DATE: no application/submittal field in DATA — nothing to do.

    # PERMIT_DATE ← Issue Date when it is a real calendar date.
    # Under Review / Incomplete shells put memos into Issue Date; those
    # fail the date guard and are left missing (correct for pre-issuance).
    _apply_date(repairs, row, "PERMIT_DATE", d.get("Issue Date"))

    # FINAL_DATE: no finaled / completion / CO date in DATA — nothing to do.
    _ = effective_status


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Holmes Beach permit records using information from the raw DATA JSON.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Holmes Beach".  Must
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
        if schema != "missing":
            _repair_record(row, d, repairs)

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
    city = df[df["JURISDICTION"] == "Holmes Beach"].copy()

    print(f"Holmes Beach records: {len(city):,}\n")

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

    still_null = repaired[repaired["STATUS_NORMALIZED"].isna()]
    print(f"\nRemaining null STATUS_NORMALIZED: {len(still_null)}")
    if len(still_null):
        types = still_null["DATA"].apply(
            lambda x: (_safe_parse(x) or {}).get("Permit Type")
        )
        print(types.value_counts(dropna=False).to_string())

    if AGENT_DATA_PATH:
        out_path = os.path.join(AGENT_DATA_PATH, "holmes_beach_repaired_sample.parquet")
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote {out_path}")

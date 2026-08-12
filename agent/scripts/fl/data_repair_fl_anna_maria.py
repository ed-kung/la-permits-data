"""Data repair for Anna Maria (FL) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Anna Maria DATA is a flat city-portal export. Key names vary slightly
across rows (five sub-schemas):

  - flat_hash_wd:     Permit# + Issue Date + Work Description
  - flat_space_wd:    Permit # + Issue Date + Work Description
  - flat_hash:        Permit# + Issue Date (no Work Description)
  - flat_space:       Permit # + Issue Date (no Work Description)
  - flat_minimal:     no Issue Date (mostly Lien Search / incomplete)

Canonical mappings (all schemas):
  - Status                              → STATUS_NORMALIZED
  - Issue Date (when a real date)       → PERMIT_DATE
  - No application / finalization date  → FILE_DATE / FINAL_DATE
    cannot be populated from DATA

Known issues repaired:
  - STATUS_NORMALIZED null for Lien Search rows where Status is
    "Lien Search" or a street address (portal field misalignment) →
    FILLED as Final from Permit Type.
  - STATUS_NORMALIZED wrong when STATUS_ORIGINAL lagged DATA.Status
    (e.g. issued/under review vs Closed/Withdrawn/Rejected) → FIXED.
  - Rejected / Withdrawn left as In Review via stale STATUS_ORIGINAL
    → FIXED to Inactive.

Not repairable / left as-is:
  - FILE_DATE always missing; DATA has no application/submittal date
    (Work Description "Permit Notes" check dates are not used).
  - FINAL_DATE always missing; Closed/Completed expose no completion
    / finaled timestamp.
  - PERMIT_DATE missing when Issue Date holds non-date text (parking
    violation descriptions, work descriptions, "Lien search",
    pre-application labels) — cannot invent an issuance date.
  - Parking / citation rows with Status polluted by violation text
    and no recognizable status token → STATUS_NORMALIZED stays null.
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
        return json.loads(data)
    return data


def _safe_to_datetime(val):
    """Parse a date value, returning pd.NaT on failure / non-date text."""
    if val is None or (isinstance(val, str) and not str(val).strip()):
        return pd.NaT
    if not isinstance(val, str) and pd.isna(val):
        return pd.NaT
    text = str(val).strip()
    if text.upper() in ("TBD", "NONE", "N/A", "NA", "00/00/0000", "0/0/0000"):
        return pd.NaT
    # Anna Maria often puts descriptions into Issue Date; only accept
    # values that are (or start as) calendar dates, not free text.
    if not _DATE_RE.match(text) and not _DATE_RE.match(text.split()[0] if text.split() else ""):
        # Allow ISO-like / pandas-parseable pure dates without slash form
        try:
            dt = pd.to_datetime(text, errors="raise")
            # Reject long free-text that happens to contain a date token
            if len(text) > 30:
                return pd.NaT
            return dt
        except (ValueError, TypeError, OverflowError):
            return pd.NaT
    try:
        return pd.to_datetime(text)
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


def _apply_status(repairs: dict, current, raw_status: Optional[str], status_map: dict):
    """Map raw status → STATUS_NORMALIZED; return effective status."""
    if raw_status is None:
        return current if not (isinstance(current, float) and pd.isna(current)) else None

    expected = status_map.get(raw_status)
    if expected is None:
        raw_norm = str(raw_status).strip()
        expected = status_map.get(raw_norm)
        if expected is None:
            for k, v in status_map.items():
                if k.lower() == raw_norm.lower():
                    expected = v
                    break
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


# ── Status maps ──────────────────────────────────────────────────────────────

# DATA.Status (Title Case in portal) → STATUS_NORMALIZED
_STATUS_MAP = {
    # Final / completed
    "Closed": "Final",
    "Completed": "Final",
    "Lien Search": "Final",
    # Active / issued
    "Issued": "Active",
    "Approved": "Active",
    # In review / pre-issuance
    "Online Application Received": "In Review",
    "Paid": "In Review",
    "Pending": "In Review",
    "Under Review": "In Review",
    "Unpaid": "In Review",
    # Inactive / closed without completion
    "Denied": "Inactive",
    "Void": "Inactive",
    "Withdrawn": "Inactive",
    "Expired": "Inactive",
    "Abandon": "Inactive",
    "Rejected": "Inactive",
}


# ── Per-schema repair logic ─────────────────────────────────────────────────

def _repair_record(row, d: dict, repairs: dict) -> None:
    """Repair an Anna Maria flat-portal record."""
    raw_status = d.get("Status")
    if isinstance(raw_status, str):
        raw_status = raw_status.strip() or None

    effective_status = _apply_status(
        repairs, row["STATUS_NORMALIZED"], raw_status, _STATUS_MAP
    )

    # Lien Search portal rows often put the property address into Status.
    # When Status is not a known token, fall back to Permit Type.
    if effective_status is None or (isinstance(effective_status, float) and pd.isna(effective_status)):
        permit_type = str(d.get("Permit Type") or "").strip()
        if permit_type.lower() == "lien search":
            current = row["STATUS_NORMALIZED"]
            if pd.isna(current):
                repairs["STATUS_NORMALIZED"] = "Final"
                repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"
                effective_status = "Final"
            elif current != "Final":
                repairs["STATUS_NORMALIZED"] = "Final"
                repairs["STATUS_NORMALIZED_FLAG"] = "FIXED"
                effective_status = "Final"

    # FILE_DATE: no application/submittal field in DATA — nothing to do.

    # PERMIT_DATE ← Issue Date when it is a real calendar date
    _apply_date(repairs, row, "PERMIT_DATE", d.get("Issue Date"))

    # FINAL_DATE: no finaled / completion / CO date in DATA — nothing to do.
    # Non-Final rows should not carry a finaled date (none observed).
    _ = effective_status


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Anna Maria permit records using information from the raw DATA JSON.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Anna Maria".  Must
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
    city = df[df["JURISDICTION"] == "Anna Maria"].copy()

    print(f"Anna Maria records: {len(city):,}\n")

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

    # Remaining null statuses
    still_null = repaired[repaired["STATUS_NORMALIZED"].isna()]
    print(f"\nRemaining null STATUS_NORMALIZED: {len(still_null)}")
    if len(still_null):
        types = still_null["DATA"].apply(
            lambda x: (_safe_parse(x) or {}).get("Permit Type")
        )
        print(types.value_counts(dropna=False).to_string())

    if AGENT_DATA_PATH:
        out_path = os.path.join(AGENT_DATA_PATH, "anna_maria_repaired_sample.parquet")
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote {out_path}")

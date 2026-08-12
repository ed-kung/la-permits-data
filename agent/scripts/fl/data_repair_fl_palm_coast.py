"""Data repair for Palm Coast (FL) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Palm Coast DATA is an eTRAKiT-style portal extract with top-level
``Status``, ``Issue Date``, ``Expiration Date``, ``Fees``,
``Review History``, and ``Inspection History``. Two layout variants
appear in this sample:

  - etrakit_flat:    flattened owner_* / Applicant Name / Name fields
  - etrakit_nested:  nested Owner / Contractor / Sub Contractors objects

Content suffixes further split by which canonical signals are present
(``_issued_insp_rev``, ``_issued_insp``, ``_issued_rev``, ``_issued``,
``_insp_rev``, ``_insp``, ``_rev``, ``_status_only``).

Canonical mappings:
  - DATA.Status                                      → STATUS_NORMALIZED
  - Earliest Review History Date In; else earliest
    Fee Date Paid; else Issue Date                   → FILE_DATE
  - Issue Date                                       → PERMIT_DATE
  - Latest approved FINAL inspection Request Date
    (Result FINAL APPROVED, or Type contains FINAL
    with an approved result)                         → FINAL_DATE

Known issues repaired:
  - 10 rows with null STATUS_NORMALIZED (ADMCLSD /
    CODEACT / STATE) → FILLED from Status.
  - FILE_DATE entirely missing upstream → FILLED from
    review / fee / issue dates when present.
  - FINAL_DATE was ingested from Expiration Date
    (typically Issue + ~6 months), not completion →
    FIXED to final-inspection dates for Final rows,
    or cleared when no true final signal exists.
  - Spurious FINAL_DATE on Inactive (cancel / expired /
    void) Expiration stamps → cleared (FIXED).

Not repairable from DATA:
  - Rows with empty Review History, blank Fees Date Paid,
    and blank Issue Date → FILE_DATE stays missing.
  - In Review / never-issued Inactive rows correctly lack
    PERMIT_DATE (no Issue Date).
  - Final rows with no approved FINAL inspection →
    FINAL_DATE stays missing after clearing Expiration.
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
        try:
            parsed = json.loads(data)
        except (json.JSONDecodeError, TypeError):
            return None
        return parsed if isinstance(parsed, dict) else None
    return data if isinstance(data, dict) else None


def _safe_to_datetime(val):
    """Parse a date value, returning pd.NaT on failure / blanks / sentinels."""
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
    if getattr(dt, "tzinfo", None) is not None:
        dt = dt.tz_convert("UTC").tz_localize(None)
    return dt


def _dates_equal(a, b) -> bool:
    """Compare two datelike values at calendar-day resolution."""
    da = _safe_to_datetime(a)
    db = _safe_to_datetime(b)
    if da is pd.NaT or db is pd.NaT or pd.isna(da) or pd.isna(db):
        return False
    return pd.Timestamp(da).normalize() == pd.Timestamp(db).normalize()


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


def _clear_date(repairs: dict, row, field: str) -> None:
    """Clear a spurious date value."""
    if not pd.isna(row[field]):
        repairs[field] = pd.NaT
        repairs[f"{field}_FLAG"] = "FIXED"


# ── Status maps ──────────────────────────────────────────────────────────────

# Portal Status strings (uppercased) → STATUS_NORMALIZED
_STATUS_MAP = {
    "FINAL": "Final",
    "COED": "Final",          # certificate / closed-out
    "ADMCLSD": "Final",       # administratively closed
    "ISSUED": "Active",
    "INSPECT": "Active",      # issued, inspections underway
    "CODEACT": "Active",      # code-action / issued work
    "STATE": "Active",        # issued; state-related review
    "APPLY": "In Review",
    "READY": "In Review",
    "CANCEL": "Inactive",
    "EXPIRED": "Inactive",
    "VOID": "Inactive",
}


def _map_status(raw: Optional[str]) -> Optional[str]:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    return _STATUS_MAP.get(text.upper())


# ── Field extractors ─────────────────────────────────────────────────────────

def _earliest_review_date(d: dict):
    """Earliest Review History Date In (application / plan-review start)."""
    rh = d.get("Review History")
    if not isinstance(rh, list):
        return pd.NaT
    dates = []
    for item in rh:
        if not isinstance(item, dict):
            continue
        dt = _safe_to_datetime(item.get("Date In"))
        if dt is not pd.NaT:
            dates.append(dt)
    return min(dates) if dates else pd.NaT


def _earliest_fee_date(d: dict):
    """Earliest Fees[].Date Paid."""
    fees = d.get("Fees")
    if not isinstance(fees, list):
        return pd.NaT
    dates = []
    for item in fees:
        if not isinstance(item, dict):
            continue
        dt = _safe_to_datetime(item.get("Date Paid"))
        if dt is not pd.NaT:
            dates.append(dt)
    return min(dates) if dates else pd.NaT


def _file_date_candidate(d: dict):
    """Prefer review start, else fee paid, else issue date."""
    candidates = [
        _earliest_review_date(d),
        _earliest_fee_date(d),
        _safe_to_datetime(d.get("Issue Date")),
    ]
    valid = [c for c in candidates if c is not pd.NaT]
    return min(valid) if valid else pd.NaT


def _final_date_from_inspections(d: dict):
    """Latest approved FINAL inspection Request Date.

    Accepts Result == 'FINAL APPROVED' (even when Type omits FINAL) or
    Type containing FINAL with an approved (non-disapproved) result.
    """
    ih = d.get("Inspection History")
    if not isinstance(ih, list):
        return pd.NaT

    dates = []
    for item in ih:
        if not isinstance(item, dict):
            continue
        typ = str(item.get("Type") or "").upper()
        res = str(item.get("Result") or "").strip().upper()
        if not res:
            continue
        if "DISAPPROVED" in res:
            continue

        is_final_result = res == "FINAL APPROVED"
        is_final_type = "FINAL" in typ and "APPROVED" in res
        if not (is_final_result or is_final_type):
            continue

        dt = _safe_to_datetime(item.get("Request Date"))
        if dt is not pd.NaT:
            dates.append(dt)

    return max(dates) if dates else pd.NaT


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"

    keys = set(data_dict.keys())
    if "Owner" in keys and "Contractor" in keys:
        base = "etrakit_nested"
    elif "owner_name" in keys or "Applicant Name" in keys or "Name" in keys:
        base = "etrakit_flat"
    elif "Status" in keys and "Permit Number" in keys:
        base = "etrakit_flat"
    else:
        return "unknown"

    has_issue = _safe_to_datetime(data_dict.get("Issue Date")) is not pd.NaT
    rh = data_dict.get("Review History")
    has_rev = isinstance(rh, list) and any(
        isinstance(x, dict) and _safe_to_datetime(x.get("Date In")) is not pd.NaT
        for x in rh
    )
    ih = data_dict.get("Inspection History")
    has_insp = isinstance(ih, list) and any(
        isinstance(x, dict) and str(x.get("Result") or "").strip()
        for x in ih
    )

    if has_issue and has_insp and has_rev:
        suffix = "_issued_insp_rev"
    elif has_issue and has_insp:
        suffix = "_issued_insp"
    elif has_issue and has_rev:
        suffix = "_issued_rev"
    elif has_issue:
        suffix = "_issued"
    elif has_insp and has_rev:
        suffix = "_insp_rev"
    elif has_insp:
        suffix = "_insp"
    elif has_rev:
        suffix = "_rev"
    else:
        suffix = "_status_only"

    return base + suffix


# ── Per-record repair ────────────────────────────────────────────────────────

def _repair_record(row, d: dict, repairs: dict) -> None:
    """Repair one Palm Coast eTRAKiT record."""
    expected = _map_status(d.get("Status"))
    effective_status = _apply_status(repairs, row["STATUS_NORMALIZED"], expected)

    # FILE_DATE ← earliest review / fee / issue signal
    _apply_date(repairs, row, "FILE_DATE", _file_date_candidate(d))

    # PERMIT_DATE ← Issue Date (Active / Final; keep issued Inactive)
    issue = _safe_to_datetime(d.get("Issue Date"))
    if issue is not pd.NaT:
        if effective_status in ("Active", "Final", "Inactive"):
            _apply_date(repairs, row, "PERMIT_DATE", issue)
    elif effective_status == "In Review":
        # Unissued applications should not carry a permit stamp.
        _clear_date(repairs, row, "PERMIT_DATE")

    # FINAL_DATE ← final inspection (Final only); clear Expiration misuse
    final_src = _final_date_from_inspections(d)
    current_final = row["FINAL_DATE"]
    if effective_status == "Final":
        if final_src is not pd.NaT:
            if pd.isna(current_final):
                repairs["FINAL_DATE"] = final_src
                repairs["FINAL_DATE_FLAG"] = "FILLED"
            elif not _dates_equal(current_final, final_src):
                repairs["FINAL_DATE"] = final_src
                repairs["FINAL_DATE_FLAG"] = "FIXED"
        elif not pd.isna(current_final):
            # Current value is Expiration Date, not a true final.
            _clear_date(repairs, row, "FINAL_DATE")
    elif not pd.isna(current_final):
        _clear_date(repairs, row, "FINAL_DATE")


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Palm Coast permit records using information from the raw DATA JSON.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Palm Coast".  Must contain
        columns STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, FINAL_DATE,
        and DATA.

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
        _repair_record(row, d, repairs)

        for key, value in repairs.items():
            out.at[idx, key] = value

    for col in ("FILE_DATE", "PERMIT_DATE", "FINAL_DATE"):
        out[col] = pd.to_datetime(out[col], errors="coerce")

    return out


# ── CLI: run standalone to preview repair stats ─────────────────────────────

if __name__ == "__main__":
    import os
    from dotenv import load_dotenv

    load_dotenv("/Users/ekung/projects/la-permits-data/.env")
    MY_DATA_PATH = os.getenv("MY_DATA_PATH")
    AGENT_DATA_PATH = os.getenv("AGENT_DATA_PATH")
    filepath = os.path.join(MY_DATA_PATH, "processed_data", "permits_fl_sample.parquet")
    df = pd.read_parquet(filepath)
    city = df[df["JURISDICTION"] == "Palm Coast"].copy()

    print(f"Palm Coast records: {len(city):,}\n")

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
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({n_has / len(sub) if len(sub) else 0:.1%})")

    print("\nPERMIT_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["PERMIT_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({n_has / len(sub) if len(sub) else 0:.1%})")

    print("\nFINAL_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FINAL_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({n_has / len(sub) if len(sub) else 0:.1%})")

    # Sanity: FINAL should not equal Expiration after repair
    n_exp_match = 0
    n_with_exp = 0
    for idx, row in repaired.iterrows():
        d = _safe_parse(row["DATA"])
        if d is None:
            continue
        exp = _safe_to_datetime(d.get("Expiration Date"))
        if exp is pd.NaT:
            continue
        n_with_exp += 1
        if not pd.isna(row["FINAL_DATE"]) and _dates_equal(row["FINAL_DATE"], exp):
            n_exp_match += 1
    print(f"\nFINAL_DATE still equal to Expiration Date: {n_exp_match} (of {n_with_exp} with Expiration)")

    still_null = repaired[repaired["STATUS_NORMALIZED"].isna()]
    print(f"\nRemaining null STATUS_NORMALIZED: {len(still_null):,}")

    if AGENT_DATA_PATH:
        out_path = os.path.join(AGENT_DATA_PATH, "palm_coast_repaired_sample.parquet")
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote {out_path}")

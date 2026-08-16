"""Data repair for Abilene (TX) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Abilene DATA is a flat city permit-list scrape. A single top-level
key-set appears in the sample:

  - permit_list:  Owner, Address, Comment, Permit #, Completed,
                  Contractor, Inspection, Date issued, Description,
                  Permit type

Canonical mappings:
  - DATA.Completed + Inspection[*].Passed  → STATUS_NORMALIZED
  - (no application / filed date key)      → FILE_DATE cannot be recovered
  - DATA['Date issued']                    → PERMIT_DATE
  - max Inspection date where Passed=Yes   → FINAL_DATE (Final only)

Known issues repaired:
  - STATUS_NORMALIZED is missing for every sample row. Upstream
    STATUS_ORIGINAL is just DATA.Completed lowercased ('yes'/'no'),
    not a real permit status. Filled from Completed + whether any
    inspection Passed.
  - FINAL_DATE on non-Final (Completed=No) rows that still have a
    passed intermediate inspection → cleared.
  - PERMIT_DATE mismatches vs Date issued → FIXED (none in sample).

Not repairable / left as-is:
  - FILE_DATE is missing for all rows; DATA has only Date issued
    (issuance), not an application/submittal date.
  - Final-like Completed=Yes rows with no Passed inspection stay
    Inactive and cannot get a FINAL_DATE (expired / closed without
    final / never built).
"""

from __future__ import annotations

import json
import math
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
        try:
            parsed = json.loads(data)
        except (json.JSONDecodeError, TypeError):
            return None
        return parsed if isinstance(parsed, dict) else None
    return data if isinstance(data, dict) else None


def _safe_to_datetime(val):
    """Parse a date value, returning pd.NaT on failure / blanks / sentinels."""
    if val is None:
        return pd.NaT
    if isinstance(val, float) and math.isnan(val):
        return pd.NaT
    if not isinstance(val, str) and pd.isna(val):
        return pd.NaT
    if isinstance(val, dict):
        return pd.NaT
    text = str(val).strip()
    if not text or text.upper() in {
        "TBD", "NONE", "N/A", "NA", "NULL", "NAN",
        "00/00/0000", "0/0/0000",
    }:
        return pd.NaT
    try:
        dt = pd.to_datetime(val, errors="coerce")
    except (ValueError, TypeError, OverflowError):
        return pd.NaT
    if pd.isna(dt):
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
    return da.normalize() == db.normalize()


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())
    required = {
        "Completed", "Date issued", "Inspection", "Permit #", "Permit type",
    }
    if required <= keys:
        return "permit_list"
    return "unknown"


def _inspections(d: dict) -> list:
    raw = d.get("Inspection")
    if isinstance(raw, list):
        return [i for i in raw if isinstance(i, dict)]
    return []


def _has_passed_inspection(d: dict) -> bool:
    return any(str(i.get("Passed") or "").strip().lower() == "yes" for i in _inspections(d))


def _expected_status(d: dict) -> Optional[str]:
    """Map Abilene Completed + inspections → STATUS_NORMALIZED.

    Completed=No  → Active (issued, not finished)
    Completed=Yes + ≥1 Passed inspection → Final
    Completed=Yes + no Passed inspection → Inactive
        (expired / closed without final / never built / consult-only)
    """
    completed = str(d.get("Completed") or "").strip().lower()
    if completed == "no":
        return "Active"
    if completed == "yes":
        if _has_passed_inspection(d):
            return "Final"
        return "Inactive"
    return None


def _issuance_date(d: dict):
    return _safe_to_datetime(d.get("Date issued"))


def _final_date_candidate(d: dict):
    """Latest inspection date among Passed=Yes inspections."""
    dates = []
    for insp in _inspections(d):
        if str(insp.get("Passed") or "").strip().lower() != "yes":
            continue
        dt = _safe_to_datetime(insp.get("Inspection date"))
        if dt is not pd.NaT and not pd.isna(dt):
            dates.append(dt)
    return max(dates) if dates else pd.NaT


def _apply_status(repairs: dict, current, expected: Optional[str]) -> object:
    if expected is None:
        return current
    if pd.isna(current):
        repairs["STATUS_NORMALIZED"] = expected
        repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"
        return expected
    if current != expected:
        repairs["STATUS_NORMALIZED"] = expected
        repairs["STATUS_NORMALIZED_FLAG"] = "FIXED"
        return expected
    return current


def _apply_date(repairs: dict, row, field: str, candidate) -> None:
    """Fill or fix *field* from *candidate* datetime (pd.NaT = no candidate)."""
    if candidate is pd.NaT or pd.isna(candidate):
        return
    current = row[field]
    if pd.isna(current):
        repairs[field] = candidate
        repairs[f"{field}_FLAG"] = "FILLED"
    elif not _dates_equal(current, candidate):
        repairs[field] = candidate
        repairs[f"{field}_FLAG"] = "FIXED"


def _clear_date(repairs: dict, row, field: str) -> None:
    """Clear a spurious date value."""
    if pd.isna(row[field]):
        return
    repairs[field] = pd.NaT
    repairs[f"{field}_FLAG"] = "FIXED"


# ── Per-row repair ───────────────────────────────────────────────────────────

def _repair_row(row, d: dict, repairs: dict) -> None:
    """Repair one Abilene permit_list record."""
    expected = _expected_status(d)
    effective_status = _apply_status(repairs, row["STATUS_NORMALIZED"], expected)

    # -- FILE_DATE --
    # No application/submittal date exists in DATA. Date issued is issuance
    # only and must not be copied into FILE_DATE.

    # -- PERMIT_DATE ← Date issued --
    issue = _issuance_date(d)
    if issue is not pd.NaT and not pd.isna(issue):
        # Issuance date is authoritative whenever present (all statuses).
        _apply_date(repairs, row, "PERMIT_DATE", issue)

    # -- FINAL_DATE ← max Passed inspection date (Final only) --
    final_src = _final_date_candidate(d)
    if effective_status == "Final":
        if final_src is not pd.NaT and not pd.isna(final_src):
            _apply_date(repairs, row, "FINAL_DATE", final_src)
    else:
        _clear_date(repairs, row, "FINAL_DATE")


# ── Main entry point ─────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Abilene permit records using the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Abilene".  Must contain
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

    for col in ("FILE_DATE", "PERMIT_DATE", "FINAL_DATE"):
        out[col] = pd.to_datetime(out[col], errors="coerce")

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
        if schema == "permit_list":
            _repair_row(row, d, repairs)

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
    filepath = os.path.join(MY_DATA_PATH, "processed_data", "permits_tx_sample.parquet")
    df = pd.read_parquet(filepath)
    abi = df[(df["JURISDICTION"] == "Abilene") & (df["STATE"] == "TX")].copy()

    print(f"Abilene records: {len(abi):,}\n")

    repaired = data_repair(abi)

    print("INFERRED_SCHEMA distribution:")
    for s, c in repaired["INFERRED_SCHEMA"].value_counts(dropna=False).items():
        print(f"  {str(s):35s}: {c:>4,}")
    print()

    for field in ["STATUS_NORMALIZED", "FILE_DATE", "PERMIT_DATE", "FINAL_DATE"]:
        flag_col = f"{field}_FLAG"
        n_filled = (repaired[flag_col] == "FILLED").sum()
        n_fixed = (repaired[flag_col] == "FIXED").sum()
        print(f"{field}:")
        print(f"  FILLED: {n_filled:>4,}   FIXED: {n_fixed:>4,}")

        before_missing = abi[field].isna().sum()
        after_missing = repaired[field].isna().sum()
        print(f"  Missing before: {before_missing:>4,}   Missing after: {after_missing:>4,}")
        print()

    print("STATUS_NORMALIZED distribution:")
    print("  Before:")
    for s, c in abi["STATUS_NORMALIZED"].value_counts(dropna=False).items():
        print(f"    {str(s):15s}: {c:>4,}")
    print("  After:")
    for s, c in repaired["STATUS_NORMALIZED"].value_counts(dropna=False).items():
        print(f"    {str(s):15s}: {c:>4,}")

    print("\nFILE_DATE overall (after): "
          f"{repaired['FILE_DATE'].notna().sum()}/{len(repaired)}")

    print("\nPERMIT_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        if len(sub) == 0:
            continue
        n_has = sub["PERMIT_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({n_has / len(sub):.1%})")

    print("\nFINAL_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        if len(sub) == 0:
            continue
        n_has = sub["FINAL_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({n_has / len(sub):.1%})")

    if AGENT_DATA_PATH:
        out_dir = os.path.join(AGENT_DATA_PATH, "repaired")
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, "permits_tx_abilene_repaired.parquet")
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote {out_path}")

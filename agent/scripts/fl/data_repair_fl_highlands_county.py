"""Data repair for Highlands County (FL) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Highlands County DATA has a single schema:

  - permit_bundle: nested payload with permit_info, inspection_info,
                   plan_info, fee_info, owner_info, etc.

Canonical mappings (from permit_info / inspection_info):
  - Status (+ Issued Date for Open)     → STATUS_NORMALIZED
  - Application Date                    → FILE_DATE
  - Issued Date                         → PERMIT_DATE
  - C.O. Issued, else passed Final
    inspection, else last passed insp   → FINAL_DATE

Known issues repaired:
  - Open permits that already have Issued Date were mapped to
    In Review; they are FIXED to Active (issued / under inspection).
  - Final (Closed) rows missing FINAL_DATE with empty C.O. Issued are
    FILLED from a passed inspection whose TYPE contains "FINAL", else
    the latest passed inspection INSP DATE.

Not repairable / left as-is:
  - FILE_DATE already matches Application Date for all rows.
  - PERMIT_DATE already matches Issued Date; rows without Issued Date
    (including 10 Closed / Final GUP stubs) stay missing.
  - Closed / Final rows with neither C.O. Issued nor a dated passed
    inspection stay missing FINAL_DATE.
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
        return json.loads(data)
    return data


def _safe_to_datetime(val):
    """Parse a date value, returning pd.NaT on failure / blanks."""
    if val is None or (isinstance(val, str) and not str(val).strip()):
        return pd.NaT
    if not isinstance(val, str) and pd.isna(val):
        return pd.NaT
    text = str(val).strip()
    if text.upper() in ("TBD", "NONE", "N/A", "NA", "NULL", "NAN", "00/00/0000", "0/0/0000"):
        return pd.NaT
    try:
        return pd.to_datetime(val)
    except (ValueError, TypeError):
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
    if "permit_info" in keys:
        return "permit_bundle"
    return "unknown"


def _permit_info(d: dict) -> dict:
    pi = d.get("permit_info")
    return pi if isinstance(pi, dict) else {}


# ── Status mapping ───────────────────────────────────────────────────────────

# Direct Status → STATUS_NORMALIZED (Open handled separately when issued).
_STATUS_MAP = {
    "Closed": "Final",
    "Open": "In Review",  # overridden to Active when Issued Date present
    "Hold": "In Review",
    "Expired": "Inactive",
    "Void": "Inactive",
    "Reject": "Inactive",
}


def _expected_status(raw_status: Optional[str], issued) -> Optional[str]:
    if raw_status is None:
        return None
    if raw_status == "Open" and _safe_to_datetime(issued) is not pd.NaT:
        return "Active"
    return _STATUS_MAP.get(raw_status)


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


def _last_passed_final_inspection(d: dict):
    """Latest INSP DATE among passed inspections whose TYPE has 'FINAL'."""
    dates = []
    for insp in d.get("inspection_info") or []:
        if not isinstance(insp, dict):
            continue
        typ = str(insp.get("TYPE") or "")
        res = str(insp.get("RES") or "").strip().upper()
        if res != "P":
            continue
        if "FINAL" not in typ.upper():
            continue
        dt = _safe_to_datetime(insp.get("INSP DATE"))
        if dt is not pd.NaT:
            dates.append(dt)
    return max(dates) if dates else pd.NaT


def _last_passed_inspection(d: dict):
    """Latest INSP DATE among any passed inspection (RES == 'P')."""
    dates = []
    for insp in d.get("inspection_info") or []:
        if not isinstance(insp, dict):
            continue
        res = str(insp.get("RES") or "").strip().upper()
        if res != "P":
            continue
        dt = _safe_to_datetime(insp.get("INSP DATE"))
        if dt is not pd.NaT:
            dates.append(dt)
    return max(dates) if dates else pd.NaT


def _final_date_from_data(d: dict, pi: dict):
    """Prefer C.O. Issued; else passed Final inspection; else last pass."""
    co = _safe_to_datetime(pi.get("C.O. Issued"))
    if co is not pd.NaT:
        return co
    final_insp = _last_passed_final_inspection(d)
    if final_insp is not pd.NaT:
        return final_insp
    return _last_passed_inspection(d)


# ── Per-schema repair logic ─────────────────────────────────────────────────

def _repair_permit_bundle(row, d: dict, repairs: dict) -> None:
    """Repair a permit_bundle record."""
    pi = _permit_info(d)
    raw_status = pi.get("Status")
    issued = _safe_to_datetime(pi.get("Issued Date"))
    expected = _expected_status(raw_status, pi.get("Issued Date"))
    effective_status = _apply_status(repairs, row["STATUS_NORMALIZED"], expected)

    # -- FILE_DATE ← Application Date --
    app = _safe_to_datetime(pi.get("Application Date"))
    if app is not pd.NaT:
        if pd.isna(row["FILE_DATE"]):
            repairs["FILE_DATE"] = app
            repairs["FILE_DATE_FLAG"] = "FILLED"
        elif not _dates_equal(row["FILE_DATE"], app):
            repairs["FILE_DATE"] = app
            repairs["FILE_DATE_FLAG"] = "FIXED"

    # -- PERMIT_DATE ← Issued Date --
    if issued is not pd.NaT:
        if pd.isna(row["PERMIT_DATE"]):
            if effective_status in ("Active", "Final"):
                repairs["PERMIT_DATE"] = issued
                repairs["PERMIT_DATE_FLAG"] = "FILLED"
        elif not _dates_equal(row["PERMIT_DATE"], issued):
            repairs["PERMIT_DATE"] = issued
            repairs["PERMIT_DATE_FLAG"] = "FIXED"

    # -- FINAL_DATE ← C.O. Issued / passed Final insp / last pass --
    final_src = _final_date_from_data(d, pi)
    current_final = row["FINAL_DATE"]
    if effective_status == "Final":
        if final_src is not pd.NaT:
            if pd.isna(current_final):
                repairs["FINAL_DATE"] = final_src
                repairs["FINAL_DATE_FLAG"] = "FILLED"
            elif not _dates_equal(current_final, final_src):
                # Prefer C.O. Issued when it disagrees with upstream.
                co = _safe_to_datetime(pi.get("C.O. Issued"))
                if co is not pd.NaT:
                    repairs["FINAL_DATE"] = final_src
                    repairs["FINAL_DATE_FLAG"] = "FIXED"
    elif not pd.isna(current_final):
        repairs["FINAL_DATE"] = pd.NaT
        repairs["FINAL_DATE_FLAG"] = "FIXED"


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Highlands County permit records using information from the raw DATA JSON.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Highlands County".  Must
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

        if schema == "permit_bundle":
            _repair_permit_bundle(row, d, repairs)

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
    hc = df[df["JURISDICTION"] == "Highlands County"].copy()

    print(f"Highlands County records: {len(hc):,}\n")

    repaired = data_repair(hc)

    print("INFERRED_SCHEMA:")
    print(repaired["INFERRED_SCHEMA"].value_counts(dropna=False).to_string())
    print()

    for field in ["STATUS_NORMALIZED", "FILE_DATE", "PERMIT_DATE", "FINAL_DATE"]:
        flag_col = f"{field}_FLAG"
        n_filled = (repaired[flag_col] == "FILLED").sum()
        n_fixed = (repaired[flag_col] == "FIXED").sum()
        print(f"{field}:")
        print(f"  FILLED: {n_filled:>4,}   FIXED: {n_fixed:>4,}")

        before_missing = hc[field].isna().sum()
        after_missing = repaired[field].isna().sum()
        print(f"  Missing before: {before_missing:>4,}   Missing after: {after_missing:>4,}")
        print()

    print("STATUS_NORMALIZED distribution:")
    print("  Before:")
    for s, c in hc["STATUS_NORMALIZED"].value_counts(dropna=False).items():
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

    # Sanity: Open+Issued should be Active; FINAL fills should not invent CO
    n_open_issued_still_review = 0
    n_final_eq_co = 0
    n_final_with_co = 0
    for idx in repaired.index:
        d = _safe_parse(repaired.at[idx, "DATA"]) or {}
        pi = _permit_info(d)
        if pi.get("Status") == "Open" and _safe_to_datetime(pi.get("Issued Date")) is not pd.NaT:
            if repaired.at[idx, "STATUS_NORMALIZED"] != "Active":
                n_open_issued_still_review += 1
        if repaired.at[idx, "STATUS_NORMALIZED"] == "Final":
            co = _safe_to_datetime(pi.get("C.O. Issued"))
            if co is not pd.NaT:
                n_final_with_co += 1
                if _dates_equal(repaired.at[idx, "FINAL_DATE"], co):
                    n_final_eq_co += 1

    print(f"\nOpen+Issued still not Active: {n_open_issued_still_review}")
    print(f"Final with CO where FINAL_DATE == C.O. Issued: {n_final_eq_co} / {n_final_with_co}")

    if AGENT_DATA_PATH:
        out_path = os.path.join(AGENT_DATA_PATH, "highlands_county_repaired_sample.parquet")
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote {out_path}")

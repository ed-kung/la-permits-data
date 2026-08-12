"""Data repair for Collier County (FL) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Collier County DATA is a county portal payload with top-level Summary,
Contacts, Inspections, and either Permit Info or Permits. Two sub-schemas:

  - permit_info:      Summary + Permit Info (+ optional Locations,
                      Business Name at Location (Portal))
  - project_permits:  Summary + Permits list (+ project_id; optional
                      Locations)

Canonical mappings (both schemas share Summary dates/status):
  - Summary.Application Status          → STATUS_NORMALIZED
  - Summary.Application Date            → FILE_DATE
  - Summary.Issued Date                 → PERMIT_DATE
  - Summary.Date Finaled                → FINAL_DATE
    (fallback: last passed Final inspection DateCompleted;
     then last passed inspection for Final rows without Date Finaled)

Known issues repaired:
  - STATUS_NORMALIZED null for Inspections Commenced, Finalled -
    Processing Refund, Invalid License, Revision – Rejected, Pending
    Fees GMD, Address Verification, Fees Paid GMD → FILLED.
  - Final / Inspections Completed rows with null Date Finaled but
    passed inspections → FINAL_DATE FILLED from inspection dates.
  - FILE_DATE / PERMIT_DATE / FINAL_DATE already match Summary dates
    when present; mismatches overwritten defensively.

Not repairable / left as-is:
  - Inactive / In Review rows with no Issued Date → PERMIT_DATE stays
    missing (expected for pre-issuance / never-issued).
  - No true finalization date and no passed inspection → FINAL_DATE
    stays missing (none observed once inspection fallback is applied).
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
    """Parse a date value, returning pd.NaT on failure / sentinels."""
    if val is None or (isinstance(val, str) and not str(val).strip()):
        return pd.NaT
    if not isinstance(val, str) and pd.isna(val):
        return pd.NaT
    text = str(val).strip()
    if text.upper() in ("TBD", "NONE", "N/A", "NA", "00/00/0000", "0/0/0000"):
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
    if "Permits" in keys:
        return "project_permits"
    if "Permit Info" in keys:
        return "permit_info"
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


def _clear_date(repairs: dict, row, field: str) -> None:
    """Clear an incorrect non-null date field."""
    if field in repairs and pd.isna(repairs[field]):
        return
    current = repairs.get(field, row[field])
    if pd.isna(current):
        return
    repairs[field] = pd.NaT
    repairs[f"{field}_FLAG"] = "FIXED"


def _is_pass_outcome(outcome: Optional[str]) -> bool:
    if outcome is None:
        return False
    text = str(outcome).strip().lower()
    if not text:
        return False
    if "fail" in text:
        return False
    return "pass" in text


def _last_passed_final_inspection(d: dict):
    """Latest DateCompleted among passed inspections whose Activity has 'final'."""
    dates = []
    for insp in d.get("Inspections") or []:
        if not isinstance(insp, dict):
            continue
        activity = str(insp.get("Activity") or "")
        if "final" not in activity.lower():
            continue
        if not _is_pass_outcome(insp.get("Outcome")):
            continue
        dc = _safe_to_datetime(insp.get("DateCompleted"))
        if dc is not pd.NaT:
            dates.append(dc)
    return max(dates) if dates else pd.NaT


def _last_passed_inspection(d: dict):
    """Latest DateCompleted among any passed inspection."""
    dates = []
    for insp in d.get("Inspections") or []:
        if not isinstance(insp, dict):
            continue
        if not _is_pass_outcome(insp.get("Outcome")):
            continue
        dc = _safe_to_datetime(insp.get("DateCompleted"))
        if dc is not pd.NaT:
            dates.append(dc)
    return max(dates) if dates else pd.NaT


# ── Status maps ──────────────────────────────────────────────────────────────

# Summary.Application Status (Title Case, as in DATA) → STATUS_NORMALIZED
_STATUS_MAP = {
    # Final / completed
    "Finaled": "Final",
    "Finalled - Processing Refund": "Final",
    "Inspections Completed": "Final",
    # Active / issued / under construction
    "Issued": "Active",
    "Inspections Commenced": "Active",
    # In review / pre-issuance
    "Under Review": "In Review",
    "Ready for Issuance": "In Review",
    "Pending": "In Review",
    "Incomplete Application": "In Review",
    "Reactivate": "In Review",
    "Pending Fees GMD": "In Review",
    "Address Verification": "In Review",
    "Fees Paid GMD": "In Review",
    # Inactive / closed without completion
    "Expired": "Inactive",
    "Cancelled": "Inactive",
    "Denied": "Inactive",
    "Void": "Inactive",
    "Abandoned": "Inactive",
    "Rejected": "Inactive",
    "Invalid License": "Inactive",
    "Revision – Rejected": "Inactive",  # en-dash as in DATA
    "Revision - Rejected": "Inactive",
}


# ── Per-schema repair logic ─────────────────────────────────────────────────

def _repair_record(row, d: dict, repairs: dict) -> None:
    """Repair a Collier County record (shared Summary fields)."""
    summary = d.get("Summary") if isinstance(d.get("Summary"), dict) else {}

    effective_status = _apply_status(
        repairs, row["STATUS_NORMALIZED"], summary.get("Application Status"), _STATUS_MAP
    )

    # FILE_DATE ← Application Date
    _apply_date(repairs, row, "FILE_DATE", summary.get("Application Date"))

    # PERMIT_DATE ← Issued Date
    issued = _safe_to_datetime(summary.get("Issued Date"))
    if issued is not pd.NaT:
        if pd.isna(row["PERMIT_DATE"]):
            if effective_status in ("Active", "Final"):
                repairs["PERMIT_DATE"] = issued
                repairs["PERMIT_DATE_FLAG"] = "FILLED"
        elif not _dates_equal(row["PERMIT_DATE"], issued):
            repairs["PERMIT_DATE"] = issued
            repairs["PERMIT_DATE_FLAG"] = "FIXED"

    # FINAL_DATE ← Date Finaled, else passed Final inspection, else last pass
    date_finaled = _safe_to_datetime(summary.get("Date Finaled"))
    current_final = row["FINAL_DATE"]

    if effective_status == "Final":
        candidate = date_finaled
        if candidate is pd.NaT:
            candidate = _last_passed_final_inspection(d)
        if candidate is pd.NaT:
            candidate = _last_passed_inspection(d)

        if candidate is not pd.NaT:
            if pd.isna(current_final):
                repairs["FINAL_DATE"] = candidate
                repairs["FINAL_DATE_FLAG"] = "FILLED"
            elif not _dates_equal(current_final, candidate):
                # Prefer Summary.Date Finaled over a mismatched upstream value.
                if date_finaled is not pd.NaT:
                    repairs["FINAL_DATE"] = candidate
                    repairs["FINAL_DATE_FLAG"] = "FIXED"
    else:
        # Non-Final rows should not carry a finaled date.
        if not pd.isna(current_final):
            _clear_date(repairs, row, "FINAL_DATE")


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Collier County permit records using information from the raw DATA JSON.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Collier County".  Must
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

        if schema in ("permit_info", "project_permits"):
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
    cc = df[df["JURISDICTION"] == "Collier County"].copy()

    print(f"Collier County records: {len(cc):,}\n")

    repaired = data_repair(cc)

    print("INFERRED_SCHEMA:")
    print(repaired["INFERRED_SCHEMA"].value_counts(dropna=False).to_string())
    print()

    for field in ["STATUS_NORMALIZED", "FILE_DATE", "PERMIT_DATE", "FINAL_DATE"]:
        flag_col = f"{field}_FLAG"
        n_filled = (repaired[flag_col] == "FILLED").sum()
        n_fixed = (repaired[flag_col] == "FIXED").sum()
        print(f"{field}:")
        print(f"  FILLED: {n_filled:>4,}   FIXED: {n_fixed:>4,}")

        before_missing = cc[field].isna().sum()
        after_missing = repaired[field].isna().sum()
        print(f"  Missing before: {before_missing:>4,}   Missing after: {after_missing:>4,}")
        print()

    print("STATUS_NORMALIZED distribution:")
    print("  Before:")
    for s, c in cc["STATUS_NORMALIZED"].value_counts(dropna=False).items():
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

    if AGENT_DATA_PATH:
        out_path = os.path.join(AGENT_DATA_PATH, "collier_county_repaired_sample.parquet")
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote {out_path}")

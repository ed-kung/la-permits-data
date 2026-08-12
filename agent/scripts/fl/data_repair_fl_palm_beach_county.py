"""Data repair for Palm Beach County (FL) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Palm Beach County DATA is a flat PZB / Accela-style permit payload with
top-level keys ``StatusDescription``, ``ApplicationDate``,
``IssuedDate``, ``CompletionDate``, ``ProjDateInactive``, plus optional
detail blocks (``Contact``, ``Contractor``, ``Review - Summary``,
``Inspection``).

Content variants (INFERRED_SCHEMA):

  - pbc_issued_finaled: ApplicationDate + IssuedDate + CompletionDate
  - pbc_issued:         ApplicationDate + IssuedDate (no CompletionDate)
  - pbc_finaled:        ApplicationDate + CompletionDate (no IssuedDate)
  - pbc_applied:        ApplicationDate only
  - pbc_status_only:    StatusDescription present, no usable dates
  - missing / unknown

Canonical mappings:
  - StatusDescription (+ IssuedDate for Approved / Printed /
    Submitted)                                      → STATUS_NORMALIZED
  - ApplicationDate                                 → FILE_DATE
  - IssuedDate                                      → PERMIT_DATE
  - CompletionDate (Final only; never ProjDateInactive)
                                                    → FINAL_DATE

Known issues repaired:
  - 2 ``Complete (Multiple)`` and 1 ``Inactive (Multiple)`` rows had
    null STATUS_NORMALIZED → FILLED to Final / Inactive.
  - 86 ``Admin Closed`` rows wrongly mapped to Final (no CompletionDate;
    only ProjDateInactive) → FIXED to Inactive.
  - 3 ``Printed`` rows with IssuedDate wrongly mapped to In Review
    → FIXED to Active.
  - 23 ``Approved`` (and 1 ``Submitted``) rows without / with IssuedDate
    remapped so Active requires issuance → FIXED where needed.
  - Spurious FINAL_DATE on non-Final rows (including NaN-status
    Complete/Inactive Multiple before fill) cleared when needed.
  - Calendar-day mismatches vs DATA dates overwritten as FIXED
    (none observed in the FL sample, but handled defensively).

Not repairable from DATA:
  - FILE_DATE already matches ApplicationDate for every sample row.
  - 2 ``Finished`` Final rows have CompletionDate but no IssuedDate
    → PERMIT_DATE stays missing.
  - ``Draft`` / ``In Process`` / ``Ready for Issuance`` / unissued
    ``Approved`` rows correctly lack IssuedDate → PERMIT_DATE stays
    missing under In Review.
  - ProjDateInactive is an expiration / inactive stamp, not a
    completion date — never used for FINAL_DATE.
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
    """Parse a date value, returning pd.NaT on failure / out-of-range."""
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
    if da is pd.NaT or db is pd.NaT:
        return False
    return da.normalize() == db.normalize()


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())
    if "StatusDescription" not in keys and "ApplicationDate" not in keys:
        return "unknown"

    app = _safe_to_datetime(data_dict.get("ApplicationDate"))
    issued = _safe_to_datetime(data_dict.get("IssuedDate"))
    final = _safe_to_datetime(data_dict.get("CompletionDate"))

    has_app = app is not pd.NaT
    has_issued = issued is not pd.NaT
    has_final = final is not pd.NaT

    if has_issued and has_final:
        return "pbc_issued_finaled"
    if has_issued:
        return "pbc_issued"
    if has_final:
        return "pbc_finaled"
    if has_app:
        return "pbc_applied"
    if "StatusDescription" in keys:
        return "pbc_status_only"
    return "unknown"


# ── Status mapping ───────────────────────────────────────────────────────────

# Direct StatusDescription → STATUS_NORMALIZED (no IssuedDate needed).
_STATUS_MAP = {
    "Complete": "Final",
    "Complete (Multiple)": "Final",
    "Finished": "Final",
    "Active": "Active",
    "Issued": "Active",
    "Draft": "In Review",
    "In Process": "In Review",
    "Ready for Issuance": "In Review",
    "Admin Closed": "Inactive",
    "Inactive": "Inactive",
    "Inactive (Multiple)": "Inactive",
    "Permit Cancelled": "Inactive",
    "Void": "Inactive",
}

# Statuses that are Active only when IssuedDate is present; otherwise In Review.
_ISSUANCE_GATED = {
    "Approved",
    "Printed",
    "Submitted",
}


def _expected_status(raw_status: Optional[str], issued) -> Optional[str]:
    if raw_status is None:
        return None
    status = str(raw_status).strip()
    if status in _ISSUANCE_GATED:
        return "Active" if issued is not pd.NaT else "In Review"
    return _STATUS_MAP.get(status)


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


# ── Per-schema repair logic ─────────────────────────────────────────────────

def _repair_pbc(row, d: dict, repairs: dict) -> None:
    """Repair a Palm Beach County PZB permit record."""
    raw_status = d.get("StatusDescription")
    issued = _safe_to_datetime(d.get("IssuedDate"))
    expected = _expected_status(raw_status, issued)
    effective_status = _apply_status(repairs, row["STATUS_NORMALIZED"], expected)

    # -- FILE_DATE ← ApplicationDate --
    app = _safe_to_datetime(d.get("ApplicationDate"))
    if app is not pd.NaT:
        if pd.isna(row["FILE_DATE"]):
            repairs["FILE_DATE"] = app
            repairs["FILE_DATE_FLAG"] = "FILLED"
        elif not _dates_equal(row["FILE_DATE"], app):
            repairs["FILE_DATE"] = app
            repairs["FILE_DATE_FLAG"] = "FIXED"

    # -- PERMIT_DATE ← IssuedDate --
    if issued is not pd.NaT:
        if pd.isna(row["PERMIT_DATE"]):
            if effective_status in ("Active", "Final"):
                repairs["PERMIT_DATE"] = issued
                repairs["PERMIT_DATE_FLAG"] = "FILLED"
        elif not _dates_equal(row["PERMIT_DATE"], issued):
            repairs["PERMIT_DATE"] = issued
            repairs["PERMIT_DATE_FLAG"] = "FIXED"

    # -- FINAL_DATE ← CompletionDate (Final only); clear on non-Final --
    # ProjDateInactive is intentionally ignored (expiration / inactive stamp).
    completion = _safe_to_datetime(d.get("CompletionDate"))
    current_final = row["FINAL_DATE"]
    if effective_status == "Final":
        if completion is not pd.NaT:
            if pd.isna(current_final):
                repairs["FINAL_DATE"] = completion
                repairs["FINAL_DATE_FLAG"] = "FILLED"
            elif not _dates_equal(current_final, completion):
                repairs["FINAL_DATE"] = completion
                repairs["FINAL_DATE_FLAG"] = "FIXED"
    elif not pd.isna(current_final):
        repairs["FINAL_DATE"] = pd.NaT
        repairs["FINAL_DATE_FLAG"] = "FIXED"


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Palm Beach County permit records using information from the raw DATA JSON.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Palm Beach County".  Must
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
        if d is None or schema == "unknown":
            continue

        repairs: dict = {}
        _repair_pbc(row, d, repairs)

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
    pbc = df[df["JURISDICTION"] == "Palm Beach County"].copy()

    print(f"Palm Beach County records: {len(pbc):,}\n")

    repaired = data_repair(pbc)

    print("INFERRED_SCHEMA:")
    print(repaired["INFERRED_SCHEMA"].value_counts(dropna=False).to_string())
    print()

    for field in ["STATUS_NORMALIZED", "FILE_DATE", "PERMIT_DATE", "FINAL_DATE"]:
        flag_col = f"{field}_FLAG"
        n_filled = (repaired[flag_col] == "FILLED").sum()
        n_fixed = (repaired[flag_col] == "FIXED").sum()
        print(f"{field}:")
        print(f"  FILLED: {n_filled:>4,}   FIXED: {n_fixed:>4,}")

        before_missing = pbc[field].isna().sum()
        after_missing = repaired[field].isna().sum()
        print(f"  Missing before: {before_missing:>4,}   Missing after: {after_missing:>4,}")
        print()

    print("STATUS_NORMALIZED distribution:")
    print("  Before:")
    for s, c in pbc["STATUS_NORMALIZED"].value_counts(dropna=False).items():
        print(f"    {str(s):15s}: {c:>4,}")
    print("  After:")
    for s, c in repaired["STATUS_NORMALIZED"].value_counts(dropna=False).items():
        print(f"    {str(s):15s}: {c:>4,}")

    print("\nStatus transitions (STATUS_ORIGINAL → before → after):")
    cmp = pd.DataFrame({
        "STATUS_ORIGINAL": pbc["STATUS_ORIGINAL"].values,
        "before": pbc["STATUS_NORMALIZED"].values,
        "after": repaired["STATUS_NORMALIZED"].values,
        "flag": repaired["STATUS_NORMALIZED_FLAG"].values,
    })
    changed = cmp[cmp["before"].fillna("__NA__") != cmp["after"].fillna("__NA__")]
    print(changed.groupby(["STATUS_ORIGINAL", "before", "after", "flag"]).size().to_string())

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

    # Sanity checks vs DATA
    n_file_mismatch = 0
    n_permit_mismatch = 0
    n_final_mismatch = 0
    n_admin_still_final = 0
    n_final_without_completion = 0
    for idx in repaired.index:
        d = _safe_parse(repaired.at[idx, "DATA"]) or {}
        if not _dates_equal(repaired.at[idx, "FILE_DATE"], d.get("ApplicationDate")):
            if _safe_to_datetime(d.get("ApplicationDate")) is not pd.NaT:
                n_file_mismatch += 1
        issued = _safe_to_datetime(d.get("IssuedDate"))
        if issued is not pd.NaT and not pd.isna(repaired.at[idx, "PERMIT_DATE"]):
            if not _dates_equal(repaired.at[idx, "PERMIT_DATE"], issued):
                n_permit_mismatch += 1
        if repaired.at[idx, "STATUS_NORMALIZED"] == "Final":
            comp = _safe_to_datetime(d.get("CompletionDate"))
            if comp is pd.NaT:
                n_final_without_completion += 1
            elif not pd.isna(repaired.at[idx, "FINAL_DATE"]) and not _dates_equal(
                repaired.at[idx, "FINAL_DATE"], comp
            ):
                n_final_mismatch += 1
        if str(d.get("StatusDescription")) == "Admin Closed":
            if repaired.at[idx, "STATUS_NORMALIZED"] == "Final":
                n_admin_still_final += 1

    print(f"\nFILE_DATE mismatches vs ApplicationDate: {n_file_mismatch}")
    print(f"PERMIT_DATE mismatches vs IssuedDate: {n_permit_mismatch}")
    print(f"FINAL_DATE mismatches vs CompletionDate (Final): {n_final_mismatch}")
    print(f"Admin Closed still Final: {n_admin_still_final}")
    print(f"Final without CompletionDate: {n_final_without_completion}")

    if AGENT_DATA_PATH:
        out_path = os.path.join(AGENT_DATA_PATH, "palm_beach_county_repaired_sample.parquet")
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote {out_path}")

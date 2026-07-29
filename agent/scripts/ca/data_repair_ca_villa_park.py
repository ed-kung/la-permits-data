"""Data repair for Villa Park (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Villa Park DATA is a flat civic portal scrape. All rows share core
top-level keys (``Status``, ``Permit Date``, ``Finalized Date``,
``Permit Number``, ``Permit Type``, ``fees``, ``payments``,
``contractors``, ``inspections``, ``property_info``, …). Optional keys
define the INFERRED_SCHEMA variants:

  - portal_reviews:               has ``reviews`` (no plan_reviews)
  - portal_plan_reviews:          has ``plan_reviews`` (no record_type)
  - portal_plan_reviews_rtype:    has ``plan_reviews`` +
                                  ``record_type_from_contractor_box``

Canonical mappings:
  - DATA.Status              → STATUS_NORMALIZED
  - DATA['Permit Date']      → FILE_DATE  (application / submittal)
  - (no Issued Date field)   → PERMIT_DATE cannot be filled from DATA
  - DATA['Finalized Date']   → FINAL_DATE (when status is Final;
                                ignore 01/01/1900 sentinel)

Known issues repaired:
  - 805 null STATUS_NORMALIZED rows for unmapped portal statuses
    (Paid and Issued → Active/Final, Approved Plan Check /
    Approved Pending Payment / Submitted Pending Payment → In Review)
    → FILLED. One STATUS_ORIGINAL lag (In Review while DATA.Status is
    Paid and Issued) and two Issued→Final promotions → FIXED.
  - Active-class rows (Issued / Paid and Issued) that carry a real
    Finalized Date are promoted to Final (portal status lag).
  - All 14 existing PERMIT_DATE values were incorrectly copied from
    plan_reviews/reviews completed_date (plan-check stamps, not
    issuance) → cleared FIXED.
  - FINAL_DATE on non-Final rows (1900-01-01 sentinels on Opened/Void;
    Finalized Date leftovers on void/expired/approved-plan-check)
    → cleared FIXED (26). Promoted Final rows already carried matching
    Finalized Date values.
  - Finaled rows already matching Finalized Date are left alone;
    Finaled with empty Finalized Date cannot be filled (inspections
    lack completed_date).

Not repairable / left as-is:
  - FILE_DATE already matches Permit Date for every sample row.
  - No Issued Date / Issue Date field exists; Active/Final PERMIT_DATE
    remains empty after clearing the 14 false positives.
  - 46 blank Status and 1 Engineering General rows stay
    STATUS_NORMALIZED null.
  - 128 Finaled rows have empty Finalized Date → FINAL_DATE stays null.
"""

from __future__ import annotations

import json
import math
from typing import Optional

import numpy as np
import pandas as pd


_MIN_YEAR = 1901
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
        return json.loads(data)
    return data


def _safe_to_datetime(val):
    """Parse a date value, returning pd.NaT on failure or sentinel/implausible year."""
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return pd.NaT
    if isinstance(val, str) and not str(val).strip():
        return pd.NaT
    try:
        dt = pd.to_datetime(val, errors="coerce")
    except (ValueError, TypeError):
        return pd.NaT
    if dt is pd.NaT or pd.isna(dt):
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


_CORE_KEYS = {
    "Status",
    "Permit Date",
    "Finalized Date",
    "Permit Number",
}


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())
    if not _CORE_KEYS <= keys:
        return "unknown"
    if "plan_reviews" in keys and "record_type_from_contractor_box" in keys:
        return "portal_plan_reviews_rtype"
    if "plan_reviews" in keys:
        return "portal_plan_reviews"
    if "reviews" in keys:
        return "portal_reviews"
    return "portal_core"


# ── Status mapping ──────────────────────────────────────────────────────────

_STATUS_MAP = {
    # Final
    "Finaled": "Final",
    "Complete": "Final",
    # Active — issued / approved open permits
    "Issued": "Active",
    "Paid and Issued": "Active",
    "Approved": "Active",
    # In Review — application / plan check / hold / payment pending
    "In Plan Check": "In Review",
    "Opened": "In Review",
    "Submitted": "In Review",
    "ON HOLD": "In Review",
    "On Hold": "In Review",
    "Approved Plan Check": "In Review",
    "Approved Pending Payment": "In Review",
    "Submitted Pending Payment": "In Review",
    # Inactive
    "Void": "Inactive",
    "Expired": "Inactive",
    "Canceled": "Inactive",
    "Cancelled": "Inactive",
    "Withdrawn": "Inactive",
    "Denied": "Inactive",
}

# Statuses that are Active-class before a Finalized Date promotion.
_ACTIVE_FOR_FINAL_PROMOTE = {"Active"}


def _raw_status(d: dict) -> Optional[str]:
    raw = d.get("Status")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return None


def _expected_status(d: dict) -> Optional[str]:
    raw = _raw_status(d)
    if raw is None:
        return None
    return _STATUS_MAP.get(raw)


def _file_date_from_data(d: dict):
    return _safe_to_datetime(d.get("Permit Date"))


def _finalized_date(d: dict):
    """Return Finalized Date, treating 01/01/1900 as missing."""
    return _safe_to_datetime(d.get("Finalized Date"))


# ── Repair logic ────────────────────────────────────────────────────────────

def _repair_record(row, d: dict, repairs: dict):
    current_status = row["STATUS_NORMALIZED"]
    expected = _expected_status(d)
    finalized = _finalized_date(d)

    # -- STATUS_NORMALIZED --
    # Map from portal Status, then promote Active + real Finalized Date → Final
    # (portal Status often lags as Paid and Issued / Issued after finaling).
    candidate = expected
    if candidate in _ACTIVE_FOR_FINAL_PROMOTE and finalized is not pd.NaT:
        candidate = "Final"

    if candidate is not None:
        if pd.isna(current_status):
            repairs["STATUS_NORMALIZED"] = candidate
            repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"
        elif current_status != candidate:
            repairs["STATUS_NORMALIZED"] = candidate
            repairs["STATUS_NORMALIZED_FLAG"] = "FIXED"

    effective_status = repairs.get("STATUS_NORMALIZED", current_status)

    # -- FILE_DATE --
    file_date = _file_date_from_data(d)
    if file_date is not pd.NaT:
        if pd.isna(row["FILE_DATE"]):
            repairs["FILE_DATE"] = file_date
            repairs["FILE_DATE_FLAG"] = "FILLED"
        elif not _dates_equal(row["FILE_DATE"], file_date):
            repairs["FILE_DATE"] = file_date
            repairs["FILE_DATE_FLAG"] = "FIXED"

    # -- PERMIT_DATE --
    # Villa Park has no Issued Date field. Existing PERMIT_DATE values in
    # the sample match plan_reviews/reviews completed_date (plan-check
    # stamps), not issuance → clear them.
    current_permit = row["PERMIT_DATE"]
    if not pd.isna(current_permit):
        repairs["PERMIT_DATE"] = pd.NaT
        repairs["PERMIT_DATE_FLAG"] = "FIXED"

    # -- FINAL_DATE --
    current_final = row["FINAL_DATE"]
    # Treat sentinel 1900-01-01 in the column as missing/incorrect.
    current_final_ok = _safe_to_datetime(current_final)

    if effective_status == "Final":
        if finalized is not pd.NaT:
            if pd.isna(current_final_ok):
                repairs["FINAL_DATE"] = finalized
                repairs["FINAL_DATE_FLAG"] = "FILLED"
            elif not _dates_equal(current_final_ok, finalized):
                repairs["FINAL_DATE"] = finalized
                repairs["FINAL_DATE_FLAG"] = "FIXED"
        elif not pd.isna(current_final) and pd.isna(current_final_ok):
            # Final without usable Finalized Date but column has sentinel → clear.
            repairs["FINAL_DATE"] = pd.NaT
            repairs["FINAL_DATE_FLAG"] = "FIXED"
    elif not pd.isna(current_final):
        repairs["FINAL_DATE"] = pd.NaT
        repairs["FINAL_DATE_FLAG"] = "FIXED"


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Villa Park (CA) permit records using information from the raw DATA JSON.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Villa Park". Must contain
        columns STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, FINAL_DATE,
        and DATA.

    Returns
    -------
    pd.DataFrame
        Copy of *df* with corrected field values, an INFERRED_SCHEMA column
        naming the DATA JSON sub-schema identified for each record, and new
        flag columns: STATUS_NORMALIZED_FLAG, FILE_DATE_FLAG,
        PERMIT_DATE_FLAG, FINAL_DATE_FLAG. Flag values are "FILLED"
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
    from pathlib import Path

    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[3] / ".env")
    MY_DATA_PATH = os.getenv("MY_DATA_PATH")
    AGENT_DATA_PATH = os.getenv("AGENT_DATA_PATH")
    filepath = os.path.join(MY_DATA_PATH, "processed_data", "permits_ca_sample.parquet")
    df = pd.read_parquet(filepath)
    city = df[(df["JURISDICTION"] == "Villa Park") & (df["STATE"] == "CA")].copy()

    print(f"Villa Park records: {len(city):,}\n")

    repaired = data_repair(city)

    print("INFERRED_SCHEMA:")
    for s, c in repaired["INFERRED_SCHEMA"].value_counts(dropna=False).items():
        print(f"  {str(s):45s}: {c:>4,}")
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

    print("\nStatus transitions (where flag set):")
    changed = repaired[repaired["STATUS_NORMALIZED_FLAG"].notna()]
    for (a, b), n in (
        pd.DataFrame({
            "before": city.loc[changed.index, "STATUS_NORMALIZED"].fillna("null"),
            "after": changed["STATUS_NORMALIZED"].fillna("null"),
        })
        .value_counts()
        .items()
    ):
        print(f"  {a!s:15s} → {b!s:15s}: {n}")

    print("\nPERMIT_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["PERMIT_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} "
              f"({n_has / len(sub) if len(sub) else 0:.1%})")

    print("\nFINAL_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FINAL_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} "
              f"({n_has / len(sub) if len(sub) else 0:.1%})")

    print("\nFILE_DATE coverage after repair: "
          f"{repaired['FILE_DATE'].notna().sum()} / {len(repaired)}")

    if AGENT_DATA_PATH:
        out_dir = Path(AGENT_DATA_PATH) / "repaired"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "permits_ca_villa_park_repaired.parquet"
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote repaired sample → {out_path}")

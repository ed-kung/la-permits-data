"""Data repair for Calistoga (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Calistoga DATA is a civic portal scrape with top-level keys ``Status:``,
``Permit Details``, ``Inspections``, ``Reviews``, etc. Content variants
(INFERRED_SCHEMA):

  - portal_migrated:              Sub Type Migrated / migrated form fields
  - portal_reviews_inspections:   nonempty Reviews + Inspections
  - portal_reviews:               nonempty Reviews only
  - portal_inspections:           nonempty Inspections only
  - portal_basic:                 Status / Permit Details shell only
  - missing

Canonical mappings:
  - DATA['Status:']                                         → STATUS_NORMALIZED
  - Earliest Reviews[].Start                                → FILE_DATE
  - Permit Details['Issue Date:']                           → PERMIT_DATE
  - Latest passed Final* inspection (type contains 'Final') → FINAL_DATE

Known issues repaired:
  - FILE_DATE often taken from a mid-stream review Start/Completion
    (Permit Review, Review Complete, …) instead of the earliest
    Reviews[].Start application date → FIXED; missing FILE with
    Reviews → FILLED.
  - FINAL_DATE missing on every row; Closed permits with a passed
    Final / Occupancy - Final / Final Fire* inspection → FILLED.

Not repairable / left as-is:
  - One blank-Status encroachment shell → STATUS stays missing.
  - ~1.7k rows (mostly Migrated) have no Reviews → FILE_DATE stays
    missing.
  - Active/Final rows with empty Issue Date: (mostly Migrated) →
    PERMIT_DATE stays missing.
  - Most Closed Migrated shells have empty Inspections → FINAL_DATE
    stays missing.
  - Migrated Jan-1 Issue Dates match DATA and are left unchanged.
"""

from __future__ import annotations

import json
import math
from typing import Optional

import numpy as np
import pandas as pd


_MIN_YEAR = 1970
_MAX_YEAR = 2035

_PASS_STATUSES = {"pass", "completed", "complete"}


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
    """Parse a date value, returning pd.NaT on failure or implausible year."""
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
    if getattr(dt, "tzinfo", None) is not None:
        dt = dt.tz_convert("UTC").tz_localize(None)
    year = int(dt.year)
    if year < _MIN_YEAR or year > _MAX_YEAR:
        return pd.NaT
    return dt


def _dates_equal(a, b) -> bool:
    da = _safe_to_datetime(a)
    db = _safe_to_datetime(b)
    if da is pd.NaT or db is pd.NaT:
        return False
    return da.normalize() == db.normalize()


def _permit_details(d: dict) -> dict:
    pd_ = d.get("Permit Details")
    return pd_ if isinstance(pd_, dict) else {}


def _reviews(d: dict) -> list:
    revs = d.get("Reviews")
    return revs if isinstance(revs, list) else []


def _inspections(d: dict) -> list:
    insp = d.get("Inspections")
    return insp if isinstance(insp, list) else []


def _insp_status_clean(raw) -> str:
    return str(raw or "").split("\n")[0].strip().lower()


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())
    subtype = str(data_dict.get("Sub Type") or _permit_details(data_dict).get("Sub Type:") or "")
    migrated = subtype == "Migrated" or any("migrated" in k.lower() for k in keys)
    if migrated:
        return "portal_migrated"

    has_reviews = bool(_reviews(data_dict))
    has_insp = bool(_inspections(data_dict))
    if has_reviews and has_insp:
        return "portal_reviews_inspections"
    if has_reviews:
        return "portal_reviews"
    if has_insp:
        return "portal_inspections"
    return "portal_basic"


# ── Status mapping ───────────────────────────────────────────────────────────

_STATUS_MAP = {
    "Closed": "Final",
    "Issued": "Active",
    "Under Review": "In Review",
    "Ready to Issue": "In Review",
    "Online Application Received": "In Review",
    "Expired": "Inactive",
    "Void": "Inactive",
    "Withdrawn": "Inactive",
    "Refunded": "Inactive",
}


def _expected_status(d: dict) -> Optional[str]:
    raw = d.get("Status:")
    if isinstance(raw, str) and raw.strip():
        return _STATUS_MAP.get(raw.strip())
    return None


def _file_date_from_data(d: dict):
    """Earliest Reviews[].Start = application / intake date."""
    starts = []
    for r in _reviews(d):
        if not isinstance(r, dict):
            continue
        dt = _safe_to_datetime(r.get("Start"))
        if dt is not pd.NaT:
            starts.append(dt)
    return min(starts) if starts else pd.NaT


def _issue_date(d: dict):
    return _safe_to_datetime(_permit_details(d).get("Issue Date:"))


def _final_date_from_data(d: dict):
    """Latest passed inspection whose type name contains 'Final'."""
    dates = []
    for i in _inspections(d):
        if not isinstance(i, dict):
            continue
        itype = str(i.get("Inspection Type") or "")
        if "final" not in itype.lower():
            continue
        if _insp_status_clean(i.get("Status")) not in _PASS_STATUSES:
            continue
        dt = _safe_to_datetime(i.get("Date"))
        if dt is not pd.NaT:
            dates.append(dt)
    return max(dates) if dates else pd.NaT


# ── Repair logic ─────────────────────────────────────────────────────────────

def _repair_record(row, d: dict, repairs: dict):
    # -- STATUS_NORMALIZED --
    current_status = row["STATUS_NORMALIZED"]
    expected = _expected_status(d)
    if expected is not None:
        if pd.isna(current_status):
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"
        elif current_status != expected:
            repairs["STATUS_NORMALIZED"] = expected
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
    issued = _issue_date(d)
    if issued is not pd.NaT:
        if pd.isna(row["PERMIT_DATE"]):
            if effective_status in ("Active", "Final"):
                repairs["PERMIT_DATE"] = issued
                repairs["PERMIT_DATE_FLAG"] = "FILLED"
        elif not _dates_equal(row["PERMIT_DATE"], issued):
            repairs["PERMIT_DATE"] = issued
            repairs["PERMIT_DATE_FLAG"] = "FIXED"

    # -- FINAL_DATE --
    if effective_status == "Final":
        final_date = _final_date_from_data(d)
        if final_date is not pd.NaT:
            if pd.isna(row["FINAL_DATE"]):
                repairs["FINAL_DATE"] = final_date
                repairs["FINAL_DATE_FLAG"] = "FILLED"
            elif not _dates_equal(row["FINAL_DATE"], final_date):
                repairs["FINAL_DATE"] = final_date
                repairs["FINAL_DATE_FLAG"] = "FIXED"


# ── Main entry point ─────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Calistoga (CA) permit records using information from the raw DATA JSON.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Calistoga". Must contain
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


# ── CLI: run standalone to preview repair stats ──────────────────────────────

if __name__ == "__main__":
    import os
    from pathlib import Path

    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[3] / ".env")
    MY_DATA_PATH = os.getenv("MY_DATA_PATH")
    AGENT_DATA_PATH = os.getenv("AGENT_DATA_PATH")
    filepath = os.path.join(MY_DATA_PATH, "processed_data", "permits_ca_sample.parquet")
    df = pd.read_parquet(filepath)
    city = df[(df["JURISDICTION"] == "Calistoga") & (df["STATE"] == "CA")].copy()

    print(f"Calistoga records: {len(city):,}\n")

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
        out_path = Path(AGENT_DATA_PATH) / "calistoga_repaired_sample.parquet"
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote repaired sample → {out_path}")

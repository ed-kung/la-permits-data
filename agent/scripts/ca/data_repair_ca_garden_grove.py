"""Data repair for Garden Grove (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Garden Grove DATA is a city permit-portal scrape with two top-level
schemas (used as INFERRED_SCHEMA):

  - permit_status:  keys include ``permit#``, ``permit status``,
                    ``inspection status``, ``location`` (~97% of rows)
  - project_status: keys include ``Project``, ``status``, ``address``
                    (recent scrapes; STATUS_NORMALIZED was never set)

Canonical mappings:
  - DATA['permit status'] or DATA['status']     → STATUS_NORMALIZED
  - DATA['created on'] (else DATA['issued on']) → FILE_DATE
  - DATA['issued on']                           → PERMIT_DATE
  - Latest dated inspection whose type contains
    "Final" (skip Canceled / Final Application
    Evaluation)                                 → FINAL_DATE

Known issues repaired:
  - 52 project_status rows and 1 empty-permit-status row have null
    STATUS_NORMALIZED → FILLED from DATA status / inspection status.
  - 12 Suspended rows were normalized as In Review → FIXED to Inactive.
  - FILE_DATE missing wherever ``created on`` / ``issued on`` exist
    (mostly legacy permit_status shells with blank created on, plus
    all project_status rows) → FILLED.
  - PERMIT_DATE missing on Active/Final rows that have ``issued on``
    (project_status rows) → FILLED.
  - FINAL_DATE missing on Final rows with a usable final inspection
    → FILLED; values that disagree with the latest final inspection
    → FIXED.

Not repairable / left as-is:
  - ~1,200 legacy Finaled / Inspections shells have blank ``created on``
    and no alternate application date other than ``issued on`` (used as
    FILE_DATE proxy) or neither date.
  - Vast majority of Finaled rows have empty ``inspections`` ("No
    inspections in System") → FINAL_DATE stays missing.
  - A handful of Active/Final rows have blank ``issued on`` →
    PERMIT_DATE stays missing.
"""

from __future__ import annotations

import json
import math
import re
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
    """Parse a date value, returning pd.NaT on failure."""
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return pd.NaT
    if isinstance(val, str) and not str(val).strip():
        return pd.NaT
    try:
        dt = pd.to_datetime(val, utc=True)
    except (ValueError, TypeError):
        return pd.NaT
    if dt is pd.NaT or pd.isna(dt):
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
    if "permit status" in keys and "permit#" in keys:
        return "permit_status"
    if "status" in keys and "Project" in keys:
        return "project_status"
    return "unknown"


# ── Status mapping ───────────────────────────────────────────────────────────

# Shared vocabulary across permit_status and project_status schemas.
_STATUS_MAP = {
    # Final
    "finaled": "Final",
    "closed": "Final",
    # Active
    "inspections": "Active",
    "issued": "Active",
    # In Review
    "plan check": "In Review",
    "plan check final": "In Review",
    "payment check": "In Review",
    "applicaion": "In Review",  # portal typo
    "application": "In Review",
    "undefined": "In Review",
    # Inactive
    "cancelled": "Inactive",
    "canceled": "Inactive",
    "suspended": "Inactive",
    "expired": "Inactive",
}


def _raw_status(d: dict) -> Optional[str]:
    """Return the best raw status string from DATA."""
    for key in ("permit status", "status"):
        val = d.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    # Empty permit status: fall back to first line of inspection status.
    insp = d.get("inspection status")
    if isinstance(insp, str) and insp.strip():
        return insp.strip().split("\n")[0].strip()
    return None


def _expected_status(d: dict) -> Optional[str]:
    raw = _raw_status(d)
    if raw is None:
        return None
    return _STATUS_MAP.get(raw.lower())


# ── Date extraction ──────────────────────────────────────────────────────────

def _file_date_from_data(d: dict):
    """Application / create date; fall back to issued on when create is blank."""
    created = _safe_to_datetime(d.get("created on"))
    if created is not pd.NaT:
        return created
    return _safe_to_datetime(d.get("issued on"))


def _permit_date_from_data(d: dict):
    return _safe_to_datetime(d.get("issued on"))


def _is_final_inspection_type(type_str: str) -> bool:
    if not type_str:
        return False
    cleaned = type_str.replace("\n", " ").strip()
    if not re.search(r"\bfinal\b", cleaned, re.I):
        return False
    # Administrative placeholder, usually undated / not a completion event.
    if re.search(r"final\s+application\s+evaluation", cleaned, re.I):
        return False
    return True


def _final_date_from_data(d: dict):
    """Latest dated final-type inspection, skipping canceled results."""
    best = pd.NaT
    for row in d.get("inspections") or []:
        if not isinstance(row, (list, tuple)) or len(row) < 3:
            continue
        date_s, result, typ = row[0], row[1] if len(row) > 1 else "", row[2]
        if not _is_final_inspection_type(typ or ""):
            continue
        result_s = (result or "").strip().lower()
        if result_s in ("canceled", "cancelled"):
            continue
        dt = _safe_to_datetime(date_s)
        if dt is pd.NaT:
            continue
        if best is pd.NaT or dt > best:
            best = dt
    return best


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
            # Only FIXED when created on is present and disagrees; do not
            # overwrite a correct created-on FILE_DATE with issued-on fallback.
            created = _safe_to_datetime(d.get("created on"))
            if created is not pd.NaT and not _dates_equal(row["FILE_DATE"], created):
                repairs["FILE_DATE"] = created
                repairs["FILE_DATE_FLAG"] = "FIXED"

    # -- PERMIT_DATE --
    permit_date = _permit_date_from_data(d)
    if permit_date is not pd.NaT:
        if pd.isna(row["PERMIT_DATE"]):
            if effective_status in ("Active", "Final"):
                repairs["PERMIT_DATE"] = permit_date
                repairs["PERMIT_DATE_FLAG"] = "FILLED"
        elif not _dates_equal(row["PERMIT_DATE"], permit_date):
            repairs["PERMIT_DATE"] = permit_date
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
    elif not pd.isna(row["FINAL_DATE"]):
        repairs["FINAL_DATE"] = pd.NaT
        repairs["FINAL_DATE_FLAG"] = "FIXED"


# ── Main entry point ─────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Garden Grove permit records using information from the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Garden Grove".  Must contain
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
    from dotenv import load_dotenv, find_dotenv

    load_dotenv(find_dotenv())
    MY_DATA_PATH = os.getenv("MY_DATA_PATH")
    filepath = os.path.join(
        MY_DATA_PATH, "processed_data", "permits_ca_sample.parquet"
    )
    df = pd.read_parquet(filepath)
    city = df[df["JURISDICTION"] == "Garden Grove"].copy()

    print(f"Garden Grove records: {len(city):,}\n")

    repaired = data_repair(city)

    print("INFERRED_SCHEMA:")
    for s, c in repaired["INFERRED_SCHEMA"].value_counts(dropna=False).items():
        print(f"  {str(s):30s}: {c:>4,}")
    print()

    for field in ["STATUS_NORMALIZED", "FILE_DATE", "PERMIT_DATE", "FINAL_DATE"]:
        flag_col = f"{field}_FLAG"
        n_filled = (repaired[flag_col] == "FILLED").sum()
        n_fixed = (repaired[flag_col] == "FIXED").sum()
        print(f"{field}:")
        print(f"  FILLED: {n_filled:>4,}   FIXED: {n_fixed:>4,}")

        before_missing = city[field].isna().sum()
        after_missing = repaired[field].isna().sum()
        print(
            f"  Missing before: {before_missing:>4,}   "
            f"Missing after: {after_missing:>4,}"
        )
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
        pct = n_has / len(sub) if len(sub) else 0.0
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({pct:.1%})")

    print("\nFINAL_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FINAL_DATE"].notna().sum()
        pct = n_has / len(sub) if len(sub) else 0.0
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({pct:.1%})")

    print("\nFILE_DATE missing by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_miss = sub["FILE_DATE"].isna().sum()
        print(f"  {status:15s}: missing {n_miss:>4,} / {len(sub):>4,}")

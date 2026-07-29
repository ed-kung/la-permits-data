"""Data repair for Vista (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Vista DATA is a flat agency export with the same logical fields under
three key-naming variants (INFERRED_SCHEMA):

  - flat_mixed:   mixed-case keys (``PERMIT_STATUS``, ``DATE_ENTERED``,
                  ``ParcelNo``, ``Applicant``, …)
  - flat_upper:   upper-case keys (``PERMIT_STATUS``, ``PARCELNO``,
                  ``APPLICANT``, ``VALUATION``, …)
  - flat_spaced:  spaced keys (``PERMIT STATUS``, ``DATE ENTERED``,
                  ``Parcel No``, …) plus a null placeholder key

Canonical fields (after key normalization):
  - PERMIT_STATUS  → STATUS_NORMALIZED
  - DATE_ENTERED   → FILE_DATE
  - DATE_ISSUED    → PERMIT_DATE
  - DATE_FINALED   → FINAL_DATE

Known issues repaired:
  - All 2,000 sample rows have null FILE_DATE / PERMIT_DATE / FINAL_DATE
    despite dates present in DATA → FILLED from DATE_ENTERED /
    DATE_ISSUED / DATE_FINALED.
  - Null STATUS_NORMALIZED on the entire ``flat_spaced`` scrape plus
    ``BLUES`` / ``STOP`` shells in ``flat_mixed`` (177 rows) → FILLED.
  - ``BLUES`` shells that already carry DATE_FINALED → Final (not Active).

Not repairable / left as-is:
  - 13 FINAL / FINALED shells with null DATE_FINALED → FINAL_DATE stays
    missing.
  - DATE_FINALED on VOID rows is treated as a closure stamp, not a
    permit finaled date (status stays Inactive; FINAL_DATE not filled).
  - STOP / EXPIRED / CANCEL / CD-CANCEL stay Inactive.
"""

from __future__ import annotations

import json
import math
from typing import Optional

import numpy as np
import pandas as pd


_MIN_YEAR = 1990
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
    """Parse a date value, returning pd.NaT on failure / blank / bad year."""
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return pd.NaT
    if isinstance(val, str):
        s = val.strip()
        if not s or s.upper() in {"TBD", "NULL", "NONE", "N/A", "NA"}:
            return pd.NaT
    try:
        dt = pd.to_datetime(val, errors="coerce")
    except (ValueError, TypeError):
        return pd.NaT
    if dt is pd.NaT or pd.isna(dt):
        return pd.NaT
    dt = pd.Timestamp(dt)
    if getattr(dt, "tzinfo", None) is not None:
        dt = dt.tz_convert("UTC").tz_localize(None)
    year = int(dt.year)
    if year < _MIN_YEAR or year > _MAX_YEAR:
        return pd.NaT
    return dt


def _dates_equal(a, b) -> bool:
    da = _safe_to_datetime(a)
    db = _safe_to_datetime(b)
    if da is pd.NaT or db is pd.NaT or pd.isna(da) or pd.isna(db):
        return False
    return da.normalize() == db.normalize()


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())
    if "PERMIT STATUS" in keys or "DATE ENTERED" in keys:
        return "flat_spaced"
    if "APPLICANT" in keys or "PARCELNO" in keys or "VALUATION" in keys:
        return "flat_upper"
    if "PERMIT_STATUS" in keys or "DATE_ENTERED" in keys:
        return "flat_mixed"
    return "unknown"


def _normalize_keys(d: dict) -> dict:
    """Map spaced / mixed / upper key variants onto underscore names."""
    out = {}
    for k, v in d.items():
        if not isinstance(k, str):
            continue
        nk = k.strip().replace(" ", "_").upper()
        # Prefer first non-null when duplicates appear.
        if nk in out and out[nk] is not None:
            continue
        out[nk] = v
    return out


def _strip_status(val) -> Optional[str]:
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return None
    s = str(val).strip()
    return s or None


# ── Status mapping ───────────────────────────────────────────────────────────

_STATUS_MAP = {
    "FINALED": "Final",
    "FINAL": "Final",
    "ISSUED": "Active",
    "CD-ISSUED": "Active",
    "APPROVED": "Active",
    "BLUES": "Active",
    "OPEN": "Active",
    "CE-OPEN": "Active",
    "EXPIRED": "Inactive",
    "VOID": "Inactive",
    "CANCEL": "Inactive",
    "CD-CANCEL": "Inactive",
    "STOP": "Inactive",
    "CD-OPEN": "In Review",
    "PREAPP": "In Review",
}


def _expected_status(raw_status: Optional[str], date_issued, date_finaled) -> Optional[str]:
    if raw_status is None:
        return None
    expected = _STATUS_MAP.get(raw_status)
    if expected is None:
        return None

    # Pre-issuance open/preapp shells without an issue stamp stay In Review.
    if raw_status in ("OPEN", "CE-OPEN") and date_issued is pd.NaT:
        return "In Review"

    # BLUES with a finaled stamp is a completed shell mislabeled as blues.
    if raw_status == "BLUES" and date_finaled is not pd.NaT:
        return "Final"

    return expected


def _set_field(repairs: dict, field: str, new_val, current_val):
    """Record a FILLED or FIXED repair for *field*."""
    if pd.isna(current_val):
        repairs[field] = new_val
        repairs[f"{field}_FLAG"] = "FILLED"
    else:
        repairs[field] = new_val
        repairs[f"{field}_FLAG"] = "FIXED"


def _repair_row(row, d: dict, repairs: dict):
    norm = _normalize_keys(d)
    raw_status = _strip_status(norm.get("PERMIT_STATUS"))
    date_entered = _safe_to_datetime(norm.get("DATE_ENTERED"))
    date_issued = _safe_to_datetime(norm.get("DATE_ISSUED"))
    date_finaled = _safe_to_datetime(norm.get("DATE_FINALED"))

    # -- STATUS_NORMALIZED --
    current_status = row["STATUS_NORMALIZED"]
    expected = _expected_status(raw_status, date_issued, date_finaled)
    if expected is not None:
        if pd.isna(current_status):
            _set_field(repairs, "STATUS_NORMALIZED", expected, current_status)
        elif current_status != expected:
            _set_field(repairs, "STATUS_NORMALIZED", expected, current_status)

    effective_status = repairs.get("STATUS_NORMALIZED", current_status)

    # -- FILE_DATE --
    if date_entered is not pd.NaT:
        if pd.isna(row["FILE_DATE"]):
            _set_field(repairs, "FILE_DATE", date_entered, row["FILE_DATE"])
        elif not _dates_equal(row["FILE_DATE"], date_entered):
            _set_field(repairs, "FILE_DATE", date_entered, row["FILE_DATE"])

    # -- PERMIT_DATE --
    if effective_status in ("Active", "Final") and date_issued is not pd.NaT:
        if pd.isna(row["PERMIT_DATE"]):
            _set_field(repairs, "PERMIT_DATE", date_issued, row["PERMIT_DATE"])
        elif not _dates_equal(row["PERMIT_DATE"], date_issued):
            _set_field(repairs, "PERMIT_DATE", date_issued, row["PERMIT_DATE"])

    # -- FINAL_DATE --
    if effective_status == "Final":
        if date_finaled is not pd.NaT:
            if pd.isna(row["FINAL_DATE"]):
                _set_field(repairs, "FINAL_DATE", date_finaled, row["FINAL_DATE"])
            elif not _dates_equal(row["FINAL_DATE"], date_finaled):
                _set_field(repairs, "FINAL_DATE", date_finaled, row["FINAL_DATE"])
    else:
        # Clear spurious FINAL_DATE on non-Final rows (e.g. VOID closure stamps).
        if not pd.isna(row["FINAL_DATE"]):
            repairs["FINAL_DATE"] = pd.NaT
            repairs["FINAL_DATE_FLAG"] = "FIXED"


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Vista (CA) permit records using information from the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Vista".  Must contain
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
        _repair_row(row, d, repairs)

        for key, value in repairs.items():
            out.at[idx, key] = value

    return out


# ── CLI: run standalone to preview repair stats ─────────────────────────────

if __name__ == "__main__":
    import os
    from dotenv import load_dotenv, find_dotenv

    load_dotenv(find_dotenv())
    MY_DATA_PATH = os.getenv("MY_DATA_PATH")
    filepath = os.path.join(MY_DATA_PATH, "processed_data", "permits_ca_sample.parquet")
    df = pd.read_parquet(filepath)
    vista = df[df["JURISDICTION"] == "Vista"].copy()

    print(f"Vista records: {len(vista):,}\n")

    repaired = data_repair(vista)

    print("INFERRED_SCHEMA:")
    print(repaired["INFERRED_SCHEMA"].value_counts(dropna=False).to_string())
    print()

    for field in ["STATUS_NORMALIZED", "FILE_DATE", "PERMIT_DATE", "FINAL_DATE"]:
        flag_col = f"{field}_FLAG"
        n_filled = (repaired[flag_col] == "FILLED").sum()
        n_fixed = (repaired[flag_col] == "FIXED").sum()
        print(f"{field}:")
        print(f"  FILLED: {n_filled:>4,}   FIXED: {n_fixed:>4,}")

        before_missing = vista[field].isna().sum()
        after_missing = repaired[field].isna().sum()
        print(f"  Missing before: {before_missing:>4,}   Missing after: {after_missing:>4,}")
        print()

    print("STATUS_NORMALIZED distribution:")
    print("  Before:")
    for s, c in vista["STATUS_NORMALIZED"].value_counts(dropna=False).items():
        print(f"    {str(s):15s}: {c:>4,}")
    print("  After:")
    for s, c in repaired["STATUS_NORMALIZED"].value_counts(dropna=False).items():
        print(f"    {str(s):15s}: {c:>4,}")

    print("\nFINAL_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FINAL_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({n_has / len(sub) if len(sub) else 0:.1%})")

    print("\nPERMIT_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["PERMIT_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({n_has / len(sub) if len(sub) else 0:.1%})")

    print("\nFILE_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FILE_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({n_has / len(sub) if len(sub) else 0:.1%})")

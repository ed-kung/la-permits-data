"""Data repair for Jacksonville (FL) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Jacksonville DATA has two sub-schemas from the city's permit portal:

  - full_permit: rich permit detail payload with StatusDescription,
                 DateEntered, DateIssued, DateFinal, IsIssued, etc.
  - mini_record: lightweight associated-permit summary with top-level
                 keys (CanDoOperation, description, key, link,
                 mini_record, obj, title, type). Status and DateIssued
                 live under obj; no application or final dates.

Canonical mappings:
  - StatusDescription / obj.Status  → STATUS_NORMALIZED
  - DateEntered                     → FILE_DATE   (full_permit only)
  - DateIssued / obj.DateIssued     → PERMIT_DATE
  - DateFinal                       → FINAL_DATE  (full_permit only)

Known issues repaired:
  - STATUS_NORMALIZED missing for Finalized / Finalized-NIF and several
    Inactive / In Review statuses (especially Finalized-NIF, which was
    never mapped in the upstream normalizer).
  - FILE_DATE / PERMIT_DATE / FINAL_DATE missing on full_permit rows
    despite DateEntered / DateIssued / DateFinal being present in DATA.
  - Calendar-day mismatches vs DATA dates overwritten as FIXED (none
    observed in the FL sample, but handled defensively).

Not repairable / left as-is:
  - mini_record rows have no DateEntered → FILE_DATE stays missing.
  - mini_record rows have no DateFinal → FINAL_DATE stays missing for
    Finalized / Finalized-NIF summaries.
  - A small set of full_permit rows lack DateIssued / DateFinal in DATA
    (never issued / never finalized) → corresponding dates stay missing.
"""

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
    """Parse a date value, returning pd.NaT on failure."""
    if val is None or (isinstance(val, str) and not str(val).strip()):
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
    if "StatusDescription" in keys or "DateEntered" in keys:
        return "full_permit"
    if "mini_record" in keys or "CanDoOperation" in keys:
        return "mini_record"
    return "unknown"


# ── Status mapping ───────────────────────────────────────────────────────────

# Jacksonville StatusDescription / obj.Status → STATUS_NORMALIZED
_STATUS_MAP = {
    "Finalized": "Final",
    "Finalized-NIF": "Final",  # finalized without inspection final (NIF)
    "Active": "Active",
    "Expired": "Inactive",
    "Void": "Inactive",
    "Cancelled": "Inactive",
    "Denied": "Inactive",
    "Not Submitted": "In Review",
    "Return for Corrections": "In Review",
    "Pending Payment": "In Review",
    "Suspended": "In Review",
}


def _apply_status(repairs: dict, current, raw_status: Optional[str]) -> Optional[str]:
    """Map raw status → STATUS_NORMALIZED; return effective status."""
    if raw_status is None:
        return current if not (isinstance(current, float) and pd.isna(current)) else None

    expected = _STATUS_MAP.get(raw_status)
    if expected is None:
        return current if not (isinstance(current, float) and pd.isna(current)) else None

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


# ── Per-schema repair logic ─────────────────────────────────────────────────

def _repair_full_permit(row, d: dict, repairs: dict):
    """Repair a full_permit detail record."""
    raw_status = d.get("StatusDescription")
    effective_status = _apply_status(repairs, row["STATUS_NORMALIZED"], raw_status)

    # FILE_DATE ← DateEntered (application / entered date)
    _apply_date(repairs, row, "FILE_DATE", d.get("DateEntered"))

    # PERMIT_DATE ← DateIssued
    # Ideal: populate for Active / Final. Also correct mismatches whenever
    # DateIssued is present and the existing value disagrees.
    issued = _safe_to_datetime(d.get("DateIssued"))
    if issued is not pd.NaT:
        if pd.isna(row["PERMIT_DATE"]):
            if effective_status in ("Active", "Final"):
                repairs["PERMIT_DATE"] = issued
                repairs["PERMIT_DATE_FLAG"] = "FILLED"
        elif not _dates_equal(row["PERMIT_DATE"], issued):
            repairs["PERMIT_DATE"] = issued
            repairs["PERMIT_DATE_FLAG"] = "FIXED"

    # FINAL_DATE ← DateFinal for Final records
    final = _safe_to_datetime(d.get("DateFinal"))
    if final is not pd.NaT:
        if effective_status == "Final":
            if pd.isna(row["FINAL_DATE"]):
                repairs["FINAL_DATE"] = final
                repairs["FINAL_DATE_FLAG"] = "FILLED"
            elif not _dates_equal(row["FINAL_DATE"], final):
                repairs["FINAL_DATE"] = final
                repairs["FINAL_DATE_FLAG"] = "FIXED"
        elif not pd.isna(row["FINAL_DATE"]) and not _dates_equal(row["FINAL_DATE"], final):
            # Non-Final row with a FINAL_DATE that disagrees with DateFinal
            repairs["FINAL_DATE"] = final
            repairs["FINAL_DATE_FLAG"] = "FIXED"


def _repair_mini_record(row, d: dict, repairs: dict):
    """Repair a mini_record associated-permit summary."""
    obj = d.get("obj") if isinstance(d.get("obj"), dict) else {}
    raw_status = obj.get("Status")
    effective_status = _apply_status(repairs, row["STATUS_NORMALIZED"], raw_status)

    # No DateEntered / DateFinal in this schema — FILE_DATE and FINAL_DATE
    # cannot be recovered from DATA.

    # PERMIT_DATE ← obj.DateIssued
    issued = _safe_to_datetime(obj.get("DateIssued"))
    if issued is not pd.NaT:
        if pd.isna(row["PERMIT_DATE"]):
            if effective_status in ("Active", "Final"):
                repairs["PERMIT_DATE"] = issued
                repairs["PERMIT_DATE_FLAG"] = "FILLED"
        elif not _dates_equal(row["PERMIT_DATE"], issued):
            repairs["PERMIT_DATE"] = issued
            repairs["PERMIT_DATE_FLAG"] = "FIXED"


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Jacksonville permit records using information from the raw DATA JSON.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Jacksonville".  Must contain
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

        if schema == "full_permit":
            _repair_full_permit(row, d, repairs)
        elif schema == "mini_record":
            _repair_mini_record(row, d, repairs)

        for key, value in repairs.items():
            out.at[idx, key] = value

    return out


# ── CLI: run standalone to preview repair stats ─────────────────────────────

if __name__ == "__main__":
    import os
    from dotenv import load_dotenv, find_dotenv

    load_dotenv(find_dotenv())
    MY_DATA_PATH = os.getenv("MY_DATA_PATH")
    filepath = os.path.join(MY_DATA_PATH, "processed_data", "permits_fl_sample.parquet")
    df = pd.read_parquet(filepath)
    jax = df[df["JURISDICTION"] == "Jacksonville"].copy()

    print(f"Jacksonville records: {len(jax):,}\n")

    repaired = data_repair(jax)

    print("INFERRED_SCHEMA:")
    for s, c in repaired["INFERRED_SCHEMA"].value_counts(dropna=False).items():
        print(f"  {str(s):20s}: {c:>4,}")
    print()

    for field in ["STATUS_NORMALIZED", "FILE_DATE", "PERMIT_DATE", "FINAL_DATE"]:
        flag_col = f"{field}_FLAG"
        n_filled = (repaired[flag_col] == "FILLED").sum()
        n_fixed = (repaired[flag_col] == "FIXED").sum()
        print(f"{field}:")
        print(f"  FILLED: {n_filled:>4,}   FIXED: {n_fixed:>4,}")

        before_missing = jax[field].isna().sum()
        after_missing = repaired[field].isna().sum()
        print(f"  Missing before: {before_missing:>4,}   Missing after: {after_missing:>4,}")
        print()

    print("STATUS_NORMALIZED distribution:")
    print("  Before:")
    for s, c in jax["STATUS_NORMALIZED"].value_counts(dropna=False).items():
        print(f"    {str(s):15s}: {c:>4,}")
    print("  After:")
    for s, c in repaired["STATUS_NORMALIZED"].value_counts(dropna=False).items():
        print(f"    {str(s):15s}: {c:>4,}")

    print("\nFILE_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FILE_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({n_has / max(len(sub), 1):.1%})")

    print("\nPERMIT_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["PERMIT_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({n_has / max(len(sub), 1):.1%})")

    print("\nFINAL_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FINAL_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({n_has / max(len(sub), 1):.1%})")

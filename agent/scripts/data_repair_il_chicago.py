"""Data repair for Chicago (IL) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Chicago DATA is a flat City of Chicago open-data payload. Two sub-schemas
appear in the sample:

  - status_milestone: includes PERMIT_STATUS / PERMIT_MILESTONE keys
    (often empty strings on older extracts)
  - legacy_flat: older rows without those keys (uses 'STREET DIRECTION'
    with a space instead of STREET_DIRECTION)

Canonical mappings:
  - DATA.PERMIT_STATUS              → STATUS_NORMALIZED
  - DATA.APPLICATION_START_DATE     → FILE_DATE
  - DATA.ISSUE_DATE                 → PERMIT_DATE
  - (no completion/final date key)  → FINAL_DATE cannot be recovered

Known issues repaired:
  - STATUS_NORMALIZED is entirely missing upstream; filled from
    PERMIT_STATUS when non-empty (ACTIVE/COMPLETE/EXPIRED/CANCELLED/OPEN).
  - One re-filed / re-issued row keeps stale 2010 FILE_DATE and
    PERMIT_DATE while DATA carries 2024 APPLICATION_START_DATE /
    ISSUE_DATE → FIXED to the DATA dates.
  - Rows with empty PERMIT_STATUS (vast majority) and all FINAL_DATE
    values cannot be recovered from DATA; left as missing.
"""

import json
import math
from typing import Optional

import pandas as pd
import numpy as np


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
    if str(val).strip().upper() == "TBD":
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
    if "PERMIT_STATUS" in keys or "PERMIT_MILESTONE" in keys:
        return "status_milestone"
    return "legacy_flat"


# ── Status mapping ───────────────────────────────────────────────────────────

_STATUS_MAP = {
    "ACTIVE": "Active",
    "COMPLETE": "Final",
    "EXPIRED": "Inactive",
    "CANCELLED": "Inactive",
    "OPEN": "In Review",
}


# ── Per-row repair ───────────────────────────────────────────────────────────

def _repair_row(row, d: dict, repairs: dict):
    """Repair one Chicago record from its flat DATA dict."""

    # -- STATUS_NORMALIZED --
    current_status = row["STATUS_NORMALIZED"]
    raw_status = d.get("PERMIT_STATUS")
    if isinstance(raw_status, str):
        raw_status = raw_status.strip()
    else:
        raw_status = raw_status if raw_status not in (None, "") else None

    expected = _STATUS_MAP.get(raw_status) if raw_status else None
    if expected is not None:
        if pd.isna(current_status):
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"
        elif current_status != expected:
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FIXED"

    effective_status = repairs.get("STATUS_NORMALIZED", current_status)

    app_date = _safe_to_datetime(d.get("APPLICATION_START_DATE"))
    issue_date = _safe_to_datetime(d.get("ISSUE_DATE"))

    # -- FILE_DATE --
    # Prefer APPLICATION_START_DATE. Overwrite when present in DATA and
    # the row value is missing or disagrees (stale re-issue).
    if app_date is not pd.NaT:
        if pd.isna(row["FILE_DATE"]):
            repairs["FILE_DATE"] = app_date
            repairs["FILE_DATE_FLAG"] = "FILLED"
        elif not _dates_equal(row["FILE_DATE"], app_date):
            repairs["FILE_DATE"] = app_date
            repairs["FILE_DATE_FLAG"] = "FIXED"

    # -- PERMIT_DATE --
    # ISSUE_DATE is the issuance date. Overwrite when present in DATA and
    # the row value is missing or disagrees. Ideal: populate for Active/Final;
    # also fill/fix whenever ISSUE_DATE is authoritative in DATA.
    if issue_date is not pd.NaT:
        if pd.isna(row["PERMIT_DATE"]):
            if pd.isna(effective_status) or effective_status in ("Active", "Final", "In Review", "Inactive"):
                repairs["PERMIT_DATE"] = issue_date
                repairs["PERMIT_DATE_FLAG"] = "FILLED"
        elif not _dates_equal(row["PERMIT_DATE"], issue_date):
            repairs["PERMIT_DATE"] = issue_date
            repairs["PERMIT_DATE_FLAG"] = "FIXED"

    # -- FINAL_DATE --
    # Chicago open-data payloads have no completion / finalization /
    # sign-off date field. COMPLETE status confirms finalization for a
    # handful of rows but carries no associated date. Nothing to fill.
    # (Left explicit so callers know this branch was considered.)
    _ = effective_status  # status available if a future schema adds a date


# ── Main entry point ─────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Chicago permit records using information from the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Chicago". Must contain
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
        _repair_row(row, d, repairs)

        for key, value in repairs.items():
            out.at[idx, key] = value

    return out


# ── CLI: run standalone to preview repair stats ──────────────────────────────

if __name__ == "__main__":
    import os
    from dotenv import load_dotenv, find_dotenv

    load_dotenv(find_dotenv())
    MY_DATA_PATH = os.getenv("MY_DATA_PATH")
    filepath = os.path.join(MY_DATA_PATH, "processed_data", "permits_top50_sample.parquet")
    df = pd.read_parquet(filepath)
    chi = df[df["JURISDICTION"] == "Chicago"].copy()

    print(f"Chicago records: {len(chi):,}\n")

    repaired = data_repair(chi)

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

        before_missing = chi[field].isna().sum()
        after_missing = repaired[field].isna().sum()
        print(f"  Missing before: {before_missing:>4,}   Missing after: {after_missing:>4,}")
        print()

    print("STATUS_NORMALIZED distribution:")
    print("  Before:")
    for s, c in chi["STATUS_NORMALIZED"].value_counts(dropna=False).items():
        print(f"    {str(s):15s}: {c:>4,}")
    print("  After:")
    for s, c in repaired["STATUS_NORMALIZED"].value_counts(dropna=False).items():
        print(f"    {str(s):15s}: {c:>4,}")

    print("\nFINAL_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive", None]:
        if status is None:
            sub = repaired[repaired["STATUS_NORMALIZED"].isna()]
            label = "nan"
        else:
            sub = repaired[repaired["STATUS_NORMALIZED"] == status]
            label = status
        n_has = sub["FINAL_DATE"].notna().sum()
        if len(sub) == 0:
            continue
        print(f"  {label:15s}: {n_has:>4,} / {len(sub):>4,} ({n_has/len(sub):.1%})")

    print("\nPERMIT_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive", None]:
        if status is None:
            sub = repaired[repaired["STATUS_NORMALIZED"].isna()]
            label = "nan"
        else:
            sub = repaired[repaired["STATUS_NORMALIZED"] == status]
            label = status
        n_has = sub["PERMIT_DATE"].notna().sum()
        if len(sub) == 0:
            continue
        print(f"  {label:15s}: {n_has:>4,} / {len(sub):>4,} ({n_has/len(sub):.1%})")

    print("\nFILE_DATE coverage:")
    n_has = repaired["FILE_DATE"].notna().sum()
    print(f"  {n_has:>4,} / {len(repaired):>4,} ({n_has/len(repaired):.1%})")

"""Data repair for Houston (TX) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Houston DATA is a City of Houston permit-search scrape with two
top-level key-set variants:

  - details_search:      top-level keys 'details' + 'search'
  - date_details_search: top-level keys 'date' + 'details' + 'search'

Within either variant, ``details`` may be an empty dict (search stub).

Canonical mappings:
  - STATUS_ORIGINAL / implicit 'issued'  → STATUS_NORMALIZED
      (DATA has no status field; all sample rows are STATUS_ORIGINAL
      == 'issued' → Active)
  - (no application / filed date key)    → FILE_DATE cannot be recovered
  - details.Date                         → PERMIT_DATE (canonical)
  - top-level date                       → PERMIT_DATE fill-only fallback
      when details are empty
  - (no completion / final date key)     → FINAL_DATE cannot be recovered

Known issues repaired:
  - Active rows with empty ``details`` and missing PERMIT_DATE →
    FILLED from top-level ``date``.
  - Rows (mostly Sign / Elevator renewals) where PERMIT_DATE
    disagrees with ``details.Date`` → FIXED to ``details.Date``.

Not repairable / left as-is:
  - FILE_DATE is missing for all rows; ``details.Date`` and top-level
    ``date`` are issuance-like, not filing dates.
  - FINAL_DATE is missing for all rows; DATA has no completion field
    and STATUS never leaves Active / 'issued'.
  - STATUS_NORMALIZED is already Active for every sample row; no
    contrary signal exists in DATA.
  - Existing PERMIT_DATE on empty-details stubs is left unchanged
    when it disagrees with top-level ``date`` (top date is too weak
    a signal to overwrite).
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
    if keys >= {"date", "details", "search"}:
        return "date_details_search"
    if keys >= {"details", "search"}:
        return "details_search"
    return "unknown"


# ── Status mapping ───────────────────────────────────────────────────────────

# Houston DATA has no status field. Upstream STATUS_ORIGINAL is uniformly
# "issued" in the sample; map that (and common synonyms) if STATUS_NORMALIZED
# is ever missing.
_STATUS_ORIGINAL_MAP = {
    "issued": "Active",
    "active": "Active",
    "approved": "Active",
}


def _expected_status(row) -> Optional[str]:
    raw = row.get("STATUS_ORIGINAL")
    if raw is None or (isinstance(raw, float) and math.isnan(raw)):
        return None
    key = str(raw).strip().lower()
    return _STATUS_ORIGINAL_MAP.get(key)


def _details_date(d: dict):
    """Issuance date from the agency details payload, if present."""
    details = d.get("details")
    if isinstance(details, dict):
        return _safe_to_datetime(details.get("Date"))
    return pd.NaT


def _top_date(d: dict):
    """Top-level ``date`` (present on a minority of rows; weaker signal)."""
    return _safe_to_datetime(d.get("date"))


# ── Per-row repair ───────────────────────────────────────────────────────────

def _repair_row(row, d: dict, repairs: dict):
    """Repair one Houston record from its DATA dict."""

    # -- STATUS_NORMALIZED --
    current_status = row["STATUS_NORMALIZED"]
    expected = _expected_status(row)
    if expected is not None:
        if pd.isna(current_status):
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"
        elif current_status != expected:
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FIXED"

    effective_status = repairs.get("STATUS_NORMALIZED", current_status)

    # -- FILE_DATE --
    # No application / filed / submitted date exists in Houston DATA.
    # details.Date and top-level date are issuance-like (match PERMIT_DATE).

    # -- PERMIT_DATE --
    # details.Date is the canonical issuance date (matches existing PERMIT_DATE
    # on ~99% of rows that have both). Top-level date is only used to FILL
    # missing values when details are empty — it is not trusted to overwrite
    # an existing PERMIT_DATE.
    det_date = _details_date(d)
    top_date = _top_date(d)
    if det_date is not pd.NaT:
        if pd.isna(row["PERMIT_DATE"]):
            if effective_status in ("Active", "Final") or pd.isna(effective_status):
                repairs["PERMIT_DATE"] = det_date
                repairs["PERMIT_DATE_FLAG"] = "FILLED"
        elif not _dates_equal(row["PERMIT_DATE"], det_date):
            repairs["PERMIT_DATE"] = det_date
            repairs["PERMIT_DATE_FLAG"] = "FIXED"
    elif pd.isna(row["PERMIT_DATE"]) and top_date is not pd.NaT:
        if effective_status in ("Active", "Final") or pd.isna(effective_status):
            repairs["PERMIT_DATE"] = top_date
            repairs["PERMIT_DATE_FLAG"] = "FILLED"

    # -- FINAL_DATE --
    # No completion / final / sign-off date exists in Houston DATA, and no
    # sample row has STATUS_NORMALIZED == Final.


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Houston permit records using information from the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Houston".  Must contain
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
    filepath = os.path.join(MY_DATA_PATH, "processed_data", "permits_top50_sample.parquet")
    df = pd.read_parquet(filepath)
    hou = df[(df["JURISDICTION"] == "Houston") & (df["STATE"] == "TX")].copy()

    print(f"Houston records: {len(hou):,}\n")

    repaired = data_repair(hou)

    print("INFERRED_SCHEMA distribution:")
    for s, c in repaired["INFERRED_SCHEMA"].value_counts(dropna=False).items():
        print(f"  {str(s):25s}: {c:>4,}")
    print()

    for field in ["STATUS_NORMALIZED", "FILE_DATE", "PERMIT_DATE", "FINAL_DATE"]:
        flag_col = f"{field}_FLAG"
        n_filled = (repaired[flag_col] == "FILLED").sum()
        n_fixed = (repaired[flag_col] == "FIXED").sum()
        print(f"{field}:")
        print(f"  FILLED: {n_filled:>4,}   FIXED: {n_fixed:>4,}")

        before_missing = hou[field].isna().sum()
        after_missing = repaired[field].isna().sum()
        print(f"  Missing before: {before_missing:>4,}   Missing after: {after_missing:>4,}")
        print()

    print("STATUS_NORMALIZED distribution:")
    print("  Before:")
    for s, c in hou["STATUS_NORMALIZED"].value_counts(dropna=False).items():
        print(f"    {str(s):15s}: {c:>4,}")
    print("  After:")
    for s, c in repaired["STATUS_NORMALIZED"].value_counts(dropna=False).items():
        print(f"    {str(s):15s}: {c:>4,}")

    print("\nPERMIT_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        if len(sub) == 0:
            continue
        n_has = sub["PERMIT_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({n_has/len(sub):.1%})")

    print("\nFINAL_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        if len(sub) == 0:
            continue
        n_has = sub["FINAL_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({n_has/len(sub):.1%})")

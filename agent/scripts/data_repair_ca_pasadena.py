"""Data repair for Pasadena (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Pasadena DATA is a Tyler EnerGov-style payload with top-level keys
``entity``, ``details``, ``contacts``, ``processing_status``, and
``fees``, plus optional ``reviews`` / ``holds`` / ``attachments`` /
``more_info``. Three key-set variants appear in the sample:

  - entity_fees:          entity + details + fees (+ contacts,
                          processing_status)
  - entity_fees_reviews:  entity_fees plus reviews/holds/attachments/
                          more_info
  - entity_basic:         entity + details (+ contacts,
                          processing_status); no fees block

Canonical fields live under ``entity``:
  - CaseStatus / details.PermitStatus  → STATUS_NORMALIZED
  - ApplyDate                          → FILE_DATE
  - IssueDate                          → PERMIT_DATE
  - FinalDate (fallback: details.FinalizeDate) → FINAL_DATE

Known issues repaired:
  - STATUS_NORMALIZED was derived from STATUS_ORIGINAL, which disagrees
    with entity.CaseStatus on ~7 sample rows (stale portal status vs
    current case status). Remap from CaseStatus: e.g. Finaled wrongly
    labeled Active; Expired→Active; Issued→In Review; In Review→Inactive.
  - FINAL_DATE was populated from entity.FinalDate for ~401 non-Final
    CaseStatus rows (Approved, Issued, Expired, etc.). On many of those,
    FinalDate equals IssueDate or ExpireDate and is not a finaling /
    sign-off date — clear those.
  - After status remaps, fill FINAL_DATE from FinalDate for Finaled rows
    previously labeled Active, and fill PERMIT_DATE from IssueDate for
    Issued rows previously labeled In Review.

Not repairable from DATA:
  - ~60 Active/Final rows (mostly Closed / Complete / Approved / Finaled
    legacy) have null IssueDate and Issued=False, so PERMIT_DATE cannot
    be filled. FILE_DATE is not used as a proxy.
  - ~31 Final rows (Closed / Complete / Finaled) have null FinalDate and
    FinalizeDate, so FINAL_DATE cannot be filled.
  - FILE_DATE already matches the UTC calendar date of entity.ApplyDate
    for all sample records.
"""

import json
import math
from typing import Optional

import pandas as pd
import numpy as np


# Plausible calendar-year range for permit dates in this jurisdiction.
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
        return json.loads(data)
    return data


def _safe_to_datetime(val):
    """Parse a date value as UTC, returning pd.NaT on failure or implausible year."""
    if val is None or (isinstance(val, str) and not str(val).strip()):
        return pd.NaT
    try:
        dt = pd.to_datetime(val, utc=True)
    except (ValueError, TypeError):
        return pd.NaT
    if dt is pd.NaT or pd.isna(dt):
        return pd.NaT
    year = int(dt.year)
    if year < _MIN_YEAR or year > _MAX_YEAR:
        return pd.NaT
    return dt


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())
    if not {"entity", "details"}.issubset(keys):
        return "unknown"
    has_fees = "fees" in keys
    has_reviews = bool(keys & {"reviews", "holds", "attachments", "more_info"})
    if has_fees and has_reviews:
        return "entity_fees_reviews"
    if has_fees:
        return "entity_fees"
    return "entity_basic"


# ── Status mapping ──────────────────────────────────────────────────────────

# entity.CaseStatus (Title Case / portal labels, as in DATA) → STATUS_NORMALIZED
_STATUS_MAP = {
    # Final
    "Finaled": "Final",
    "Complete": "Final",
    "Closed": "Final",
    # Active (issued / approved / still valid)
    "Approved": "Active",
    "Issued": "Active",
    "Issued - Online": "Active",
    # Inactive
    "Expired": "Inactive",
    "Canceled": "Inactive",
    "Voided": "Inactive",
    # In Review (pre-issuance / hold)
    "Received": "In Review",
    "Received - Online": "In Review",
    "In Review": "In Review",
    "Incomplete": "In Review",
    "Pending": "In Review",
    "Open": "In Review",
    "Hold": "In Review",
}


def _case_status(d: dict) -> Optional[str]:
    """Return CaseStatus from entity, falling back to details.PermitStatus."""
    entity = d.get("entity") if isinstance(d.get("entity"), dict) else {}
    details = d.get("details") if isinstance(d.get("details"), dict) else {}
    status = entity.get("CaseStatus") or details.get("PermitStatus")
    if status is None:
        return None
    status = str(status).strip()
    return status or None


def _entity_date(d: dict, entity_key: str, *detail_keys: str):
    """UTC datetime from entity.<key>, else first non-null details key."""
    entity = d.get("entity") if isinstance(d.get("entity"), dict) else {}
    dt = _safe_to_datetime(entity.get(entity_key))
    if dt is not pd.NaT:
        return dt
    details = d.get("details") if isinstance(d.get("details"), dict) else {}
    for key in detail_keys:
        dt = _safe_to_datetime(details.get(key))
        if dt is not pd.NaT:
            return dt
    return pd.NaT


def _dates_equal(a, b) -> bool:
    """Compare two datelike values at calendar-day resolution (UTC)."""
    da = _safe_to_datetime(a)
    db = _safe_to_datetime(b)
    if da is pd.NaT or db is pd.NaT:
        return False
    return da.date() == db.date()


# ── Per-record repair logic ─────────────────────────────────────────────────

def _repair_record(row, d: dict, repairs: dict):
    """Populate *repairs* with corrected values for a single Pasadena record."""
    current_status = row["STATUS_NORMALIZED"]
    raw_status = _case_status(d)
    expected = _STATUS_MAP.get(raw_status) if raw_status else None

    # -- STATUS_NORMALIZED --
    if expected is not None:
        if pd.isna(current_status):
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"
        elif current_status != expected:
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FIXED"

    effective_status = repairs.get("STATUS_NORMALIZED", current_status)

    # -- FILE_DATE (application / ApplyDate) --
    apply = _entity_date(d, "ApplyDate", "ApplyDate")
    if apply is not pd.NaT:
        if pd.isna(row["FILE_DATE"]):
            repairs["FILE_DATE"] = apply
            repairs["FILE_DATE_FLAG"] = "FILLED"
        elif not _dates_equal(row["FILE_DATE"], apply):
            repairs["FILE_DATE"] = apply
            repairs["FILE_DATE_FLAG"] = "FIXED"

    # -- PERMIT_DATE (issuance / IssueDate) --
    issue = _entity_date(d, "IssueDate", "IssueDate")
    if not pd.isna(row["PERMIT_DATE"]):
        if issue is not pd.NaT and not _dates_equal(row["PERMIT_DATE"], issue):
            repairs["PERMIT_DATE"] = issue
            repairs["PERMIT_DATE_FLAG"] = "FIXED"
    elif effective_status in ("Active", "Final") and issue is not pd.NaT:
        repairs["PERMIT_DATE"] = issue
        repairs["PERMIT_DATE_FLAG"] = "FILLED"

    # -- FINAL_DATE (finaled / FinalDate; not ExpireDate / short-term end) --
    final = _entity_date(d, "FinalDate", "FinalizeDate")
    current_final = row["FINAL_DATE"]

    if effective_status == "Final":
        if final is not pd.NaT:
            if pd.isna(current_final):
                repairs["FINAL_DATE"] = final
                repairs["FINAL_DATE_FLAG"] = "FILLED"
            elif not _dates_equal(current_final, final):
                repairs["FINAL_DATE"] = final
                repairs["FINAL_DATE_FLAG"] = "FIXED"
    elif not pd.isna(current_final):
        # Spurious FINAL_DATE on non-Final rows. Common for Approved /
        # Issued / Expired permits where entity.FinalDate mirrors
        # IssueDate or ExpireDate rather than a sign-off.
        repairs["FINAL_DATE"] = pd.NaT
        repairs["FINAL_DATE_FLAG"] = "FIXED"


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Pasadena permit records using information from the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Pasadena".  Must contain
        columns STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, FINAL_DATE,
        and DATA.

    Returns
    -------
    pd.DataFrame
        Copy of *df* with corrected field values, an INFERRED_SCHEMA column
        naming the DATA JSON schema identified for each record, and new
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


# ── CLI: run standalone to preview repair stats ─────────────────────────────

if __name__ == "__main__":
    import os
    from dotenv import load_dotenv

    load_dotenv("/Users/ekung/projects/la-permits-data/.env")
    MY_DATA_PATH = os.getenv("MY_DATA_PATH")
    filepath = os.path.join(MY_DATA_PATH, "processed_data", "permits_la_sample.parquet")
    df = pd.read_parquet(filepath)
    pasadena = df[(df["JURISDICTION"] == "Pasadena") & (df["STATE"] == "CA")].copy()

    print(f"Pasadena records: {len(pasadena):,}\n")

    repaired = data_repair(pasadena)

    print("INFERRED_SCHEMA:")
    print(repaired["INFERRED_SCHEMA"].value_counts(dropna=False).to_string())
    print()

    for field in ["STATUS_NORMALIZED", "FILE_DATE", "PERMIT_DATE", "FINAL_DATE"]:
        flag_col = f"{field}_FLAG"
        n_filled = (repaired[flag_col] == "FILLED").sum()
        n_fixed = (repaired[flag_col] == "FIXED").sum()
        print(f"{field}:")
        print(f"  FILLED: {n_filled:>4,}   FIXED: {n_fixed:>4,}")

        before_missing = pasadena[field].isna().sum()
        after_missing = repaired[field].isna().sum()
        print(f"  Missing before: {before_missing:>4,}   Missing after: {after_missing:>4,}")
        print()

    print("STATUS_NORMALIZED distribution:")
    print("  Before:")
    for s, c in pasadena["STATUS_NORMALIZED"].value_counts(dropna=False).items():
        print(f"    {str(s):15s}: {c:>4,}")
    print("  After:")
    for s, c in repaired["STATUS_NORMALIZED"].value_counts(dropna=False).items():
        print(f"    {str(s):15s}: {c:>4,}")

    print("\nPERMIT_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["PERMIT_DATE"].notna().sum()
        n = len(sub)
        pct = n_has / n if n else 0.0
        print(f"  {status:15s}: {n_has:>4,} / {n:>4,} ({pct:.1%})")

    print("\nFINAL_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FINAL_DATE"].notna().sum()
        n = len(sub)
        pct = n_has / n if n else 0.0
        print(f"  {status:15s}: {n_has:>4,} / {n:>4,} ({pct:.1%})")

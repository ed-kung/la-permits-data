"""Data repair for Los Angeles County (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Los Angeles County DATA is a Tyler EnerGov-style payload with top-level
keys ``entity``, ``details``, ``contacts``, ``fees``, and
``processing_status``, plus an optional reviews bundle
(``reviews`` / ``holds`` / ``attachments`` / ``more_info``). Three
key-set variants appear in the sample:

  - entity_fees:          entity + details + fees (+ contacts,
                          processing_status)
  - entity_fees_reviews:  entity_fees plus reviews/holds/attachments/
                          more_info
  - entity_basic:         entity + details (+ contacts, processing_status)
                          without fees (1 row)

Canonical fields live under ``entity`` (``details`` as fallback;
``CaseStatus`` and ``PermitStatus`` always agree in the sample):
  - CaseStatus / details.PermitStatus  → STATUS_NORMALIZED
  - ApplyDate                          → FILE_DATE
  - IssueDate                          → PERMIT_DATE
  - FinalDate (fallback: details.FinalizeDate) → FINAL_DATE

Known issues repaired:
  - 33 rows where STATUS_ORIGINAL is stale relative to entity.CaseStatus
    (issued→Finaled ×23, issued→Expired ×8, new-online→Issued ×1,
    approved-ready→Issued ×1) → STATUS_NORMALIZED FIXED to CaseStatus map.
  - 2 Issued rows remapped from In Review → Active get PERMIT_DATE
    FILLED from IssueDate.
  - 23 Finaled rows remapped from Active → Final get FINAL_DATE FILLED
    from FinalDate.
  - 28 non-Final rows carry FINAL_DATE copied from entity.FinalDate
    (Issued ×20, Exempt ×3, Expired ×2, Canceled/Denied/In Review ×1
    each) → cleared.

Not repairable / left as-is:
  - FILE_DATE already matches entity.ApplyDate (UTC day) for all
    sample rows; none missing.
  - Where PERMIT_DATE and IssueDate both exist they always match;
    22 CaseStatus=Finaled rows have no IssueDate (details.Issued=False)
    and no other issuance field → PERMIT_DATE left missing.
  - All CaseStatus=Finaled rows already have FinalDate (= FinalizeDate);
    after remaps, Final coverage is complete.
  - ExpireDate is a validity window, not a completion date.
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
    """Parse a date value as UTC, returning pd.NaT on failure."""
    if val is None or (isinstance(val, str) and not val.strip()):
        return pd.NaT
    try:
        return pd.to_datetime(val, utc=True)
    except (ValueError, TypeError):
        return pd.NaT


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

# entity.CaseStatus (Title Case, as in DATA) → STATUS_NORMALIZED
_STATUS_MAP = {
    # Final
    "Finaled": "Final",
    # Active
    "Issued": "Active",
    # Inactive
    "Expired": "Inactive",
    "Void": "Inactive",
    "Canceled": "Inactive",
    "Denied": "Inactive",
    # In Review (pre-issuance / hold / exempt)
    "In Review": "In Review",
    "Waiting for Applicant": "In Review",
    "New - Online": "In Review",
    "On Hold": "In Review",
    "Approved Ready for Permit": "In Review",
    "Approved Pending Clearances": "In Review",
    "New": "In Review",
    "Exempt": "In Review",
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
    """Populate *repairs* with corrected values for a single LA County record."""
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

    # -- FINAL_DATE (finaled / FinalDate; not ExpireDate) --
    # Prefer entity.FinalDate. On non-Final CaseStatus rows, FinalDate /
    # FinalizeDate is not a permit sign-off and must not populate FINAL_DATE.
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
        # Spurious FINAL_DATE on non-Final rows (copied from entity.FinalDate
        # while CaseStatus is Issued / Exempt / Expired / etc.).
        repairs["FINAL_DATE"] = pd.NaT
        repairs["FINAL_DATE_FLAG"] = "FIXED"


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Los Angeles County permit records using information from the raw DATA
    JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Los Angeles County".  Must
        contain columns STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE,
        FINAL_DATE, and DATA.

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
    city = df[
        (df["JURISDICTION"] == "Los Angeles County") & (df["STATE"] == "CA")
    ].copy()

    print(f"Los Angeles County records: {len(city):,}\n")

    repaired = data_repair(city)

    print("INFERRED_SCHEMA:")
    print(repaired["INFERRED_SCHEMA"].value_counts(dropna=False).to_string())
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

    print("\nFILE_DATE coverage (after repair):")
    n_has = repaired["FILE_DATE"].notna().sum()
    print(f"  {n_has:>4,} / {len(repaired):>4,} ({n_has/len(repaired):.1%})")

"""Data repair for Costa Mesa (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Costa Mesa DATA has two families of payloads:

  Tyler EnerGov / CityView detail scrape
    - entity_fees:          entity + details + fees (+ contacts,
                            processing_status)
    - entity_fees_reviews:  entity_fees plus reviews/holds/attachments/
                            more_info

  Flat issued list scrape (no CaseStatus / ApplyDate / FinalDate)
    - flat_issued:            APN, Address, Date Issued, Description,
                              contacts
    - flat_issued_valuation:  flat_issued plus Valuation

Canonical fields (entity schema):
  - CaseStatus / details.PermitStatus  → STATUS_NORMALIZED
  - ApplyDate                          → FILE_DATE
  - IssueDate                          → PERMIT_DATE
  - FinalDate (fallback: details.FinalizeDate) → FINAL_DATE

Canonical fields (flat schema):
  - Date Issued present                → STATUS_NORMALIZED = Active
  - Date Issued                        → PERMIT_DATE; also FILE_DATE
                                         proxy when no ApplyDate exists

Known issues repaired:
  - 32 entity rows with null STATUS_NORMALIZED for CaseStatus values the
    upstream mapper missed (Additional Information Required, Invoice
    Pending, Verifying Submittal, Issued - Revision Added, Issued
    -Revision - Additional Information Required, Application Returned,
    Revision Submittal).
  - 7 Plan Check Complete rows labeled Final despite null IssueDate /
    FinalDate → In Review (plan check finished, not issued/finaled).
  - 265 flat-list rows with null STATUS_NORMALIZED / FILE_DATE; Date
    Issued is present → Active + FILE_DATE/PERMIT_DATE from Date Issued.
  - Spurious FINAL_DATE on non-Final rows (Issued / Expired / Void)
    copied from entity.FinalDate → cleared.

Not repairable / left as-is:
  - Entity FILE_DATE already matches entity.ApplyDate for all sample
    entity rows.
  - Entity PERMIT_DATE / FINAL_DATE already match IssueDate / FinalDate
    when those source dates exist.
  - Approved / Complete / Final rows with Issued=False and null
    IssueDate keep PERMIT_DATE missing (no issuance stamp; FILE_DATE
    is not used as a proxy).
  - Flat rows have no final/completion stamp → FINAL_DATE stays null
    (status inferred Active, so final not required).
"""

from __future__ import annotations

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
    """Parse a date value as UTC, returning pd.NaT on failure."""
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
    return dt


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())
    if {"entity", "details"}.issubset(keys):
        has_fees = "fees" in keys
        has_reviews = bool(keys & {"reviews", "holds", "attachments", "more_info"})
        if has_fees and has_reviews:
            return "entity_fees_reviews"
        if has_fees:
            return "entity_fees"
        return "entity_basic"
    if "Date Issued" in keys:
        if "Valuation" in keys:
            return "flat_issued_valuation"
        return "flat_issued"
    return "unknown"


# ── Status mapping ──────────────────────────────────────────────────────────

# entity.CaseStatus (Title Case, as in DATA; lookup uses strip()) → STATUS
_STATUS_MAP = {
    # Final
    "Final": "Final",
    "Complete": "Final",
    "Legacy": "Final",
    # Active (issued / approved / issued-with-revision)
    "Issued": "Active",
    "Approved": "Active",
    "Issued - Revision Added": "Active",
    "Issued -Revision - Additional Information Required": "Active",
    # Inactive
    "Expired": "Inactive",
    "Void": "Inactive",
    "Withdrawn": "Inactive",
    "Denied": "Inactive",
    "Plan Approval Expired": "Inactive",
    "Plan Check Expired": "Inactive",
    # In Review (pre-issuance / holds / plan check done but not issued)
    "In Review": "In Review",
    "Submitted": "In Review",
    "Submitted - Online": "In Review",
    "On Hold": "In Review",
    "Application Accepted": "In Review",
    "Additional Information Required": "In Review",
    "Invoice Pending": "In Review",
    "Verifying Submittal": "In Review",
    "Application Returned": "In Review",
    "Revision Submittal": "In Review",
    "Plan Check Complete": "In Review",
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


def _set_status(repairs: dict, current_status, expected: str) -> None:
    if expected is None:
        return
    if pd.isna(current_status):
        repairs["STATUS_NORMALIZED"] = expected
        repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"
    elif current_status != expected:
        repairs["STATUS_NORMALIZED"] = expected
        repairs["STATUS_NORMALIZED_FLAG"] = "FIXED"


def _set_date(repairs: dict, field: str, current, expected) -> None:
    if expected is pd.NaT or expected is None or pd.isna(expected):
        return
    if pd.isna(current):
        repairs[field] = expected
        repairs[f"{field}_FLAG"] = "FILLED"
    elif not _dates_equal(current, expected):
        repairs[field] = expected
        repairs[f"{field}_FLAG"] = "FIXED"


# ── Per-schema repair logic ─────────────────────────────────────────────────

def _repair_entity(row, d: dict, repairs: dict) -> None:
    """Repair a Tyler EnerGov / CityView entity record."""
    current_status = row["STATUS_NORMALIZED"]
    raw_status = _case_status(d)
    expected = _STATUS_MAP.get(raw_status) if raw_status else None
    _set_status(repairs, current_status, expected)
    effective_status = repairs.get("STATUS_NORMALIZED", current_status)

    apply = _entity_date(d, "ApplyDate", "ApplyDate")
    _set_date(repairs, "FILE_DATE", row["FILE_DATE"], apply)

    issue = _entity_date(d, "IssueDate", "IssueDate")
    if not pd.isna(row["PERMIT_DATE"]):
        if issue is not pd.NaT and not _dates_equal(row["PERMIT_DATE"], issue):
            repairs["PERMIT_DATE"] = issue
            repairs["PERMIT_DATE_FLAG"] = "FIXED"
    elif effective_status in ("Active", "Final") and issue is not pd.NaT:
        repairs["PERMIT_DATE"] = issue
        repairs["PERMIT_DATE_FLAG"] = "FILLED"

    final = _entity_date(d, "FinalDate", "FinalizeDate")
    current_final = row["FINAL_DATE"]
    if effective_status == "Final":
        _set_date(repairs, "FINAL_DATE", current_final, final)
    elif not pd.isna(current_final):
        # Spurious FINAL_DATE on non-Final (Issued / Expired / Void, etc.).
        repairs["FINAL_DATE"] = pd.NaT
        repairs["FINAL_DATE_FLAG"] = "FIXED"


def _repair_flat(row, d: dict, repairs: dict) -> None:
    """Repair a flat issued-list record (Date Issued only)."""
    issued = _safe_to_datetime(d.get("Date Issued"))
    current_status = row["STATUS_NORMALIZED"]

    # Flat list rows are issued permits with no CaseStatus → Active.
    if issued is not pd.NaT:
        _set_status(repairs, current_status, "Active")
        # No ApplyDate in this schema; Date Issued is the only usable
        # calendar stamp for FILE_DATE and PERMIT_DATE.
        _set_date(repairs, "FILE_DATE", row["FILE_DATE"], issued)
        _set_date(repairs, "PERMIT_DATE", row["PERMIT_DATE"], issued)

    effective_status = repairs.get("STATUS_NORMALIZED", current_status)
    if effective_status != "Final" and not pd.isna(row["FINAL_DATE"]):
        repairs["FINAL_DATE"] = pd.NaT
        repairs["FINAL_DATE_FLAG"] = "FIXED"


def _repair_record(row, d: dict, schema: str, repairs: dict) -> None:
    if schema.startswith("entity"):
        _repair_entity(row, d, repairs)
    elif schema.startswith("flat_issued"):
        _repair_flat(row, d, repairs)


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Costa Mesa permit records using information from the raw DATA JSON.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Costa Mesa".  Must contain
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
        _repair_record(row, d, schema, repairs)

        for key, value in repairs.items():
            out.at[idx, key] = value

    return out


# ── CLI: run standalone to preview repair stats ─────────────────────────────

if __name__ == "__main__":
    import os
    from dotenv import load_dotenv

    load_dotenv("/Users/ekung/projects/la-permits-data/.env")
    MY_DATA_PATH = os.getenv("MY_DATA_PATH")
    filepath = os.path.join(MY_DATA_PATH, "processed_data", "permits_ca_sample.parquet")
    df = pd.read_parquet(filepath)
    city = df[(df["JURISDICTION"] == "Costa Mesa") & (df["STATE"] == "CA")].copy()

    print(f"Costa Mesa records: {len(city):,}\n")

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

    print("\nSTATUS_NORMALIZED_FLAG breakdown (CaseStatus / schema → new status):")
    for flag in ["FILLED", "FIXED"]:
        sub = repaired[repaired["STATUS_NORMALIZED_FLAG"] == flag]
        print(f"  {flag} ({len(sub)}):")
        for idx in sub.index:
            d = _safe_parse(city.loc[idx, "DATA"])
            schema = repaired.loc[idx, "INFERRED_SCHEMA"]
            cs = _case_status(d) if d and schema.startswith("entity") else None
            before = city.loc[idx, "STATUS_NORMALIZED"]
            after = repaired.loc[idx, "STATUS_NORMALIZED"]
            label = cs if cs is not None else schema
            print(f"    {label!r}: {before!r} → {after!r}")

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

    print("\nFILE_DATE missing by schema (after):")
    print(
        repaired.groupby("INFERRED_SCHEMA")["FILE_DATE"]
        .apply(lambda s: s.isna().sum())
        .to_string()
    )

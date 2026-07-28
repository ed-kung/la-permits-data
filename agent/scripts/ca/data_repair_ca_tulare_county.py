"""Data repair for Tulare County (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Tulare County DATA is Tyler EnerGov with two key-set variants:

  - entity_fees: top-level ``entity``, ``details``, ``fees``, ``contacts``,
    ``processing_status``
  - entity_fees_reviews: same plus ``reviews``, ``holds``, ``attachments``,
    ``more_info``

Canonical mappings:
  - entity.CaseStatus (else details.PermitStatus) → STATUS_NORMALIZED;
    Active/Issued/Approved rows with FinalDate → Final
  - entity.ApplyDate (else details.ApplyDate) → FILE_DATE
  - entity.IssueDate (else details.IssueDate) → PERMIT_DATE
  - entity.FinalDate (else details.FinalizeDate) → FINAL_DATE

Known issues repaired:
  - Incomplete/Resubmit left as null STATUS_NORMALIZED → FILLED In Review
    (~17); clear spurious FINAL_DATE on those rows.
  - Active/Issued/Approved rows that already have FinalDate (or CaseStatus
    Finaled/Complete) → FIXED to Final (~52); fill FINAL_DATE when missing.
  - Ready To Issue / Issued mismatches vs STATUS_ORIGINAL → FIXED.
  - Spurious FINAL_DATE on In Review / Inactive → cleared (FIXED).
  - Missing PERMIT_DATE on Active/Final when IssueDate exists → FILLED.

Not repairable from DATA:
  - FILE_DATE already matches ApplyDate for all sample rows.
  - Many Complete/Finaled rows have null IssueDate → PERMIT_DATE stays
    missing (~159 Final after repair).
  - One Finaled row (I1500027) has no FinalDate/FinalizeDate → FINAL_DATE
    stays missing.
"""

from __future__ import annotations

import json
import math
from typing import Optional

import numpy as np
import pandas as pd


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
    year = int(dt.year)
    if year < _MIN_YEAR or year > _MAX_YEAR:
        return pd.NaT
    return dt


def _dates_equal(a, b) -> bool:
    """Compare two datelike values at calendar-day resolution (UTC)."""
    da = _safe_to_datetime(a)
    db = _safe_to_datetime(b)
    if da is pd.NaT or db is pd.NaT:
        return False
    return da.date() == db.date()


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())
    if {"entity", "details"}.issubset(keys):
        has_reviews = bool(keys & {"reviews", "holds", "attachments", "more_info"})
        if has_reviews:
            return "entity_fees_reviews"
        return "entity_fees"
    return "unknown"


# ── Status mapping ──────────────────────────────────────────────────────────

# EnerGov CaseStatus / PermitStatus (Title Case) → STATUS_NORMALIZED
_ENERGOV_STATUS_MAP = {
    "Finaled": "Final",
    "Complete": "Final",
    "Closed": "Final",
    "Issued": "Active",
    "Active": "Active",
    "Approved": "Active",
    "Applied": "In Review",
    "Accepted": "In Review",
    "Pending": "In Review",
    "Under Review": "In Review",
    "On Hold": "In Review",
    "Ready To Issue": "In Review",
    "Waiting on Customer": "In Review",
    "Incomplete/Resubmit": "In Review",
    "Exempt": "In Review",
    "Non – OP year 1": "In Review",  # en-dash
    "Denied": "Inactive",
    "Expired": "Inactive",
    "Inactive": "Inactive",
    "Abandoned": "Inactive",
    "Revoked": "Inactive",
    "Void/Withdrawn": "Inactive",
    "Withdrawn": "Inactive",
}


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


def _expected_status_energov(d: dict) -> Optional[str]:
    entity = d.get("entity") if isinstance(d.get("entity"), dict) else {}
    details = d.get("details") if isinstance(d.get("details"), dict) else {}
    raw = entity.get("CaseStatus") or details.get("PermitStatus")
    if raw is None or not str(raw).strip():
        return None
    raw = str(raw).strip()
    expected = _ENERGOV_STATUS_MAP.get(raw)

    permit_status = details.get("PermitStatus")
    if isinstance(permit_status, str) and permit_status.strip() in ("Finaled", "Complete", "Closed"):
        expected = "Final"

    # EnerGov sometimes leaves CaseStatus as Issued/Active/Approved after
    # a FinalDate has been recorded; treat those as Final.
    final = _entity_date(d, "FinalDate", "FinalizeDate")
    if expected == "Active" and final is not pd.NaT:
        expected = "Final"

    return expected


# ── Per-schema repair logic ─────────────────────────────────────────────────

def _set_status(row, expected: Optional[str], repairs: dict) -> object:
    current = row["STATUS_NORMALIZED"]
    if expected is None:
        return current
    if pd.isna(current):
        repairs["STATUS_NORMALIZED"] = expected
        repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"
        return expected
    if current != expected:
        repairs["STATUS_NORMALIZED"] = expected
        repairs["STATUS_NORMALIZED_FLAG"] = "FIXED"
        return expected
    return current


def _repair_energov(row, d: dict, repairs: dict):
    expected = _expected_status_energov(d)
    effective_status = _set_status(row, expected, repairs)

    apply = _entity_date(d, "ApplyDate", "ApplyDate")
    if apply is not pd.NaT:
        if pd.isna(row["FILE_DATE"]):
            repairs["FILE_DATE"] = apply
            repairs["FILE_DATE_FLAG"] = "FILLED"
        elif not _dates_equal(row["FILE_DATE"], apply):
            repairs["FILE_DATE"] = apply
            repairs["FILE_DATE_FLAG"] = "FIXED"

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
        if final is not pd.NaT:
            if pd.isna(current_final):
                repairs["FINAL_DATE"] = final
                repairs["FINAL_DATE_FLAG"] = "FILLED"
            elif not _dates_equal(current_final, final):
                repairs["FINAL_DATE"] = final
                repairs["FINAL_DATE_FLAG"] = "FIXED"
    elif not pd.isna(current_final):
        # FinalDate appears on Incomplete/Resubmit and other non-final
        # statuses; do not treat those as true finalization dates.
        repairs["FINAL_DATE"] = pd.NaT
        repairs["FINAL_DATE_FLAG"] = "FIXED"


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Tulare County permit records using information from the raw DATA JSON.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Tulare County".  Must contain
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
        if schema in ("entity_fees", "entity_fees_reviews"):
            _repair_energov(row, d, repairs)

        for key, value in repairs.items():
            out.at[idx, key] = value

    return out


# ── CLI: run standalone to preview repair stats ─────────────────────────────

if __name__ == "__main__":
    import os
    from collections import Counter

    from dotenv import load_dotenv

    load_dotenv("/Users/ekung/projects/la-permits-data/.env")
    MY_DATA_PATH = os.getenv("MY_DATA_PATH")
    AGENT_DATA_PATH = os.getenv("AGENT_DATA_PATH")
    filepath = os.path.join(MY_DATA_PATH, "processed_data", "permits_ca_sample.parquet")
    df = pd.read_parquet(filepath)
    city = df[(df["JURISDICTION"] == "Tulare County") & (df["STATE"] == "CA")].copy()

    print(f"Tulare County records: {len(city):,}\n")

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

    print("\nSTATUS_NORMALIZED_FLAG breakdown:")
    for flag in ["FILLED", "FIXED"]:
        sub = repaired[repaired["STATUS_NORMALIZED_FLAG"] == flag]
        print(f"  {flag} ({len(sub)}):")
        pairs = Counter()
        for idx in sub.index:
            d = _safe_parse(city.loc[idx, "DATA"])
            entity = d.get("entity") if d and isinstance(d.get("entity"), dict) else {}
            raw = entity.get("CaseStatus")
            before = city.loc[idx, "STATUS_NORMALIZED"]
            after = repaired.loc[idx, "STATUS_NORMALIZED"]
            pairs[(raw, before, after)] += 1
        for (raw, before, after), n in pairs.most_common():
            print(f"    {raw!r}: {before!r} → {after!r}  n={n}")

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
    print(f"  {n_has:>4,} / {len(repaired):>4,}")

    if AGENT_DATA_PATH:
        out_path = os.path.join(AGENT_DATA_PATH, "permits_ca_tulare_county_repaired.parquet")
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote {out_path}")

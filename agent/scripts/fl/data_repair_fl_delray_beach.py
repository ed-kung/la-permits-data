"""Data repair for Delray Beach (FL) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Delray Beach DATA has two families in this sample:

  - entity_fees_reviews: Tyler EnerGov-style payload with top-level
    keys entity, details, fees, contacts, processing_status, plus
    reviews / holds / attachments / more_info
  - permit_inspections: legacy portal payload with Permit,
    Plan Review, and Inspection List

Canonical fields (entity schema):
  - CaseStatus / details.PermitStatus  → STATUS_NORMALIZED
    (Issued + FinalDate treated as Final — portal status lag)
  - ApplyDate                          → FILE_DATE
  - IssueDate                          → PERMIT_DATE
  - FinalDate (fallback: details.FinalizeDate,
    else latest Passed final-ish inspection
    in processing_status)              → FINAL_DATE

Canonical fields (permit_inspections schema):
  - Application Status                 → STATUS_NORMALIZED
  - No ApplyDate / IssueDate in DATA   → FILE_DATE / PERMIT_DATE
    not fillable from this schema
  - Latest Approved final-ish
    Inspection List date               → FINAL_DATE (Final only)

Known issues repaired:
  - STATUS_NORMALIZED null for New Document / Upload and Submit /
    Respond and Resubmit → FILLED as In Review.
  - Issued rows that already carry FinalDate (and usually a Passed
    Building Final) remapped Active → Final so FINAL_DATE is kept.
  - Missing FINAL_DATE on Final rows filled from FinalDate /
    FinalizeDate, Passed final inspections (entity), or Approved
    final Inspection List dates (permit_inspections).
  - Spurious FINAL_DATE on Inactive Expired Closed → cleared.

Not repairable from DATA:
  - entity FILE_DATE already matches ApplyDate for all sample rows.
  - entity PERMIT_DATE already matches IssueDate whenever present.
    Many Complete / Closed Final shells and one Issued Active shell
    have Issued=False / null IssueDate → PERMIT_DATE stays missing.
  - Most Closed Final rows lack FinalDate / FinalizeDate and have
    no usable Passed final inspection → FINAL_DATE stays missing.
  - All 55 permit_inspections rows lack ApplyDate → FILE_DATE stays
    missing. PERMIT_DATE has no reliable IssueDate analogue in DATA.
"""

from __future__ import annotations

import json
import math
import re
from typing import Optional

import numpy as np
import pandas as pd


# Plausible calendar-year range for permit dates in this jurisdiction.
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
    """Parse a date value as UTC, returning pd.NaT on failure or implausible year."""
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return pd.NaT
    if isinstance(val, str) and not str(val).strip():
        return pd.NaT
    try:
        dt = pd.to_datetime(val, utc=True, errors="coerce")
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
    if {"Permit", "Plan Review", "Inspection List"}.issubset(keys):
        return "permit_inspections"
    if not {"entity", "details"}.issubset(keys):
        return "unknown"
    has_fees = "fees" in keys
    has_reviews = bool(keys & {"reviews", "holds", "attachments", "more_info"})
    if has_fees and has_reviews:
        return "entity_fees_reviews"
    if has_fees:
        return "entity_fees"
    return "entity_basic"


def _dates_equal(a, b) -> bool:
    """Compare two datelike values at calendar-day resolution (UTC)."""
    da = _safe_to_datetime(a)
    db = _safe_to_datetime(b)
    if da is pd.NaT or db is pd.NaT:
        return False
    return da.date() == db.date()


# ── Status mapping ──────────────────────────────────────────────────────────

# entity.CaseStatus (Title Case, as in DATA) → STATUS_NORMALIZED
_ENTITY_STATUS_MAP = {
    # Final
    "Complete": "Final",
    "Closed": "Final",
    "Administratively Closed": "Final",
    "Final Inspection Complete": "Final",
    "C.O. Issued": "Final",
    # Active
    "Issued": "Active",
    # Inactive
    "Void": "Inactive",
    "Expired Closed": "Inactive",
    # In Review
    "In Review": "In Review",
    "On Hold": "In Review",
    "Fees Due": "In Review",
    "New Document": "In Review",
    "Upload and Submit": "In Review",
    "Respond and Resubmit": "In Review",
}

# permit_inspections Application Status → STATUS_NORMALIZED
_PERMIT_STATUS_MAP = {
    "C.O. ISSUED": "Final",
    "FINAL INSPECTION COMPLETE": "Final",
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


_FINAL_INSP_RE = re.compile(
    r"FINAL|\bFNL\b|CLOSEOUT|CERTIFICATE|\bC/?O\b|\bCOC\b",
    re.IGNORECASE,
)


def _final_inspection_date_entity(d: dict):
    """Latest Passed/Approved processing_status inspection that looks final."""
    ps = d.get("processing_status")
    if not isinstance(ps, list):
        return pd.NaT
    candidates = []
    for insp in ps:
        if not isinstance(insp, dict):
            continue
        status = str(insp.get("status") or "").strip().lower()
        if status not in ("passed", "approved"):
            continue
        desc = str(insp.get("description") or "")
        if not _FINAL_INSP_RE.search(desc):
            continue
        dt = _safe_to_datetime(insp.get("scheduled_date"))
        if dt is pd.NaT:
            dt = _safe_to_datetime(insp.get("requested_date"))
        if dt is not pd.NaT:
            candidates.append(dt)
    return max(candidates) if candidates else pd.NaT


_INSP_DATE_RE = re.compile(r"(\d{1,2}/\d{1,2}/\d{4})")


def _parse_inspection_list_date(raw) -> pd.Timestamp:
    """Parse 'Inspection Date M/D/YYYY' strings from Inspection List."""
    if raw is None or (isinstance(raw, float) and math.isnan(raw)):
        return pd.NaT
    m = _INSP_DATE_RE.search(str(raw))
    if not m:
        return pd.NaT
    return _safe_to_datetime(m.group(1))


def _final_inspection_date_permit(d: dict):
    """Latest Approved final-ish date from Inspection List."""
    insp_list = d.get("Inspection List")
    if not isinstance(insp_list, list):
        return pd.NaT
    candidates = []
    for insp in insp_list:
        if not isinstance(insp, dict):
            continue
        status = str(insp.get("InspectionStatus") or "").strip().lower()
        if "approv" not in status:
            continue
        itype = str(insp.get("InspectionType") or "")
        if not _FINAL_INSP_RE.search(itype):
            continue
        dt = _parse_inspection_list_date(insp.get("DateOfInspection"))
        if dt is not pd.NaT:
            candidates.append(dt)
    return max(candidates) if candidates else pd.NaT


def _expected_entity_status(d: dict) -> Optional[str]:
    """Map CaseStatus to STATUS_NORMALIZED, with Issued+FinalDate → Final."""
    raw = _case_status(d)
    if raw is None:
        return None
    expected = _ENTITY_STATUS_MAP.get(raw)
    if expected is None:
        # Case-insensitive fallback
        for key, val in _ENTITY_STATUS_MAP.items():
            if key.lower() == raw.lower():
                expected = val
                break
    if expected == "Active" and raw.lower() == "issued":
        final = _entity_date(d, "FinalDate", "FinalizeDate")
        if final is not pd.NaT:
            return "Final"
    return expected


def _expected_permit_status(d: dict) -> Optional[str]:
    permit = d.get("Permit") if isinstance(d.get("Permit"), dict) else {}
    raw = permit.get("Application Status")
    if raw is None:
        return None
    raw = str(raw).strip()
    if not raw:
        return None
    if raw in _PERMIT_STATUS_MAP:
        return _PERMIT_STATUS_MAP[raw]
    for key, val in _PERMIT_STATUS_MAP.items():
        if key.lower() == raw.lower():
            return val
    return None


# ── Per-record repair logic ─────────────────────────────────────────────────

def _repair_entity(row, d: dict, repairs: dict) -> None:
    current_status = row["STATUS_NORMALIZED"]
    expected = _expected_entity_status(d)

    if expected is not None:
        if pd.isna(current_status):
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"
        elif current_status != expected:
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FIXED"

    effective_status = repairs.get("STATUS_NORMALIZED", current_status)

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
    if final is pd.NaT and effective_status == "Final":
        final = _final_inspection_date_entity(d)
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
        repairs["FINAL_DATE"] = pd.NaT
        repairs["FINAL_DATE_FLAG"] = "FIXED"


def _repair_permit_inspections(row, d: dict, repairs: dict) -> None:
    current_status = row["STATUS_NORMALIZED"]
    expected = _expected_permit_status(d)

    if expected is not None:
        if pd.isna(current_status):
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"
        elif current_status != expected:
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FIXED"

    effective_status = repairs.get("STATUS_NORMALIZED", current_status)

    # No ApplyDate / IssueDate in this schema — leave FILE_DATE / PERMIT_DATE.

    final = _final_inspection_date_permit(d)
    current_final = row["FINAL_DATE"]

    if effective_status == "Final":
        if final is not pd.NaT:
            if pd.isna(current_final):
                repairs["FINAL_DATE"] = final
                repairs["FINAL_DATE_FLAG"] = "FILLED"
            # Do not overwrite an existing FINAL_DATE that differs: C.O.
            # dates are often absent from Inspection List.
    elif not pd.isna(current_final):
        repairs["FINAL_DATE"] = pd.NaT
        repairs["FINAL_DATE_FLAG"] = "FIXED"


def _repair_record(row, d: dict, schema: str, repairs: dict) -> None:
    if schema.startswith("entity"):
        _repair_entity(row, d, repairs)
    elif schema == "permit_inspections":
        _repair_permit_inspections(row, d, repairs)


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Delray Beach permit records using the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Delray Beach".  Must contain
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
        _repair_record(row, d, schema, repairs)

        for key, value in repairs.items():
            out.at[idx, key] = value

    for col in ("FILE_DATE", "PERMIT_DATE", "FINAL_DATE"):
        out[col] = pd.to_datetime(out[col], errors="coerce", utc=True).dt.tz_localize(None)

    return out


# ── CLI: run standalone to preview repair stats ─────────────────────────────

if __name__ == "__main__":
    import os

    from dotenv import load_dotenv

    load_dotenv("/Users/ekung/projects/la-permits-data/.env")
    MY_DATA_PATH = os.getenv("MY_DATA_PATH")
    AGENT_DATA_PATH = os.getenv("AGENT_DATA_PATH")
    filepath = os.path.join(MY_DATA_PATH, "processed_data", "permits_fl_sample.parquet")
    df = pd.read_parquet(filepath)
    city = df[df["JURISDICTION"] == "Delray Beach"].copy()

    print(f"Delray Beach records: {len(city):,}\n")

    repaired = data_repair(city)

    print("INFERRED_SCHEMA:")
    for s, c in repaired["INFERRED_SCHEMA"].value_counts(dropna=False).items():
        print(f"  {str(s):25s}: {c:>4,}")
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
        counts = {}
        for idx in sub.index:
            d = _safe_parse(city.loc[idx, "DATA"])
            schema = repaired.loc[idx, "INFERRED_SCHEMA"]
            if schema == "permit_inspections":
                permit = d.get("Permit") if d and isinstance(d.get("Permit"), dict) else {}
                cs = permit.get("Application Status")
            else:
                cs = _case_status(d) if d else None
            before = city.loc[idx, "STATUS_NORMALIZED"]
            after = repaired.loc[idx, "STATUS_NORMALIZED"]
            key = (cs, before, after)
            counts[key] = counts.get(key, 0) + 1
        for (cs, before, after), n in sorted(counts.items(), key=lambda x: -x[1]):
            print(f"    {n:>3}  {cs!r}: {before!r} → {after!r}")

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

    print("\nFINAL_DATE_FLAG detail:")
    for flag in ["FILLED", "FIXED"]:
        sub = repaired[repaired["FINAL_DATE_FLAG"] == flag]
        print(f"  {flag} ({len(sub)})")
        for idx in list(sub.index)[:20]:
            d = _safe_parse(city.loc[idx, "DATA"])
            schema = repaired.loc[idx, "INFERRED_SCHEMA"]
            if schema == "permit_inspections":
                permit = d.get("Permit") if d and isinstance(d.get("Permit"), dict) else {}
                cs = permit.get("Application Status")
            else:
                cs = _case_status(d) if d else None
            print(
                f"    [{schema}] {cs!r}: before={city.loc[idx, 'FINAL_DATE']!r} "
                f"after={repaired.loc[idx, 'FINAL_DATE']!r} "
                f"status={repaired.loc[idx, 'STATUS_NORMALIZED']!r}"
            )
        if len(sub) > 20:
            print(f"    ... ({len(sub) - 20} more)")

    if AGENT_DATA_PATH:
        out_path = os.path.join(AGENT_DATA_PATH, "delray_beach_repaired_sample.parquet")
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote {out_path}")

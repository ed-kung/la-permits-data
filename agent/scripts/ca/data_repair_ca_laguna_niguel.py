"""Data repair for Laguna Niguel (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Laguna Niguel DATA has two families of payloads:

  Civic-portal / Accela-style scrape (``permit_info``)
    Top-level keys: fees, contacts, site_info, inspections, permit_info,
    search_data. Sub-schemas reflect which permit_info dates are populated
    (``1/1/1900`` treated as blank):

      - permit_info_issued_finaled
      - permit_info_issued
      - permit_info_finaled_only
      - permit_info_approved_only
      - permit_info_applied_only

  Tyler EnerGov / CityView detail scrape (``entity``)
      - entity:          entity + details + fees (+ contacts,
                         processing_status)
      - entity_reviews:  entity plus reviews/holds/attachments/more_info

Canonical fields (permit_info):
  - PermitStatus                          → STATUS_NORMALIZED
  - PermitAppliedDate                     → FILE_DATE
  - PermitIssuedDate (fallback: Approved) → PERMIT_DATE
  - PermitFinaledDate (reject year<=1900) → FINAL_DATE

Canonical fields (entity):
  - CaseStatus / details.PermitStatus     → STATUS_NORMALIZED
  - ApplyDate                             → FILE_DATE
  - IssueDate                             → PERMIT_DATE
  - FinalDate / details.FinalizeDate      → FINAL_DATE

Known issues repaired:
  - APPLIED-ONLINE left STATUS_NORMALIZED null → FILLED In Review.
  - Active/Final missing PERMIT_DATE when Issued blank but Approved
    present → FILLED.
  - 701 APPLIED / In Review rows carry sentinel PermitFinaledDate
    ``1/1/1900`` copied into FINAL_DATE → cleared (FIXED).
  - Spurious FINAL_DATE on Inactive (EXPIRED / Plan Approval Expired)
    → cleared.

Not repairable / left as-is:
  - FILE_DATE already matches Applied / ApplyDate for all sample rows.
  - ~3 Final rows with blank Issued and Approved → PERMIT_DATE stays
    missing.
  - Entity Active/Final PERMIT_DATE / FINAL_DATE already match source
    when those dates exist.
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
    """Parse a date value, returning pd.NaT on failure or sentinel.

    Laguna Niguel civic-portal rows use ``1/1/1900`` as a blank placeholder
    for PermitFinaledDate; treat year <= 1900 as missing.
    """
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return pd.NaT
    if isinstance(val, str) and not str(val).strip():
        return pd.NaT
    try:
        dt = pd.to_datetime(val)
    except (ValueError, TypeError):
        return pd.NaT
    if dt is pd.NaT or pd.isna(dt):
        return pd.NaT
    if getattr(dt, "tzinfo", None) is not None:
        dt = dt.tz_convert("UTC").tz_localize(None)
    if getattr(dt, "year", None) is not None and dt.year <= 1900:
        return pd.NaT
    return dt


def _dates_equal(a, b) -> bool:
    """Compare two datelike values at calendar-day resolution."""
    da = _safe_to_datetime(a)
    db = _safe_to_datetime(b)
    if da is pd.NaT or db is pd.NaT or pd.isna(da) or pd.isna(db):
        return False
    return da.normalize() == db.normalize()


def _permit_info(d: dict) -> dict:
    pi = d.get("permit_info")
    return pi if isinstance(pi, dict) else {}


def _entity(d: dict) -> dict:
    ent = d.get("entity")
    return ent if isinstance(ent, dict) else {}


def _details(d: dict) -> dict:
    det = d.get("details")
    return det if isinstance(det, dict) else {}


def _pi_date(d: dict, *keys: str):
    pi = _permit_info(d)
    for key in keys:
        dt = _safe_to_datetime(pi.get(key))
        if dt is not pd.NaT:
            return dt
    return pd.NaT


def _entity_date(d: dict, entity_key: str, *detail_keys: str):
    ent = _entity(d)
    dt = _safe_to_datetime(ent.get(entity_key))
    if dt is not pd.NaT:
        return dt
    det = _details(d)
    for key in detail_keys:
        dt = _safe_to_datetime(det.get(key))
        if dt is not pd.NaT:
            return dt
    return pd.NaT


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())

    if "permit_info" in keys:
        pi = _permit_info(data_dict)
        if not pi:
            return "permit_info_empty"
        issued = _safe_to_datetime(pi.get("PermitIssuedDate"))
        finaled = _safe_to_datetime(pi.get("PermitFinaledDate"))
        approved = _safe_to_datetime(pi.get("PermitApprovedDate"))
        applied = _safe_to_datetime(pi.get("PermitAppliedDate"))
        has_issued = issued is not pd.NaT
        has_finaled = finaled is not pd.NaT
        has_approved = approved is not pd.NaT
        has_applied = applied is not pd.NaT
        if has_issued and has_finaled:
            return "permit_info_issued_finaled"
        if has_issued:
            return "permit_info_issued"
        if has_finaled:
            return "permit_info_finaled_only"
        if has_approved:
            return "permit_info_approved_only"
        if has_applied:
            return "permit_info_applied_only"
        return "permit_info_empty_dates"

    if "entity" in keys:
        if keys & {"reviews", "holds", "attachments", "more_info"}:
            return "entity_reviews"
        return "entity"

    return "unknown"


# ── Status mapping ──────────────────────────────────────────────────────────

# permit_info.PermitStatus (uppercased) → STATUS_NORMALIZED
_PI_STATUS_MAP = {
    "FINALED": "Final",
    "ISSUED": "Active",
    "APPROVED": "Active",
    "APPLIED": "In Review",
    "APPLIED-ONLINE": "In Review",
    "PLANCHECK": "In Review",
    "CORRECTION": "In Review",
    "EXPIRED": "Inactive",
    "EXPIRED-CODE": "Inactive",
    "PLANCHECK EXPIRED": "Inactive",
    "VOID": "Inactive",
    "WITHDRAWN": "Inactive",
    "REVOKE": "Inactive",
}

# entity.CaseStatus (as stored; lookup uses strip()) → STATUS_NORMALIZED
_ENTITY_STATUS_MAP = {
    "Finaled": "Final",
    "Complete": "Final",
    "Issued": "Active",
    "Approved": "Active",
    "Submitted - Online": "In Review",
    "Submitted": "In Review",
    "In Review": "In Review",
    "Fees Due": "In Review",
    "Fees Paid": "In Review",
    "Pending": "In Review",
    "Plan Check": "In Review",
    "Expired": "Inactive",
    "Void": "Inactive",
    "Withdrawn": "Inactive",
    "Plan Approval Expired": "Inactive",
}


def _normalize_pi_status(raw) -> str:
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return ""
    return str(raw).strip().upper()


def _derive_pi_status(pi: dict) -> Optional[str]:
    raw = _normalize_pi_status(pi.get("PermitStatus"))
    if not raw:
        return None
    if raw in _PI_STATUS_MAP:
        return _PI_STATUS_MAP[raw]
    if "FINAL" in raw:
        return "Final"
    if "EXPIRE" in raw or "VOID" in raw or "CANCEL" in raw or "WITHDRAW" in raw or "REVOKE" in raw:
        return "Inactive"
    if "APPLI" in raw or "PLAN" in raw or "REVIEW" in raw or "CORRECTION" in raw:
        return "In Review"
    if "ISSUE" in raw or "APPROV" in raw:
        return "Active"
    return None


def _case_status(d: dict) -> Optional[str]:
    ent = _entity(d)
    det = _details(d)
    status = ent.get("CaseStatus") or det.get("PermitStatus")
    if status is None:
        return None
    status = str(status).strip()
    return status or None


def _set_status(repairs: dict, current_status, expected: Optional[str]) -> None:
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

def _repair_permit_info(row, d: dict, repairs: dict) -> None:
    """Repair a civic-portal permit_info record."""
    pi = _permit_info(d)
    current_status = row["STATUS_NORMALIZED"]
    expected = _derive_pi_status(pi)
    _set_status(repairs, current_status, expected)
    effective_status = repairs.get("STATUS_NORMALIZED", current_status)

    applied = _pi_date(d, "PermitAppliedDate")
    _set_date(repairs, "FILE_DATE", row["FILE_DATE"], applied)

    issued = _pi_date(d, "PermitIssuedDate")
    approved = _pi_date(d, "PermitApprovedDate")
    permit_src = issued if issued is not pd.NaT else approved

    if not pd.isna(row["PERMIT_DATE"]):
        if issued is not pd.NaT and not _dates_equal(row["PERMIT_DATE"], issued):
            repairs["PERMIT_DATE"] = issued
            repairs["PERMIT_DATE_FLAG"] = "FIXED"
    elif effective_status in ("Active", "Final") and permit_src is not pd.NaT:
        repairs["PERMIT_DATE"] = permit_src
        repairs["PERMIT_DATE_FLAG"] = "FILLED"

    preferred_final = _pi_date(d, "PermitFinaledDate")
    current_final = row["FINAL_DATE"]
    if effective_status == "Final":
        _set_date(repairs, "FINAL_DATE", current_final, preferred_final)
    elif not pd.isna(current_final):
        # Sentinel 1/1/1900 on APPLIED, or EXPIRED close stamps, etc.
        repairs["FINAL_DATE"] = pd.NaT
        repairs["FINAL_DATE_FLAG"] = "FIXED"


def _repair_entity(row, d: dict, repairs: dict) -> None:
    """Repair a Tyler EnerGov / CityView entity record."""
    current_status = row["STATUS_NORMALIZED"]
    raw_status = _case_status(d)
    expected = _ENTITY_STATUS_MAP.get(raw_status) if raw_status else None
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
        # Spurious FINAL_DATE on Inactive (Plan Approval Expired, etc.).
        repairs["FINAL_DATE"] = pd.NaT
        repairs["FINAL_DATE_FLAG"] = "FIXED"


def _repair_record(row, d: dict, schema: str, repairs: dict) -> None:
    if schema.startswith("permit_info"):
        _repair_permit_info(row, d, repairs)
    elif schema.startswith("entity"):
        _repair_entity(row, d, repairs)


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Laguna Niguel permit records using information from the raw DATA JSON.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Laguna Niguel".  Must contain
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

    return out


# ── CLI: run standalone to preview repair stats ─────────────────────────────

if __name__ == "__main__":
    import os
    from dotenv import load_dotenv

    load_dotenv("/Users/ekung/projects/la-permits-data/.env")
    MY_DATA_PATH = os.getenv("MY_DATA_PATH")
    AGENT_DATA_PATH = os.getenv("AGENT_DATA_PATH")
    filepath = os.path.join(MY_DATA_PATH, "processed_data", "permits_ca_sample.parquet")
    df = pd.read_parquet(filepath)
    city = df[df["JURISDICTION"] == "Laguna Niguel"].copy()

    print(f"Laguna Niguel records: {len(city):,}\n")

    repaired = data_repair(city)

    print("INFERRED_SCHEMA:")
    for s, c in repaired["INFERRED_SCHEMA"].value_counts().items():
        print(f"  {s}: {c:,}")
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

    print("\nFINAL_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FINAL_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({n_has / max(len(sub), 1):.1%})")

    print("\nPERMIT_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["PERMIT_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({n_has / max(len(sub), 1):.1%})")

    if AGENT_DATA_PATH:
        out_path = os.path.join(AGENT_DATA_PATH, "laguna_niguel_repaired_sample.parquet")
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote {out_path}")

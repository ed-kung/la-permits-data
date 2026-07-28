"""Data repair for La Quinta (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

La Quinta DATA is a single flat civic-portal schema (all sample rows share
the same top-level keys: contacts, fees, inspections, permit_info,
search_data, site_info). ``inspections`` and ``fees`` are always empty /
null in the sample. Canonical fields live under ``permit_info`` (with
``search_data`` as a partial mirror for STATUS / APPLIED / APPROVED /
Issued Date / FINALED):

  - permit_info.PermitStatus       → STATUS_NORMALIZED
  - permit_info.PermitAppliedDate  → FILE_DATE
  - permit_info.PermitIssuedDate   → PERMIT_DATE
      (fallback: PermitApprovedDate)
  - permit_info.PermitFinaledDate  → FINAL_DATE

Content variants (used as INFERRED_SCHEMA) differ by which permit_info
date fields are populated:

  - permit_info_full:          Applied + Issued + Finaled
  - permit_info_issued:        Applied + Issued (no Finaled)
  - permit_info_approved:      Applied + Approved (no Issued/Finaled)
  - permit_info_applied_only:  Applied only
  - permit_info_partial:       Issued/Approved/Finaled without Applied
  - permit_info_shell:         no usable Applied/Issued/Approved/Finaled
  - unknown / missing

Known issues repaired:
  - 175 blank PermitStatus legacy CONV shells → FILLED status inferred
    from Finaled / Issued / Approved / Applied dates.
  - 11 Active rows (ISSUED / APPROVED) with a true PermitFinaledDate →
    FIXED to Final.
  - Active/Final rows missing PERMIT_DATE when Issued is empty but
    Approved is present → FILLED from PermitApprovedDate (~141 after
    status repair, including newly Active/Final blank-status shells).
  - Spurious FINAL_DATE on non-Final rows (e.g. DENIED with a close
    stamp) → cleared (FIXED).

Not repairable from DATA:
  - 10 FILE_DATE gaps (no PermitAppliedDate; mostly Closed / Active /
    Permit Issued legacy shells that only expose Issued).
  - CLOSED Final rows (~408) have neither Issued nor Finaled; most also
    lack Approved → PERMIT_DATE and FINAL_DATE stay missing.
  - ~38 FINALED rows lack PermitFinaledDate and have empty inspections
    → FINAL_DATE stays missing.
  - No inspection Completed dates available as a finaling proxy.
"""

from __future__ import annotations

import json
import math
from datetime import date, datetime
from typing import Optional

import numpy as np
import pandas as pd


# Plausible calendar-year range for permit dates in this jurisdiction.
_MIN_YEAR = 1950
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
    """Parse a date value, returning pd.NaT on failure or implausible year."""
    if val is None or (isinstance(val, str) and not str(val).strip()):
        return pd.NaT
    try:
        dt = pd.to_datetime(val)
    except (ValueError, TypeError):
        return pd.NaT
    if dt is pd.NaT or pd.isna(dt):
        return pd.NaT
    year = int(dt.year)
    if year < _MIN_YEAR or year > _MAX_YEAR:
        return pd.NaT
    return dt


def _as_date(val) -> Optional[date]:
    """Normalize a datelike value to datetime.date."""
    if _is_missing(val):
        return None
    if isinstance(val, date) and not isinstance(val, datetime):
        return val
    if isinstance(val, pd.Timestamp):
        if pd.isna(val):
            return None
        return val.date()
    dt = _safe_to_datetime(val)
    if dt is pd.NaT or pd.isna(dt):
        return None
    return dt.date()


def _normalize_status_key(raw) -> str:
    if raw is None:
        return ""
    return str(raw).strip().upper()


def _permit_info(d: dict) -> dict:
    pi = d.get("permit_info")
    return pi if isinstance(pi, dict) else {}


def _search_data(d: dict) -> dict:
    sd = d.get("search_data")
    return sd if isinstance(sd, dict) else {}


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())
    if not {"permit_info", "search_data"}.issubset(keys):
        return "unknown"

    pi = _permit_info(data_dict)
    has_applied = _as_date(pi.get("PermitAppliedDate")) is not None
    has_issued = _as_date(pi.get("PermitIssuedDate")) is not None
    has_approved = _as_date(pi.get("PermitApprovedDate")) is not None
    has_finaled = _as_date(pi.get("PermitFinaledDate")) is not None

    if has_applied and has_issued and has_finaled:
        return "permit_info_full"
    if has_applied and has_issued:
        return "permit_info_issued"
    if has_applied and has_approved and not has_issued:
        return "permit_info_approved"
    if has_applied:
        return "permit_info_applied_only"
    if has_issued or has_approved or has_finaled:
        return "permit_info_partial"
    return "permit_info_shell"


# ── Status mapping ──────────────────────────────────────────────────────────

# PermitStatus (uppercased) → STATUS_NORMALIZED
_STATUS_MAP = {
    # Final
    "FINALED": "Final",
    "FINAL": "Final",
    "CLOSED": "Final",
    "COMPLETE": "Final",
    "COMPLETED": "Final",
    # Active
    "ISSUED": "Active",
    "ISSUED - ONLINE": "Active",
    "PERMIT ISSUED": "Active",
    "ACTIVE": "Active",
    "APPROVED": "Active",
    # In Review
    "OK TO ISSUE": "In Review",
    "READY TO ISSUE": "In Review",
    "APPLIED": "In Review",
    "PLAN CHECK": "In Review",
    "UNDER REVIEW": "In Review",
    "SUBMITTED": "In Review",
    "APPROVED-CONDITIONS": "In Review",
    "REVISIONS REQUESTED": "In Review",
    "ON HOLD": "In Review",
    "INCOMPLETE SUBMITTAL": "In Review",
    "PENDING": "In Review",
    # Inactive
    "VOIDED": "Inactive",
    "VOID": "Inactive",
    "EXPIRED": "Inactive",
    "WITHDRAWN": "Inactive",
    "DENIED": "Inactive",
    "CANCELLED": "Inactive",
    "CANCELED": "Inactive",
    "INACTIVE": "Inactive",
}


def _map_permit_status(raw) -> Optional[str]:
    key = _normalize_status_key(raw)
    if key in _STATUS_MAP:
        return _STATUS_MAP[key]
    if not key:
        return None
    if "FINAL" in key or key in ("CLOSED", "COMPLETE", "COMPLETED"):
        return "Final"
    if "ISSUED" in key or key == "ACTIVE" or key.startswith("APPROV"):
        # APPROVED-CONDITIONS already handled above; bare APPROVED* → Active
        if "CONDITION" in key:
            return "In Review"
        return "Active"
    if (
        "EXPIRE" in key
        or "VOID" in key
        or "CANCEL" in key
        or "WITHDRAW" in key
        or "DENIED" in key
    ):
        return "Inactive"
    if (
        "REVIEW" in key
        or "PENDING" in key
        or "PLAN CHECK" in key
        or "HOLD" in key
        or "SUBMIT" in key
        or "APPLIED" in key
        or "REVISION" in key
        or "INCOMPLETE" in key
        or "OK TO ISSUE" in key
        or "READY TO ISSUE" in key
    ):
        return "In Review"
    return None


def _derive_status(pi: dict) -> Optional[str]:
    """Map PermitStatus; infer from dates when blank; upgrade when finaled.

    Inactive labels stay Inactive even when PermitFinaledDate is populated
    (DENIED / VOIDED close stamps are not treated as successful sign-offs).
    """
    mapped = _map_permit_status(pi.get("PermitStatus"))

    if mapped == "Inactive":
        return "Inactive"

    if _as_date(pi.get("PermitFinaledDate")) is not None:
        return "Final"

    if mapped is not None:
        return mapped

    # Blank / unmapped: infer from dates (legacy CONV shells).
    if _as_date(pi.get("PermitIssuedDate")) is not None:
        return "Active"
    if _as_date(pi.get("PermitApprovedDate")) is not None:
        return "Active"
    if _as_date(pi.get("PermitAppliedDate")) is not None:
        return "In Review"
    return None


def _preferred_file_date(pi: dict, d: dict) -> Optional[date]:
    applied = _as_date(pi.get("PermitAppliedDate"))
    if applied is not None:
        return applied
    sd = _search_data(d)
    return _as_date(sd.get("APPLIED") or sd.get("Applied") or sd.get("Application"))


def _preferred_permit_date(pi: dict, d: dict) -> Optional[date]:
    issued = _as_date(pi.get("PermitIssuedDate"))
    if issued is not None:
        return issued
    approved = _as_date(pi.get("PermitApprovedDate"))
    if approved is not None:
        return approved
    sd = _search_data(d)
    return _as_date(sd.get("Issued Date") or sd.get("ISSUED") or sd.get("Issued"))


def _preferred_final_date(pi: dict, d: dict) -> Optional[date]:
    finaled = _as_date(pi.get("PermitFinaledDate"))
    if finaled is not None:
        return finaled
    sd = _search_data(d)
    return _as_date(sd.get("FINALED") or sd.get("Finaled"))


# ── Per-record repair logic ─────────────────────────────────────────────────

def _repair_record(row, d: dict, repairs: dict):
    """Populate *repairs* with corrected values for a single La Quinta record."""
    pi = _permit_info(d)

    # -- STATUS_NORMALIZED --
    current_status = row["STATUS_NORMALIZED"]
    expected = _derive_status(pi)
    if expected is not None:
        if pd.isna(current_status):
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"
        elif current_status != expected:
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FIXED"

    effective_status = repairs.get("STATUS_NORMALIZED", current_status)

    # -- FILE_DATE --
    preferred_fd = _preferred_file_date(pi, d)
    current_fd = _as_date(row["FILE_DATE"])
    if preferred_fd is not None:
        if current_fd is None:
            repairs["FILE_DATE"] = pd.Timestamp(preferred_fd)
            repairs["FILE_DATE_FLAG"] = "FILLED"
        elif current_fd != preferred_fd:
            repairs["FILE_DATE"] = pd.Timestamp(preferred_fd)
            repairs["FILE_DATE_FLAG"] = "FIXED"

    # -- PERMIT_DATE --
    preferred_pd = _preferred_permit_date(pi, d)
    current_pd = _as_date(row["PERMIT_DATE"])
    if preferred_pd is not None:
        if current_pd is None:
            if effective_status in ("Active", "Final"):
                repairs["PERMIT_DATE"] = pd.Timestamp(preferred_pd)
                repairs["PERMIT_DATE_FLAG"] = "FILLED"
        elif current_pd != preferred_pd:
            repairs["PERMIT_DATE"] = pd.Timestamp(preferred_pd)
            repairs["PERMIT_DATE_FLAG"] = "FIXED"

    # -- FINAL_DATE --
    preferred_final = _preferred_final_date(pi, d)
    current_final = _as_date(row["FINAL_DATE"])
    if effective_status != "Final":
        if current_final is not None:
            repairs["FINAL_DATE"] = pd.NaT
            repairs["FINAL_DATE_FLAG"] = "FIXED"
    elif preferred_final is not None:
        if current_final is None:
            repairs["FINAL_DATE"] = pd.Timestamp(preferred_final)
            repairs["FINAL_DATE_FLAG"] = "FILLED"
        elif current_final != preferred_final:
            repairs["FINAL_DATE"] = pd.Timestamp(preferred_final)
            repairs["FINAL_DATE_FLAG"] = "FIXED"


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    La Quinta permit records using information from the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "La Quinta".  Must contain
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
    AGENT_DATA_PATH = os.getenv("AGENT_DATA_PATH")
    filepath = os.path.join(MY_DATA_PATH, "processed_data", "permits_ca_sample.parquet")
    df = pd.read_parquet(filepath)
    city = df[(df["JURISDICTION"] == "La Quinta") & (df["STATE"] == "CA")].copy()

    print(f"La Quinta records: {len(city):,}\n")

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

    print("\nFILE_DATE coverage:")
    n_has = repaired["FILE_DATE"].notna().sum()
    print(f"  {n_has:,} / {len(repaired):,} ({n_has / len(repaired):.1%})")

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

    final_sub = repaired[repaired["STATUS_NORMALIZED"] == "Final"]
    print(f"\nFinal still missing PERMIT_DATE: {final_sub['PERMIT_DATE'].isna().sum()}")
    print(f"Final still missing FINAL_DATE:  {final_sub['FINAL_DATE'].isna().sum()}")

    if AGENT_DATA_PATH:
        out_dir = os.path.join(AGENT_DATA_PATH, "repaired")
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, "permits_ca_la_quinta_repaired.parquet")
        for col in ["FILE_DATE", "PERMIT_DATE", "FINAL_DATE"]:
            repaired[col] = pd.to_datetime(repaired[col], errors="coerce")
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote {out_path}")

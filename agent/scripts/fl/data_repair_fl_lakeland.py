"""Data repair for Lakeland (FL) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Lakeland DATA has two portal families:

  - civic (permit_info / search_data / site_info): City eTRAKiT-style
    payload with PermitStatus, PermitAppliedDate, PermitIssuedDate,
    PermitFinaledDate, PermitApprovedDate.
  - accela (Permit / ViewMilestones / CustomFields): IMS Accela-style
    payload with Milestone plus Submitted / Created / Issued / Finaled
    milestone dates.

Content variants (INFERRED_SCHEMA) further split each family by which
canonical dates are populated:

  - {civic|accela}_issued_finaled
  - {civic|accela}_issued
  - {civic|accela}_finaled
  - {civic|accela}_applied
  - {civic|accela}_status_only
  - missing / unknown

Canonical mappings:
  - PermitStatus / Milestone (+ Issued for APPROVED) → STATUS_NORMALIZED
  - PermitAppliedDate / Submitted (fallback Created) → FILE_DATE
  - PermitIssuedDate / Issued                        → PERMIT_DATE
  - PermitFinaledDate / Finaled (Final only)         → FINAL_DATE

Known issues repaired:
  - Unmapped labels (ABANDONED/FBC CH1, Approved Pending Payment,
    NOC REQUIRED, Revisions Pending, SWO) had null STATUS_NORMALIZED
    → FILLED.
  - CLOSED ADMIN / HB447 CLOSED wrongly mapped to Final (almost never
    have a finaled date) → FIXED to Inactive.
  - EVENT COMPLETED special-event rows wrongly mapped to In Review
    → FIXED to Final.
  - Unissued APPROVED rows wrongly mapped to Active → FIXED to In Review.
  - Stale STATUS_ORIGINAL==issued rows whose live Milestone is Finaled
    or Under Review → FIXED.
  - Missing FINAL_DATE on Final rows filled from PermitFinaledDate /
    ViewMilestones.Finaled (especially Accela ``Finaled`` rows where
    upstream left FINAL_DATE null).
  - Missing FILE_DATE / calendar-day drift vs Submitted filled/fixed.
  - Spurious FINAL_DATE on non-Final rows cleared.

Not repairable from DATA:
  - Many legacy FINALED civic rows lack PermitIssuedDate /
    PermitFinaledDate → PERMIT_DATE / FINAL_DATE stay missing.
  - A few rows have empty date fields and empty ViewMilestones.
  - PermitApprovedDate is intentionally not used as PERMIT_DATE
    (approval ≠ issuance).
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
        try:
            parsed = json.loads(data)
        except (json.JSONDecodeError, TypeError):
            return None
        return parsed if isinstance(parsed, dict) else None
    return data if isinstance(data, dict) else None


def _safe_to_datetime(val):
    """Parse a date value, returning pd.NaT on failure / out-of-range."""
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return pd.NaT
    if isinstance(val, dict):
        return pd.NaT
    if isinstance(val, str):
        s = val.strip()
        if not s or s.upper() in {
            "TBD", "NULL", "NONE", "N/A", "NA", "NAN",
            "00/00/0000", "0/0/0000",
        }:
            return pd.NaT
    try:
        dt = pd.to_datetime(val, errors="coerce")
    except (ValueError, TypeError, OverflowError):
        return pd.NaT
    if pd.isna(dt):
        return pd.NaT
    year = int(dt.year)
    if year < _MIN_YEAR or year > _MAX_YEAR:
        return pd.NaT
    if getattr(dt, "tzinfo", None) is not None:
        dt = dt.tz_convert("UTC").tz_localize(None)
    return dt


def _dates_equal(a, b) -> bool:
    """Compare two datelike values at calendar-day resolution."""
    da = _safe_to_datetime(a)
    db = _safe_to_datetime(b)
    if da is pd.NaT or db is pd.NaT:
        return False
    return da.normalize() == db.normalize()


def _family(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())
    if "permit_info" in keys:
        return "civic"
    if "Permit" in keys:
        return "accela"
    return "unknown"


def _extract_fields(d: dict, family: str):
    """Return (raw_status, applied, issued, finaled) for a DATA payload."""
    if family == "civic":
        pi = d.get("permit_info") or {}
        if not isinstance(pi, dict):
            pi = {}
        raw = pi.get("PermitStatus")
        applied = _safe_to_datetime(pi.get("PermitAppliedDate"))
        issued = _safe_to_datetime(pi.get("PermitIssuedDate"))
        finaled = _safe_to_datetime(pi.get("PermitFinaledDate"))
        return raw, applied, issued, finaled

    if family == "accela":
        perm = d.get("Permit") or {}
        vm = d.get("ViewMilestones") or {}
        if not isinstance(perm, dict):
            perm = {}
        if not isinstance(vm, dict):
            vm = {}
        raw = perm.get("Milestone") or vm.get("Milestone")
        applied = _safe_to_datetime(vm.get("Submitted"))
        if applied is pd.NaT:
            applied = _safe_to_datetime(vm.get("Created"))
        issued = _safe_to_datetime(vm.get("Issued"))
        finaled = _safe_to_datetime(vm.get("Finaled"))
        return raw, applied, issued, finaled

    return None, pd.NaT, pd.NaT, pd.NaT


def _classify_schema(data_dict: Optional[dict]) -> str:
    family = _family(data_dict)
    if family in ("missing", "unknown"):
        return family

    _, applied, issued, finaled = _extract_fields(data_dict, family)
    has_applied = applied is not pd.NaT
    has_issued = issued is not pd.NaT
    has_final = finaled is not pd.NaT

    if has_issued and has_final:
        return f"{family}_issued_finaled"
    if has_issued:
        return f"{family}_issued"
    if has_final:
        return f"{family}_finaled"
    if has_applied:
        return f"{family}_applied"
    return f"{family}_status_only"


# ── Status mapping ───────────────────────────────────────────────────────────

# Case-insensitive raw portal status → STATUS_NORMALIZED.
_STATUS_MAP = {
    "finaled": "Final",
    "complete": "Final",
    "closed": "Final",
    "event completed": "Final",
    "issued": "Active",
    "open": "In Review",
    "under review": "In Review",
    "applied": "In Review",
    "received": "In Review",
    "submitted": "In Review",
    "approved pending payment": "In Review",
    "noc required": "In Review",
    "revisions pending": "In Review",
    "closed admin": "Inactive",
    "hb447 closed": "Inactive",
    "cancelled": "Inactive",
    "expired in viol": "Inactive",
    "expired": "Inactive",
    "void": "Inactive",
    "voided": "Inactive",
    "withdrawn": "Inactive",
    "abandoned/fbc ch1": "Inactive",
    "disapproved": "Inactive",
    "swo": "Inactive",
}

# Active only when an issuance date is present; otherwise In Review.
_ISSUANCE_GATED = {
    "approved",
}


def _expected_status(raw_status: Optional[str], issued) -> Optional[str]:
    if raw_status is None:
        return None
    key = str(raw_status).strip().lower()
    if not key:
        return None
    if key in _ISSUANCE_GATED:
        return "Active" if issued is not pd.NaT else "In Review"
    # Revisions Pending after issuance is still an active permit.
    if key == "revisions pending" and issued is not pd.NaT:
        return "Active"
    return _STATUS_MAP.get(key)


def _apply_status(repairs: dict, current, expected: Optional[str]) -> Optional[str]:
    """Apply expected STATUS_NORMALIZED; return effective status."""
    if expected is None:
        if pd.isna(current):
            return None
        return current

    if pd.isna(current):
        repairs["STATUS_NORMALIZED"] = expected
        repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"
    elif current != expected:
        repairs["STATUS_NORMALIZED"] = expected
        repairs["STATUS_NORMALIZED_FLAG"] = "FIXED"

    return repairs.get("STATUS_NORMALIZED", current)


# ── Per-record repair ───────────────────────────────────────────────────────

def _repair_record(row, d: dict, family: str, repairs: dict) -> None:
    raw_status, applied, issued, finaled = _extract_fields(d, family)
    expected = _expected_status(raw_status, issued)
    effective_status = _apply_status(repairs, row["STATUS_NORMALIZED"], expected)

    # -- FILE_DATE ← applied / Submitted (Created fallback already applied) --
    if applied is not pd.NaT:
        if pd.isna(row["FILE_DATE"]):
            repairs["FILE_DATE"] = applied
            repairs["FILE_DATE_FLAG"] = "FILLED"
        elif not _dates_equal(row["FILE_DATE"], applied):
            repairs["FILE_DATE"] = applied
            repairs["FILE_DATE_FLAG"] = "FIXED"

    # -- PERMIT_DATE ← issued --
    if issued is not pd.NaT:
        if pd.isna(row["PERMIT_DATE"]):
            if effective_status in ("Active", "Final"):
                repairs["PERMIT_DATE"] = issued
                repairs["PERMIT_DATE_FLAG"] = "FILLED"
        elif not _dates_equal(row["PERMIT_DATE"], issued):
            repairs["PERMIT_DATE"] = issued
            repairs["PERMIT_DATE_FLAG"] = "FIXED"

    # -- FINAL_DATE ← finaled (Final only); clear on non-Final --
    current_final = row["FINAL_DATE"]
    if effective_status == "Final":
        if finaled is not pd.NaT:
            if pd.isna(current_final):
                repairs["FINAL_DATE"] = finaled
                repairs["FINAL_DATE_FLAG"] = "FILLED"
            elif not _dates_equal(current_final, finaled):
                repairs["FINAL_DATE"] = finaled
                repairs["FINAL_DATE_FLAG"] = "FIXED"
    elif not pd.isna(current_final):
        repairs["FINAL_DATE"] = pd.NaT
        repairs["FINAL_DATE_FLAG"] = "FIXED"


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Lakeland permit records using information from the raw DATA JSON.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Lakeland".  Must contain
        columns STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, FINAL_DATE,
        and DATA.

    Returns
    -------
    pd.DataFrame
        Copy of *df* with corrected field values, an INFERRED_SCHEMA
        column naming the DATA JSON sub-schema identified for each
        record, and flag columns: STATUS_NORMALIZED_FLAG, FILE_DATE_FLAG,
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
        family = _family(d)
        if d is None or family in ("missing", "unknown"):
            continue

        repairs: dict = {}
        _repair_record(row, d, family, repairs)

        for key, value in repairs.items():
            out.at[idx, key] = value

    for col in ("FILE_DATE", "PERMIT_DATE", "FINAL_DATE"):
        out[col] = pd.to_datetime(out[col], errors="coerce")

    return out


# ── CLI: run standalone to preview repair stats ─────────────────────────────

if __name__ == "__main__":
    import os
    from dotenv import load_dotenv, find_dotenv

    load_dotenv(find_dotenv())
    MY_DATA_PATH = os.getenv("MY_DATA_PATH")
    AGENT_DATA_PATH = os.getenv("AGENT_DATA_PATH")
    filepath = os.path.join(MY_DATA_PATH, "processed_data", "permits_fl_sample.parquet")
    df = pd.read_parquet(filepath)
    city = df[df["JURISDICTION"] == "Lakeland"].copy()

    print(f"Lakeland records: {len(city):,}\n")

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

    print("\nFINAL_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FINAL_DATE"].notna().sum()
        pct = n_has / len(sub) if len(sub) else 0.0
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({pct:.1%})")

    print("\nPERMIT_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["PERMIT_DATE"].notna().sum()
        pct = n_has / len(sub) if len(sub) else 0.0
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({pct:.1%})")

    print("\nFILE_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FILE_DATE"].notna().sum()
        pct = n_has / len(sub) if len(sub) else 0.0
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({pct:.1%})")

    # Spot-check CLOSED ADMIN no longer Final
    n_admin_still_final = 0
    for idx in repaired.index:
        d = _safe_parse(repaired.at[idx, "DATA"])
        family = _family(d)
        if family in ("missing", "unknown"):
            continue
        raw, *_ = _extract_fields(d, family)
        if str(raw).strip().lower() == "closed admin":
            if repaired.at[idx, "STATUS_NORMALIZED"] == "Final":
                n_admin_still_final += 1
    print(f"\nCLOSED ADMIN still Final: {n_admin_still_final}")

    if AGENT_DATA_PATH:
        out_path = os.path.join(AGENT_DATA_PATH, "lakeland_repaired_sample.parquet")
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote repaired sample → {out_path}")

"""Data repair for South San Francisco (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

South San Francisco DATA is a single flat portal schema (all sample rows
share the same top-level keys: contacts, fees, inspections, permit_info,
search_data, site_info). Content variants (used as INFERRED_SCHEMA)
differ by which permit_info date fields are populated:

  - permit_info_full:          Applied + Issued + Finaled
  - permit_info_issued:        Applied + Issued (no Finaled)
  - permit_info_approved:      Applied + Approved (no Issued/Finaled)
  - permit_info_applied_only:  Applied only
  - permit_info_partial:       Issued/Approved/Finaled without Applied
  - permit_info_shell:         no usable Applied/Issued/Approved/Finaled
  - unknown / missing

Canonical mappings:
  - permit_info.PermitStatus       → STATUS_NORMALIZED
  - permit_info.PermitAppliedDate  → FILE_DATE
  - permit_info.PermitIssuedDate   → PERMIT_DATE
      (fallback: PermitApprovedDate)
  - permit_info.PermitFinaledDate  → FINAL_DATE
      (fallback for Final rows: latest inspection Completed date
       where Type contains FINAL and Result is APPROVED/PASSED/…)

``PermitExpirationDate`` is a permit-validity window, not a finaling /
completion date. ``search_data`` in this jurisdiction carries Address /
RECORDID / Permit Number only (no Application or Issued keys).

Known issues repaired:
  - STATUS_NORMALIZED stale vs PermitStatus (FINALED mislabeled Active /
    In Review; CANCELLED mislabeled Active; ACTIVE / ISSUED mislabeled
    In Review) → FIXED.
  - Rows with PermitFinaledDate but non-Final STATUS_NORMALIZED
    (including DEPOSIT RFND, ISSUED, CANCELLED, NON COMPLIANT,
    READY TO ISSUE) → Final.
  - Empty PermitStatus (legacy CRW shells) inferred from Finaled date,
    successful finaling inspection, Issued/Approved, or Applied →
    FILLED Final / Active / In Review.
  - SSF-specific portal labels: COMPLIANT → Final; NON COMPLIANT →
    Inactive; PLAN CHECK / UNDER REVIEW / CORRECTIONS / DEPOSIT RFND /
    BALANCE DUE / READY TO ISSUE / PENDING → In Review;
    NOT APPROVED → Inactive.
  - PERMIT_DATE missing on Active/Final when Issued empty but Approved
    is present → FILLED.
  - FINAL_DATE missing on Final rows when PermitFinaledDate empty but a
    finaling inspection exists → FILLED.
  - Spurious FINAL_DATE on non-Final rows with no finaled signal → cleared
    (normally avoided because Finaled-date rows are remapped to Final).

Not repairable from DATA:
  - FILE_DATE already matches PermitAppliedDate whenever Applied is
    present; 2 shells have neither Applied nor any other application
    date in search_data.
  - Many Active/Final rows (esp. COMPLIANT fire/occupancy inspections)
    lack both Issued and Approved → PERMIT_DATE stays missing.
  - Many Final COMPLIANT / FINALED rows lack PermitFinaledDate and a
    usable finaling inspection → FINAL_DATE stays missing.
"""

from __future__ import annotations

import json
import math
from datetime import date, datetime
from typing import Optional

import numpy as np
import pandas as pd


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
    """Uppercase PermitStatus / inspection Result / Type."""
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

# Normalized PermitStatus → STATUS_NORMALIZED
_STATUS_MAP = {
    "FINALED": "Final",
    "COMPLIANT": "Final",
    "CLOSED": "Final",
    "COMPLETE": "Final",
    "ISSUED": "Active",
    "ACTIVE": "Active",
    "APPROVED": "Active",
    "PENDING": "In Review",
    "READY TO ISSUE": "In Review",
    "PLAN CHECK": "In Review",
    "UNDER REVIEW": "In Review",
    "CORRECTIONS": "In Review",
    "DEPOSIT RFND": "In Review",
    "BALANCE DUE": "In Review",
    "EXPIRED": "Inactive",
    "CANCELLED": "Inactive",
    "CANCELED": "Inactive",
    "INACTIVE": "Inactive",
    "NON COMPLIANT": "Inactive",
    "NOT APPROVED": "Inactive",
    "VOID": "Inactive",
    "<NONE>": None,
    "": None,
}


def _map_permit_status(raw) -> Optional[str]:
    key = _normalize_status_key(raw)
    if key in _STATUS_MAP:
        return _STATUS_MAP[key]
    if "FINALED" in key or key in ("CLOSED", "COMPLETE", "COMPLETED", "COMPLIANT"):
        return "Final"
    if key in ("EXPIRED", "WITHDRAWN", "DENIED", "VOID", "INACTIVE", "NOT APPROVED") \
            or "CANCEL" in key or "NON COMPLIANT" in key:
        return "Inactive"
    if "PENDING" in key or "REVIEW" in key or "ROUTING" in key or "PLAN CHECK" in key \
            or "CORRECTION" in key or "BALANCE" in key or "DEPOSIT" in key:
        return "In Review"
    if key in ("ISSUED", "ACTIVE", "APPROVED") or "ISSUED" in key:
        return "Active"
    return None


# Inspection Result values treated as successful / completed when the Type
# itself is a final-* inspection.
_FINAL_INSP_OK_RESULTS = {
    "",
    "PASS",
    "PASSED",
    "APPROVED",
    "AP",
    "FINALED",
    "COMPLETE",
    "COMPLETED",
    "PARTIAL - SEE NOTES",
    "PARTIAL",
    "PARTIAL APPROVAL",
}


def _finaled_from_inspections(d: dict) -> Optional[date]:
    """Latest Completed date from a finaling inspection.

    Accepts either:
      - Result containing FINALED, or
      - Type containing FINAL with a successful / neutral Result.
        Failed / canceled / not-ready / FOLLOW UP admin sweeps ignored.
    """
    inspections = d.get("inspections")
    if not isinstance(inspections, list):
        return None
    dates = []
    for item in inspections:
        if not isinstance(item, dict):
            continue
        result = _normalize_status_key(item.get("Result"))
        typ = _normalize_status_key(item.get("Type"))
        if "FOLLOW" in typ:
            continue
        result_is_finaled = "FINALED" in result
        type_is_final = "FINAL" in typ
        if result_is_finaled:
            ok = True
        elif type_is_final and (
            result in _FINAL_INSP_OK_RESULTS or result.startswith("PARTIAL")
        ):
            ok = True
        else:
            ok = False
        if not ok:
            continue
        completed = _as_date(item.get("Completed"))
        if completed is not None:
            dates.append(completed)
    return max(dates) if dates else None


def _derive_status(pi: dict, d: dict) -> Optional[str]:
    """Map PermitStatus to STATUS_NORMALIZED; prefer Final when finaled.

    Empty / unmapped portal statuses are inferred from available dates
    and successful finaling inspections: Finaled or final insp → Final,
    Issued/Approved → Active, Applied-only → In Review.
    """
    status = _map_permit_status(pi.get("PermitStatus"))

    # A populated finaled date is stronger evidence of completion than a
    # stale ISSUED / DEPOSIT RFND / CANCELLED / empty portal label.
    if _as_date(pi.get("PermitFinaledDate")) is not None:
        return "Final"

    if status is not None:
        return status

    if _finaled_from_inspections(d) is not None:
        return "Final"
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
    return _as_date(_search_data(d).get("Application"))


def _preferred_permit_date(pi: dict, d: dict) -> Optional[date]:
    issued = _as_date(pi.get("PermitIssuedDate"))
    if issued is not None:
        return issued
    approved = _as_date(pi.get("PermitApprovedDate"))
    if approved is not None:
        return approved
    return _as_date(_search_data(d).get("Issued"))


def _preferred_final_date(pi: dict, d: dict) -> Optional[date]:
    finaled = _as_date(pi.get("PermitFinaledDate"))
    if finaled is not None:
        return finaled
    return _finaled_from_inspections(d)


# ── Per-record repair logic ─────────────────────────────────────────────────

def _repair_record(row, d: dict, repairs: dict):
    """Populate *repairs* with corrected values for a single SSF record."""
    pi = _permit_info(d)

    # -- STATUS_NORMALIZED --
    current_status = row["STATUS_NORMALIZED"]
    expected = _derive_status(pi, d)
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
    if preferred_final is not None:
        if current_final is None:
            if effective_status == "Final":
                repairs["FINAL_DATE"] = pd.Timestamp(preferred_final)
                repairs["FINAL_DATE_FLAG"] = "FILLED"
        elif current_final != preferred_final:
            repairs["FINAL_DATE"] = pd.Timestamp(preferred_final)
            repairs["FINAL_DATE_FLAG"] = "FIXED"
    elif current_final is not None and effective_status != "Final":
        # Clear final dates on non-Final rows when DATA has no finaled signal.
        repairs["FINAL_DATE"] = pd.NaT
        repairs["FINAL_DATE_FLAG"] = "FIXED"


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    South San Francisco permit records using information from the raw DATA
    JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "South San Francisco".  Must
        contain columns STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE,
        FINAL_DATE, and DATA.

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
    city = df[(df["JURISDICTION"] == "South San Francisco") & (df["STATE"] == "CA")].copy()

    print(f"South San Francisco records: {len(city):,}\n")

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
    print(f"  {n_has:>4,} / {len(repaired):>4,} ({n_has / len(repaired):.1%})")

    # Chronology checks (normalize to Timestamp — FILE may be date vs Timestamp)
    chk = repaired.copy()
    for col in ("FILE_DATE", "PERMIT_DATE", "FINAL_DATE"):
        chk[col] = pd.to_datetime(chk[col], errors="coerce")
    both_fp = chk["FILE_DATE"].notna() & chk["PERMIT_DATE"].notna()
    n_fp_bad = (chk.loc[both_fp, "FILE_DATE"] > chk.loc[both_fp, "PERMIT_DATE"]).sum()
    both_pf = chk["PERMIT_DATE"].notna() & chk["FINAL_DATE"].notna()
    n_pf_bad = (chk.loc[both_pf, "PERMIT_DATE"] > chk.loc[both_pf, "FINAL_DATE"]).sum()
    print(f"\nChronology: FILE>PERMIT={n_fp_bad}, PERMIT>FINAL={n_pf_bad}")

    # Status change detail
    print("\nSTATUS changes (before → after):")
    before = city["STATUS_NORMALIZED"].fillna("(nan)").astype(str)
    after = repaired["STATUS_NORMALIZED"].fillna("(nan)").astype(str)
    changed = before != after
    if changed.any():
        ct = pd.crosstab(before[changed], after[changed])
        print(ct.to_string())
    else:
        print("  (none)")

    if AGENT_DATA_PATH:
        out_dir = os.path.join(AGENT_DATA_PATH, "repaired")
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, "permits_ca_south_san_francisco_repaired.parquet")
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote repaired sample to {out_path}")

"""Data repair for Orange (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Orange DATA is a uniform GIS / open-data scrape. Every row has the same
top-level keys (``contacts``, ``fees``, ``inspections``, ``permit_info``,
``search_data``, ``site_info``). Content variants used as INFERRED_SCHEMA
differ by which ``permit_info`` dates are populated and whether
inspections are present:

  - permit_info_complete:     Applied + Issued + Finaled
  - permit_info_issued:       Applied + Issued (no Finaled)
  - permit_info_application:  Applied only
  - permit_info_partial:      missing Applied but other dates present
  - permit_info_empty:        no usable permit_info dates
  - unknown / missing

Optional ``_insp`` suffix when ``inspections`` is a non-empty list.

Canonical mappings:
  - permit_info.PermitStatus       → STATUS_NORMALIZED
      (ISSUED / APPROVED / PO OPEN with a true PermitFinaledDate
       upgrade to Final)
  - permit_info.PermitAppliedDate  → FILE_DATE
  - permit_info.PermitIssuedDate   → PERMIT_DATE
      (fallback: PermitApprovedDate)
  - permit_info.PermitFinaledDate  → FINAL_DATE
      (fallback for Final rows: latest finaling inspection Completed)

Known issues repaired:
  - STATUS_NORMALIZED disagrees with PermitStatus (ISSUED→In Review,
    FINALED→Active) and stale ISSUED rows that carry a real FinaledDate
    → FIXED to Active / Final.
  - PO OPEN (issued, still open) mis-normalized as In Review → FIXED
    to Active.
  - Active/Final rows missing PERMIT_DATE despite Issued / Approved →
    FILLED.
  - Final rows missing FINAL_DATE despite FinaledDate (or a finaling
    inspection) → FILLED; spurious FINAL_DATE on non-Final rows →
    cleared.

Not repairable from DATA:
  - 3 FILE_DATE gaps (empty PermitAppliedDate; fee Paid Date is not
    used as an application-date proxy).
  - A handful of Final / Active rows lack both Issued and Approved, or
    lack FinaledDate and finaling inspections.
"""

from __future__ import annotations

import json
import math
from datetime import date, datetime
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
    """Parse a date value, returning pd.NaT on failure or implausible year."""
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return pd.NaT
    if isinstance(val, str) and not str(val).strip():
        return pd.NaT
    if isinstance(val, str) and str(val).strip().upper() == "TBD":
        return pd.NaT
    try:
        dt = pd.to_datetime(val)
    except (ValueError, TypeError):
        return pd.NaT
    if dt is pd.NaT or pd.isna(dt):
        return pd.NaT
    if getattr(dt, "tzinfo", None) is not None:
        dt = dt.tz_convert("UTC").tz_localize(None)
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


def _permit_info(d: dict) -> dict:
    pi = d.get("permit_info")
    return pi if isinstance(pi, dict) else {}


def _normalize_status_key(raw) -> str:
    if raw is None:
        return ""
    return str(raw).strip().upper()


def _has_inspections(d: dict) -> bool:
    insp = d.get("inspections")
    return isinstance(insp, list) and len(insp) > 0


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
    has_any_other = has_issued or has_approved or has_finaled

    has_issuance = has_issued or has_approved
    if has_applied and has_issuance and has_finaled:
        base = "permit_info_complete"
    elif has_applied and has_issuance:
        base = "permit_info_issued"
    elif has_applied and not has_any_other:
        base = "permit_info_application"
    elif has_any_other and (not has_applied or not has_issuance):
        # Missing applied, or applied+finaled without issuance dates.
        base = "permit_info_partial"
    else:
        base = "permit_info_empty"

    if _has_inspections(data_dict):
        return f"{base}_insp"
    return base


# ── Status mapping ──────────────────────────────────────────────────────────

# PermitStatus (uppercased) → STATUS_NORMALIZED
_STATUS_MAP = {
    # Final
    "FINALED": "Final",
    "FINALIZED": "Final",
    "FINAL": "Final",
    "CLOSED": "Final",
    # Active — issued / approved / open permit
    "ISSUED": "Active",
    "APPROVED": "Active",
    "PO OPEN": "Active",
    # In Review — application / plan check
    "SUBMITTED": "In Review",
    "PC OPEN": "In Review",
    "CORRECTIONS": "In Review",
    "UNDER REVIEW": "In Review",
    "HOLD": "In Review",
    # Inactive
    "EXPIRED": "Inactive",
    "EXPIRE": "Inactive",
    "CANCELLED": "Inactive",
    "CANCEL": "Inactive",
    "WITHDRAWN": "Inactive",
}


def _map_permit_status(raw) -> Optional[str]:
    key = _normalize_status_key(raw)
    if key in _STATUS_MAP:
        return _STATUS_MAP[key]
    if not key:
        return None
    if "FINAL" in key or key == "CLOSED":
        return "Final"
    if "EXPIRE" in key or "CANCEL" in key or "WITHDRAW" in key:
        return "Inactive"
    if "ISSUE" in key or "APPROV" in key:
        return "Active"
    return None


def _has_true_finaled(pi: dict) -> bool:
    return _as_date(pi.get("PermitFinaledDate")) is not None


def _derive_status(pi: dict) -> Optional[str]:
    """Map PermitStatus; upgrade stale Active labels when FinaledDate set.

    Inactive labels stay Inactive even if PermitFinaledDate is populated.
    In Review labels stay In Review (plan-check / submittal is not a
    sign-off). ISSUED / APPROVED / PO OPEN (or blank) with a FinaledDate
    are remapped to Final.
    """
    mapped = _map_permit_status(pi.get("PermitStatus"))

    if mapped == "Inactive":
        return "Inactive"
    if mapped == "In Review":
        return "In Review"
    if mapped == "Final":
        return "Final"

    # Active or unmapped/blank: upgrade to Final when FinaledDate present.
    if _has_true_finaled(pi):
        return "Final"

    if mapped is not None:
        return mapped

    if _as_date(pi.get("PermitIssuedDate")) is not None:
        return "Active"
    if _as_date(pi.get("PermitApprovedDate")) is not None:
        return "Active"
    if _as_date(pi.get("PermitAppliedDate")) is not None:
        return "In Review"
    return None


def _preferred_file_date(pi: dict) -> Optional[date]:
    return _as_date(pi.get("PermitAppliedDate"))


def _preferred_permit_date(pi: dict) -> Optional[date]:
    issued = _as_date(pi.get("PermitIssuedDate"))
    if issued is not None:
        return issued
    return _as_date(pi.get("PermitApprovedDate"))


_FINAL_INSP_OK_RESULTS = {
    "",
    "PASSED",
    "APPROVED",
    "AP",
    "FINAL",
    "FINALED",
    "CLEARED",
    "PARTIAL",
}


def _finaled_from_inspections(d: dict) -> Optional[date]:
    """Latest Completed date from a finaling inspection."""
    inspections = d.get("inspections")
    if not isinstance(inspections, list):
        return None
    dates = []
    for item in inspections:
        if not isinstance(item, dict):
            continue
        result = _normalize_status_key(item.get("Result"))
        typ = _normalize_status_key(item.get("Type"))
        result_is_final = result in {"FINAL", "FINALED"} or "FINALED" in result
        type_is_final = "FINAL" in typ
        if result_is_final:
            ok = True
        elif type_is_final and result in _FINAL_INSP_OK_RESULTS:
            ok = True
        else:
            ok = False
        if not ok:
            continue
        completed = _as_date(item.get("Completed"))
        if completed is not None:
            dates.append(completed)
    return max(dates) if dates else None


def _preferred_final_date(pi: dict, d: dict) -> Optional[date]:
    finaled = _as_date(pi.get("PermitFinaledDate"))
    if finaled is not None:
        return finaled
    return _finaled_from_inspections(d)


# ── Per-record repair logic ─────────────────────────────────────────────────

def _repair_record(row, d: dict, repairs: dict):
    """Populate *repairs* with corrected values for a single Orange record."""
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
    preferred_fd = _preferred_file_date(pi)
    current_fd = _as_date(row["FILE_DATE"])
    if preferred_fd is not None:
        if current_fd is None:
            repairs["FILE_DATE"] = pd.Timestamp(preferred_fd)
            repairs["FILE_DATE_FLAG"] = "FILLED"
        elif current_fd != preferred_fd:
            repairs["FILE_DATE"] = pd.Timestamp(preferred_fd)
            repairs["FILE_DATE_FLAG"] = "FIXED"

    # -- PERMIT_DATE --
    preferred_pd = _preferred_permit_date(pi)
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
    Orange permit records using information from the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Orange".  Must contain
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
    filepath = os.path.join(
        MY_DATA_PATH, "processed_data", "permits_ca_sample.parquet"
    )
    df = pd.read_parquet(filepath)
    city = df[df["JURISDICTION"] == "Orange"].copy()

    print(f"Orange records: {len(city):,}\n")

    repaired = data_repair(city)

    print("INFERRED_SCHEMA:")
    for s, c in repaired["INFERRED_SCHEMA"].value_counts(dropna=False).items():
        print(f"  {str(s):35s}: {c:>4,}")
    print()

    for field in ["STATUS_NORMALIZED", "FILE_DATE", "PERMIT_DATE", "FINAL_DATE"]:
        flag_col = f"{field}_FLAG"
        n_filled = (repaired[flag_col] == "FILLED").sum()
        n_fixed = (repaired[flag_col] == "FIXED").sum()
        print(f"{field}:")
        print(f"  FILLED: {n_filled:>4,}   FIXED: {n_fixed:>4,}")

        before_missing = city[field].isna().sum()
        after_missing = repaired[field].isna().sum()
        print(
            f"  Missing before: {before_missing:>4,}   "
            f"Missing after: {after_missing:>4,}"
        )
        print()

    print("STATUS_NORMALIZED distribution:")
    print("  Before:")
    for s, c in city["STATUS_NORMALIZED"].value_counts(dropna=False).items():
        print(f"    {str(s):15s}: {c:>4,}")
    print("  After:")
    for s, c in repaired["STATUS_NORMALIZED"].value_counts(dropna=False).items():
        print(f"    {str(s):15s}: {c:>4,}")

    print("\nStatus FIXED transitions (raw PermitStatus → before → after):")
    fixed = repaired[repaired["STATUS_NORMALIZED_FLAG"] == "FIXED"]
    from collections import Counter

    transitions = Counter()
    for idx in fixed.index:
        pi = _permit_info(_safe_parse(city.loc[idx, "DATA"]))
        transitions[
            (
                pi.get("PermitStatus"),
                city.loc[idx, "STATUS_NORMALIZED"],
                repaired.loc[idx, "STATUS_NORMALIZED"],
            )
        ] += 1
    for (raw, before, after), c in transitions.most_common():
        print(f"  {raw!s:15s}  {before!s:12s} → {after!s:12s}: {c}")

    print("\nPERMIT_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["PERMIT_DATE"].notna().sum()
        pct = n_has / len(sub) if len(sub) else 0.0
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({pct:.1%})")

    print("\nFINAL_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FINAL_DATE"].notna().sum()
        pct = n_has / len(sub) if len(sub) else 0.0
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({pct:.1%})")

    print("\nRemaining Active/Final PERMIT_DATE gaps by PermitStatus:")
    gaps = Counter()
    for idx in repaired.index:
        if repaired.at[idx, "STATUS_NORMALIZED"] not in ("Active", "Final"):
            continue
        if pd.notna(repaired.at[idx, "PERMIT_DATE"]):
            continue
        pi = _permit_info(_safe_parse(city.loc[idx, "DATA"]))
        gaps[
            (
                repaired.at[idx, "STATUS_NORMALIZED"],
                _normalize_status_key(pi.get("PermitStatus")),
            )
        ] += 1
    for k, c in gaps.most_common(20):
        print(f"  {k}: {c}")

    print("\nRemaining Final FINAL_DATE gaps by PermitStatus:")
    gaps = Counter()
    for idx in repaired.index:
        if repaired.at[idx, "STATUS_NORMALIZED"] != "Final":
            continue
        if pd.notna(repaired.at[idx, "FINAL_DATE"]):
            continue
        pi = _permit_info(_safe_parse(city.loc[idx, "DATA"]))
        gaps[_normalize_status_key(pi.get("PermitStatus"))] += 1
    for k, c in gaps.most_common(20):
        print(f"  {k}: {c}")

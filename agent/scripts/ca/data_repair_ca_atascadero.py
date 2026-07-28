"""Data repair for Atascadero (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Atascadero DATA is a civic portal payload. All sample rows share the
same top-level keys: ``fees``, ``contacts``, ``site_info``,
``inspections``, ``permit_info``, ``search_data``. Canonical fields live
under ``permit_info`` (with ``search_data`` as a partial mirror for
Issued / Approved / Permit Status on ~60% of rows):

  - PermitStatus                          → STATUS_NORMALIZED
  - PermitAppliedDate                     → FILE_DATE
  - PermitIssuedDate (fallback:
    PermitApprovedDate / SD Issued Date /
    SD Approved Date)                     → PERMIT_DATE
  - PermitFinaledDate                     → FINAL_DATE

Content variants (same keys; differ by which fields are populated):

  - permit_info_issued_finaled: Issued + Finaled present
  - permit_info_issued:         Issued present, Finaled blank
  - permit_info_finaled_only:   Finaled present, Issued blank
  - permit_info_approved_only:  Approved present, Issued/Finaled blank
  - permit_info_applied_only:   only Applied populated

Known issues repaired:
  - STATUS_NORMALIZED was derived from STATUS_ORIGINAL, which often
    mirrors a stale search_data ``Permit Status`` (or an older snapshot)
    rather than live permit_info.PermitStatus. FINALED / ISSUED rows
    labeled Active or In Review → FIXED to Final / Active. Rows with a
    PermitFinaledDate (non-inactive) are treated as Final.
  - Active/Final missing PERMIT_DATE when Issued blank but Approved
    present → FILLED from Approved (~35 rows).
  - Final missing FINAL_DATE when PermitFinaledDate exists (often after
    status FIXED from Active/In Review) → FILLED.
  - Spurious FINAL_DATE on non-Final rows → cleared (FIXED).

Not repairable / left as-is:
  - FILE_DATE already matches PermitAppliedDate for all sample rows.
  - ~20 FINALED rows lack PermitFinaledDate and have empty inspections
    → FINAL_DATE stays missing.
  - Active/Final rows with neither Issued nor Approved → PERMIT_DATE
    stays missing.
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
    """Parse a date value, returning pd.NaT on failure."""
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


def _search_data(d: dict) -> dict:
    sd = d.get("search_data")
    return sd if isinstance(sd, dict) else {}


def _pi_date(d: dict, *keys: str):
    pi = _permit_info(d)
    for key in keys:
        dt = _safe_to_datetime(pi.get(key))
        if dt is not pd.NaT:
            return dt
    return pd.NaT


def _sd_date(d: dict, *keys: str):
    sd = _search_data(d)
    for key in keys:
        dt = _safe_to_datetime(sd.get(key))
        if dt is not pd.NaT:
            return dt
    return pd.NaT


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())
    if "permit_info" not in keys:
        return "unknown"
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


# ── Status mapping ──────────────────────────────────────────────────────────

# PermitStatus (uppercased) → STATUS_NORMALIZED
_STATUS_MAP = {
    "FINALED": "Final",
    "CLOSED": "Final",
    "ISSUED": "Active",
    "APPROVED": "Active",
    "RECEIVED": "In Review",
    "READY TO ISSUE": "In Review",
    "PERMIT PREP": "In Review",
    "OUT FOR CORRECTION": "In Review",
    "OUT FOR CORRECTIONS": "In Review",
    "CORRECTIONS READY": "In Review",
    "PENDING": "In Review",
    "APPLICATION": "In Review",
    "UNDER REVIEW": "In Review",
    "EXPIRED": "Inactive",
    "WITHDRAWN": "Inactive",
    "VOID": "Inactive",
    "CANCELLED": "Inactive",
    "CANCELED": "Inactive",
}

# Terminal inactive labels: PermitFinaledDate on these is a close/void
# timestamp, not evidence the permit should be treated as Final.
_INACTIVE_KEEP = {
    "EXPIRED",
    "WITHDRAWN",
    "VOID",
    "CANCELLED",
    "CANCELED",
}


def _normalize_status_key(raw) -> str:
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return ""
    return str(raw).strip().upper()


def _derive_status(d: dict) -> Optional[str]:
    """Map PermitStatus; prefer Final when a non-inactive row is finaled.

    Canonical source is permit_info.PermitStatus (live civic status),
    not the often-stale search_data / STATUS_ORIGINAL mirror.
    """
    pi = _permit_info(d)
    raw = _normalize_status_key(pi.get("PermitStatus"))

    status = _STATUS_MAP.get(raw) if raw else None

    if raw in _INACTIVE_KEEP:
        return status or "Inactive"

    finaled = _pi_date(d, "PermitFinaledDate")
    if finaled is not pd.NaT:
        return "Final"

    if status is not None:
        return status

    if raw:
        if "FINAL" in raw or raw == "CLOSED":
            return "Final"
        if "EXPIRE" in raw or "VOID" in raw or "CANCEL" in raw or "WITHDRAW" in raw:
            return "Inactive"
        if "ISSUE" in raw or "APPROV" in raw:
            return "Active"
        if (
            "REVIEW" in raw
            or "RECEIV" in raw
            or "PENDING" in raw
            or "PREP" in raw
            or "CORRECT" in raw
            or "APPLICATION" in raw
        ):
            return "In Review"
        return None

    return None


def _preferred_permit_date(d: dict):
    issued = _pi_date(d, "PermitIssuedDate")
    if issued is pd.NaT:
        issued = _sd_date(d, "Issued Date")
    if issued is not pd.NaT:
        return issued
    approved = _pi_date(d, "PermitApprovedDate")
    if approved is pd.NaT:
        approved = _sd_date(d, "Approved Date")
    return approved


def _preferred_file_date(d: dict):
    return _pi_date(d, "PermitAppliedDate")


def _preferred_final_date(d: dict):
    return _pi_date(d, "PermitFinaledDate")


# ── Per-record repair logic ─────────────────────────────────────────────────

def _repair_record(row, d: dict, repairs: dict):
    """Populate *repairs* with corrected values for a single Atascadero record."""
    # -- STATUS_NORMALIZED --
    current_status = row["STATUS_NORMALIZED"]
    expected = _derive_status(d)
    if expected is not None:
        if pd.isna(current_status):
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"
        elif current_status != expected:
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FIXED"

    effective_status = repairs.get("STATUS_NORMALIZED", current_status)

    # -- FILE_DATE (application / PermitAppliedDate) --
    applied = _preferred_file_date(d)
    if applied is not pd.NaT:
        if pd.isna(row["FILE_DATE"]):
            repairs["FILE_DATE"] = applied
            repairs["FILE_DATE_FLAG"] = "FILLED"
        elif not _dates_equal(row["FILE_DATE"], applied):
            repairs["FILE_DATE"] = applied
            repairs["FILE_DATE_FLAG"] = "FIXED"

    # -- PERMIT_DATE (issuance; fallback Approved) --
    issued = _pi_date(d, "PermitIssuedDate")
    if issued is pd.NaT:
        issued = _sd_date(d, "Issued Date")
    permit_src = _preferred_permit_date(d)

    if not pd.isna(row["PERMIT_DATE"]):
        if issued is not pd.NaT and not _dates_equal(row["PERMIT_DATE"], issued):
            repairs["PERMIT_DATE"] = issued
            repairs["PERMIT_DATE_FLAG"] = "FIXED"
    elif effective_status in ("Active", "Final") and permit_src is not pd.NaT:
        repairs["PERMIT_DATE"] = permit_src
        repairs["PERMIT_DATE_FLAG"] = "FILLED"

    # -- FINAL_DATE --
    preferred_final = _preferred_final_date(d)
    current_final = row["FINAL_DATE"]

    if effective_status == "Final":
        if preferred_final is not pd.NaT:
            if pd.isna(current_final):
                repairs["FINAL_DATE"] = preferred_final
                repairs["FINAL_DATE_FLAG"] = "FILLED"
            elif not _dates_equal(current_final, preferred_final):
                repairs["FINAL_DATE"] = preferred_final
                repairs["FINAL_DATE_FLAG"] = "FIXED"
    elif not pd.isna(current_final):
        # Spurious FINAL_DATE on non-Final rows.
        repairs["FINAL_DATE"] = pd.NaT
        repairs["FINAL_DATE_FLAG"] = "FIXED"


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Atascadero permit records using information from the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Atascadero".  Must contain
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
    city = df[(df["JURISDICTION"] == "Atascadero") & (df["STATE"] == "CA")].copy()

    print(f"Atascadero records: {len(city):,}\n")

    repaired = data_repair(city)

    if AGENT_DATA_PATH:
        out_path = os.path.join(AGENT_DATA_PATH, "atascadero_repaired_sample.parquet")
        repaired.to_parquet(out_path, index=False)
        print(f"Wrote {out_path}\n")

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
    print(repaired["STATUS_NORMALIZED_FLAG"].value_counts(dropna=False).to_string())

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

"""Data repair for Morgan Hill (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Morgan Hill DATA is a civic portal payload (same shape as El Segundo /
Brentwood / San Carlos). All sample rows share top-level keys:
``fees``, ``contacts``, ``site_info``, ``inspections``,
``permit_info``, ``search_data``. Canonical fields live under
``permit_info``:

  - PermitStatus                          → STATUS_NORMALIZED
  - PermitAppliedDate                     → FILE_DATE
  - PermitIssuedDate (fallback:
    PermitApprovedDate)                   → PERMIT_DATE
  - PermitFinaledDate (fallback: latest
    approved final inspection)            → FINAL_DATE

Content variants (INFERRED_SCHEMA) when DATA is present:

  - permit_info_issued_finaled: Issued + Finaled present
  - permit_info_issued:         Issued present, Finaled blank
  - permit_info_finaled_only:   Finaled present, Issued blank
  - permit_info_approved_only:  Approved present, Issued/Finaled blank
  - permit_info_applied_only:   only Applied populated
  - permit_info_empty_dates:    status text, no usable dates
  - legacy_no_status:           blank PermitStatus but dates present
  - permit_info_empty_dates (blank status, no dates): conversion
    shells (mostly BLD ARCHIVE / OVERSIZE) with a 2016 migration
    stamp in PermitNotes — not a real application date

Known issues repaired:
  - 6 FINALED rows previously mapped to Active (FINAL_DATE also
    missing despite PermitFinaledDate) → FIXED to Final + fill
    FINAL_DATE.
  - 1 ISSUED and 1 APPROVED row previously mapped to In Review →
    FIXED to Active.
  - Blank PermitStatus with Issued/Approved → Active; with Applied
    only → In Review (FILLED).
  - Active/Final missing PERMIT_DATE when Issued is empty but
    Approved is present → FILLED from PermitApprovedDate.

Not repairable / left as-is:
  - ~266 blank-status conversion shells with no Applied/Issued/
    Approved/Finaled dates (PermitNotes leading date is a 5/10/2016
    migration stamp, not FILE_DATE).
  - ~270 rows missing FILE_DATE with no PermitAppliedDate (Issued /
    Finaled alone are not used as application-date proxies).
  - FINALED rows lacking PermitFinaledDate and a passed final
    inspection → FINAL_DATE stays missing.
  - Final rows with neither Issued nor Approved → PERMIT_DATE stays
    missing (Finaled is not used as an issuance proxy).
  - PermitExpirationDate is a validity window, not completion.
"""

from __future__ import annotations

import json
import math
import re
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
    """Parse a date value as UTC, returning pd.NaT on failure."""
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


def _dates_equal(a, b) -> bool:
    """Compare two datelike values at calendar-day resolution (UTC)."""
    da = _safe_to_datetime(a)
    db = _safe_to_datetime(b)
    if da is pd.NaT or db is pd.NaT:
        return False
    return da.date() == db.date()


def _permit_info(d: dict) -> dict:
    pi = d.get("permit_info")
    return pi if isinstance(pi, dict) else {}


def _pi_date(d: dict, *keys: str):
    pi = _permit_info(d)
    for key in keys:
        dt = _safe_to_datetime(pi.get(key))
        if dt is not pd.NaT:
            return dt
    return pd.NaT


def _normalize_status_key(raw) -> str:
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return ""
    s = str(raw).strip().upper()
    if s in {"<NONE>", "NONE", "NULL", "N/A"}:
        return ""
    return s


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())
    if "permit_info" not in keys:
        return "unknown"

    pi = _permit_info(data_dict)
    if not pi:
        return "permit_info_empty"

    raw_status = _normalize_status_key(pi.get("PermitStatus"))
    has_issued = _safe_to_datetime(pi.get("PermitIssuedDate")) is not pd.NaT
    has_finaled = _safe_to_datetime(pi.get("PermitFinaledDate")) is not pd.NaT
    has_approved = _safe_to_datetime(pi.get("PermitApprovedDate")) is not pd.NaT
    has_applied = _safe_to_datetime(pi.get("PermitAppliedDate")) is not pd.NaT

    if not raw_status:
        if has_issued or has_finaled or has_approved or has_applied:
            return "legacy_no_status"
        return "permit_info_empty_dates"

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
    # Final
    "FINALED": "Final",
    "FINAL": "Final",
    # Active
    "ISSUED": "Active",
    "APPROVED": "Active",
    # In Review
    "RECEIVED": "In Review",
    "UNDER REVIEW": "In Review",
    "SUBMITTED": "In Review",
    # Inactive
    "EXPIRED": "Inactive",
    "CANCELED": "Inactive",
    "CANCELLED": "Inactive",
    "VOID": "Inactive",
    "DENIED": "Inactive",
    "WITHDRAWN": "Inactive",
}

# Terminal inactive labels: do not promote to Final even if a FinaledDate
# stamp is present (none observed in sample, but keep the guard).
_INACTIVE_KEEP = {
    "EXPIRED",
    "CANCELED",
    "CANCELLED",
    "VOID",
    "DENIED",
    "WITHDRAWN",
}

_FINAL_INSP_OK = {
    "",
    "PASS",
    "PASSED",
    "APPROVED",
    "FINAL",
    "FINALED",
    "COMPLETED",
    "COMPLETE",
    "OK",
}

_FINAL_TITLE_RE = re.compile(
    r"(?i)("
    r"\*{0,2}\s*final|"
    r"certificate\s*of\s*occup|"
    r"c\s*of\s*o"
    r")"
)


def _lookup_status(raw: str) -> Optional[str]:
    if not raw:
        return None
    if raw in _STATUS_MAP:
        return _STATUS_MAP[raw]
    if "CANCEL" in raw or raw.startswith("VOID"):
        return "Inactive"
    if "EXPIRE" in raw:
        return "Inactive"
    if "WITHDRAW" in raw or "DENIED" in raw:
        return "Inactive"
    if raw.startswith("FINAL"):
        return "Final"
    if raw.startswith("ISSUED") or "APPROV" in raw:
        return "Active"
    if "REVIEW" in raw or "RECEIVED" in raw or "SUBMIT" in raw:
        return "In Review"
    return None


def _is_inactive_keep(raw: str) -> bool:
    if not raw:
        return False
    if raw in _INACTIVE_KEEP:
        return True
    if "EXPIRE" in raw or "CANCEL" in raw or raw.startswith("VOID"):
        return True
    if "WITHDRAW" in raw or "DENIED" in raw:
        return True
    return False


def _derive_status(d: dict) -> Optional[str]:
    """Map PermitStatus; prefer Final when a non-inactive row is finaled."""
    pi = _permit_info(d)
    raw = _normalize_status_key(pi.get("PermitStatus"))
    status = _lookup_status(raw)

    if _is_inactive_keep(raw):
        return status or "Inactive"

    finaled = _pi_date(d, "PermitFinaledDate")
    if finaled is not pd.NaT:
        return "Final"

    if status is not None:
        return status

    if raw:
        return None

    # Blank status: infer from dates (legacy encroachment / archive shells).
    issued = _pi_date(d, "PermitIssuedDate")
    approved = _pi_date(d, "PermitApprovedDate")
    applied = _pi_date(d, "PermitAppliedDate")

    if issued is not pd.NaT or approved is not pd.NaT:
        return "Active"
    if applied is not pd.NaT:
        return "In Review"
    return None


def _result_ok(result: str) -> bool:
    result_u = result.strip().upper()
    if result_u in _FINAL_INSP_OK:
        return True
    if result_u.startswith("PASS") or result_u.startswith("APPROV"):
        return True
    return False


def _is_final_inspection(item: dict) -> bool:
    typ = str(item.get("Type") or item.get("Title") or "").strip()
    result = str(item.get("Result") or "").strip()
    result_u = result.upper()

    if result_u in ("FINAL", "FINALED"):
        return True
    if _FINAL_TITLE_RE.search(typ) and _result_ok(result):
        return True
    return False


def _final_from_inspections(d: dict):
    """Latest completion date from an approved final inspection."""
    inspections = d.get("inspections")
    if not isinstance(inspections, list):
        return pd.NaT
    dates = []
    for item in inspections:
        if not isinstance(item, dict):
            continue
        if not _is_final_inspection(item):
            continue
        completed = _safe_to_datetime(item.get("Completed"))
        if completed is pd.NaT:
            completed = _safe_to_datetime(item.get("Scheduled Date"))
        if completed is not pd.NaT:
            dates.append(completed)
    return max(dates) if dates else pd.NaT


def _preferred_file_date(d: dict):
    """Application / submittal date from PermitAppliedDate only.

    Do not fall back to PermitNotes — leading timestamps on blank-status
    archive rows are a 2016 conversion stamp, not the application date.
    """
    return _pi_date(d, "PermitAppliedDate")


def _preferred_permit_date(d: dict):
    issued = _pi_date(d, "PermitIssuedDate")
    if issued is not pd.NaT:
        return issued
    return _pi_date(d, "PermitApprovedDate")


def _preferred_final_date(d: dict):
    finaled = _pi_date(d, "PermitFinaledDate")
    if finaled is not pd.NaT:
        return finaled
    return _final_from_inspections(d)


# ── Per-record repair logic ─────────────────────────────────────────────────

def _repair_record(row, d: dict, repairs: dict):
    """Populate *repairs* with corrected values for a single Morgan Hill record."""
    current_status = row["STATUS_NORMALIZED"]
    expected = _derive_status(d)

    # -- STATUS_NORMALIZED --
    if expected is not None:
        if pd.isna(current_status):
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"
        elif current_status != expected:
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FIXED"

    effective_status = repairs.get("STATUS_NORMALIZED", current_status)

    # -- FILE_DATE --
    preferred_fd = _preferred_file_date(d)
    if preferred_fd is not pd.NaT:
        if pd.isna(row["FILE_DATE"]):
            repairs["FILE_DATE"] = preferred_fd
            repairs["FILE_DATE_FLAG"] = "FILLED"
        elif not _dates_equal(row["FILE_DATE"], preferred_fd):
            repairs["FILE_DATE"] = preferred_fd
            repairs["FILE_DATE_FLAG"] = "FIXED"

    # -- PERMIT_DATE --
    preferred_pd = _preferred_permit_date(d)
    if not pd.isna(row["PERMIT_DATE"]):
        if preferred_pd is not pd.NaT and not _dates_equal(
            row["PERMIT_DATE"], preferred_pd
        ):
            repairs["PERMIT_DATE"] = preferred_pd
            repairs["PERMIT_DATE_FLAG"] = "FIXED"
    elif effective_status in ("Active", "Final") and preferred_pd is not pd.NaT:
        repairs["PERMIT_DATE"] = preferred_pd
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
        repairs["FINAL_DATE"] = pd.NaT
        repairs["FINAL_DATE_FLAG"] = "FIXED"


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Morgan Hill permit records using information from the raw DATA JSON
    column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Morgan Hill".  Must contain
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
        _repair_record(row, d, repairs)

        for key, value in repairs.items():
            out.at[idx, key] = value

    for col in ("FILE_DATE", "PERMIT_DATE", "FINAL_DATE"):
        if col in out.columns:
            out[col] = pd.to_datetime(out[col], utc=True, errors="coerce")

    return out


# ── CLI: run standalone to preview repair stats ─────────────────────────────

if __name__ == "__main__":
    import os
    from pathlib import Path

    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[3] / ".env")
    MY_DATA_PATH = os.getenv("MY_DATA_PATH")
    AGENT_DATA_PATH = os.getenv("AGENT_DATA_PATH")
    filepath = os.path.join(
        MY_DATA_PATH, "processed_data", "permits_ca_sample.parquet"
    )
    df = pd.read_parquet(filepath)
    city = df[
        (df["JURISDICTION"] == "Morgan Hill") & (df["STATE"] == "CA")
    ].copy()

    print(f"Morgan Hill records: {len(city):,}\n")

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

    print("\nStatus transitions (before → after):")
    mask = repaired["STATUS_NORMALIZED_FLAG"].notna()
    if mask.any():
        transitions = (
            pd.DataFrame({
                "before": city.loc[mask, "STATUS_NORMALIZED"].astype(str),
                "after": repaired.loc[mask, "STATUS_NORMALIZED"].astype(str),
            })
            .value_counts()
            .reset_index(name="n")
        )
        for _, trow in transitions.iterrows():
            print(f"  {trow['before']:15s} → {trow['after']:15s}: {trow['n']:>4,}")
    else:
        print("  (none)")

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

    fd = pd.to_datetime(repaired["FILE_DATE"], utc=True, errors="coerce")
    pd_ = pd.to_datetime(repaired["PERMIT_DATE"], utc=True, errors="coerce")
    ff = pd.to_datetime(repaired["FINAL_DATE"], utc=True, errors="coerce")
    both_fp = fd.notna() & pd_.notna()
    both_pf = pd_.notna() & ff.notna()
    print("\nChronology inversions:")
    print(f"  FILE > PERMIT: {(both_fp & (fd.dt.normalize() > pd_.dt.normalize())).sum()}")
    print(f"  PERMIT > FINAL: {(both_pf & (pd_.dt.normalize() > ff.dt.normalize())).sum()}")

    if AGENT_DATA_PATH:
        out_dir = Path(AGENT_DATA_PATH) / "repaired"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "permits_ca_morgan_hill_repaired.parquet"
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote repaired sample → {out_path}")

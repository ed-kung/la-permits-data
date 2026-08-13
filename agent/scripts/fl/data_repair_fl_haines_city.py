"""Data repair for Haines City (FL) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Haines City DATA is a city portal payload with top-level permit fields
(Status, Application Status, Building Plan Review Status, Permit Date,
Permit Issued Date, Final Inspection Date, Permit Close Out Date,
NSFR CO Issued Date) plus nested contractors / fees / inspections /
payments / property_info / reviews. Key-set variants add plan_reviews
and optionally record_type_from_contractor_box.

Canonical fields:

  - Status (current workflow), else Building Plan Review Status /
    Application Status / STATUS_ORIGINAL lifecycle signals
      → STATUS_NORMALIZED
  - Permit Date → FILE_DATE
  - Permit Issued Date → PERMIT_DATE
  - Final Inspection Date, else Permit Close Out Date, else
    NSFR CO Issued Date, else latest approved final inspection
      → FINAL_DATE

Key-set variants (INFERRED_SCHEMA prefixes):
  - city_portal:               reviews present, no plan_reviews
  - city_portal_plan_reviews:  plan_reviews, no record_type box
  - city_portal_record_type:   plan_reviews + record_type_from_contractor_box

Content suffixes further split by which canonical dates are populated
(``_issued_finaled``, ``_issued``, ``_finaled``, ``_applied``,
``_status_only``).

Known issues repaired:
  - Unmapped STATUS_ORIGINAL values (on/hold, under building/planning
    review, planning/building approval, denied/*, priority violations)
    left STATUS_NORMALIZED null → FILLED from DATA Status / BPR.
  - STATUS_ORIGINAL lag: issued/approved while Status is UNDER REVIEW
    or ON/HOLD → FIXED In Review.
  - STATUS_ORIGINAL lag: approved/issued while BPR is Finaled/Closed
    (or ORIG finaled*) → FIXED Final.
  - Spurious PERMIT_DATE with blank / sentinel Permit Issued Date
    → FIXED clear (or replace sentinel when a real Issued date exists).
  - Missing FINAL_DATE on Final shells → FILLED from close-out / CO /
    approved final inspections when Final Inspection Date is blank.
  - Sentinel 01/01/1900 FINAL_DATE / PERMIT_DATE → FIXED.
  - FINAL_DATE on non-Final shells, or with no supporting DATA date
    → FIXED clear.

Not repairable from DATA:
  - FILE_DATE already matches Permit Date for every sample row.
  - Active / Final shells with blank Permit Issued Date (common for
    APPROVED / Building Approval pre-issuance, and some Closed shells)
    → PERMIT_DATE remains missing.
  - Final shells with no Final Inspection / Close Out / CO / passed
    final inspection → FINAL_DATE remains missing.
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

_FINAL_INSP_RE = re.compile(r"final|fnl|certificate|\bco\b", re.IGNORECASE)

_PASS_STATUS_FRAGMENTS = (
    "approved",
    "pass",
    "private provider",
)


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
    """Parse a date value, returning pd.NaT on failure / sentinel / OOR."""
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return pd.NaT
    if isinstance(val, dict):
        return pd.NaT
    if isinstance(val, str):
        s = val.strip().replace("\xa0", " ")
        if not s or s.upper() in {
            "TBD", "NULL", "NONE", "N/A", "NA", "NAN",
            "00/00/0000", "0/0/0000",
        }:
            return pd.NaT
        if s.startswith("0001-01-01") or s.startswith("1900-01-01"):
            return pd.NaT
        if s in {"01/01/1900", "1/1/1900", "01/01/0001"}:
            return pd.NaT
    try:
        dt = pd.to_datetime(val, utc=True, errors="coerce")
    except (ValueError, TypeError, OverflowError):
        return pd.NaT
    if pd.isna(dt):
        return pd.NaT
    year = int(dt.year)
    if year < _MIN_YEAR or year > _MAX_YEAR:
        return pd.NaT
    return dt.tz_convert("UTC").tz_localize(None)


def _dates_equal(a, b) -> bool:
    da = _safe_to_datetime(a)
    db = _safe_to_datetime(b)
    if da is pd.NaT or db is pd.NaT or pd.isna(da) or pd.isna(db):
        return False
    return pd.Timestamp(da).normalize() == pd.Timestamp(db).normalize()


def _present(dt) -> bool:
    return dt is not pd.NaT and not pd.isna(dt)


def _has_usable_date(val) -> bool:
    return _present(_safe_to_datetime(val))


def _norm_text(val) -> str:
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return ""
    return str(val).strip()


# ── Field extractors ─────────────────────────────────────────────────────────

def _file_date(d: dict):
    return _safe_to_datetime(d.get("Permit Date"))


def _permit_date(d: dict):
    return _safe_to_datetime(d.get("Permit Issued Date"))


def _final_from_inspections(d: dict):
    """Latest completed_date among approved/passed final-ish inspections."""
    inspections = d.get("inspections")
    if not isinstance(inspections, list):
        return pd.NaT
    best = pd.NaT
    for insp in inspections:
        if not isinstance(insp, dict):
            continue
        itype = str(insp.get("inspection_type") or "")
        if not _FINAL_INSP_RE.search(itype):
            continue
        status = str(insp.get("status") or "").lower()
        if not any(frag in status for frag in _PASS_STATUS_FRAGMENTS):
            continue
        dt = _safe_to_datetime(insp.get("completed_date"))
        if not _present(dt):
            continue
        if not _present(best) or dt > best:
            best = dt
    return best


def _final_date(d: dict):
    for key in (
        "Final Inspection Date",
        "Permit Close Out Date",
        "NSFR CO Issued Date",
    ):
        dt = _safe_to_datetime(d.get(key))
        if _present(dt):
            return dt
    return _final_from_inspections(d)


# ── Schema classification ────────────────────────────────────────────────────

def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())
    if "Permit Date" not in keys and "Permit Number" not in keys:
        return "unknown"

    if "record_type_from_contractor_box" in keys:
        base = "city_portal_record_type"
    elif "plan_reviews" in keys:
        base = "city_portal_plan_reviews"
    else:
        base = "city_portal"

    has_file = _present(_file_date(data_dict))
    has_issue = _present(_permit_date(data_dict))
    has_final = _present(_final_date(data_dict))

    if has_issue and has_final:
        return f"{base}_issued_finaled"
    if has_issue:
        return f"{base}_issued"
    if has_final:
        return f"{base}_finaled"
    if has_file:
        return f"{base}_applied"
    return f"{base}_status_only"


# ── Status mapping ───────────────────────────────────────────────────────────

_STATUS_FIELD_MAP = {
    "FINALED/CLOSED": "Final",
    "FINALED": "Final",
    "CLOSED": "Final",
    "ISSUED": "Active",
    "APPROVED": "Active",
    "UNDER REVIEW": "In Review",
    "ON/HOLD": "In Review",
    "EXPIRED": "Inactive",
    "VOID": "Inactive",
    "CANCELLED": "Inactive",
    "CANCELED": "Inactive",
    "DENIED/DISAPPROVE": "Inactive",
    "DENIED PER PLANNING": "Inactive",
}

_BPR_MAP = {
    "Finaled": "Final",
    "Closed": "Final",
    "Issued": "Active",
    "Building Approval": "Active",
    "Planning Approval": "Active",
    "BUILDING UNDER REVIEW": "In Review",
    "Under Building Review": "In Review",
    "Under Planning Review": "In Review",
    "Open": "In Review",
    "BUILDING ON/HOLD": "In Review",
    "Expired": "Inactive",
    "Void": "Inactive",
    "Cancelled": "Inactive",
    "Canceled": "Inactive",
    "Denied per Planning": "Inactive",
}

_APP_MAP = {
    "FINALED": "Final",
    "CLOSED": "Final",
    "ISSUED": "Active",
    "APPROVED": "Active",
    "SUBMITTED FOR REVIEW": "In Review",
    "PENDING/INCOMPLETE": "In Review",
    "VOID": "Inactive",
}

_ORIG_MAP = {
    "finaled/closed": "Final",
    "finaled": "Final",
    "closed": "Final",
    "issued": "Active",
    "approved": "Active",
    "building approval": "Active",
    "planning approval": "Active",
    "under review": "In Review",
    "open": "In Review",
    "on/hold": "In Review",
    "under building review": "In Review",
    "under planning review": "In Review",
    "expired": "Inactive",
    "void": "Inactive",
    "cancelled": "Inactive",
    "canceled": "Inactive",
    "denied/disapprove": "Inactive",
    "denied per planning": "Inactive",
}


def _expected_status(row, d: dict) -> Optional[str]:
    """Infer STATUS_NORMALIZED from DATA + STATUS_ORIGINAL signals.

    Priority:
      1. Explicit current ``Status`` when it is Final / Inactive / In Review
         (captures workflow advances and holds that lag STATUS_ORIGINAL).
      2. Strong Final signals from BPR / Application Status / STATUS_ORIGINAL
         (captures Finaled shells whose Status still says APPROVED/ISSUED
         or is blank).
      3. Active / In Review / Inactive from remaining Status / BPR / App /
         STATUS_ORIGINAL maps.
    """
    status = _norm_text(d.get("Status")).upper()
    bpr = _norm_text(d.get("Building Plan Review Status"))
    app = _norm_text(d.get("Application Status")).upper()
    orig = _norm_text(row.get("STATUS_ORIGINAL")).lower()

    if status in {"FINALED/CLOSED", "FINALED", "CLOSED"}:
        return "Final"
    if status in {
        "EXPIRED", "VOID", "CANCELLED", "CANCELED",
        "DENIED/DISAPPROVE", "DENIED PER PLANNING",
    }:
        return "Inactive"
    if status in {"UNDER REVIEW", "ON/HOLD"}:
        return "In Review"

    if (
        bpr in {"Finaled", "Closed"}
        or app in {"FINALED", "CLOSED"}
        or orig in {"finaled", "finaled/closed", "closed"}
    ):
        return "Final"

    if status in _STATUS_FIELD_MAP:
        return _STATUS_FIELD_MAP[status]
    if bpr in _BPR_MAP:
        return _BPR_MAP[bpr]
    if app in _APP_MAP:
        return _APP_MAP[app]
    if orig in _ORIG_MAP:
        return _ORIG_MAP[orig]

    # Code-enforcement style status with Finaled BPR already handled above.
    if "violation" in status.lower() or "violation" in orig:
        return "Active"

    return None


def _apply_status(repairs: dict, current, expected: Optional[str]) -> Optional[str]:
    if expected is None:
        return None if pd.isna(current) else current
    if pd.isna(current):
        repairs["STATUS_NORMALIZED"] = expected
        repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"
    elif current != expected:
        repairs["STATUS_NORMALIZED"] = expected
        repairs["STATUS_NORMALIZED_FLAG"] = "FIXED"
    return repairs.get("STATUS_NORMALIZED", current)


def _apply_date(repairs: dict, row, field: str, candidate) -> None:
    cand = _safe_to_datetime(candidate)
    if not _present(cand):
        return
    current = row[field]
    if pd.isna(current) or not _has_usable_date(current):
        if pd.isna(current):
            repairs[field] = cand
            repairs[f"{field}_FLAG"] = "FILLED"
        else:
            repairs[field] = cand
            repairs[f"{field}_FLAG"] = "FIXED"
        return
    if not _dates_equal(current, cand):
        repairs[field] = cand
        repairs[f"{field}_FLAG"] = "FIXED"


def _clear_date(repairs: dict, row, field: str) -> None:
    current = repairs.get(field, row[field])
    if pd.isna(current):
        return
    repairs[field] = pd.NaT
    repairs[f"{field}_FLAG"] = "FIXED"


# ── Per-record repair ────────────────────────────────────────────────────────

def _repair_record(row, d: dict, repairs: dict) -> None:
    expected = _expected_status(row, d)
    effective_status = _apply_status(repairs, row["STATUS_NORMALIZED"], expected)

    file_dt = _file_date(d)
    issue_dt = _permit_date(d)
    final_dt = _final_date(d)

    # -- FILE_DATE --
    if not _has_usable_date(row["FILE_DATE"]):
        _apply_date(repairs, row, "FILE_DATE", file_dt)
    elif _present(file_dt) and not _dates_equal(row["FILE_DATE"], file_dt):
        _apply_date(repairs, row, "FILE_DATE", file_dt)

    # -- PERMIT_DATE --
    # Canonical source is Permit Issued Date only. Unsupported or sentinel
    # values are cleared; Active/Final gaps are filled when Issued exists.
    if _has_usable_date(row["PERMIT_DATE"]):
        if _present(issue_dt):
            if not _dates_equal(row["PERMIT_DATE"], issue_dt):
                _apply_date(repairs, row, "PERMIT_DATE", issue_dt)
        else:
            _clear_date(repairs, row, "PERMIT_DATE")
    else:
        # Missing or sentinel current value.
        if not pd.isna(row["PERMIT_DATE"]) and not _has_usable_date(row["PERMIT_DATE"]):
            # Sentinel / OOR currently stored.
            if _present(issue_dt) and effective_status in ("Active", "Final"):
                _apply_date(repairs, row, "PERMIT_DATE", issue_dt)
            else:
                _clear_date(repairs, row, "PERMIT_DATE")
        elif effective_status in ("Active", "Final"):
            _apply_date(repairs, row, "PERMIT_DATE", issue_dt)

    # -- FINAL_DATE --
    if effective_status == "Final":
        if _has_usable_date(row["FINAL_DATE"]):
            if _present(final_dt):
                # Prefer canonical Final Inspection Date when current matches
                # it; otherwise align to the best DATA-derived final date.
                fin_insp = _safe_to_datetime(d.get("Final Inspection Date"))
                if _present(fin_insp) and _dates_equal(row["FINAL_DATE"], fin_insp):
                    pass
                elif not _dates_equal(row["FINAL_DATE"], final_dt):
                    # Keep only if current equals some supporting DATA date.
                    supporting = [
                        _safe_to_datetime(d.get("Final Inspection Date")),
                        _safe_to_datetime(d.get("Permit Close Out Date")),
                        _safe_to_datetime(d.get("NSFR CO Issued Date")),
                        _final_from_inspections(d),
                    ]
                    if not any(
                        _present(s) and _dates_equal(row["FINAL_DATE"], s)
                        for s in supporting
                    ):
                        _apply_date(repairs, row, "FINAL_DATE", final_dt)
            else:
                _clear_date(repairs, row, "FINAL_DATE")
        else:
            if not pd.isna(row["FINAL_DATE"]) and not _has_usable_date(row["FINAL_DATE"]):
                if _present(final_dt):
                    _apply_date(repairs, row, "FINAL_DATE", final_dt)
                else:
                    _clear_date(repairs, row, "FINAL_DATE")
            else:
                _apply_date(repairs, row, "FINAL_DATE", final_dt)
    else:
        if not pd.isna(row["FINAL_DATE"]):
            _clear_date(repairs, row, "FINAL_DATE")


# ── Main entry point ─────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Haines City permit records using information from the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Haines City".  Must contain
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
    from pathlib import Path

    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[3] / ".env")
    MY_DATA_PATH = os.getenv("MY_DATA_PATH")
    filepath = os.path.join(
        MY_DATA_PATH, "processed_data", "permits_fl_sample.parquet"
    )
    df = pd.read_parquet(filepath)
    city = df[df["JURISDICTION"] == "Haines City"].copy()

    print(f"Haines City records: {len(city):,}\n")

    repaired = data_repair(city)

    print("INFERRED_SCHEMA distribution:")
    for s, c in repaired["INFERRED_SCHEMA"].value_counts(dropna=False).items():
        print(f"  {str(s):40s}: {c:>5,}")
    print()

    for field in ["STATUS_NORMALIZED", "FILE_DATE", "PERMIT_DATE", "FINAL_DATE"]:
        flag_col = f"{field}_FLAG"
        n_filled = (repaired[flag_col] == "FILLED").sum()
        n_fixed = (repaired[flag_col] == "FIXED").sum()
        print(f"{field}:")
        print(f"  FILLED: {n_filled:>4,}   FIXED: {n_fixed:>4,}")

        before_missing = city[field].isna().sum()
        after_missing = repaired[field].isna().sum()
        # Also treat sentinel years as missing for before/after if present
        print(f"  Missing before: {before_missing:>4,}   Missing after: {after_missing:>4,}")
        print()

    print("STATUS_NORMALIZED distribution:")
    print("  Before:")
    for s, c in city["STATUS_NORMALIZED"].value_counts(dropna=False).items():
        print(f"    {str(s):15s}: {c:>4,}")
    print("  After:")
    for s, c in repaired["STATUS_NORMALIZED"].value_counts(dropna=False).items():
        print(f"    {str(s):15s}: {c:>4,}")

    print("\nFILE_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FILE_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({(n_has/len(sub) if len(sub) else 0):.1%})")

    print("\nPERMIT_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["PERMIT_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({(n_has/len(sub) if len(sub) else 0):.1%})")

    print("\nFINAL_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FINAL_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({(n_has/len(sub) if len(sub) else 0):.1%})")

"""Data repair for Denton (TX) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Denton DATA is a single City permit-portal payload shape with top-level
keys ``contacts``, ``fees``, ``inspections``, ``permit_info``,
``search_data``, and ``site_info``. Most rows have a populated
``PermitStatus`` (schema label: ``permit_info``); a legacy subset has
blank status (``permit_info_unstated``).

Canonical mappings:
  - permit_info.PermitStatus       → STATUS_NORMALIZED
    (blank status: infer from Finaled / Issued / Approved / Applied)
  - permit_info.PermitAppliedDate  → FILE_DATE
    (fallback: PermitIssuedDate when Applied is blank — legacy rows)
  - permit_info.PermitIssuedDate   → PERMIT_DATE
    (fallback: PermitApprovedDate when Issued is blank)
  - permit_info.PermitFinaledDate  → FINAL_DATE (Final status only)
    (fallback: latest approved/pass inspection Completed date)

Known issues repaired:
  - STATUS_NORMALIZED missing for blank PermitStatus and * PENDING
    INTAKE variants → FILLED.
  - Mis-normalized FINALED / CLOSED as Active or In Review → FIXED
    to Final; ISSUED as In Review → Active; ARCHIVED as In Review →
    Inactive; PENDING CO as Final → Active.
  - Missing FILE_DATE on legacy blank-status rows with blank Applied
    but populated Issued → FILLED from IssuedDate.
  - Missing / incorrect PERMIT_DATE vs Issued (fallback Approved) →
    FILLED / FIXED.
  - Missing FINAL_DATE on Final rows → FILLED from FinaledDate or
    approved/pass inspection Completed; one Final row whose FINAL_DATE
    matched Approved instead of Finaled → FIXED.
  - Spurious FINAL_DATE on non-Final rows → cleared (FIXED).

Not repairable / left as-is:
  - Rows with neither Applied nor Issued (nor usable Approved for
    FILE) → FILE_DATE stays missing.
  - Active/Final rows with neither Issued nor Approved dates
    → PERMIT_DATE stays missing.
  - Final rows with neither FinaledDate nor approved/pass inspection
    Completed dates → FINAL_DATE stays missing.
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
        try:
            parsed = json.loads(data)
        except (json.JSONDecodeError, TypeError):
            return None
        return parsed if isinstance(parsed, dict) else None
    return data if isinstance(data, dict) else None


def _safe_to_datetime(val):
    """Parse a date value, returning pd.NaT on failure / blanks / sentinels."""
    if val is None:
        return pd.NaT
    if isinstance(val, float) and math.isnan(val):
        return pd.NaT
    if not isinstance(val, str) and pd.isna(val):
        return pd.NaT
    if isinstance(val, dict):
        return pd.NaT
    text = str(val).strip()
    if not text or text.upper() in {
        "TBD", "NONE", "N/A", "NA", "NULL", "NAN",
        "00/00/0000", "0/0/0000",
    }:
        return pd.NaT
    try:
        dt = pd.to_datetime(val, errors="coerce")
    except (ValueError, TypeError, OverflowError):
        return pd.NaT
    if pd.isna(dt):
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
    return pd.Timestamp(da).normalize() == pd.Timestamp(db).normalize()


def _permit_info(d: dict) -> dict:
    pi = d.get("permit_info")
    return pi if isinstance(pi, dict) else {}


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())
    required = {"permit_info", "search_data", "inspections", "fees", "contacts", "site_info"}
    if not required <= keys:
        return "unknown"
    status = str(_permit_info(data_dict).get("PermitStatus") or "").strip()
    if status:
        return "permit_info"
    return "permit_info_unstated"


# ── Status mapping ───────────────────────────────────────────────────────────

_STATUS_MAP = {
    # Final
    "CLOSED": "Final",
    "FINALED": "Final",
    "CO": "Final",
    "CERT OF COMPLETION": "Final",
    "COMPLETE": "Final",
    "COMPLETED": "Final",
    "FINAL": "Final",
    # Active
    "ISSUED": "Active",
    "APPROVED": "Active",
    "ACTIVATED": "Active",
    "ACTIVE": "Active",
    "EXTENDED PERMIT": "Active",
    "CURRENT": "Active",
    "PENDING CO": "Active",  # awaiting certificate of occupancy
    # In Review
    "SUBMITTED": "In Review",
    "UNDER REVIEW": "In Review",
    "HOLD": "In Review",
    "PAID": "In Review",
    "PAYMENT PENDING": "In Review",
    "PENDING PAYMENT": "In Review",
    "PENDING REGISTRATION": "In Review",
    "PENDING REVISIONS": "In Review",
    "NE PENDING INTAKE": "In Review",
    "GD PENDING INTAKE": "In Review",
    "AR2 PENDING INTAKE": "In Review",
    "JS PENDING INTAKE": "In Review",
    "NF PENDING INTAKE": "In Review",
    "APPLIED": "In Review",
    "SUSPENDED": "In Review",
    "APPROVED, FEES DUE": "In Review",
    # Inactive
    "EXPIRED": "Inactive",
    "EXPIRED PERMIT": "Inactive",
    "VOID": "Inactive",
    "DENIED": "Inactive",
    "CANCELLED": "Inactive",
    "WITHDRAWN": "Inactive",
    "REVOKED": "Inactive",
    "INACTIVE": "Inactive",
    "ARCHIVED": "Inactive",  # historical archive, not an open review
}


def _infer_status_from_dates(pi: dict) -> Optional[str]:
    """Infer status for legacy rows with blank PermitStatus."""
    if _safe_to_datetime(pi.get("PermitFinaledDate")) is not pd.NaT:
        return "Final"
    if _safe_to_datetime(pi.get("PermitIssuedDate")) is not pd.NaT:
        return "Active"
    if _safe_to_datetime(pi.get("PermitApprovedDate")) is not pd.NaT:
        return "Active"
    if _safe_to_datetime(pi.get("PermitAppliedDate")) is not pd.NaT:
        return "In Review"
    return None


def _expected_status(d: dict) -> Optional[str]:
    pi = _permit_info(d)
    raw = pi.get("PermitStatus")
    if raw is not None and not (isinstance(raw, float) and math.isnan(raw)):
        key = str(raw).strip().upper()
        if key:
            # Generic "* PENDING INTAKE" catch-all for new intake codes
            if key.endswith("PENDING INTAKE") and key not in _STATUS_MAP:
                return "In Review"
            return _STATUS_MAP.get(key)
    return _infer_status_from_dates(pi)


def _apply_status(repairs: dict, current, expected: Optional[str]):
    """Apply expected STATUS_NORMALIZED; return effective status."""
    if expected is None:
        return current

    if pd.isna(current):
        repairs["STATUS_NORMALIZED"] = expected
        repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"
    elif current != expected:
        repairs["STATUS_NORMALIZED"] = expected
        repairs["STATUS_NORMALIZED_FLAG"] = "FIXED"

    return repairs.get("STATUS_NORMALIZED", current)


def _apply_date(repairs: dict, row, field: str, candidate) -> None:
    """Fill or fix *field* from *candidate* datetime (pd.NaT = no candidate)."""
    cand = _safe_to_datetime(candidate)
    if cand is pd.NaT or pd.isna(cand):
        return

    current = row[field]
    if pd.isna(current):
        repairs[field] = cand
        repairs[f"{field}_FLAG"] = "FILLED"
    elif not _dates_equal(current, cand):
        repairs[field] = cand
        repairs[f"{field}_FLAG"] = "FIXED"


def _clear_date(repairs: dict, row, field: str) -> None:
    """Clear a spurious date value."""
    current = repairs.get(field, row[field])
    if pd.isna(current):
        return
    repairs[field] = pd.NaT
    repairs[f"{field}_FLAG"] = "FIXED"


def _is_approved_inspection_result(result) -> bool:
    """Denton uses APPROVED, APP W/COND, PASSED, and related pass codes."""
    text = str(result or "").strip().upper()
    if not text:
        return False
    if text.startswith("APPROVED"):
        return True
    if text.startswith("APP W"):  # APP W/COND, APP W/ CONDI, APP W COND, …
        return True
    if "PASS" in text and "DISAPPROVED" not in text and "FAIL" not in text:
        return True
    return False


def _last_approved_inspection_date(d: dict):
    """Latest Completed date among inspections with an approved/pass result."""
    dates = []
    for insp in d.get("inspections") or []:
        if not isinstance(insp, dict):
            continue
        if not _is_approved_inspection_result(insp.get("Result")):
            continue
        dt = _safe_to_datetime(insp.get("Completed"))
        if dt is not pd.NaT and not pd.isna(dt):
            dates.append(dt)
    return max(dates) if dates else pd.NaT


def _final_date_candidate(d: dict):
    """Prefer PermitFinaledDate; else last approved inspection Completed."""
    pi = _permit_info(d)
    finaled = _safe_to_datetime(pi.get("PermitFinaledDate"))
    if finaled is not pd.NaT and not pd.isna(finaled):
        return finaled
    return _last_approved_inspection_date(d)


def _permit_date_candidate(d: dict):
    """Prefer IssuedDate; fall back to ApprovedDate."""
    pi = _permit_info(d)
    issued = _safe_to_datetime(pi.get("PermitIssuedDate"))
    if issued is not pd.NaT and not pd.isna(issued):
        return issued
    return _safe_to_datetime(pi.get("PermitApprovedDate"))


def _file_date_candidate(d: dict):
    """Prefer AppliedDate; fall back to IssuedDate for legacy blank-Applied rows."""
    pi = _permit_info(d)
    applied = _safe_to_datetime(pi.get("PermitAppliedDate"))
    if applied is not pd.NaT and not pd.isna(applied):
        return applied
    return _safe_to_datetime(pi.get("PermitIssuedDate"))


# ── Per-row repair ───────────────────────────────────────────────────────────

def _repair_row(row, d: dict, repairs: dict) -> None:
    """Repair one Denton permit_info record."""
    expected = _expected_status(d)
    effective_status = _apply_status(repairs, row["STATUS_NORMALIZED"], expected)

    _apply_date(repairs, row, "FILE_DATE", _file_date_candidate(d))
    _apply_date(repairs, row, "PERMIT_DATE", _permit_date_candidate(d))

    if effective_status == "Final":
        _apply_date(repairs, row, "FINAL_DATE", _final_date_candidate(d))
    else:
        _clear_date(repairs, row, "FINAL_DATE")


# ── Main entry point ─────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Denton permit records using the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Denton".  Must contain
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

    for col in ("FILE_DATE", "PERMIT_DATE", "FINAL_DATE"):
        out[col] = pd.to_datetime(out[col], errors="coerce")

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
        if schema in {"permit_info", "permit_info_unstated"}:
            _repair_row(row, d, repairs)

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
    filepath = os.path.join(MY_DATA_PATH, "processed_data", "permits_tx_sample.parquet")
    df = pd.read_parquet(filepath)
    city = df[(df["JURISDICTION"] == "Denton") & (df["STATE"] == "TX")].copy()

    print(f"Denton records: {len(city):,}\n")

    repaired = data_repair(city)

    print("INFERRED_SCHEMA distribution:")
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
        print(f"  Missing before: {before_missing:>4,}   Missing after: {after_missing:>4,}")
        print()

    print("STATUS_NORMALIZED distribution:")
    print("  Before:")
    for s, c in city["STATUS_NORMALIZED"].value_counts(dropna=False).items():
        print(f"    {str(s):15s}: {c:>4,}")
    print("  After:")
    for s, c in repaired["STATUS_NORMALIZED"].value_counts(dropna=False).items():
        print(f"    {str(s):15s}: {c:>4,}")

    print("\nFILE_DATE overall (after): "
          f"{repaired['FILE_DATE'].notna().sum()}/{len(repaired)}")

    print("\nPERMIT_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        if len(sub) == 0:
            continue
        n_has = sub["PERMIT_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({n_has / len(sub):.1%})")

    print("\nFINAL_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        if len(sub) == 0:
            continue
        n_has = sub["FINAL_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({n_has / len(sub):.1%})")

    fin = repaired[repaired["STATUS_NORMALIZED"] == "Final"]
    print(f"\nFinal still missing FINAL_DATE: {fin['FINAL_DATE'].isna().sum()}")
    print(f"Final still missing PERMIT_DATE: {fin['PERMIT_DATE'].isna().sum()}")
    act = repaired[repaired["STATUS_NORMALIZED"] == "Active"]
    print(f"Active still missing PERMIT_DATE: {act['PERMIT_DATE'].isna().sum()}")

    # Sanity: no remaining status nulls that have a mappable PermitStatus / dates
    still_null = repaired[repaired["STATUS_NORMALIZED"].isna()]
    print(f"\nSTATUS still null: {len(still_null)}")

    if AGENT_DATA_PATH:
        out_dir = os.path.join(AGENT_DATA_PATH, "repaired")
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, "permits_tx_denton_repaired.parquet")
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote {out_path}")

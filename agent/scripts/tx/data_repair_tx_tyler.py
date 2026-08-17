"""Data repair for Tyler (TX) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Tyler DATA is a single City permit-portal payload shape with top-level
keys ``contacts``, ``fees``, ``inspections``, ``permit_info``,
``search_data``, and ``site_info``. Most rows have a populated
``PermitStatus`` (schema label: ``permit_info``); a subset has blank
``permit_info`` status/dates but usable ``search_data`` fields
(``permit_info_search_fallback``).

Canonical mappings:
  - permit_info.PermitStatus       → STATUS_NORMALIZED
    (blank: search_data.STATUS; else infer from Finaled / Issued /
    Approved / Applied / search ISSUED+APPLIED)
  - permit_info.PermitAppliedDate  → FILE_DATE
    (fallback: search_data.APPLIED, then Issued / search ISSUED)
  - permit_info.PermitIssuedDate   → PERMIT_DATE
    (fallback: search_data.ISSUED, then PermitApprovedDate)
  - permit_info.PermitFinaledDate  → FINAL_DATE (Final status only)
    (fallback: latest approved FINAL / CO inspection Completed)

Known issues repaired:
  - STATUS_NORMALIZED missing for blank PermitStatus (80 rows; fill
    from search_data.STATUS) and TEMPORARY C.O. ISSUE → FILLED.
  - Mis-normalized FINALED / CO ISSUED as Active → Final; ISSUED as
    In Review (STATUS_ORIGINAL still projectdox) → Active → FIXED.
  - Missing FILE_DATE / PERMIT_DATE on blank-permit_info rows with
    search_data APPLIED / ISSUED → FILLED.
  - Missing PERMIT_DATE when Issued blank but Approved present
    (common Approved / some Issued rows) → FILLED.
  - Missing FINAL_DATE on Final rows with FinaledDate or FINAL/CO
    inspection Completed → FILLED (includes status-corrected Final).
  - Spurious FINAL_DATE on non-Final rows (Active ISSUED that still
    carry PermitFinaledDate; Inactive revoked) → cleared (FIXED).

Not repairable / left as-is:
  - Active / Final rows with neither Issued, search ISSUED, nor
    Approved → PERMIT_DATE stays missing.
  - Final CLOSED / CERTIFICATE ISSUED / blank-info FINALED rows with
    no FinaledDate and no FINAL/CO inspection → FINAL_DATE stays
    missing.
  - Active ISSUED rows that carry PermitFinaledDate are left Active
    (portal status authoritative); FINAL_DATE is cleared.
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


def _search_data(d: dict) -> dict:
    sd = d.get("search_data")
    return sd if isinstance(sd, dict) else {}


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
    return "permit_info_search_fallback"


# ── Status mapping ───────────────────────────────────────────────────────────

_STATUS_MAP = {
    # Final
    "FINAL INSPECTION COM": "Final",
    "FINAL INSP COMPLETE": "Final",
    "COMPLETE": "Final",
    "COMPLETED": "Final",
    "CLOSED": "Final",
    "FINALED": "Final",
    "FINAL": "Final",
    "C.O. ISSUED": "Final",
    "CO ISSUED": "Final",
    "CERTIFICATE ISSUED": "Final",
    "TEMPORARY C.O. ISSUE": "Final",
    "CERT OF COMPLETION": "Final",
    "CO": "Final",
    # Active
    "ISSUED": "Active",
    "APPROVED": "Active",
    "ACTIVATED": "Active",
    "ACTIVE": "Active",
    # In Review
    "RECEIVED": "In Review",
    "TO BE ISSUED": "In Review",
    "PROJECTDOX": "In Review",
    "HOLD": "In Review",
    "UNDER REVIEW": "In Review",
    "ETRAKIT APP": "In Review",
    "SUBMITTED": "In Review",
    "APPLIED": "In Review",
    # Inactive
    "VOID": "Inactive",
    "REJECTED": "Inactive",
    "PERMIT REVOKED": "Inactive",
    "REVOKED": "Inactive",
    "EXPIRED": "Inactive",
    "WITHDRAWN": "Inactive",
    "DENIED": "Inactive",
    "CANCELLED": "Inactive",
    "CANCELED": "Inactive",
}


def _normalize_status_key(raw) -> str:
    if raw is None or (isinstance(raw, float) and math.isnan(raw)):
        return ""
    return str(raw).strip().upper()


def _infer_status_from_dates(d: dict) -> Optional[str]:
    """Infer status when PermitStatus and search_data.STATUS are blank."""
    pi = _permit_info(d)
    sd = _search_data(d)
    if _safe_to_datetime(pi.get("PermitFinaledDate")) is not pd.NaT:
        return "Final"
    if _safe_to_datetime(pi.get("PermitIssuedDate")) is not pd.NaT:
        return "Active"
    if _safe_to_datetime(sd.get("ISSUED")) is not pd.NaT:
        return "Active"
    if _safe_to_datetime(pi.get("PermitApprovedDate")) is not pd.NaT:
        return "Active"
    if _safe_to_datetime(pi.get("PermitAppliedDate")) is not pd.NaT:
        return "In Review"
    if _safe_to_datetime(sd.get("APPLIED")) is not pd.NaT:
        return "In Review"
    return None


def _expected_status(d: dict) -> Optional[str]:
    pi = _permit_info(d)
    key = _normalize_status_key(pi.get("PermitStatus"))
    if key:
        return _STATUS_MAP.get(key)

    sd_key = _normalize_status_key(_search_data(d).get("STATUS"))
    if sd_key:
        return _STATUS_MAP.get(sd_key)

    return _infer_status_from_dates(d)


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
    text = str(result or "").strip().upper()
    if not text:
        return False
    if text.startswith("APPROVED"):
        return True
    if "PASS" in text and "DISAPPROVED" not in text and "FAIL" not in text:
        return True
    return False


def _is_completion_inspection_type(insp_type) -> bool:
    """True for final / certificate-of-occupancy style inspection types."""
    text = str(insp_type or "").strip().upper()
    if not text:
        return False
    if "FINAL" in text:
        return True
    if "CERTIFICATE OF OCCUPANCY" in text:
        return True
    if "C.O" in text or text.endswith(" COM CO") or text == "CO":
        return True
    return False


def _last_completion_inspection_date(d: dict):
    """Latest Completed among approved FINAL / CO inspections."""
    dates = []
    for insp in d.get("inspections") or []:
        if not isinstance(insp, dict):
            continue
        if not _is_approved_inspection_result(insp.get("Result")):
            continue
        if not _is_completion_inspection_type(insp.get("Type")):
            continue
        dt = _safe_to_datetime(insp.get("Completed"))
        if dt is not pd.NaT and not pd.isna(dt):
            dates.append(dt)
    return max(dates) if dates else pd.NaT


def _final_date_candidate(d: dict):
    """Prefer PermitFinaledDate; else latest approved FINAL/CO inspection."""
    pi = _permit_info(d)
    finaled = _safe_to_datetime(pi.get("PermitFinaledDate"))
    if finaled is not pd.NaT and not pd.isna(finaled):
        return finaled
    return _last_completion_inspection_date(d)


def _permit_date_candidate(d: dict):
    """Prefer IssuedDate; then search_data.ISSUED; then ApprovedDate."""
    pi = _permit_info(d)
    issued = _safe_to_datetime(pi.get("PermitIssuedDate"))
    if issued is not pd.NaT and not pd.isna(issued):
        return issued
    sd_issued = _safe_to_datetime(_search_data(d).get("ISSUED"))
    if sd_issued is not pd.NaT and not pd.isna(sd_issued):
        return sd_issued
    return _safe_to_datetime(pi.get("PermitApprovedDate"))


def _file_date_candidate(d: dict):
    """Prefer AppliedDate; then search APPLIED; then Issued / search ISSUED."""
    pi = _permit_info(d)
    sd = _search_data(d)
    applied = _safe_to_datetime(pi.get("PermitAppliedDate"))
    if applied is not pd.NaT and not pd.isna(applied):
        return applied
    sd_applied = _safe_to_datetime(sd.get("APPLIED"))
    if sd_applied is not pd.NaT and not pd.isna(sd_applied):
        return sd_applied
    issued = _safe_to_datetime(pi.get("PermitIssuedDate"))
    if issued is not pd.NaT and not pd.isna(issued):
        return issued
    return _safe_to_datetime(sd.get("ISSUED"))


# ── Per-row repair ───────────────────────────────────────────────────────────

def _repair_row(row, d: dict, repairs: dict) -> None:
    """Repair one Tyler permit_info / search_fallback record."""
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
    Tyler permit records using the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Tyler".  Must contain
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
        if schema in {"permit_info", "permit_info_search_fallback"}:
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
    city = df[(df["JURISDICTION"] == "Tyler") & (df["STATE"] == "TX")].copy()

    print(f"Tyler records: {len(city):,}\n")

    repaired = data_repair(city)

    print("INFERRED_SCHEMA distribution:")
    for s, c in repaired["INFERRED_SCHEMA"].value_counts(dropna=False).items():
        print(f"  {str(s):40s}: {c:>4,}")
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

    still_null = repaired[repaired["STATUS_NORMALIZED"].isna()]
    print(f"\nSTATUS still null: {len(still_null)}")

    if AGENT_DATA_PATH:
        out_dir = os.path.join(AGENT_DATA_PATH, "repaired")
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, "permits_tx_tyler_repaired.parquet")
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote {out_path}")

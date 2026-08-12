"""Data repair for Bal Harbour (FL) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Bal Harbour DATA has two portal families:

  - civic (permit_info / search_data / site_info): Village eTRAKiT-style
    payload with PermitStatus, PermitAppliedDate, PermitIssuedDate,
    PermitFinaledDate, PermitApprovedDate. Sentinel dates ``1/1/2999``
    (and other years outside 1980–2035) are treated as missing.
  - empty_shell (Build Status / Permit Details / …): alternate portal
    envelope present on 422 sample rows, but every nested field is null
    or empty — no repairable status or dates.

Content variants (INFERRED_SCHEMA) further split the civic family by
which canonical dates are populated:

  - civic_issued_finaled
  - civic_issued
  - civic_finaled
  - civic_applied
  - civic_approved
  - civic_status_only
  - empty_shell
  - missing / unknown

Canonical mappings:
  - PermitStatus (+ Issued/Finaled for IMPORTED / APPROVED /
    EARLY START APPROVAL / TCC)              → STATUS_NORMALIZED
  - PermitAppliedDate                        → FILE_DATE
  - PermitIssuedDate                         → PERMIT_DATE
  - PermitFinaledDate else last approved
    final-ish inspection else last approved
    inspection (Final only)                  → FINAL_DATE

Known issues repaired:
  - 513 civic null STATUS_NORMALIZED rows (mostly IMPORTED, plus
    FIRST REVIEW / CC / EARLY START / TCC / NOT SUBMITTED /
    WRITTEN WARNING) → FILLED from PermitStatus (+ dates for IMPORTED).
  - Stale STATUS_ORIGINAL snapshots (e.g. issued/ready/denied while
    live PermitStatus is FINALED / ISSUED / CC / CO) → FIXED.
  - Unissued APPROVED labeled Active → FIXED to In Review.
  - CC / CO / EARLY START APPROVAL EXPIRED remapped using live status.
  - Missing PERMIT_DATE filled from PermitIssuedDate on Active/Final.
  - Missing FINAL_DATE on Final rows filled from usable
    PermitFinaledDate or approved inspections (especially CLOSED rows
    whose FinaledDate is the ``1/1/2999`` sentinel).
  - Spurious FINAL_DATE on non-Final rows cleared.

Not repairable from DATA:
  - 422 empty_shell rows have no status or dates → all target fields
    stay missing.
  - Many CLOSED Final rows have only the ``1/1/2999`` FinaledDate and
    no inspections → FINAL_DATE stays missing.
  - A few FINALED / CERTIFICATE rows lack both FinaledDate and a
    usable approved inspection → FINAL_DATE stays missing.
  - ACTIVE / IMPORTED rows with sentinel IssuedDate have no real
    PERMIT_DATE in DATA.
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

_FINAL_INSP_RE = re.compile(
    r"final|fnl|cert(?:ificate)?\s*of\s*(?:occupancy|completion)|"
    r"\bco\b|\bcc\b",
    re.I,
)
_PASS_RESULTS = {
    "APPROVED",
    "APPROVED W EXCEPTION",
    "APPROVED WITH COMMENTS",
    "APPROVED WITH CONDITIONS",
    "PASS",
    "PASSED",
    "PARTIAL APPROVED",
    "PARTIAL APPROVAL",
    "COMPLIANT",
}


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
    if da is pd.NaT or db is pd.NaT or pd.isna(da) or pd.isna(db):
        return False
    return pd.Timestamp(da).normalize() == pd.Timestamp(db).normalize()


def _family(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())
    if "permit_info" in keys:
        return "civic"
    if "Build Status" in keys or "Permit Details" in keys:
        return "empty_shell"
    return "unknown"


def _extract_civic(d: dict):
    """Return (raw_status, applied, issued, approved, finaled)."""
    pi = d.get("permit_info") if isinstance(d.get("permit_info"), dict) else {}
    sd = d.get("search_data") if isinstance(d.get("search_data"), dict) else {}
    raw = (pi.get("PermitStatus") or sd.get("STATUS") or "").strip()
    applied = _safe_to_datetime(pi.get("PermitAppliedDate"))
    issued = _safe_to_datetime(pi.get("PermitIssuedDate"))
    approved = _safe_to_datetime(pi.get("PermitApprovedDate"))
    finaled = _safe_to_datetime(pi.get("PermitFinaledDate"))
    return raw, applied, issued, approved, finaled


def _classify_schema(data_dict: Optional[dict]) -> str:
    family = _family(data_dict)
    if family in ("missing", "unknown", "empty_shell"):
        return family

    _, applied, issued, approved, finaled = _extract_civic(data_dict)
    has_applied = applied is not pd.NaT and not pd.isna(applied)
    has_issued = issued is not pd.NaT and not pd.isna(issued)
    has_final = finaled is not pd.NaT and not pd.isna(finaled)
    has_approved = approved is not pd.NaT and not pd.isna(approved)

    if has_issued and has_final:
        return "civic_issued_finaled"
    if has_issued:
        return "civic_issued"
    if has_final:
        return "civic_finaled"
    if has_approved:
        return "civic_approved"
    if has_applied:
        return "civic_applied"
    return "civic_status_only"


# ── Status mapping ───────────────────────────────────────────────────────────

_STATUS_MAP = {
    # Final / completed / certificate closeout
    "FINALED": "Final",
    "CLOSED": "Final",
    "CERTIFICATE OF COMPLETION": "Final",
    "CERTIFICATE OF OCCUPANCY": "Final",
    "PROJECT COMPLETE": "Final",
    "CC": "Final",
    "CO": "Final",
    # Active / issued
    "ISSUED": "Active",
    "ACTIVE": "Active",
    "RENEWED": "Active",
    # In review / pre-issuance
    "APPLICATION REVIEW": "In Review",
    "FIRST REVIEW": "In Review",
    "ON REVIEW": "In Review",
    "READY": "In Review",
    "PENDING": "In Review",
    "HOLD": "In Review",
    "PAID ONLINE": "In Review",
    "COMPLIED": "In Review",
    "INCOMPLETE APPLICATION": "In Review",
    "NOT SUBMITTED": "In Review",
    # Inactive
    "CANCELLED": "Inactive",
    "EXPIRED": "Inactive",
    "PERMIT EXPIRED": "Inactive",
    "EXPIRED PERMIT": "Inactive",
    "APPLICATION EXPIRED": "Inactive",
    "VOID": "Inactive",
    "NULL AND VOID": "Inactive",
    "DENIED": "Inactive",
    "EARLY START APPROVAL EXPIRED": "Inactive",
    "WRITTEN WARNING": "Inactive",
}

# Require a real IssuedDate for Active; otherwise In Review.
_ISSUANCE_GATED = {
    "APPROVED",
    "EARLY START APPROVAL",
    "TCC",
}


def _expected_status(raw_status: str, issued, finaled) -> Optional[str]:
    key = (raw_status or "").strip().upper()
    if not key:
        return None

    has_issued = issued is not pd.NaT and not pd.isna(issued)
    has_finaled = finaled is not pd.NaT and not pd.isna(finaled)

    # Legacy import batch: status label itself is uninformative; infer
    # from which canonical dates are present.
    if key == "IMPORTED":
        if has_finaled:
            return "Final"
        if has_issued:
            return "Active"
        return "In Review"

    if key in _ISSUANCE_GATED:
        if has_finaled:
            return "Final"
        return "Active" if has_issued else "In Review"

    return _STATUS_MAP.get(key)


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


# ── Inspection date helpers ──────────────────────────────────────────────────

def _is_pass_result(result) -> bool:
    if result is None:
        return False
    return str(result).strip().upper() in _PASS_RESULTS


def _last_approved_final_inspection(d: dict):
    dates = []
    for insp in d.get("inspections") or []:
        if not isinstance(insp, dict):
            continue
        if not _is_pass_result(insp.get("Result")):
            continue
        typ = str(insp.get("Type") or "")
        if not _FINAL_INSP_RE.search(typ):
            continue
        dc = _safe_to_datetime(insp.get("Completed"))
        if dc is not pd.NaT and not pd.isna(dc):
            dates.append(dc)
    return max(dates) if dates else pd.NaT


def _last_approved_inspection(d: dict):
    dates = []
    for insp in d.get("inspections") or []:
        if not isinstance(insp, dict):
            continue
        if not _is_pass_result(insp.get("Result")):
            continue
        dc = _safe_to_datetime(insp.get("Completed"))
        if dc is not pd.NaT and not pd.isna(dc):
            dates.append(dc)
    return max(dates) if dates else pd.NaT


# ── Per-record repair ────────────────────────────────────────────────────────

def _apply_date(repairs: dict, row, field: str, candidate) -> None:
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
    current = repairs.get(field, row[field])
    if pd.isna(current):
        return
    repairs[field] = pd.NaT
    repairs[f"{field}_FLAG"] = "FIXED"


def _repair_civic(row, d: dict, repairs: dict) -> None:
    raw, applied, issued, approved, finaled = _extract_civic(d)
    expected = _expected_status(raw, issued, finaled)
    effective_status = _apply_status(repairs, row["STATUS_NORMALIZED"], expected)

    # -- FILE_DATE ← PermitAppliedDate --
    _apply_date(repairs, row, "FILE_DATE", applied)

    # -- PERMIT_DATE ← PermitIssuedDate --
    has_issued = issued is not pd.NaT and not pd.isna(issued)
    if has_issued:
        if pd.isna(row["PERMIT_DATE"]):
            if effective_status in ("Active", "Final"):
                repairs["PERMIT_DATE"] = issued
                repairs["PERMIT_DATE_FLAG"] = "FILLED"
        elif not _dates_equal(row["PERMIT_DATE"], issued):
            repairs["PERMIT_DATE"] = issued
            repairs["PERMIT_DATE_FLAG"] = "FIXED"

    # -- FINAL_DATE ← Finaled else inspections (Final only) --
    if effective_status == "Final":
        candidate = finaled
        if candidate is pd.NaT or pd.isna(candidate):
            candidate = _last_approved_final_inspection(d)
        if candidate is pd.NaT or pd.isna(candidate):
            candidate = _last_approved_inspection(d)

        if candidate is not pd.NaT and not pd.isna(candidate):
            if pd.isna(row["FINAL_DATE"]):
                repairs["FINAL_DATE"] = candidate
                repairs["FINAL_DATE_FLAG"] = "FILLED"
            elif not _dates_equal(row["FINAL_DATE"], candidate):
                # Prefer explicit PermitFinaledDate when correcting.
                if finaled is not pd.NaT and not pd.isna(finaled):
                    repairs["FINAL_DATE"] = finaled
                    repairs["FINAL_DATE_FLAG"] = "FIXED"
    else:
        _clear_date(repairs, row, "FINAL_DATE")


# ── Main entry point ─────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Bal Harbour permit records using information from the raw DATA JSON.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Bal Harbour".  Must contain
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
        if d is None or family != "civic":
            continue

        repairs: dict = {}
        _repair_civic(row, d, repairs)
        for key, value in repairs.items():
            out.at[idx, key] = value

    for col in ("FILE_DATE", "PERMIT_DATE", "FINAL_DATE"):
        out[col] = pd.to_datetime(out[col], errors="coerce")

    return out


# ── CLI: run standalone to preview repair stats ──────────────────────────────

if __name__ == "__main__":
    import os
    from pathlib import Path

    from dotenv import load_dotenv

    repo_root = Path(__file__).resolve().parents[3]
    load_dotenv(repo_root / ".env")
    my_data_path = os.getenv("MY_DATA_PATH")
    agent_data_path = os.getenv("AGENT_DATA_PATH")
    filepath = os.path.join(my_data_path, "processed_data", "permits_fl_sample.parquet")
    df = pd.read_parquet(filepath)
    city = df[
        (df["JURISDICTION"] == "Bal Harbour") & (df["STATE"] == "FL")
    ].copy()

    print(f"Bal Harbour records: {len(city):,}\n")
    repaired = data_repair(city)

    print("INFERRED_SCHEMA:")
    print(repaired["INFERRED_SCHEMA"].value_counts(dropna=False).to_string())
    print()

    for field in ["STATUS_NORMALIZED", "FILE_DATE", "PERMIT_DATE", "FINAL_DATE"]:
        flag_col = f"{field}_FLAG"
        n_filled = (repaired[flag_col] == "FILLED").sum()
        n_fixed = (repaired[flag_col] == "FIXED").sum()
        before_missing = city[field].isna().sum()
        after_missing = repaired[field].isna().sum()
        print(f"{field}:")
        print(f"  FILLED: {n_filled:>4,}   FIXED: {n_fixed:>4,}")
        print(f"  Missing before: {before_missing:>4,}   Missing after: {after_missing:>4,}")
        print()

    print("STATUS_NORMALIZED distribution:")
    print("  Before:")
    for s, c in city["STATUS_NORMALIZED"].value_counts(dropna=False).items():
        print(f"    {str(s):15s}: {c:>4,}")
    print("  After:")
    for s, c in repaired["STATUS_NORMALIZED"].value_counts(dropna=False).items():
        print(f"    {str(s):15s}: {c:>4,}")

    print("\nCoverage by STATUS_NORMALIZED (after):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        if len(sub) == 0:
            continue
        for field in ["FILE_DATE", "PERMIT_DATE", "FINAL_DATE"]:
            n_has = sub[field].notna().sum()
            print(
                f"  {status:12s} {field:12s}: "
                f"{n_has:>4,} / {len(sub):>4,} ({n_has / len(sub):.1%})"
            )

    if agent_data_path:
        out_path = os.path.join(agent_data_path, "bal_harbour_repaired_sample.parquet")
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote repaired sample → {out_path}")

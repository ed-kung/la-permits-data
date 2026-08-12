"""Data repair for Sumter County (FL) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Sumter County DATA is a uniform civic / eTRAKiT-style payload with
top-level keys contacts, fees, inspections, permit_info, search_data,
and site_info. Canonical fields:

  - permit_info.PermitStatus (empty status with an issued date → Active)
      → STATUS_NORMALIZED
  - permit_info.PermitAppliedDate
    (fallback PermitIssuedDate)            → FILE_DATE
  - permit_info.PermitIssuedDate
    (fallback PermitApprovedDate)          → PERMIT_DATE
  - permit_info.PermitFinaledDate
    (fallback latest passed final-ish
    inspection; list-format inspections)   → FINAL_DATE

Content variants (INFERRED_SCHEMA) split by which canonical dates are
populated (``civic_issued_finaled``, ``civic_issued``, ``civic_finaled``,
``civic_approved``, ``civic_applied``, ``civic_status_only``).

Known issues repaired:
  - Null STATUS_NORMALIZED for EPERMIT APPLIED / HOLD - PLAN REV /
    PENDING ZONING → FILLED to In Review; blank PermitStatus with an
    issued date → FILLED to Active.
  - Missing PERMIT_DATE on Final / Inactive filled from ApprovedDate
    when IssuedDate is blank.
  - Missing FINAL_DATE on Final rows filled from PermitFinaledDate or
    passed FINAL / COFC inspections.
  - Spurious FINAL_DATE on non-Final (Active ISSUED) rows cleared.

Not repairable from DATA:
  - 3 empty portal shells (blank permit_info + no fees/inspections) keep
    null STATUS_NORMALIZED / FILE_DATE / PERMIT_DATE / FINAL_DATE.
  - ~6 Final (FINALED / Closed Out) rows have neither PermitFinaledDate
    nor a passed final inspection → FINAL_DATE stays missing.
  - Some Final / Inactive rows have blank IssuedDate and ApprovedDate
    → PERMIT_DATE stays missing (never-issued cancels, etc.).
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
    r"final|fnl|certificate|\bco\b|\bcc\b|\bcoc\b|\bcofc\b",
    re.IGNORECASE,
)

_PASS_RESULTS = {
    "approved",
    "completed",
    "passed",
    "complete",
    "pass",
    "pass partial",
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


def _permit_info(d: dict) -> dict:
    pi = d.get("permit_info")
    return pi if isinstance(pi, dict) else {}


def _extract_fields(d: dict):
    """Return (raw_status, applied, issued, approved, finaled)."""
    pi = _permit_info(d)
    raw = pi.get("PermitStatus")
    applied = _safe_to_datetime(pi.get("PermitAppliedDate"))
    issued = _safe_to_datetime(pi.get("PermitIssuedDate"))
    approved = _safe_to_datetime(pi.get("PermitApprovedDate"))
    finaled = _safe_to_datetime(pi.get("PermitFinaledDate"))
    return raw, applied, issued, approved, finaled


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())
    if "permit_info" not in keys:
        return "unknown"

    _, applied, issued, approved, finaled = _extract_fields(data_dict)
    has_applied = applied is not pd.NaT and not pd.isna(applied)
    has_issued = issued is not pd.NaT and not pd.isna(issued)
    has_approved = approved is not pd.NaT and not pd.isna(approved)
    has_final = finaled is not pd.NaT and not pd.isna(finaled)

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

# Case-insensitive raw portal status → STATUS_NORMALIZED.
_STATUS_MAP = {
    # Final
    "finaled": "Final",
    "co issued": "Final",
    "closed out": "Final",
    # Active
    "issued": "Active",
    # In Review
    "in review": "In Review",
    "hold - plan rev": "In Review",
    "pending": "In Review",
    "pending zoning": "In Review",
    "awaiting payment": "In Review",
    "epermit applied": "In Review",
    "review complete": "In Review",
    # Inactive — EXPIRING is issued-but-nearing/past expiry in this portal
    "expiring": "Inactive",
    "expired": "Inactive",
    "cancelled": "Inactive",
    "canceled": "Inactive",
}


def _expected_status(raw_status: Optional[str], issued) -> Optional[str]:
    if raw_status is None:
        raw_key = ""
    else:
        raw_key = str(raw_status).strip().lower()

    if not raw_key:
        # Legacy shells with blank PermitStatus but a real issued date.
        if issued is not pd.NaT and not pd.isna(issued):
            return "Active"
        return None

    return _STATUS_MAP.get(raw_key)


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


def _insp_type_result_date(insp):
    """Normalize civic inspection rows (list or dict) to (type, result, date)."""
    if isinstance(insp, list) and len(insp) >= 3:
        return str(insp[0] or ""), str(insp[1] or ""), insp[2]
    if isinstance(insp, dict):
        typ = insp.get("Type") or insp.get("InspectionType") or insp.get("Name") or ""
        result = insp.get("Result") or insp.get("Status") or ""
        date = (
            insp.get("Completed")
            or insp.get("Date")
            or insp.get("InspectionDate")
            or insp.get("ResultDate")
        )
        return str(typ), str(result), date
    return "", "", None


def _final_date_from_data(d: dict, finaled):
    """Resolve FINAL_DATE: PermitFinaledDate → latest passed final inspection."""
    if finaled is not pd.NaT and not pd.isna(finaled):
        return finaled

    candidates = []
    for insp in d.get("inspections") or []:
        typ, result, date = _insp_type_result_date(insp)
        result_l = result.strip().lower()
        if result_l not in _PASS_RESULTS and not result_l.startswith("pass"):
            continue
        if not _FINAL_INSP_RE.search(typ):
            continue
        dt = _safe_to_datetime(date)
        if dt is not pd.NaT and not pd.isna(dt):
            candidates.append(dt)
    return max(candidates) if candidates else pd.NaT


# ── Per-record repair ───────────────────────────────────────────────────────

def _repair_record(row, d: dict, repairs: dict) -> None:
    raw_status, applied, issued, approved, finaled = _extract_fields(d)
    resolved_final = _final_date_from_data(d, finaled)
    expected = _expected_status(raw_status, issued)
    effective_status = _apply_status(repairs, row["STATUS_NORMALIZED"], expected)

    # -- FILE_DATE ← PermitAppliedDate else PermitIssuedDate --
    file_src = applied if (applied is not pd.NaT and not pd.isna(applied)) else issued
    if file_src is not pd.NaT and not pd.isna(file_src):
        if pd.isna(row["FILE_DATE"]):
            repairs["FILE_DATE"] = file_src
            repairs["FILE_DATE_FLAG"] = "FILLED"
        elif not _dates_equal(row["FILE_DATE"], file_src) and (
            applied is not pd.NaT and not pd.isna(applied)
        ):
            # Only overwrite mismatches against the canonical applied date.
            repairs["FILE_DATE"] = applied
            repairs["FILE_DATE_FLAG"] = "FIXED"

    # -- PERMIT_DATE ← IssuedDate, else ApprovedDate --
    permit_src = issued if (issued is not pd.NaT and not pd.isna(issued)) else approved
    if permit_src is not pd.NaT and not pd.isna(permit_src):
        if pd.isna(row["PERMIT_DATE"]):
            if effective_status in ("Active", "Final", "Inactive"):
                # Inactive (expired/cancelled/expiring) often still carries issuance.
                repairs["PERMIT_DATE"] = permit_src
                repairs["PERMIT_DATE_FLAG"] = "FILLED"
        elif issued is not pd.NaT and not pd.isna(issued) and not _dates_equal(
            row["PERMIT_DATE"], issued
        ):
            repairs["PERMIT_DATE"] = issued
            repairs["PERMIT_DATE_FLAG"] = "FIXED"

    # -- FINAL_DATE ← finaled / final inspection; Final only --
    current_final = row["FINAL_DATE"]
    if effective_status == "Final":
        if resolved_final is not pd.NaT and not pd.isna(resolved_final):
            if pd.isna(current_final):
                repairs["FINAL_DATE"] = resolved_final
                repairs["FINAL_DATE_FLAG"] = "FILLED"
            elif not _dates_equal(current_final, resolved_final):
                repairs["FINAL_DATE"] = resolved_final
                repairs["FINAL_DATE_FLAG"] = "FIXED"
    elif not pd.isna(current_final):
        repairs["FINAL_DATE"] = pd.NaT
        repairs["FINAL_DATE_FLAG"] = "FIXED"


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Sumter County permit records using information from the raw DATA JSON.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Sumter County".  Must contain
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
        if d is None or schema in ("missing", "unknown"):
            continue

        repairs: dict = {}
        _repair_record(row, d, repairs)

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
    filepath = os.path.join(
        MY_DATA_PATH, "processed_data", "permits_fl_sample.parquet"
    )
    df = pd.read_parquet(filepath)
    city = df[df["JURISDICTION"] == "Sumter County"].copy()

    print(f"Sumter County records: {len(city):,}\n")

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

    print("\nSTATUS_NORMALIZED changes (before → after):")
    changed = city["STATUS_NORMALIZED"].fillna("__NA__") != repaired[
        "STATUS_NORMALIZED"
    ].fillna("__NA__")
    if changed.any():
        tmp = pd.DataFrame(
            {
                "before": city.loc[changed, "STATUS_NORMALIZED"].fillna("__NA__"),
                "after": repaired.loc[changed, "STATUS_NORMALIZED"].fillna("__NA__"),
            }
        )
        print(tmp.value_counts().to_string())
    else:
        print("  (none)")

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

    final_miss = repaired[
        (repaired["STATUS_NORMALIZED"] == "Final") & repaired["FINAL_DATE"].isna()
    ]
    print(f"\nFinal still missing FINAL_DATE: {len(final_miss)}")
    if len(final_miss):
        from collections import Counter

        ps_counts = Counter()
        for idx in final_miss.index:
            d = _safe_parse(repaired.at[idx, "DATA"])
            if d is None:
                continue
            raw = (_permit_info(d).get("PermitStatus") or "").strip() or "__EMPTY__"
            ps_counts[raw] += 1
        print("  by PermitStatus:", dict(ps_counts))

    status_null = repaired["STATUS_NORMALIZED"].isna().sum()
    print(f"\nSTATUS_NORMALIZED still null: {status_null}")

    af_miss = repaired[
        repaired["STATUS_NORMALIZED"].isin(["Active", "Final"])
        & repaired["PERMIT_DATE"].isna()
    ]
    print(f"Active/Final still missing PERMIT_DATE: {len(af_miss)}")
    if len(af_miss):
        from collections import Counter

        ps_counts = Counter()
        for idx in af_miss.index:
            d = _safe_parse(repaired.at[idx, "DATA"])
            if d is None:
                continue
            raw = (_permit_info(d).get("PermitStatus") or "").strip() or "__EMPTY__"
            ps_counts[raw] += 1
        print("  by PermitStatus:", dict(ps_counts))

    if AGENT_DATA_PATH:
        out_path = os.path.join(
            AGENT_DATA_PATH, "sumter_county_repaired_sample.parquet"
        )
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote repaired sample → {out_path}")

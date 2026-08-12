"""Data repair for Clermont (FL) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Clermont DATA is a uniform civic / eTRAKiT-style payload with top-level
keys contacts, fees, inspections, permit_info, search_data, and
site_info. Canonical fields:

  - permit_info.PermitStatus (+ issuance gating for APPROVED;
    CLOSED gated on a resolvable final stamp; empty status with an
    issued date → Active)
      → STATUS_NORMALIZED
  - permit_info.PermitAppliedDate → FILE_DATE
  - permit_info.PermitIssuedDate
    (fallback PermitApprovedDate)          → PERMIT_DATE
  - permit_info.PermitFinaledDate
    (fallback search_data FINALED / CO ISSUED,
    else latest Approved/Completed final-ish
    inspection)                            → FINAL_DATE

Content variants (INFERRED_SCHEMA) split by which canonical dates are
populated (``civic_issued_finaled``, ``civic_issued``, ``civic_finaled``,
``civic_applied``, ``civic_status_only``).

Known issues repaired:
  - Stale STATUS_NORMALIZED vs PermitStatus: Active/In Review still
    labeled while PermitStatus is FINALED → FIXED to Final; Active
    EXPIRED / REJECTED → Inactive; ISSUED mislabeled In Review /
    Inactive / null → Active; APPROVED PENDING null → In Review.
  - Unissued APPROVED rows labeled Active → FIXED to In Review.
  - CLOSED without a resolvable finaled/CO/final-inspection date
    labeled Final → FIXED to Inactive; CLOSED with a final stamp
    stays Final.
  - Missing PERMIT_DATE filled from IssuedDate, else ApprovedDate
    for Active / Final / Inactive.
  - Missing FINAL_DATE on Final rows filled from PermitFinaledDate
    (or rare inspection / search fallbacks), including rows whose
    status is corrected to Final.
  - Spurious FINAL_DATE on non-Final rows cleared.

Not repairable from DATA:
  - 4 FILE_DATE gaps: PermitAppliedDate blank (legacy shells /
    incomplete portal rows). No substitute application date in DATA.
  - ~11 Final (FINALED / CO ISSUED) rows have neither PermitFinaledDate
    nor an Approved final inspection → FINAL_DATE stays missing.
  - Some Final / Active rows have blank IssuedDate and ApprovedDate
    → PERMIT_DATE stays missing.
  - One empty PermitStatus shell with no dates stays STATUS_NORMALIZED
    null.
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
    r"final|fnl|certificate|\bco\b|\bcc\b|\bcoc\b",
    re.IGNORECASE,
)

_PASS_RESULTS = {
    "approved",
    "completed",
    "passed",
    "complete",
    "pass",
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
    if da is pd.NaT or db is pd.NaT:
        return False
    return da.normalize() == db.normalize()


def _permit_info(d: dict) -> dict:
    pi = d.get("permit_info")
    return pi if isinstance(pi, dict) else {}


def _search_data(d: dict) -> dict:
    sd = d.get("search_data")
    return sd if isinstance(sd, dict) else {}


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

    _, applied, issued, _, finaled = _extract_fields(data_dict)
    has_applied = applied is not pd.NaT
    has_issued = issued is not pd.NaT
    has_final = finaled is not pd.NaT

    if has_issued and has_final:
        return "civic_issued_finaled"
    if has_issued:
        return "civic_issued"
    if has_final:
        return "civic_finaled"
    if has_applied:
        return "civic_applied"
    return "civic_status_only"


# ── Status mapping ───────────────────────────────────────────────────────────

# Case-insensitive raw portal status → STATUS_NORMALIZED.
_STATUS_MAP = {
    # Final
    "finaled": "Final",
    "co issued": "Final",
    # Active
    "issued": "Active",
    # In Review
    "in review": "In Review",
    "pending information": "In Review",
    "approved pending": "In Review",
    "web": "In Review",
    # Inactive
    "expired": "Inactive",
    "void": "Inactive",
    "rejected": "Inactive",
    "cancelled": "Inactive",
    "canceled": "Inactive",
    "withdrawn": "Inactive",
}

# Active only when an issuance date is present; otherwise In Review.
_ISSUANCE_GATED = {
    "approved",
}


def _expected_status(
    raw_status: Optional[str],
    issued,
    resolved_final,
) -> Optional[str]:
    if raw_status is None:
        raw_key = ""
    else:
        raw_key = str(raw_status).strip().lower()

    if not raw_key:
        # Legacy shells with blank PermitStatus but a real issued date.
        if issued is not pd.NaT:
            return "Active"
        return None

    if raw_key in _ISSUANCE_GATED:
        return "Active" if issued is not pd.NaT else "In Review"

    # Bare CLOSED is Final only when DATA carries a completion stamp;
    # otherwise it is an administrative close without finalization.
    if raw_key == "closed":
        return "Final" if resolved_final is not pd.NaT else "Inactive"

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


def _final_date_from_data(d: dict, finaled):
    """Resolve FINAL_DATE: PermitFinaledDate → search FINALED/CO → final insp."""
    if finaled is not pd.NaT:
        return finaled

    sd = _search_data(d)
    for key in ("FINALED", "CO ISSUED"):
        dt = _safe_to_datetime(sd.get(key))
        if dt is not pd.NaT:
            return dt

    candidates = []
    for insp in d.get("inspections") or []:
        if not isinstance(insp, dict):
            continue
        result = str(insp.get("Result") or "").strip().lower()
        if result not in _PASS_RESULTS:
            continue
        typ = str(insp.get("Type") or "")
        if not _FINAL_INSP_RE.search(typ):
            continue
        dt = _safe_to_datetime(insp.get("Completed"))
        if dt is not pd.NaT:
            candidates.append(dt)
    return max(candidates) if candidates else pd.NaT


# ── Per-record repair ───────────────────────────────────────────────────────

def _repair_record(row, d: dict, repairs: dict) -> None:
    raw_status, applied, issued, approved, finaled = _extract_fields(d)
    resolved_final = _final_date_from_data(d, finaled)
    expected = _expected_status(raw_status, issued, resolved_final)
    effective_status = _apply_status(repairs, row["STATUS_NORMALIZED"], expected)

    # -- FILE_DATE ← PermitAppliedDate --
    if applied is not pd.NaT:
        if pd.isna(row["FILE_DATE"]):
            repairs["FILE_DATE"] = applied
            repairs["FILE_DATE_FLAG"] = "FILLED"
        elif not _dates_equal(row["FILE_DATE"], applied):
            repairs["FILE_DATE"] = applied
            repairs["FILE_DATE_FLAG"] = "FIXED"

    # -- PERMIT_DATE ← IssuedDate, else ApprovedDate --
    permit_src = issued if issued is not pd.NaT else approved
    if permit_src is not pd.NaT:
        if pd.isna(row["PERMIT_DATE"]):
            if effective_status in ("Active", "Final", "Inactive"):
                # Inactive (expired/void/rejected) often still carries issuance.
                repairs["PERMIT_DATE"] = permit_src
                repairs["PERMIT_DATE_FLAG"] = "FILLED"
        elif not _dates_equal(row["PERMIT_DATE"], permit_src):
            # Prefer IssuedDate when present; only overwrite mismatches vs
            # the chosen source (issued beats approved).
            if issued is not pd.NaT and not _dates_equal(row["PERMIT_DATE"], issued):
                repairs["PERMIT_DATE"] = issued
                repairs["PERMIT_DATE_FLAG"] = "FIXED"

    # -- FINAL_DATE ← finaled / CO / final inspection; Final only --
    current_final = row["FINAL_DATE"]
    if effective_status == "Final":
        if resolved_final is not pd.NaT:
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
    Clermont permit records using information from the raw DATA JSON.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Clermont".  Must contain
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
    city = df[df["JURISDICTION"] == "Clermont"].copy()

    print(f"Clermont records: {len(city):,}\n")

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

    # Remaining Final gaps
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

    # Active/Final still missing PERMIT
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
        out_path = os.path.join(AGENT_DATA_PATH, "clermont_repaired_sample.parquet")
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote repaired sample → {out_path}")

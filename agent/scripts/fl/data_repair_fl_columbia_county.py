"""Data repair for Columbia County (FL) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Columbia County DATA is a flat county-portal extract with ``Status``,
``Submitted``, ``Issued``, ``Completed``, ``Expires``, ``Review``, and
``Inspection``. Two layout variants appear:

  - portal_geo:   includes street / city / state / zip (almost all rows)
  - portal_base:  same permit fields without those address keys (1 row)

Content suffixes further split by which canonical dates are set
(``_completed``, ``_issued``, ``_submitted``, ``_status_only``).

Canonical mappings:
  - DATA.Status (+ Issued / Completed when Status blank)
      → STATUS_NORMALIZED
  - Submitted; else earliest Review key date; else earliest
    Inspection Date; else Issued                     → FILE_DATE
  - Issued (ignoring post-completion reissues); else
    Review note announcing permit issuance           → PERMIT_DATE
  - Completed (Final only)                           → FINAL_DATE

Status rules:
  - Completed → Final
  - Permit Issued / Permit Reissued / reissue notes → Active
  - Final Review - Complete → Active (always issued here)
  - Blank Status + Completed → Final; + Issued → Active; else In Review
  - Other named review/pending statuses → Active if Issued present,
    else In Review

Known issues repaired:
  - 451 null STATUS_NORMALIZED (blank Status with Issued, plus many
    review-stage labels) → FILLED.
  - Stale STATUS_ORIGINAL ``permit issued`` while DATA.Status is
    Completed (18 rows) → FIXED to Final; FINAL_DATE filled.
  - Permit Issued / review-stage rows mislabeled Final or Active → FIXED.
  - Spurious PERMIT_DATE on unissued In Review rows → cleared.
  - Spurious FINAL_DATE on non-Final rows → cleared.
  - Missing FILE_DATE when Submitted blank → FILLED from Review /
    Inspection / Issued.
  - PERMIT_DATE disagreeing with Issued (when Issued is not a
    post-completion reissue) → FIXED.
  - Missing FINAL_DATE on Completed rows → FILLED.

Not repairable from DATA:
  - A minority of Final rows have empty Issued and no issuance Review
    note → PERMIT_DATE stays missing.
  - No cancel / void / expired Status values observed → Inactive unused.
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

_REVIEW_KEY_DATE_RE = re.compile(r"^(\d{1,2}/\d{1,2}/\d{4})$")
_ISSUANCE_NOTE_RE = re.compile(
    r"permit\s+issued|permit\s+reissued|created and approved",
    re.I,
)

_ACTIVE_STATUS_EXACT = {
    "Permit Issued",
    "Permit Reissued",
    "Permit reissued to reflect updated information.",
    "Final Review - Complete",
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
    """Parse a date value, returning pd.NaT on failure / blanks / OOR."""
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
        if s.startswith("0001-01-01"):
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


def _apply_date(repairs: dict, row, field: str, candidate) -> None:
    """Fill or fix *field* from *candidate* datetime (pd.NaT = no candidate)."""
    cand = _safe_to_datetime(candidate)
    if cand is pd.NaT:
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
    if not pd.isna(row[field]):
        repairs[field] = pd.NaT
        repairs[f"{field}_FLAG"] = "FIXED"


# ── Field extractors ─────────────────────────────────────────────────────────

def _portal_status(d: dict) -> str:
    return str(d.get("Status") or "").strip()


def _issued_dt(d: dict):
    return _safe_to_datetime(d.get("Issued"))


def _completed_dt(d: dict):
    return _safe_to_datetime(d.get("Completed"))


def _submitted_dt(d: dict):
    return _safe_to_datetime(d.get("Submitted"))


def _review_key_dates(d: dict) -> list:
    """Dates encoded as Review list item keys (M/D/YYYY)."""
    review = d.get("Review")
    if not isinstance(review, list):
        return []
    dates = []
    for item in review:
        if not isinstance(item, dict):
            continue
        for key in item.keys():
            m = _REVIEW_KEY_DATE_RE.match(str(key).strip())
            if not m:
                continue
            dt = _safe_to_datetime(m.group(1))
            if dt is not pd.NaT:
                dates.append(dt)
    return dates


def _earliest_review_date(d: dict):
    dates = _review_key_dates(d)
    return min(dates) if dates else pd.NaT


def _earliest_inspection_date(d: dict):
    insp = d.get("Inspection")
    if not isinstance(insp, list):
        return pd.NaT
    dates = []
    for item in insp:
        if not isinstance(item, dict):
            continue
        dt = _safe_to_datetime(item.get("Date"))
        if dt is not pd.NaT:
            dates.append(dt)
    return min(dates) if dates else pd.NaT


def _file_date_candidate(d: dict):
    """Prefer Submitted, else earliest Review / Inspection, else Issued."""
    submitted = _submitted_dt(d)
    if submitted is not pd.NaT:
        return submitted

    candidates = [
        _earliest_review_date(d),
        _earliest_inspection_date(d),
        _issued_dt(d),
    ]
    valid = [c for c in candidates if c is not pd.NaT]
    return min(valid) if valid else pd.NaT


def _issued_from_review(d: dict, before=None):
    """Earliest Review key whose note announces permit issuance."""
    review = d.get("Review")
    if not isinstance(review, list):
        return pd.NaT

    before_n = None
    if before is not None and before is not pd.NaT and not pd.isna(before):
        before_n = pd.Timestamp(before).normalize()

    dates = []
    for item in review:
        if not isinstance(item, dict):
            continue
        for key, note in item.items():
            if not _ISSUANCE_NOTE_RE.search(str(note or "")):
                continue
            m = _REVIEW_KEY_DATE_RE.match(str(key).strip())
            if not m:
                continue
            dt = _safe_to_datetime(m.group(1))
            if dt is pd.NaT:
                continue
            if before_n is not None and pd.Timestamp(dt).normalize() > before_n:
                continue
            dates.append(dt)
    return min(dates) if dates else pd.NaT


def _permit_date_candidate(d: dict):
    """Issued when it is not a post-completion reissue; else Review issuance."""
    issued = _issued_dt(d)
    completed = _completed_dt(d)

    if issued is not pd.NaT:
        if completed is pd.NaT or pd.isna(completed):
            return issued
        if pd.Timestamp(issued).normalize() <= pd.Timestamp(completed).normalize():
            return issued
        # Issued after Completed → reissue stamp; ignore for PERMIT_DATE.

    return _issued_from_review(d, before=completed)


def _expected_status(d: dict) -> Optional[str]:
    """Map portal Status (+ date presence) to STATUS_NORMALIZED."""
    status = _portal_status(d)
    issued = _issued_dt(d)
    completed = _completed_dt(d)

    if status == "Completed":
        return "Final"
    if not status and completed is not pd.NaT:
        return "Final"

    if status in _ACTIVE_STATUS_EXACT:
        return "Active"

    if not status:
        if issued is not pd.NaT:
            return "Active"
        return "In Review"

    # Named review / pending / misc workflow labels.
    if issued is not pd.NaT:
        return "Active"
    return "In Review"


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    if not isinstance(data_dict, dict):
        return "unknown"

    keys = set(data_dict.keys())
    if not {"Status", "Submitted", "Issued", "Completed"} <= keys:
        if "Status" not in keys:
            return "unknown"

    if {"street", "city", "zip"} & keys:
        base = "portal_geo"
    else:
        base = "portal_base"

    has_completed = _completed_dt(data_dict) is not pd.NaT
    has_issued = _issued_dt(data_dict) is not pd.NaT
    has_submitted = _submitted_dt(data_dict) is not pd.NaT

    if has_completed:
        suffix = "_completed"
    elif has_issued:
        suffix = "_issued"
    elif has_submitted:
        suffix = "_submitted"
    else:
        suffix = "_status_only"

    return base + suffix


# ── Per-record repair ────────────────────────────────────────────────────────

def _repair_record(row, d: dict, repairs: dict) -> None:
    """Repair one Columbia County portal record."""
    expected = _expected_status(d)
    effective_status = _apply_status(repairs, row["STATUS_NORMALIZED"], expected)

    # FILE_DATE ← Submitted / Review / Inspection / Issued
    _apply_date(repairs, row, "FILE_DATE", _file_date_candidate(d))

    # PERMIT_DATE ← Issued (or issuance Review); clear on In Review
    permit_src = _permit_date_candidate(d)
    if effective_status in ("Active", "Final"):
        if permit_src is not pd.NaT:
            _apply_date(repairs, row, "PERMIT_DATE", permit_src)
        # If no candidate, leave existing PERMIT_DATE (may be original
        # issuance retained after a post-completion reissue stamp).
    elif effective_status == "In Review":
        # Unissued applications should not carry a permit stamp.
        _clear_date(repairs, row, "PERMIT_DATE")

    # FINAL_DATE ← Completed for Final only; clear otherwise
    completed = _completed_dt(d)
    if effective_status == "Final":
        if completed is not pd.NaT:
            _apply_date(repairs, row, "FINAL_DATE", completed)
    else:
        _clear_date(repairs, row, "FINAL_DATE")


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Columbia County permit records using information from the raw DATA JSON.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Columbia County".  Must
        contain columns STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE,
        FINAL_DATE, and DATA.

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
        if d is None:
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
    from dotenv import load_dotenv

    load_dotenv("/Users/ekung/projects/la-permits-data/.env")
    MY_DATA_PATH = os.getenv("MY_DATA_PATH")
    AGENT_DATA_PATH = os.getenv("AGENT_DATA_PATH")
    filepath = os.path.join(MY_DATA_PATH, "processed_data", "permits_fl_sample.parquet")
    df = pd.read_parquet(filepath)
    city = df[df["JURISDICTION"] == "Columbia County"].copy()

    print(f"Columbia County records: {len(city):,}\n")

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

    print("\nFILE_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FILE_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} "
              f"({n_has / len(sub) if len(sub) else 0:.1%})")

    print("\nPERMIT_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["PERMIT_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} "
              f"({n_has / len(sub) if len(sub) else 0:.1%})")

    print("\nFINAL_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FINAL_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} "
              f"({n_has / len(sub) if len(sub) else 0:.1%})")

    # Sanity: dates vs DATA
    n_file_mismatch = 0
    n_permit_mismatch = 0
    n_final_mismatch = 0
    for idx, row in repaired.iterrows():
        d = _safe_parse(row["DATA"])
        if d is None:
            continue
        sub = _submitted_dt(d)
        if sub is not pd.NaT and not pd.isna(row["FILE_DATE"]):
            if not _dates_equal(row["FILE_DATE"], sub):
                n_file_mismatch += 1
        permit_src = _permit_date_candidate(d)
        if (
            permit_src is not pd.NaT
            and row["STATUS_NORMALIZED"] in ("Active", "Final")
            and not pd.isna(row["PERMIT_DATE"])
            and not _dates_equal(row["PERMIT_DATE"], permit_src)
        ):
            n_permit_mismatch += 1
        completed = _completed_dt(d)
        if (
            row["STATUS_NORMALIZED"] == "Final"
            and completed is not pd.NaT
            and not pd.isna(row["FINAL_DATE"])
            and not _dates_equal(row["FINAL_DATE"], completed)
        ):
            n_final_mismatch += 1

    print(f"\nFILE_DATE != Submitted (when both set): {n_file_mismatch}")
    print(f"PERMIT_DATE != candidate (Active/Final): {n_permit_mismatch}")
    print(f"FINAL_DATE != Completed (Final): {n_final_mismatch}")

    still_null = repaired[repaired["STATUS_NORMALIZED"].isna()]
    print(f"\nRemaining null STATUS_NORMALIZED: {len(still_null):,}")

    if AGENT_DATA_PATH:
        out_path = os.path.join(AGENT_DATA_PATH, "columbia_county_repaired_sample.parquet")
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote {out_path}")

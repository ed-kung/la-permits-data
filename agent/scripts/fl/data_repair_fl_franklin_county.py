"""Data repair for Franklin County (FL) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Franklin County DATA has two top-level key-set variants scraped from the
same portal:

  - simple: Status, Address , Permit #, Issue Date, Permit Type, Sub Type,
    Work Description (optional)
  - rich:   Status:, Address:, Permit #:, Issue Date, Permit Type, Sub Type,
            Work Description, Reviews, Inspections, Permit Details,
            Project #:, Description:, and optionally Balance Due:

Canonical fields:

  - Status / Status: (fallback Sub Type when Status is garbage /
      date / work-description misaligned) → STATUS_NORMALIZED
      (+ upgrade to Final when a passed Final Inspection exists;
      + upgrade In Review → Active when a real Issue Date exists)
  - Reviews.Start (earliest; fallback Issue Date from top-level or
      Permit Details; fallback date-as-Status on misaligned rows)
      → FILE_DATE
  - Issue Date (top-level) else Permit Details["Issue Date:"]
      (fallback date-as-Status on misaligned Closed rows)
      → PERMIT_DATE
  - Latest passed final-ish inspection date → FINAL_DATE

INFERRED_SCHEMA splits simple vs rich, then by which canonical dates are
available (``_issued_finaled``, ``_issued``, ``_finaled``, ``_applied``,
``_status_only``). Rich rows are further tagged ``_balanced`` when
``Balance Due:`` is present.

Known issues repaired:
  - Null STATUS_NORMALIZED for misaligned shells (date/work-description
    stored in Status, true status in Sub Type) and for
    Approved - Awaiting Payment → FILLED.
  - TEST labeled In Review with Sub Type Void → FIXED to Inactive.
  - Issued rows with a passed Final Inspection still labeled Active →
    FIXED to Final.
  - Under Review carrying a real Issue Date → FIXED to Active.
  - FILE_DATE sourced from Reviews.Completion instead of Start → FIXED.
  - Missing FILE_DATE filled from Reviews.Start or Issue Date.
  - Missing PERMIT_DATE on Active / Final filled from Issue Date sources
    (including date-as-Status on misaligned Closed rows).
  - Spurious PERMIT_DATE on In Review cleared.
  - Missing FINAL_DATE on Final filled from passed final inspections.
  - Spurious FINAL_DATE on non-Final cleared (none in sample).

Not repairable from DATA:
  - Most simple-schema Closed / CO Issued / CC Issued rows have no
    Inspections array → FINAL_DATE stays missing.
  - Some Void / incomplete shells have no parseable dates at all.
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

# Prefer whole-permit finals over trade-only finals when ranking.
_PRIMARY_FINAL_RE = re.compile(
    r"^final inspection(\s*\(home\))?$",
    re.IGNORECASE,
)

_DATE_AS_STATUS_RE = re.compile(r"^\d{1,2}/\d{1,2}/\d{2,4}$")

_STATUS_LIKE_SUBTYPES = {
    "closed",
    "void",
    "issued",
    "co issued",
    "cc issued",
    "under review",
    "denied",
    "online application received",
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


def _present(dt) -> bool:
    return dt is not pd.NaT and not pd.isna(dt)


def _clean_status_text(val) -> Optional[str]:
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return None
    s = str(val).strip()
    return s or None


# ── Field extractors ─────────────────────────────────────────────────────────

def _raw_status_fields(d: dict):
    """Return (primary_status, subtype, status_as_date, misaligned)."""
    primary = _clean_status_text(d.get("Status") if "Status" in d else d.get("Status:"))
    subtype = _clean_status_text(d.get("Sub Type"))
    status_as_date = _safe_to_datetime(primary) if primary else pd.NaT
    misaligned = False
    if primary is not None and subtype is not None:
        primary_l = primary.lower()
        subtype_l = subtype.lower()
        # Status looks like a date / work description while Sub Type
        # holds the lifecycle label (scraping column shift).
        if subtype_l in _STATUS_LIKE_SUBTYPES and primary_l not in _STATUS_MAP:
            misaligned = True
    return primary, subtype, status_as_date, misaligned


def _issue_date(d: dict):
    """Issue Date from top-level, else Permit Details."""
    top = _safe_to_datetime(d.get("Issue Date"))
    if _present(top):
        return top
    details = d.get("Permit Details")
    if isinstance(details, dict):
        return _safe_to_datetime(details.get("Issue Date:"))
    return pd.NaT


def _review_dates(d: dict):
    """Return (earliest Start, earliest Completion) from Reviews."""
    reviews = d.get("Reviews")
    starts, completions = [], []

    def _consume(item):
        if not isinstance(item, dict):
            return
        s = _safe_to_datetime(item.get("Start"))
        c = _safe_to_datetime(item.get("Completion"))
        if _present(s):
            starts.append(s)
        if _present(c):
            completions.append(c)

    if isinstance(reviews, dict):
        _consume(reviews)
    elif isinstance(reviews, list):
        for item in reviews:
            _consume(item)

    earliest_start = min(starts) if starts else pd.NaT
    earliest_comp = min(completions) if completions else pd.NaT
    return earliest_start, earliest_comp


def _insp_passed(status: str) -> bool:
    s = (status or "").split("\r")[0].strip().lower()
    return s.startswith("passed") or s in {
        "pass", "approved", "complete", "completed",
    }


def _final_insp_date(d: dict, primary_only: bool = False):
    """Latest passed final-ish inspection date.

    If *primary_only*, only count whole-permit ``Final Inspection`` rows
    (used to decide Active → Final upgrades).
    """
    insp = d.get("Inspections")
    if not isinstance(insp, list):
        return pd.NaT

    primary_dates = []
    other_dates = []
    for item in insp:
        if not isinstance(item, dict):
            continue
        itype = str(item.get("Inspection Type") or "").strip()
        if not _insp_passed(str(item.get("Status") or "")):
            continue
        dt = _safe_to_datetime(item.get("Date"))
        if not _present(dt):
            continue
        if _PRIMARY_FINAL_RE.match(itype):
            primary_dates.append(dt)
        elif _FINAL_INSP_RE.search(itype):
            other_dates.append(dt)

    if primary_dates:
        return max(primary_dates)
    if primary_only:
        return pd.NaT
    return max(other_dates) if other_dates else pd.NaT


def _file_date_src(d: dict, status_as_date, misaligned: bool):
    """Prefer Reviews.Start, else Issue Date, else misaligned Status date."""
    start, _comp = _review_dates(d)
    if _present(start):
        return start
    issued = _issue_date(d)
    if _present(issued):
        return issued
    if misaligned and _present(status_as_date):
        return status_as_date
    return pd.NaT


def _permit_date_src(d: dict, status_as_date, misaligned: bool):
    issued = _issue_date(d)
    if _present(issued):
        return issued
    if misaligned and _present(status_as_date):
        return status_as_date
    return pd.NaT


# ── Schema classification ────────────────────────────────────────────────────

def _base_schema(data_dict: dict) -> str:
    if "Reviews" in data_dict or "Permit Details" in data_dict:
        if "Balance Due:" in data_dict:
            return "rich_balanced"
        return "rich"
    if "Status" in data_dict or "Status:" in data_dict:
        return "simple"
    return "unknown"


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"

    base = _base_schema(data_dict)
    if base == "unknown":
        return "unknown"

    _primary, _subtype, status_as_date, misaligned = _raw_status_fields(data_dict)
    start, _ = _review_dates(data_dict)
    issued = _permit_date_src(data_dict, status_as_date, misaligned)
    final = _final_insp_date(data_dict)
    has_applied = _present(start) or (
        misaligned and _present(status_as_date)
    )
    has_issued = _present(issued)
    has_final = _present(final)

    if has_issued and has_final:
        return f"{base}_issued_finaled"
    if has_issued:
        return f"{base}_issued"
    if has_final:
        return f"{base}_finaled"
    if has_applied:
        return f"{base}_applied"
    return f"{base}_status_only"


# ── Status mapping ───────────────────────────────────────────────────────────

_STATUS_MAP = {
    # Final
    "closed": "Final",
    "co issued": "Final",
    "cc issued": "Final",
    # Active
    "issued": "Active",
    # In Review
    "under review": "In Review",
    "online application received": "In Review",
    "incomplete application": "In Review",
    "approved - awaiting payment": "In Review",
    # Inactive
    "void": "Inactive",
    "denied": "Inactive",
    "test": "Inactive",
}


def _lookup_status(label: Optional[str]) -> Optional[str]:
    if label is None:
        return None
    return _STATUS_MAP.get(label.strip().lower())


def _expected_status(d: dict) -> Optional[str]:
    primary, subtype, status_as_date, misaligned = _raw_status_fields(d)
    issued = _issue_date(d)
    primary_final = _final_insp_date(d, primary_only=True)

    mapped = _lookup_status(primary)
    if mapped is None and misaligned:
        mapped = _lookup_status(subtype)
    if mapped is None and misaligned and _present(status_as_date):
        # Date-as-Status with Closed subtype already handled; if subtype
        # mapped above we're done. Otherwise no signal.
        pass

    if mapped is None:
        # No mappable status text. Infer from dates / inspections only.
        if _present(primary_final):
            return "Final"
        if _present(issued):
            return "Active"
        return None

    # Terminal inactive wins over inspection evidence.
    if mapped == "Inactive":
        return "Inactive"

    # Passed whole-permit Final Inspection upgrades Issued → Final.
    if mapped == "Active" and _present(primary_final):
        return "Final"

    # Pre-issuance labels with a real issue date are post-issuance.
    if mapped == "In Review" and _present(issued):
        return "Active"

    # Closed / CO / CC already Final; if somehow lacking mapped Final but
    # has primary final insp, keep Final.
    if mapped == "Final":
        return "Final"

    return mapped


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


# ── Per-record repair ───────────────────────────────────────────────────────

def _repair_record(row, d: dict, repairs: dict) -> None:
    _primary, _subtype, status_as_date, misaligned = _raw_status_fields(d)
    expected = _expected_status(d)
    effective_status = _apply_status(repairs, row["STATUS_NORMALIZED"], expected)

    start, _comp = _review_dates(d)
    file_src = _file_date_src(d, status_as_date, misaligned)
    permit_src = _permit_date_src(d, status_as_date, misaligned)
    final_src = _final_insp_date(d)

    # -- FILE_DATE ← Reviews.Start else Issue Date else status-as-date --
    if _present(file_src):
        if pd.isna(row["FILE_DATE"]):
            repairs["FILE_DATE"] = file_src
            repairs["FILE_DATE_FLAG"] = "FILLED"
        elif _present(start) and not _dates_equal(row["FILE_DATE"], start):
            # Upstream often stored Reviews.Completion; prefer Start.
            repairs["FILE_DATE"] = start
            repairs["FILE_DATE_FLAG"] = "FIXED"

    # -- PERMIT_DATE ← Issue Date (+ misaligned Status date) --
    current_permit = row["PERMIT_DATE"]
    if effective_status in ("Active", "Final", "Inactive"):
        if _present(permit_src):
            if pd.isna(current_permit):
                repairs["PERMIT_DATE"] = permit_src
                repairs["PERMIT_DATE_FLAG"] = "FILLED"
            elif not _dates_equal(current_permit, permit_src):
                repairs["PERMIT_DATE"] = permit_src
                repairs["PERMIT_DATE_FLAG"] = "FIXED"
    elif effective_status == "In Review" and not pd.isna(current_permit):
        repairs["PERMIT_DATE"] = pd.NaT
        repairs["PERMIT_DATE_FLAG"] = "FIXED"

    # -- FINAL_DATE ← passed final inspection; Final only --
    current_final = row["FINAL_DATE"]
    if effective_status == "Final":
        if _present(final_src):
            if pd.isna(current_final):
                repairs["FINAL_DATE"] = final_src
                repairs["FINAL_DATE_FLAG"] = "FILLED"
            elif not _dates_equal(current_final, final_src):
                repairs["FINAL_DATE"] = final_src
                repairs["FINAL_DATE_FLAG"] = "FIXED"
    elif not pd.isna(current_final):
        repairs["FINAL_DATE"] = pd.NaT
        repairs["FINAL_DATE_FLAG"] = "FIXED"


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Franklin County permit records using information from the raw DATA JSON.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Franklin County".  Must
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
    city = df[df["JURISDICTION"] == "Franklin County"].copy()

    print(f"Franklin County records: {len(city):,}\n")

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
        schema_counts = Counter()
        for idx in final_miss.index:
            d = _safe_parse(repaired.at[idx, "DATA"])
            schema_counts[repaired.at[idx, "INFERRED_SCHEMA"]] += 1
            if d is None:
                continue
            raw = _clean_status_text(
                d.get("Status") if "Status" in d else d.get("Status:")
            ) or "__EMPTY__"
            ps_counts[raw] += 1
        print("  by Status:", dict(ps_counts))
        print("  by schema:", dict(schema_counts))

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
            raw = _clean_status_text(
                d.get("Status") if "Status" in d else d.get("Status:")
            ) or "__EMPTY__"
            ps_counts[raw] += 1
        print("  by Status:", dict(ps_counts))

    if AGENT_DATA_PATH:
        out_path = os.path.join(
            AGENT_DATA_PATH, "franklin_county_repaired_sample.parquet"
        )
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote repaired sample → {out_path}")

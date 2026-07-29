"""Data repair for Imperial (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Imperial DATA is a municipal portal scrape with two top-level shapes
(INFERRED_SCHEMA):

  - list:    search/list row — Status, Issue Date, Permit# / Permit #,
             Permit Type, Sub Type, optional Work Description / Address
  - detail:  detail page — Status:, Permit Details, Reviews, Inspections,
             Issue Date (usually empty), Project #:, etc.

Canonical mappings:
  - Status / Status: (Under Review, Approved, Issued, Closed, …)
                                                      → STATUS_NORMALIZED
  - Passed "Job Complete" inspection                  → Final (override)
  - Application Intake Start, else earliest Review
    Start                                             → FILE_DATE
  - Parseable Issue Date, else Final Review Completion
    (Active / Final only)                             → PERMIT_DATE
  - Passed Job Complete inspection Date (Final only)  → FINAL_DATE

Known issues repaired:
  - Portal Status lags behind a passed Job Complete inspection
    (Under Review / Approved / Issued / blank) → FIXED/FILLED to Final;
    FINAL_DATE FILLED from the inspection Date.
  - FILE_DATE on detail rows was taken from a Review Completion
    (usually Final Review) rather than the application/review start →
    FIXED to Application Intake Start or earliest Review Start; missing
    FILE_DATE FILLED from the same sources.
  - Active / Final shells missing PERMIT_DATE with no parseable Issue
    Date → FILLED from Final Review Completion when present.
  - List-schema Issue Date is often a work-description string (column
    shift when Work Description is absent); only parseable calendar
    dates are treated as issuance.

Not repairable / left as-is:
  - ~244 rows whose Status field holds a permit-type / description /
    date fragment (Garage Sale Permit, PV System, patio, MM/DD/YYYY,
    etc.) rather than a lifecycle label — STATUS_NORMALIZED stays null
    unless a Job Complete Pass is present.
  - Closed Final garage-sale shells with empty Issue Date, Reviews, and
    Inspections — no FILE / PERMIT / FINAL dates in DATA.
  - List-schema rows have no Reviews, so FILE_DATE cannot be filled.
  - Non-date Issue Date text is not used as PERMIT_DATE.
"""

from __future__ import annotations

import json
import math
import re
from typing import Optional

import numpy as np
import pandas as pd


_MIN_YEAR = 1990
_MAX_YEAR = 2035

# Portal Status / Status: → STATUS_NORMALIZED (case-insensitive lookup).
_STATUS_MAP = {
    "under review": "In Review",
    "online application received": "In Review",
    "pending": "In Review",
    "approved": "Active",
    "issued": "Active",
    "closed": "Final",
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
        if not data.strip():
            return None
        return json.loads(data)
    return data


def _safe_to_datetime(val):
    """Parse a date value, returning pd.NaT on failure or implausible year.

    Rejects alphabetic strings that are not leading-digit dates so that
    work-description text parked in Issue Date is not treated as a stamp.
    """
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return pd.NaT
    if isinstance(val, dict):
        return pd.NaT
    if isinstance(val, str):
        s = val.strip()
        if not s:
            return pd.NaT
        # "Scheduled for", "PV System", "New House", etc.
        if re.search(r"[A-Za-z]", s) and not re.match(r"^\d", s):
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


def _same_calendar_day(a, b) -> bool:
    if a is pd.NaT or b is pd.NaT or pd.isna(a) or pd.isna(b):
        return False
    return pd.Timestamp(a).tz_localize(None).normalize() == pd.Timestamp(
        b
    ).tz_localize(None).normalize()


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    if not isinstance(data_dict, dict) or not data_dict:
        return "unknown"
    keys = set(data_dict.keys())
    if keys & {"Permit Details", "Inspections", "Reviews", "Status:"}:
        return "detail"
    if keys & {"Status", "Permit#", "Permit #", "Issue Date", "Permit Type"}:
        return "list"
    return "unknown"


def _raw_status(d: dict) -> Optional[str]:
    for key in ("Status", "Status:"):
        raw = d.get(key)
        if raw is None:
            continue
        s = str(raw).strip()
        if s:
            return s
    return None


def _mapped_status(d: dict) -> Optional[str]:
    raw = _raw_status(d)
    if raw is None:
        return None
    return _STATUS_MAP.get(raw.lower().strip())


def _job_complete_date(d: dict):
    """Latest passed Job Complete inspection date."""
    best = pd.NaT
    inspections = d.get("Inspections")
    if not isinstance(inspections, list):
        return best
    for item in inspections:
        if not isinstance(item, dict):
            continue
        itype = str(item.get("Inspection Type") or "").lower()
        status = str(item.get("Status") or "").strip().lower()
        if "job complete" not in itype:
            continue
        if status != "pass":
            continue
        dt = _safe_to_datetime(item.get("Date"))
        if dt is pd.NaT:
            continue
        if best is pd.NaT or dt > best:
            best = dt
    return best


def _application_intake_start(d: dict):
    reviews = d.get("Reviews")
    if not isinstance(reviews, list):
        return pd.NaT
    best = pd.NaT
    for item in reviews:
        if not isinstance(item, dict):
            continue
        if "application intake" not in str(item.get("Task") or "").lower():
            continue
        dt = _safe_to_datetime(item.get("Start"))
        if dt is pd.NaT:
            continue
        if best is pd.NaT or dt < best:
            best = dt
    return best


def _earliest_review_start(d: dict):
    reviews = d.get("Reviews")
    if not isinstance(reviews, list):
        return pd.NaT
    best = pd.NaT
    for item in reviews:
        if not isinstance(item, dict):
            continue
        dt = _safe_to_datetime(item.get("Start"))
        if dt is pd.NaT:
            continue
        if best is pd.NaT or dt < best:
            best = dt
    return best


def _file_date_candidate(d: dict):
    """Prefer Application Intake Start; else earliest Review Start."""
    intake = _application_intake_start(d)
    if intake is not pd.NaT:
        return intake
    return _earliest_review_start(d)


def _issue_date(d: dict):
    """Parseable Issue Date from list or Permit Details."""
    dt = _safe_to_datetime(d.get("Issue Date"))
    if dt is not pd.NaT:
        return dt
    details = d.get("Permit Details")
    if isinstance(details, dict):
        return _safe_to_datetime(details.get("Issue Date:"))
    return pd.NaT


def _final_review_completion(d: dict):
    """Latest Final Review Completion stamp."""
    reviews = d.get("Reviews")
    if not isinstance(reviews, list):
        return pd.NaT
    best = pd.NaT
    for item in reviews:
        if not isinstance(item, dict):
            continue
        if "final review" not in str(item.get("Task") or "").lower():
            continue
        dt = _safe_to_datetime(item.get("Completion"))
        if dt is pd.NaT:
            continue
        if best is pd.NaT or dt > best:
            best = dt
    return best


def _expected_status(d: dict) -> Optional[str]:
    """Lifecycle status from portal label, with Job Complete → Final."""
    mapped = _mapped_status(d)
    if _job_complete_date(d) is not pd.NaT:
        return "Final"
    return mapped


def _set_field(repairs: dict, field: str, new_val, current_val):
    """Record FILLED/FIXED repair for *field* when *new_val* differs."""
    if new_val is pd.NaT or new_val is None or pd.isna(new_val):
        return
    cur_missing = current_val is None or (
        not isinstance(current_val, str) and pd.isna(current_val)
    )
    if isinstance(new_val, str):
        if cur_missing:
            repairs[field] = new_val
            repairs[f"{field}_FLAG"] = "FILLED"
        elif str(current_val) != str(new_val):
            repairs[field] = new_val
            repairs[f"{field}_FLAG"] = "FIXED"
        return

    if cur_missing:
        repairs[field] = new_val
        repairs[f"{field}_FLAG"] = "FILLED"
    elif not _same_calendar_day(current_val, new_val):
        repairs[field] = new_val
        repairs[f"{field}_FLAG"] = "FIXED"


# ── Per-record repair ────────────────────────────────────────────────────────

def _repair_record(row, d: dict, repairs: dict):
    expected = _expected_status(d)
    _set_field(repairs, "STATUS_NORMALIZED", expected, row["STATUS_NORMALIZED"])
    effective_status = repairs.get("STATUS_NORMALIZED", row["STATUS_NORMALIZED"])
    if isinstance(effective_status, float) and math.isnan(effective_status):
        effective_status = None

    file_cand = _file_date_candidate(d)
    _set_field(repairs, "FILE_DATE", file_cand, row["FILE_DATE"])

    issue = _issue_date(d)
    fr = _final_review_completion(d)
    permit_cand = issue
    if permit_cand is pd.NaT and effective_status in ("Active", "Final"):
        permit_cand = fr
    if effective_status in ("Active", "Final"):
        _set_field(repairs, "PERMIT_DATE", permit_cand, row["PERMIT_DATE"])
    elif permit_cand is not pd.NaT and (
        row["PERMIT_DATE"] is None or pd.isna(row["PERMIT_DATE"])
    ):
        # Keep existing Issue Date → PERMIT_DATE fills for In Review rows
        # that already carry a real issuance stamp in DATA but were left
        # blank (none in the current sample; harmless if future feeds lag).
        if issue is not pd.NaT:
            _set_field(repairs, "PERMIT_DATE", issue, row["PERMIT_DATE"])

    if effective_status == "Final":
        jc = _job_complete_date(d)
        _set_field(repairs, "FINAL_DATE", jc, row["FINAL_DATE"])


# ── Main entry point ─────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Imperial (CA) permit records using information from the raw DATA JSON.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Imperial". Must contain
        columns STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, FINAL_DATE,
        and DATA.

    Returns
    -------
    pd.DataFrame
        Copy of *df* with corrected field values, an INFERRED_SCHEMA column
        naming the DATA JSON sub-schema identified for each record, and new
        flag columns: STATUS_NORMALIZED_FLAG, FILE_DATE_FLAG,
        PERMIT_DATE_FLAG, FINAL_DATE_FLAG. Flag values are "FILLED"
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

    # Normalize repaired date columns to datetime64 (avoid mixed date/Timestamp).
    for col in ("FILE_DATE", "PERMIT_DATE", "FINAL_DATE"):
        out[col] = pd.to_datetime(out[col], utc=True, errors="coerce")

    return out


# ── CLI: run standalone to preview repair stats ──────────────────────────────

if __name__ == "__main__":
    import os
    from dotenv import load_dotenv

    load_dotenv("/Users/ekung/projects/la-permits-data/.env")
    MY_DATA_PATH = os.getenv("MY_DATA_PATH")
    AGENT_DATA_PATH = os.getenv("AGENT_DATA_PATH")
    filepath = os.path.join(MY_DATA_PATH, "processed_data", "permits_ca_sample.parquet")
    df = pd.read_parquet(filepath)
    city = df[(df["JURISDICTION"] == "Imperial") & (df["STATE"] == "CA")].copy()

    print(f"Imperial records: {len(city):,}\n")
    repaired = data_repair(city)

    print("INFERRED_SCHEMA:")
    for s, c in repaired["INFERRED_SCHEMA"].value_counts(dropna=False).items():
        print(f"  {str(s):20s}: {c:>4,}")
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

    print("\nStatus transitions (where FLAG set):")
    mask = repaired["STATUS_NORMALIZED_FLAG"].notna()
    if mask.any():
        trans = (
            pd.DataFrame(
                {
                    "before": city.loc[mask, "STATUS_NORMALIZED"].fillna("nan").astype(str),
                    "after": repaired.loc[mask, "STATUS_NORMALIZED"].fillna("nan").astype(str),
                }
            )
            .value_counts()
            .sort_values(ascending=False)
        )
        for (b, a), c in trans.items():
            print(f"  {b:15s} → {a:15s}: {c:>4,}")

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

    print("\nFILE_DATE coverage:")
    print(f"  before: {city['FILE_DATE'].notna().sum()} / {len(city)}")
    print(f"  after:  {repaired['FILE_DATE'].notna().sum()} / {len(repaired)}")

    if AGENT_DATA_PATH:
        out_dir = os.path.join(AGENT_DATA_PATH, "repaired")
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, "permits_ca_imperial_repaired.parquet")
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote {out_path}")

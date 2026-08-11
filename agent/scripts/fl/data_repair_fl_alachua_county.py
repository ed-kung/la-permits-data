"""Data repair for Alachua County (FL) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Alachua County DATA comes from a citizen-portal scrape. Every row has the
same core keys (``Status:``, ``Permit Details``, ``Reviews``,
``Inspections``, ``Issue Date``, ``Permit Type``, …) but form fields and
workflow depth vary. Sub-schemas:

  - pas:      Permit Type == Pre-Application Screening
  - workflow: dated Reviews and/or Inspections present
  - legacy:   no dated workflow (mostly old converted records)

Canonical mappings:
  - DATA['Status:']                         → STATUS_NORMALIZED
  - earliest Review Start (else Completion,
    else Permit Details Issue Date)         → FILE_DATE
  - Permit Details['Issue Date:']
    (else Review Complete / latest approved
    or latest review Completion)            → PERMIT_DATE
  - latest successful final-like Inspection
    (else Review Complete / latest review
    Completion / Issue Date for Final)      → FINAL_DATE

Known issues repaired:
  - STATUS_NORMALIZED missing for PAS Approved and Irrigation
    Resubmittal Required → FILLED.
  - Closed Administratively mapped to Final despite almost never having
    a final inspection → FIXED to Inactive.
  - FILE_DATE often copied from Issue Date / late review Completion
    even when an earlier Review Start exists → FIXED.
  - FILE_DATE / PERMIT_DATE / FINAL_DATE missing despite dates in
    Permit Details, Reviews, or Inspections → FILLED.
  - FINAL_DATE missing on all rows in the FL sample; filled from
    Pass/Approved final inspections (including trade finals and
    CO Request) and from Review Complete for PAS / desk reviews.

Not repairable / left as-is:
  - Legacy Void / Closed Administratively shells with no Reviews and no
    Issue Date cannot get a FILE_DATE.
  - In Review rows with empty Reviews (no dates in DATA) stay missing
    FILE_DATE / PERMIT_DATE.
  - Some Closed lien-search / misc records never issued a permit →
    PERMIT_DATE may stay missing even after status is Final; FINAL_DATE
    is then taken from the last review Completion when available.
"""

from __future__ import annotations

import json
import math
import re
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
        return json.loads(data)
    return data


def _safe_to_datetime(val):
    """Parse a date value, returning pd.NaT on failure."""
    if val is None or (isinstance(val, str) and not str(val).strip()):
        return pd.NaT
    try:
        return pd.to_datetime(val)
    except (ValueError, TypeError):
        return pd.NaT


def _dates_equal(a, b) -> bool:
    """Compare two datelike values at calendar-day resolution."""
    da = _safe_to_datetime(a)
    db = _safe_to_datetime(b)
    if da is pd.NaT or db is pd.NaT:
        return False
    return da.normalize() == db.normalize()


def _clean_text(val) -> str:
    """Normalize portal status strings that embed 'View Comments' junk."""
    if val is None:
        return ""
    text = str(val).replace("\r", "\n")
    return text.split("\n")[0].strip()


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    ptype = str(data_dict.get("Permit Type") or "")
    if ptype == "Pre-Application Screening":
        return "pas"

    reviews = data_dict.get("Reviews") or []
    inspections = data_dict.get("Inspections") or []
    has_dated_review = False
    if isinstance(reviews, list):
        for r in reviews:
            if not isinstance(r, dict):
                continue
            if _safe_to_datetime(r.get("Start")) is not pd.NaT:
                has_dated_review = True
                break
            if _safe_to_datetime(r.get("Completion")) is not pd.NaT:
                has_dated_review = True
                break
    has_inspections = isinstance(inspections, list) and len(inspections) > 0
    if has_dated_review or has_inspections:
        return "workflow"
    return "legacy"


# ── Status mapping ───────────────────────────────────────────────────────────

_STATUS_MAP = {
    "Closed": "Final",
    "Complete": "Final",
    "COED": "Final",
    "PAS Approved": "Final",
    "Issued": "Active",
    "Approved": "Active",
    "Under Review": "In Review",
    "Online Application Received": "In Review",
    "Payment Due": "In Review",
    "Resubmittal Required": "In Review",
    "Irrigation Resubmittal Required": "In Review",
    "SUSPEND": "In Review",
    "Void": "Inactive",
    "Expired": "Inactive",
    "Withdrawn": "Inactive",
    "Denied": "Inactive",
    # Admin closures are not inspection-finaled completions.
    "Closed Administratively": "Inactive",
}


_PASS_STATUSES = {
    "approved",
    "pass",
    "passed",
    "complete",
    "completed",
}


def _apply_status(repairs: dict, current, raw_status: Optional[str]) -> Optional[str]:
    """Map raw status → STATUS_NORMALIZED; return effective status."""
    if raw_status is None:
        return current if not (isinstance(current, float) and pd.isna(current)) else None

    expected = _STATUS_MAP.get(_clean_text(raw_status))
    if expected is None:
        return current if not (isinstance(current, float) and pd.isna(current)) else None

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


# ── Date extractors ──────────────────────────────────────────────────────────

def _issue_date(d: dict):
    details = d.get("Permit Details")
    if isinstance(details, dict):
        for key in ("Issue Date:", "Issue Date"):
            dt = _safe_to_datetime(details.get(key))
            if dt is not pd.NaT:
                return dt
    # Top-level Issue Date is present on every row but always null in sample.
    return _safe_to_datetime(d.get("Issue Date"))


def _review_dates(d: dict):
    """Return (starts, completions, review_complete_completion, latest_approved_completion)."""
    starts = []
    completions = []
    review_complete = pd.NaT
    approved_completions = []

    reviews = d.get("Reviews") or []
    if not isinstance(reviews, list):
        return starts, completions, review_complete, approved_completions

    for r in reviews:
        if not isinstance(r, dict):
            continue
        task = _clean_text(r.get("Task")).lower()
        status = _clean_text(r.get("Status")).lower()
        start = _safe_to_datetime(r.get("Start"))
        comp = _safe_to_datetime(r.get("Completion"))
        if start is not pd.NaT:
            starts.append(start)
        if comp is not pd.NaT:
            completions.append(comp)
            if status in _PASS_STATUSES or status.startswith("approved"):
                approved_completions.append(comp)
            if "review complete" in task and (
                status in _PASS_STATUSES or status.startswith("approved") or status == ""
            ):
                # Prefer the latest Review Complete when several exist.
                if review_complete is pd.NaT or comp > review_complete:
                    review_complete = comp

    return starts, completions, review_complete, approved_completions


def _file_date_candidate(d: dict):
    """Application / submittal date proxy."""
    starts, completions, _, _ = _review_dates(d)

    # Prefer Application Intake Start when present.
    reviews = d.get("Reviews") or []
    intake_starts = []
    intake_comps = []
    if isinstance(reviews, list):
        for r in reviews:
            if not isinstance(r, dict):
                continue
            task = _clean_text(r.get("Task")).lower()
            if "intake" in task:
                st = _safe_to_datetime(r.get("Start"))
                cp = _safe_to_datetime(r.get("Completion"))
                if st is not pd.NaT:
                    intake_starts.append(st)
                if cp is not pd.NaT:
                    intake_comps.append(cp)
    if intake_starts:
        return min(intake_starts)
    if starts:
        return min(starts)
    if intake_comps:
        return min(intake_comps)
    if completions:
        return min(completions)
    return _issue_date(d)


def _permit_date_candidate(d: dict):
    issue = _issue_date(d)
    if issue is not pd.NaT:
        return issue

    _, completions, review_complete, approved_completions = _review_dates(d)
    if review_complete is not pd.NaT:
        return review_complete
    if approved_completions:
        return max(approved_completions)
    # Desk reviews (lien search, misc) often close without Issue Date or an
    # "Approved" review status — use latest review Completion as issuance proxy.
    if completions:
        return max(completions)
    return pd.NaT


def _is_final_inspection(inspection_type: str) -> bool:
    itype = inspection_type.lower()
    if "final" in itype:
        return True
    if "co request" in itype:
        return True
    if re.search(r"\b7090\b", itype):
        return True
    return False


def _final_date_candidate(d: dict, raw_status: str):
    """Completion / sign-off date for Final records."""
    inspections = d.get("Inspections") or []
    final_dates = []
    if isinstance(inspections, list):
        for insp in inspections:
            if not isinstance(insp, dict):
                continue
            status = _clean_text(insp.get("Status")).lower()
            if status not in _PASS_STATUSES:
                continue
            itype = str(insp.get("Inspection Type") or "")
            if not _is_final_inspection(itype):
                continue
            dt = _safe_to_datetime(insp.get("Date"))
            if dt is not pd.NaT:
                final_dates.append(dt)
    if final_dates:
        return max(final_dates)

    # Desk / PAS completions: no field inspection final.
    _, completions, review_complete, approved_completions = _review_dates(d)
    if review_complete is not pd.NaT:
        return review_complete

    status = _clean_text(raw_status)
    if status in ("PAS Approved", "Complete", "Closed", "COED"):
        if approved_completions:
            return max(approved_completions)
        if completions:
            return max(completions)
        return _issue_date(d)

    return pd.NaT


# ── Per-record repair ────────────────────────────────────────────────────────

def _repair_record(row, d: dict, repairs: dict):
    raw_status = d.get("Status:")
    effective_status = _apply_status(repairs, row["STATUS_NORMALIZED"], raw_status)

    # -- FILE_DATE --
    file_cand = _file_date_candidate(d)
    _apply_date(repairs, row, "FILE_DATE", file_cand)

    # -- PERMIT_DATE --
    permit_cand = _permit_date_candidate(d)
    permit_dt = _safe_to_datetime(permit_cand)
    if permit_dt is not pd.NaT:
        if pd.isna(row["PERMIT_DATE"]):
            if effective_status in ("Active", "Final"):
                repairs["PERMIT_DATE"] = permit_dt
                repairs["PERMIT_DATE_FLAG"] = "FILLED"
        elif not _dates_equal(row["PERMIT_DATE"], permit_dt):
            repairs["PERMIT_DATE"] = permit_dt
            repairs["PERMIT_DATE_FLAG"] = "FIXED"

    # -- FINAL_DATE --
    if effective_status == "Final":
        final_cand = _final_date_candidate(d, raw_status or "")
        _apply_date(repairs, row, "FINAL_DATE", final_cand)


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Alachua County permit records using information from the raw DATA JSON.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Alachua County".  Must contain
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

    for col in ("FILE_DATE", "PERMIT_DATE", "FINAL_DATE"):
        out[col] = pd.to_datetime(out[col], errors="coerce")

    return out


# ── CLI: run standalone to preview repair stats ─────────────────────────────

if __name__ == "__main__":
    import os
    from dotenv import load_dotenv

    load_dotenv("/Users/ekung/projects/la-permits-data/.env")
    MY_DATA_PATH = os.getenv("MY_DATA_PATH")
    filepath = os.path.join(MY_DATA_PATH, "processed_data", "permits_fl_sample.parquet")
    df = pd.read_parquet(filepath)
    ac = df[df["JURISDICTION"] == "Alachua County"].copy()

    print(f"Alachua County records: {len(ac):,}\n")

    repaired = data_repair(ac)

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

        before_missing = ac[field].isna().sum()
        after_missing = repaired[field].isna().sum()
        print(f"  Missing before: {before_missing:>4,}   Missing after: {after_missing:>4,}")
        print()

    print("STATUS_NORMALIZED distribution:")
    print("  Before:")
    for s, c in ac["STATUS_NORMALIZED"].value_counts(dropna=False).items():
        print(f"    {str(s):15s}: {c:>4,}")
    print("  After:")
    for s, c in repaired["STATUS_NORMALIZED"].value_counts(dropna=False).items():
        print(f"    {str(s):15s}: {c:>4,}")

    print("\nFILE_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FILE_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({n_has / max(len(sub), 1):.1%})")

    print("\nPERMIT_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["PERMIT_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({n_has / max(len(sub), 1):.1%})")

    print("\nFINAL_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FINAL_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({n_has / max(len(sub), 1):.1%})")

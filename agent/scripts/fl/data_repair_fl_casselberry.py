"""Data repair for Casselberry (FL) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Casselberry DATA comes from a citizen-portal scrape. Every row has the
same core keys (``Status:``, ``Permit Details``, ``Reviews``,
``Inspections``, ``Issue Date``, ``Permit Type``, …) but form fields and
workflow depth vary. ``Reviews`` / ``Inspections`` are usually lists but
occasionally a bare dict. Content variants (INFERRED_SCHEMA):

  - issued_insp_rev: Issue Date + Inspections + Reviews
  - issued_insp:     Issue Date + Inspections
  - issued_rev:      Issue Date + Reviews
  - issued:          Issue Date only
  - insp_rev:        Inspections + Reviews (no Issue Date)
  - rev:             Reviews only
  - insp:            Inspections only
  - minimal:         no Issue Date / Reviews / Inspections
  - missing / unknown

Canonical mappings:
  - DATA['Status:'] (else Issue Date /
    approved final inspection inference)    → STATUS_NORMALIZED
  - earliest Review Start (else Completion;
    else Permit Details Issue Date for
    missing FILE_DATE only)                 → FILE_DATE
  - Permit Details['Issue Date:']
    (else latest approved / latest review
    Completion)                             → PERMIT_DATE
  - latest successful final-like Inspection
    (else latest successful Inspection,
    else latest review Completion,
    else Issue Date for Closed)             → FINAL_DATE

Known issues repaired:
  - STATUS_NORMALIZED missing for Comments Sent (2) and blank Status:
    shells that still carry Issue Date / final inspections (6) → FILLED.
  - FILE_DATE often equals a late Review Completion or Issue Date even
    when an earlier Review Start exists → FIXED to earliest Start.
  - FILE_DATE missing filled from Reviews when present, else Issue Date.
  - FINAL_DATE missing on all rows; filled from passed final / other
    inspections, review Completions, or Issue Date for Closed.
  - Active/Final PERMIT_DATE gaps filled from Issue Date or, when that
    is blank, from latest review Completion.

Not repairable / left as-is:
  - 14 rows with no dated Reviews and no Issue Date cannot get FILE_DATE.
  - Closed shells with blank Issue Date and empty Reviews stay missing
    PERMIT_DATE.
  - One Closed shell with empty Reviews / Inspections / Issue Date stays
    missing FINAL_DATE.
  - ~23 In Review rows carry an Issue Date / PERMIT_DATE while Status:
    is still Approved for Payment or Under Review; status text is kept.
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
        try:
            parsed = json.loads(data)
        except (json.JSONDecodeError, TypeError):
            return None
        return parsed if isinstance(parsed, dict) else None
    return data if isinstance(data, dict) else None


def _safe_to_datetime(val):
    """Parse a date value, returning pd.NaT on failure."""
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return pd.NaT
    if isinstance(val, str) and not str(val).strip():
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
    if da is pd.NaT or db is pd.NaT:
        return False
    return pd.Timestamp(da).normalize() == pd.Timestamp(db).normalize()


def _clean_text(val) -> str:
    """Normalize portal status strings that embed 'View Comments' junk."""
    if val is None:
        return ""
    text = str(val).replace("\r", "\n")
    return text.split("\n")[0].strip()


def _as_list(val) -> list:
    """Portal sometimes emits a bare dict instead of a one-element list."""
    if val is None:
        return []
    if isinstance(val, list):
        return val
    if isinstance(val, dict):
        return [val]
    return []


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    if not isinstance(data_dict, dict):
        return "unknown"
    if "Status:" not in data_dict and "Permit Details" not in data_dict:
        return "unknown"

    details = data_dict.get("Permit Details")
    has_issue = False
    if isinstance(details, dict):
        for key in ("Issue Date:", "Issue Date"):
            if _safe_to_datetime(details.get(key)) is not pd.NaT:
                has_issue = True
                break
    if not has_issue:
        has_issue = _safe_to_datetime(data_dict.get("Issue Date")) is not pd.NaT

    reviews = _as_list(data_dict.get("Reviews"))
    inspections = _as_list(data_dict.get("Inspections"))
    has_rev = False
    for r in reviews:
        if not isinstance(r, dict):
            continue
        if _safe_to_datetime(r.get("Start")) is not pd.NaT:
            has_rev = True
            break
        if _safe_to_datetime(r.get("Completion")) is not pd.NaT:
            has_rev = True
            break
    has_insp = len(inspections) > 0

    parts = []
    if has_issue:
        parts.append("issued")
    if has_insp:
        parts.append("insp")
    if has_rev:
        parts.append("rev")
    if not parts:
        return "minimal"
    return "_".join(parts)


# ── Status mapping ───────────────────────────────────────────────────────────

_STATUS_MAP = {
    "Closed": "Final",
    "Issued": "Active",
    "Approved": "Active",
    "Online Application Received": "In Review",
    "Approved for Payment": "In Review",
    "Under Review": "In Review",
    "Comments Sent": "In Review",
    "Voided": "Inactive",
    "Expired": "Inactive",
    "Denied": "Inactive",
    "Withdrawn": "Inactive",
}


_PASS_STATUSES = {
    "approved",
    "pass",
    "passed",
    "complete",
    "completed",
    "partial pass",
    "partial approved",
}


_FINAL_INSP_RE = re.compile(
    r"final|certificate|occupancy|\bco\b|\bcc\b",
    re.I,
)


def _is_pass_status(status: str) -> bool:
    s = _clean_text(status).lower()
    if not s:
        return False
    if s in _PASS_STATUSES:
        return True
    return (
        s.startswith("approved")
        or s.startswith("pass")
        or s.startswith("complete")
    )


def _has_approved_final_inspection(d: dict) -> bool:
    inspections = _as_list(d.get("Inspections"))
    for insp in inspections:
        if not isinstance(insp, dict):
            continue
        if not _is_pass_status(insp.get("Status")):
            continue
        typ = str(insp.get("Inspection Type") or "")
        if _FINAL_INSP_RE.search(typ):
            return True
    return False


def _infer_status(d: dict) -> Optional[str]:
    """Infer STATUS_NORMALIZED when Status: is blank / unmapped."""
    if _has_approved_final_inspection(d):
        return "Final"
    if _issue_date(d) is not pd.NaT:
        return "Active"
    starts, completions, _ = _review_dates(d)
    if starts or completions:
        return "In Review"
    return None


def _apply_status(repairs: dict, current, d: dict) -> Optional[str]:
    """Map raw status → STATUS_NORMALIZED; return effective status."""
    raw_status = _clean_text(d.get("Status:"))
    expected = _STATUS_MAP.get(raw_status) if raw_status else None
    if expected is None:
        expected = _infer_status(d)

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
    """Return (starts, completions, approved_completions)."""
    starts = []
    completions = []
    approved_completions = []

    reviews = _as_list(d.get("Reviews"))
    for r in reviews:
        if not isinstance(r, dict):
            continue
        start = _safe_to_datetime(r.get("Start"))
        comp = _safe_to_datetime(r.get("Completion"))
        if start is not pd.NaT:
            starts.append(start)
        if comp is not pd.NaT:
            completions.append(comp)
            if _is_pass_status(r.get("Status")):
                approved_completions.append(comp)

    return starts, completions, approved_completions


def _file_date_from_reviews(d: dict):
    """Application / submittal date proxy from Reviews only."""
    starts, completions, _ = _review_dates(d)
    if starts:
        return min(starts)
    if completions:
        return min(completions)
    return pd.NaT


def _permit_date_candidate(d: dict):
    issue = _issue_date(d)
    if issue is not pd.NaT:
        return issue

    # Closed shells sometimes omit Issue Date; latest approved / latest
    # review Completion is the best issuance proxy in DATA.
    _, completions, approved_completions = _review_dates(d)
    if approved_completions:
        return max(approved_completions)
    if completions:
        return max(completions)
    return pd.NaT


def _is_final_inspection(inspection_type: str) -> bool:
    return bool(_FINAL_INSP_RE.search(inspection_type or ""))


def _final_date_candidate(d: dict, raw_status: str):
    """Completion / sign-off date for Final records."""
    inspections = _as_list(d.get("Inspections"))
    final_dates = []
    any_pass_dates = []
    for insp in inspections:
        if not isinstance(insp, dict):
            continue
        if not _is_pass_status(insp.get("Status")):
            continue
        dt = _safe_to_datetime(insp.get("Date"))
        if dt is pd.NaT:
            continue
        any_pass_dates.append(dt)
        if _is_final_inspection(str(insp.get("Inspection Type") or "")):
            final_dates.append(dt)
    if final_dates:
        return max(final_dates)
    if any_pass_dates:
        return max(any_pass_dates)

    _, completions, approved_completions = _review_dates(d)
    if approved_completions:
        return max(approved_completions)
    if completions:
        return max(completions)

    if _clean_text(raw_status) == "Closed":
        return _issue_date(d)

    return pd.NaT


# ── Per-record repair ────────────────────────────────────────────────────────

def _repair_record(row, d: dict, repairs: dict):
    raw_status = d.get("Status:")
    effective_status = _apply_status(repairs, row["STATUS_NORMALIZED"], d)

    # -- FILE_DATE --
    # Prefer Reviews (fill or fix). Fall back to Issue Date only when FILE
    # is missing — do not overwrite an existing FILE with Issue Date.
    review_file = _file_date_from_reviews(d)
    if review_file is not pd.NaT:
        _apply_date(repairs, row, "FILE_DATE", review_file)
    elif pd.isna(row["FILE_DATE"]):
        issue = _issue_date(d)
        if issue is not pd.NaT:
            repairs["FILE_DATE"] = issue
            repairs["FILE_DATE_FLAG"] = "FILLED"

    # -- PERMIT_DATE --
    permit_dt = _permit_date_candidate(d)
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
    elif not pd.isna(row["FINAL_DATE"]):
        # Spurious completion date on a non-Final record.
        repairs["FINAL_DATE"] = pd.NaT
        repairs["FINAL_DATE_FLAG"] = "FIXED"


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Casselberry permit records using information from the raw DATA JSON.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Casselberry".  Must contain
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
    city = df[df["JURISDICTION"] == "Casselberry"].copy()

    print(f"Casselberry records: {len(city):,}\n")

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

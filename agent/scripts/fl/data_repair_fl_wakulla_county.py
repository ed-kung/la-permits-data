"""Data repair for Wakulla County (FL) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Wakulla County DATA is a CitizenServe-style municipal portal payload.
Every sample row has colon-suffixed keys (``Status:``, ``Permit #:``,
``Permit Details``, ``Reviews``, ``Inspections``). Top-level
``Issue Date`` is always null; the usable issue stamp lives under
``Permit Details["Issue Date:"]``. Application / submittal dates come
from Plan Review Start/Completion (there is no Application Intake
task). ``Bldg - Inspection Checklist`` and ``Bldg - Final Review`` are
post-application / closeout tasks and are not used for FILE_DATE.
Final / sign-off dates come from passed Final*/CO inspections, with
``Bldg - Final Review`` Completion as a fallback.

Canonical fields:

  - DATA["Status:"] (HOLD STATUS inferred; Issued/HOLD upgraded to
    Final when primary Final Building / CO passed; In Review upgraded
    to Active when Issue Date exists)
      → STATUS_NORMALIZED
  - earliest Plan Review Start/Completion (on/before Issue), else
    earliest other non-checklist / non-final-review Review date
      → FILE_DATE
  - Permit Details["Issue Date:"]         → PERMIT_DATE
  - Latest passed Final*/CO inspection,
    else Bldg - Final Review Completion   → FINAL_DATE

Key-set variants (INFERRED_SCHEMA prefixes):
  - portal_form_residential: dwelling / sqft / contractor form extras
  - portal_form_changeout:   window / roof / HVAC change-out extras
  - portal_form:             other contractor / flood form extras
  - portal_core_select:      core + ``Select One``
  - portal_core_extra:       sparse non-form extras
  - portal_core:             minimal colon-key portal shell

Content suffixes further split by which canonical dates are recoverable
(``_issued_finaled``, ``_issued``, ``_finaled``, ``_applied``,
``_status_only``).

Known issues repaired:
  - Null STATUS_NORMALIZED on HOLD STATUS filled via Issue / Final /
    workflow inference; Issued (and issued HOLD) with Final Building /
    CO → Final; Ready for Payment / Under Review carrying Issue Date
    → Active.
  - FILE_DATE often equals Issue Date (Inspection Checklist Start) or
    latest Review Completion rather than Plan Review Start → FIXED /
    cleared when only checklist / final-review dates exist.
  - Spurious PERMIT_DATE on In Review cleared; issued shells already
    match Permit Details Issue Date (no sentinel ``01/01/2000``).
  - FINAL_DATE missing on every sample row → FILLED for Final rows
    with Final*/CO inspections or Final Review Completion.

Not repairable from DATA:
  - Shells with empty / undated Plan Reviews → FILE_DATE stays missing.
  - Closed / Issued shells with blank Issue Date → PERMIT_DATE stays
    missing.
  - Final shells without Final*/CO inspections or Final Review
    Completion → FINAL_DATE stays missing.
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

# Whole-permit closeout (status lag Issued / HOLD → Final). Trade finals
# alone (Final Electrical / Final Roof / …) are not enough to reclassify.
_PRIMARY_FINAL_RE = re.compile(
    r"final\s*building|final\s*bldg|final\s*inspection|"
    r"final\s*mobile\s*home|final\s*certificate|"
    r"certificate of occupancy|certificate of completion|"
    r"\bcoed\b|\bcoc\b|\bcofc\b",
    re.IGNORECASE,
)

_PASS_STATUS = {
    "passed",
    "pass",
    "approved",
    "approved with comments",
    "pass with comments",
    "complete",
    "completed",
    "inspection passed",
    "partial approval",
    "no violation found",
}

_STATUS_MAP = {
    # Final
    "Closed": "Final",
    "Finaled": "Final",
    "Finaled - CO": "Final",
    "Finaled - CC": "Final",
    "Certificate of Occupancy": "Final",
    # Active
    "Issued": "Active",
    "Approved": "Active",
    # In Review
    "Under Review": "In Review",
    "Online Application Received": "In Review",
    "Payment Required": "In Review",
    "Ready for Payment": "In Review",
    "Resubmittal Required": "In Review",
    "On Hold": "In Review",
    "Pending Payment": "In Review",
    # Inactive
    "Canceled": "Inactive",
    "Cancelled": "Inactive",
    "Denied": "Inactive",
    "Expired": "Inactive",
    "Permit Expired": "Inactive",
    "Withdrawn": "Inactive",
    "Void": "Inactive",
    "Abandoned": "Inactive",
}

# Post-issuance / closeout / payment — not application / submittal dates.
_NON_FILE_TASK_RE = re.compile(
    r"online document upload|online message|online resubmittal|"
    r"online payment|online inspection|co requirements|issue permit|"
    r"certificate review|admin co fee|inspection checklist|final review",
    re.IGNORECASE,
)

_PLAN_REVIEW_RE = re.compile(r"plan review", re.IGNORECASE)

_CORE_KEYS = {
    "Address:",
    "Balance Due:",
    "Description:",
    "Inspections",
    "Issue Date",
    "Permit #:",
    "Permit Details",
    "Permit Type",
    "Project #:",
    "Reviews",
    "Status:",
    "Sub Type",
    "Work Description",
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
    """Parse a date value, returning pd.NaT on failure / sentinel / OOR."""
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return pd.NaT
    if isinstance(val, dict):
        return pd.NaT
    if isinstance(val, str):
        s = val.strip().replace("\xa0", " ")
        if not s or s.upper() in {
            "TBD", "NULL", "NONE", "N/A", "NA", "NAN",
            "00/00/0000", "0/0/0000",
        }:
            return pd.NaT
        if s.startswith("0001-01-01") or s.startswith("1900-01-01"):
            return pd.NaT
        if s.lower().startswith("scheduled"):
            return pd.NaT
        # Prefer strict whole-string dates so polluted text is not scraped.
        if not re.match(r"^\d{1,2}/\d{1,2}/\d{2,4}$", s):
            m = re.search(r"(\d{1,2}/\d{1,2}/\d{2,4})", s)
            if m and len(s) <= 24:
                s = m.group(1)
            else:
                return pd.NaT
        try:
            dt = pd.to_datetime(s, errors="coerce")
        except (ValueError, TypeError, OverflowError):
            return pd.NaT
    else:
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


def _present(dt) -> bool:
    return dt is not pd.NaT and not pd.isna(dt)


def _dates_equal(a, b) -> bool:
    da = _safe_to_datetime(a)
    db = _safe_to_datetime(b)
    if not _present(da) or not _present(db):
        return False
    return pd.Timestamp(da).normalize() == pd.Timestamp(db).normalize()


def _has_usable_date(val) -> bool:
    return _present(_safe_to_datetime(val))


def _nonempty_str(val) -> Optional[str]:
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return None
    s = str(val).strip()
    return s or None


def _raw_status(d: dict) -> Optional[str]:
    return _nonempty_str(d.get("Status:")) or _nonempty_str(d.get("Status"))


def _permit_details(d: dict) -> dict:
    det = d.get("Permit Details")
    return det if isinstance(det, dict) else {}


def _issue_date(d: dict):
    """Permit Details Issue Date (top-level Issue Date is null)."""
    det = _permit_details(d)
    dt = _safe_to_datetime(det.get("Issue Date:"))
    if _present(dt):
        return dt
    return _safe_to_datetime(d.get("Issue Date"))


def _insp_status_token(status: Optional[str]) -> str:
    if not status:
        return ""
    token = re.split(r"[\r\n]", str(status), maxsplit=1)[0]
    token = re.sub(r"view comments", "", token, flags=re.IGNORECASE)
    return token.strip().lower()


def _is_pass_status(status: Optional[str]) -> bool:
    token = _insp_status_token(status)
    if not token:
        return False
    if token in _PASS_STATUS:
        return True
    return (
        token.startswith("approved")
        or token.startswith("complete")
        or token.startswith("partial approval")
        or token.startswith("inspection passed")
        or "inspection passed" in token
    )


def _inspection_is_passed_final(item: dict, primary_only: bool = False) -> bool:
    if not isinstance(item, dict):
        return False
    itype = str(item.get("Inspection Type") or "")
    if primary_only:
        if not _PRIMARY_FINAL_RE.search(itype):
            return False
    elif not _FINAL_INSP_RE.search(itype):
        return False
    date_raw = str(item.get("Date") or "")
    if date_raw.lower().startswith("scheduled"):
        return False
    if _is_pass_status(item.get("Status")):
        return _present(_safe_to_datetime(item.get("Date")))
    # Blank status with a real calendar date on a Final* type.
    if _insp_status_token(item.get("Status")) == "":
        return _present(_safe_to_datetime(item.get("Date")))
    return False


def _final_from_inspections(d: dict, primary_only: bool = False):
    insp = d.get("Inspections")
    if not isinstance(insp, list):
        return pd.NaT
    dates = []
    for item in insp:
        if _inspection_is_passed_final(item, primary_only=primary_only):
            dt = _safe_to_datetime(item.get("Date"))
            if _present(dt):
                dates.append(dt)
    return max(dates) if dates else pd.NaT


def _final_review_completion(d: dict):
    reviews = d.get("Reviews")
    if not isinstance(reviews, list):
        return pd.NaT
    dates = []
    for r in reviews:
        if not isinstance(r, dict):
            continue
        task = str(r.get("Task") or "")
        if "final review" not in task.lower():
            continue
        dt = _safe_to_datetime(r.get("Completion"))
        if _present(dt):
            dates.append(dt)
    return max(dates) if dates else pd.NaT


def _final_date(d: dict):
    """Final / CO / sign-off date proxy.

    Prefer any passed Final*/certificate inspection; fall back to
    Bldg - Final Review Completion. Floor at Issue Date when present.
    """
    latest = _final_from_inspections(d, primary_only=False)
    if not _present(latest):
        latest = _final_review_completion(d)
    if not _present(latest):
        return pd.NaT
    issue = _issue_date(d)
    if _present(issue):
        return max(
            pd.Timestamp(latest).normalize(),
            pd.Timestamp(issue).normalize(),
        )
    return latest


def _has_passed_final(d: dict) -> bool:
    return _present(_final_from_inspections(d, primary_only=False)) or _present(
        _final_review_completion(d)
    )


def _has_primary_final(d: dict) -> bool:
    return _present(_final_from_inspections(d, primary_only=True))


def _review_lists(d: dict):
    """Return plan_dates, early_starts, early_comps (excluding closeout tasks)."""
    plan = []
    early_starts = []
    early_comps = []
    reviews = d.get("Reviews")
    if not isinstance(reviews, list):
        return plan, early_starts, early_comps
    for r in reviews:
        if not isinstance(r, dict):
            continue
        task = str(r.get("Task") or "")
        st = _safe_to_datetime(r.get("Start"))
        cp = _safe_to_datetime(r.get("Completion"))
        if _NON_FILE_TASK_RE.search(task):
            continue
        if _PLAN_REVIEW_RE.search(task):
            if _present(st):
                plan.append(st)
            elif _present(cp):
                plan.append(cp)
            # Prefer Start, but still collect Completion as early_comp.
            if _present(st):
                early_starts.append(st)
            if _present(cp):
                early_comps.append(cp)
            continue
        if _present(st):
            early_starts.append(st)
        if _present(cp):
            early_comps.append(cp)
    return plan, early_starts, early_comps


def _on_or_before(candidate, issue):
    if not _present(candidate):
        return False
    if not _present(issue):
        return True
    return pd.Timestamp(candidate).normalize() <= pd.Timestamp(issue).normalize()


def _file_date(d: dict):
    """Application / submittal date proxy.

    Prefer Plan Review Start/Completion; fall back to earliest other
    non-checklist / non-final-review Review Start / Completion on/before
    Issue. Upstream FILE_DATE frequently equals Issue Date (Inspection
    Checklist) or the latest Review Completion.
    """
    issue = _issue_date(d)
    plan, early_starts, early_comps = _review_lists(d)

    plan = [dt for dt in plan if _on_or_before(dt, issue)]
    if plan:
        return min(plan)

    early_starts = [dt for dt in early_starts if _on_or_before(dt, issue)]
    if early_starts:
        return min(early_starts)

    early_comps = [dt for dt in early_comps if _on_or_before(dt, issue)]
    if early_comps:
        return min(early_comps)

    return pd.NaT


def _has_file_source(d: dict) -> bool:
    return _present(_file_date(d))


# ── Schema classification ────────────────────────────────────────────────────

def _schema_base(data_dict: dict) -> str:
    keys = set(data_dict.keys())
    has_changeout = (
        "Change Out Windows" in keys
        or "Change Out Doors" in keys
        or "Re-Roof (Tear Off)" in keys
        or "HVAC Change Out" in keys
        or "Water Heater Change Outs" in keys
        or "Water Heater Change Out" in keys
    )
    has_residential = (
        "Square Footage Main Structure" in keys
        or "Heatedsq ft" in keys
        or "# Bedrooms" in keys
        or "Occupancy Type" in keys
    )
    has_contractor = "Contractor" in keys
    has_select = "Select One" in keys

    if has_changeout:
        return "portal_form_changeout"
    if has_residential and has_contractor:
        return "portal_form_residential"
    if has_contractor:
        return "portal_form"
    if has_select:
        return "portal_core_select"
    extras = keys - _CORE_KEYS
    if extras:
        return "portal_core_extra"
    return "portal_core"


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())
    if "Status:" not in keys and "Permit Details" not in keys:
        return "unknown"

    base = _schema_base(data_dict)
    has_issue = _present(_issue_date(data_dict))
    has_final = _has_passed_final(data_dict)
    has_applied = _has_file_source(data_dict)

    if has_issue and has_final:
        return f"{base}_issued_finaled"
    if has_issue:
        return f"{base}_issued"
    if has_final:
        return f"{base}_finaled"
    if has_applied:
        return f"{base}_applied"
    return f"{base}_status_only"


# ── Status mapping ───────────────────────────────────────────────────────────

def _map_status(raw: Optional[str]) -> Optional[str]:
    if raw is None:
        return None
    if raw in _STATUS_MAP:
        return _STATUS_MAP[raw]
    for key, val in _STATUS_MAP.items():
        if key.lower() == raw.lower():
            return val
    return None


def _expected_status(d: dict) -> Optional[str]:
    """Map portal Status: → STATUS_NORMALIZED, with Issue / final inference."""
    raw = _raw_status(d)
    has_issue = _present(_issue_date(d))
    has_primary_final = _has_primary_final(d)
    has_final = _has_passed_final(d)

    # HOLD STATUS is an administrative flag spanning review / issued /
    # finaled lifecycles — infer from Issue Date and primary finals.
    if raw is not None and raw.strip().upper() == "HOLD STATUS":
        if has_primary_final:
            return "Final"
        if has_issue:
            return "Active"
        reviews = d.get("Reviews")
        insp = d.get("Inspections")
        has_workflow = (
            (isinstance(reviews, list) and len(reviews) > 0)
            or (isinstance(insp, list) and len(insp) > 0)
        )
        if has_workflow or has_final:
            return "In Review"
        return "In Review"

    if raw is None:
        if has_primary_final or has_final:
            return "Final"
        if has_issue:
            return "Active"
        reviews = d.get("Reviews")
        insp = d.get("Inspections")
        has_workflow = (
            (isinstance(reviews, list) and len(reviews) > 0)
            or (isinstance(insp, list) and len(insp) > 0)
        )
        if has_workflow:
            return "In Review"
        return None

    mapped = _map_status(raw)
    if mapped is None:
        if has_primary_final:
            return "Final"
        if has_issue:
            return "Active"
        return "In Review"

    # Pre-issuance labels that already carry Issue Date → Active.
    if mapped == "In Review" and has_issue:
        return "Active"
    # Issued lagging behind whole-permit Final Building / CO → Final.
    if mapped == "Active" and has_primary_final:
        return "Final"
    return mapped


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


def _apply_date(repairs: dict, row, field: str, candidate) -> None:
    cand = _safe_to_datetime(candidate)
    if not _present(cand):
        return
    current = row[field]
    if pd.isna(current) or not _has_usable_date(current):
        if pd.isna(current):
            repairs[field] = cand
            repairs[f"{field}_FLAG"] = "FILLED"
        else:
            repairs[field] = cand
            repairs[f"{field}_FLAG"] = "FIXED"
        return
    if not _dates_equal(current, cand):
        repairs[field] = cand
        repairs[f"{field}_FLAG"] = "FIXED"


def _clear_date(repairs: dict, row, field: str) -> None:
    current = repairs.get(field, row[field])
    if pd.isna(current):
        return
    repairs[field] = pd.NaT
    repairs[f"{field}_FLAG"] = "FIXED"


# ── Per-record repair ────────────────────────────────────────────────────────

def _repair_record(row, d: dict, repairs: dict) -> None:
    expected = _expected_status(d)
    effective_status = _apply_status(repairs, row["STATUS_NORMALIZED"], expected)

    file_dt = _file_date(d)
    issue = _issue_date(d)
    final = _final_date(d)

    # FILE_DATE ← Plan Review / earliest early Review (≤ Issue).
    if _present(file_dt):
        _apply_date(repairs, row, "FILE_DATE", file_dt)
    elif pd.notna(row["FILE_DATE"]):
        # Clear post-issue values and Issue-Date copies from checklist-only shells.
        cur = _safe_to_datetime(row["FILE_DATE"])
        if _present(cur) and _present(issue):
            if pd.Timestamp(cur).normalize() >= pd.Timestamp(issue).normalize():
                _clear_date(repairs, row, "FILE_DATE")
        elif _present(cur) and not _has_usable_date(row["FILE_DATE"]):
            _clear_date(repairs, row, "FILE_DATE")

    # PERMIT_DATE ← Issue Date for issued lifecycles.
    if effective_status == "In Review":
        _clear_date(repairs, row, "PERMIT_DATE")
    elif _present(issue) and effective_status in ("Active", "Final", "Inactive"):
        _apply_date(repairs, row, "PERMIT_DATE", issue)
    elif pd.notna(row["PERMIT_DATE"]) and not _has_usable_date(row["PERMIT_DATE"]):
        _clear_date(repairs, row, "PERMIT_DATE")

    # FINAL_DATE ← Final*/CO / Final Review for Final only.
    if effective_status == "Final":
        if _present(final):
            _apply_date(repairs, row, "FINAL_DATE", final)
        elif pd.notna(row["FINAL_DATE"]) and not _has_usable_date(row["FINAL_DATE"]):
            _clear_date(repairs, row, "FINAL_DATE")
    else:
        _clear_date(repairs, row, "FINAL_DATE")


# ── Main entry point ─────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Wakulla County permit records using the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Wakulla County". Must
        contain columns STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE,
        FINAL_DATE, and DATA.

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
    from collections import Counter
    from pathlib import Path

    from dotenv import load_dotenv

    repo_root = Path(__file__).resolve().parents[3]
    load_dotenv(repo_root / ".env")
    MY_DATA_PATH = os.getenv("MY_DATA_PATH")
    AGENT_DATA_PATH = os.getenv("AGENT_DATA_PATH")
    filepath = os.path.join(
        MY_DATA_PATH, "processed_data", "permits_fl_sample.parquet"
    )
    df = pd.read_parquet(filepath)
    city = df[
        (df["JURISDICTION"] == "Wakulla County") & (df["STATE"] == "FL")
    ].copy()

    print(f"Wakulla County records: {len(city):,}\n")

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

    print("\nDATA.Status: → STATUS_NORMALIZED (after):")
    status_from_data = repaired["DATA"].map(
        lambda x: _raw_status(_safe_parse(x) or {}) or "__EMPTY__"
    )
    ct = (
        pd.DataFrame({
            "DATA_STATUS": status_from_data,
            "STATUS_NORMALIZED": repaired["STATUS_NORMALIZED"],
        })
        .groupby(["DATA_STATUS", "STATUS_NORMALIZED"], dropna=False)
        .size()
        .reset_index(name="n")
        .sort_values("n", ascending=False)
    )
    print(ct.to_string(index=False))

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
        ps_counts = Counter()
        for idx in final_miss.index:
            d = _safe_parse(repaired.at[idx, "DATA"])
            if d is None:
                continue
            raw = (_raw_status(d) or "").strip() or "__EMPTY__"
            ps_counts[raw] += 1
        print("  by Status:", dict(ps_counts))

    status_null = repaired["STATUS_NORMALIZED"].isna().sum()
    print(f"\nSTATUS_NORMALIZED still null: {status_null}")

    af_miss = repaired[
        repaired["STATUS_NORMALIZED"].isin(["Active", "Final"])
        & repaired["PERMIT_DATE"].isna()
    ]
    print(f"Active/Final still missing PERMIT_DATE: {len(af_miss)}")

    file_gt_permit = 0
    permit_gt_final = 0
    for idx in repaired.index:
        f = repaired.at[idx, "FILE_DATE"]
        p = repaired.at[idx, "PERMIT_DATE"]
        fin = repaired.at[idx, "FINAL_DATE"]
        if (
            pd.notna(f)
            and pd.notna(p)
            and pd.Timestamp(f).normalize() > pd.Timestamp(p).normalize()
        ):
            file_gt_permit += 1
        if (
            pd.notna(p)
            and pd.notna(fin)
            and pd.Timestamp(p).normalize() > pd.Timestamp(fin).normalize()
        ):
            permit_gt_final += 1
    print(f"\nFILE_DATE > PERMIT_DATE: {file_gt_permit}")
    print(f"PERMIT_DATE > FINAL_DATE: {permit_gt_final}")

    if AGENT_DATA_PATH:
        out_dir = os.path.join(AGENT_DATA_PATH, "repaired")
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(
            out_dir, "permits_fl_wakulla_county_repaired.parquet"
        )
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote repaired sample → {out_path}")

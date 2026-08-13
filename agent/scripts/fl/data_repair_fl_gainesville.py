"""Data repair for Gainesville (FL) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Gainesville DATA is a municipal portal payload (CitizenServe-style form
fields) with top-level keys such as ``Status:``, ``Permit #:``,
``Issue Date``, ``Permit Details``, ``Inspections``, and ``Reviews``.
Top-level ``Issue Date`` is always null in the sample; the usable issue
stamp lives under ``Permit Details["Issue Date:"]``. Application /
submittal dates come from applicant-signature ``Date:AS`` /
``Permit Details["Date: AS:"]`` or from Review workflow starts
(especially ``Building Application Intake``).

Canonical fields:

  - DATA["Status:"] (with Issue-date upgrade from
    In Review → Active; empty / Project Dox inferred from
    Issue Date / passed Final* inspections)
      → STATUS_NORMALIZED
  - Intake Start else Date:AS (on/before Issue) else earliest
    non-online Review Start/Completion (on/before Issue)
      → FILE_DATE
  - Permit Details["Issue Date:"]         → PERMIT_DATE
  - Latest passed Final* inspection date  → FINAL_DATE

Key-set variants (INFERRED_SCHEMA prefixes):
  - portal_core:          core permit keys only (≤16 top-level keys)
  - portal_owner_builder: owner-builder affidavit / Initials OB* fields
  - portal_extended:      valuation / plan-review form extras, no OB
  - portal_form:          other form-key variants

Content suffixes further split by which canonical dates are recoverable
(``_issued_finaled``, ``_issued``, ``_finaled``, ``_applied``,
``_status_only``).

Known issues repaired:
  - Null STATUS_NORMALIZED for Project Dox / blank Status: → FILLED
    from Issue Date (Active), passed Final* (Final), else In Review.
  - Stale Under Review / On Hold shells that already carry an Issue Date
    → FIXED to Active (portal status lags issuance).
  - FILE_DATE often copied from Issue Date or Intake Completion → FIXED
    to Building Application Intake Start (preferred) or Date:AS /
    early Review dates on/before Issue; sparse fills where FILE was
    null but an intake/early-review source exists.
  - FINAL_DATE missing on every sample row → FILLED for Closed / Final
    rows with a passed Final* inspection.
  - Spurious PERMIT_DATE on remaining In Review cleared; spurious
    FINAL_DATE on non-Final cleared (none expected pre-repair).

Not repairable from DATA:
  - ~1,040 rows lack Intake Start / on-or-before-Issue Date:AS or early
    Review dates → FILE_DATE stays missing (mostly older shells with
    empty Reviews); 13 post-issue FILE values are cleared rather than
    replaced when no application source exists.
  - Active/Final rows with blank Issue Date (1 Active + 2 Closed in
    sample) → PERMIT_DATE stays missing.
  - Closed shells without a passed Final* inspection (~119) → FINAL_DATE
    stays missing.
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

_PASS_STATUS = {
    "passed",
    "pass",
    "approved",
    "approved with comments",
    "partially approved",
    "complete",
    "completed",
    "partial pass",
    "partial approved",
}

_STATUS_MAP = {
    "Closed": "Final",
    "Issued": "Active",
    "Approved": "Active",
    "Cancelled": "Inactive",
    "Void": "Inactive",
    "Expired Permit": "Inactive",
    "Expired": "Inactive",
    "Under Review": "In Review",
    "On Hold": "In Review",
    "Online Application Received": "In Review",
    "Project Dox": "In Review",
}

_INTAKE_TASK_RE = re.compile(
    r"building application intake|property search intake",
    re.IGNORECASE,
)

# Post-issuance portal chatter — not application / submittal dates.
_NON_FILE_TASK_RE = re.compile(
    r"online document upload|online message|online resubmittal",
    re.IGNORECASE,
)

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
        m = re.search(r"(\d{1,2}/\d{1,2}/\d{2,4})", s)
        if m:
            s = m.group(1)
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


def _nonempty_str(val) -> Optional[str]:
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return None
    s = str(val).strip()
    return s or None


def _raw_status(d: dict) -> Optional[str]:
    return _nonempty_str(d.get("Status:"))


def _permit_details(d: dict) -> dict:
    det = d.get("Permit Details")
    return det if isinstance(det, dict) else {}


def _issue_date(d: dict):
    """Permit Details Issue Date (top-level Issue Date is always null)."""
    det = _permit_details(d)
    dt = _safe_to_datetime(det.get("Issue Date:"))
    if _present(dt):
        return dt
    return _safe_to_datetime(d.get("Issue Date"))


def _date_as(d: dict):
    """Applicant-signature / application date."""
    dt = _safe_to_datetime(d.get("Date:AS"))
    if _present(dt):
        return dt
    det = _permit_details(d)
    for key in ("Date: AS:", "Date:AS:", "Date: AS", "SASDate applicant sig:"):
        dt = _safe_to_datetime(det.get(key))
        if _present(dt):
            return dt
    return _safe_to_datetime(d.get("SASDate applicant sig"))


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
        or token.startswith("pass")
        or token.startswith("complete")
        or token.startswith("partial")
    )


def _inspection_is_passed_final(item: dict) -> bool:
    if not isinstance(item, dict):
        return False
    itype = str(item.get("Inspection Type") or "")
    if not _FINAL_INSP_RE.search(itype):
        return False
    date_raw = str(item.get("Date") or "")
    if date_raw.lower().startswith("scheduled"):
        return False
    token = _insp_status_token(item.get("Status"))
    if token in _PASS_STATUS or _is_pass_status(item.get("Status")):
        return _present(_safe_to_datetime(item.get("Date")))
    # Blank status with a real calendar date on a Final* type.
    if token == "":
        return _present(_safe_to_datetime(item.get("Date")))
    return False


def _final_from_inspections(d: dict):
    insp = d.get("Inspections")
    if not isinstance(insp, list):
        return pd.NaT
    dates = []
    for item in insp:
        if _inspection_is_passed_final(item):
            dt = _safe_to_datetime(item.get("Date"))
            if _present(dt):
                dates.append(dt)
    return max(dates) if dates else pd.NaT


def _has_passed_final(d: dict) -> bool:
    return _present(_final_from_inspections(d))


def _review_lists(d: dict):
    """Return intake_starts, intake_comps, early_starts, early_comps.

    ``early_*`` exclude post-issuance online upload/message/resubmittal
    tasks that are not application dates.
    """
    intake_starts = []
    intake_comps = []
    early_starts = []
    early_comps = []
    reviews = d.get("Reviews")
    if not isinstance(reviews, list):
        return intake_starts, intake_comps, early_starts, early_comps
    for r in reviews:
        if not isinstance(r, dict):
            continue
        task = str(r.get("Task") or "")
        st = _safe_to_datetime(r.get("Start"))
        cp = _safe_to_datetime(r.get("Completion"))
        is_intake = bool(_INTAKE_TASK_RE.search(task))
        is_non_file = bool(_NON_FILE_TASK_RE.search(task))
        if is_intake:
            if _present(st):
                intake_starts.append(st)
            if _present(cp):
                intake_comps.append(cp)
        if not is_non_file:
            if _present(st):
                early_starts.append(st)
            if _present(cp):
                early_comps.append(cp)
    return intake_starts, intake_comps, early_starts, early_comps


def _on_or_before(candidate, issue):
    """True if candidate is usable given an optional issue-date upper bound."""
    if not _present(candidate):
        return False
    if not _present(issue):
        return True
    return pd.Timestamp(candidate).normalize() <= pd.Timestamp(issue).normalize()


def _file_date(d: dict):
    """Application / submittal date proxy.

    Priority: Intake Start → Date:AS (≤ Issue) → earliest non-online
    Review Start (≤ Issue) → Intake Completion (≤ Issue) → earliest
    non-online Review Completion (≤ Issue).

    ``Date:AS`` is often an owner-builder / affidavit signature stamped
    after issuance, so Intake Start is preferred and post-issue
    signatures / online uploads are ignored.
    """
    issue = _issue_date(d)
    intake_starts, intake_comps, early_starts, early_comps = _review_lists(d)

    if intake_starts:
        return min(intake_starts)

    das = _date_as(d)
    if _on_or_before(das, issue):
        return das

    early_starts = [dt for dt in early_starts if _on_or_before(dt, issue)]
    if early_starts:
        return min(early_starts)

    intake_comps = [dt for dt in intake_comps if _on_or_before(dt, issue)]
    if intake_comps:
        return min(intake_comps)

    early_comps = [dt for dt in early_comps if _on_or_before(dt, issue)]
    if early_comps:
        return min(early_comps)

    return pd.NaT


def _has_file_source(d: dict) -> bool:
    return _present(_file_date(d))


# ── Schema classification ────────────────────────────────────────────────────

def _schema_base(data_dict: dict) -> str:
    keys = set(data_dict.keys())
    nkeys = len(keys)
    has_ob = any(
        k.startswith("Initials OB")
        or k.startswith("initials OB")
        or k.startswith("owner builder")
        for k in keys
    )
    has_est = "Estimated cost of construction" in keys
    if nkeys <= 16 and not (keys - _CORE_KEYS - {""}):
        # Small core payloads (allow empty-string detail key only).
        extras = keys - _CORE_KEYS
        if not extras or extras <= {""}:
            return "portal_core"
    if nkeys <= 16 and not has_ob and not has_est:
        return "portal_core"
    if has_ob:
        return "portal_owner_builder"
    if has_est or "Plan Review Required" in keys or "Plan Review Status" in keys:
        return "portal_extended"
    return "portal_form"


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

def _expected_status(d: dict) -> Optional[str]:
    """Map portal Status: → STATUS_NORMALIZED, with Issue / final inference."""
    raw = _raw_status(d)
    has_issue = _present(_issue_date(d))
    has_final = _has_passed_final(d)

    if raw is None:
        if has_final:
            return "Final"
        if has_issue:
            return "Active"
        return "In Review"

    mapped = _STATUS_MAP.get(raw)
    if mapped is None:
        for key, val in _STATUS_MAP.items():
            if key.lower() == raw.lower():
                mapped = val
                break
    if mapped is None:
        if has_final:
            return "Final"
        if has_issue:
            return "Active"
        return "In Review"

    # Issued-event upgrade: pre-issuance / hold shells that already carry
    # an Issue Date are Active (portal Status: often lags).
    if mapped == "In Review" and has_issue:
        return "Active"
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
    if pd.isna(current):
        repairs[field] = cand
        repairs[f"{field}_FLAG"] = "FILLED"
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
    final = _final_from_inspections(d)

    # FILE_DATE ← application / submittal proxy.  Clear values that
    # post-date issuance when no usable application source exists
    # (upstream often copied Online Message / Plan Review dates).
    if _present(file_dt):
        _apply_date(repairs, row, "FILE_DATE", file_dt)
    elif pd.notna(row["FILE_DATE"]) and _present(issue):
        if pd.Timestamp(row["FILE_DATE"]).normalize() > pd.Timestamp(
            issue
        ).normalize():
            _clear_date(repairs, row, "FILE_DATE")

    # PERMIT_DATE ← Permit Details Issue Date for issued lifecycles.
    if effective_status == "In Review":
        _clear_date(repairs, row, "PERMIT_DATE")
    elif _present(issue) and effective_status in ("Active", "Final", "Inactive"):
        _apply_date(repairs, row, "PERMIT_DATE", issue)

    # FINAL_DATE ← passed Final* inspection for Final only.
    if effective_status == "Final":
        if _present(final):
            _apply_date(repairs, row, "FINAL_DATE", final)
    else:
        _clear_date(repairs, row, "FINAL_DATE")


# ── Main entry point ─────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Gainesville permit records using the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Gainesville".  Must contain
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

    from dotenv import load_dotenv

    load_dotenv("/Users/ekung/projects/la-permits-data/.env")
    MY_DATA_PATH = os.getenv("MY_DATA_PATH")
    AGENT_DATA_PATH = os.getenv("AGENT_DATA_PATH")
    filepath = os.path.join(
        MY_DATA_PATH, "processed_data", "permits_fl_sample.parquet"
    )
    df = pd.read_parquet(filepath)
    city = df[df["JURISDICTION"] == "Gainesville"].copy()

    print(f"Gainesville records: {len(city):,}\n")

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
    if len(af_miss):
        ps_counts = Counter()
        for idx in af_miss.index:
            d = _safe_parse(repaired.at[idx, "DATA"])
            if d is None:
                continue
            raw = (_raw_status(d) or "").strip() or "__EMPTY__"
            ps_counts[raw] += 1
        print("  by Status:", dict(ps_counts))

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

    mismatch = 0
    for idx in repaired.index:
        d = _safe_parse(repaired.at[idx, "DATA"])
        if d is None:
            continue
        issue = _issue_date(d)
        p = repaired.at[idx, "PERMIT_DATE"]
        if _present(issue) and pd.notna(p) and not _dates_equal(p, issue):
            mismatch += 1
    print(f"PERMIT_DATE ≠ Issue Date (when both present): {mismatch}")

    if AGENT_DATA_PATH:
        out_path = os.path.join(
            AGENT_DATA_PATH, "gainesville_permits_repaired.parquet"
        )
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote {out_path}")

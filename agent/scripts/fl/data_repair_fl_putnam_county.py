"""Data repair for Putnam County (FL) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Putnam County DATA is a CitizenServe-style municipal portal payload.
Every sample row has colon-suffixed keys (``Status:``, ``Permit #:``,
``Permit Details``, ``Reviews``, ``Inspections``). Top-level
``Issue Date`` is always null; the usable issue stamp lives under
``Permit Details["Issue Date:"]``. Application / submittal dates come
from Review Start (often ``Initial Review``); final / sign-off dates
come from passed ``Admin. Final`` / ``Inspector Final`` / other
Final* / CO / Close Out inspections.

Canonical fields:

  - DATA["Status:"] (unmapped filled; Issued upgraded to Final when a
    primary Admin/Inspector Final passed; In Review upgraded to Active
    when Issue Date exists)
      → STATUS_NORMALIZED
  - Earliest non-post-issuance Review Start (on/before Issue), else
    earliest Review Completion (on/before Issue)
      → FILE_DATE
  - Permit Details["Issue Date:"]         → PERMIT_DATE
  - Latest passed Admin. Final, else Inspector Final, else other
    Final*/CO/Close Out inspection        → FINAL_DATE

Key-set variants (INFERRED_SCHEMA prefixes):
  - portal_building:  residential/commercial project-type form
  - portal_roof:      re-roof / product-approval extras
  - portal_utility:   utility clearance extras
  - portal_planning:  rezoning / variance / FLUM extras
  - portal_form:      other form extras
  - portal_core:      minimal core permit keys

Content suffixes further split by which canonical dates are recoverable
(``_issued_finaled``, ``_issued``, ``_finaled``, ``_applied``,
``_status_only``).

Known issues repaired:
  - Null STATUS_NORMALIZED for Revise and Resubmit → FILLED In Review.
  - Issued rows with passed Admin. Final / Inspector Final still
    labeled Active → FIXED to Final.
  - In Review / Open / Online Application Received carrying a real
    Issue Date → FIXED to Active.
  - FILE_DATE often equals Final Review Completion or a later Initial
    Review cycle rather than earliest Review Start → FIXED.
  - Post-issue FILE_DATE cleared when no usable application source
    exists.
  - FINAL_DATE missing on every sample row → FILLED for Closed /
    Finaled / upgraded-Final rows with a Final*/CO stamp.
  - Spurious PERMIT_DATE on In Review cleared; spurious FINAL_DATE on
    non-Final cleared.

Not repairable from DATA:
  - Older / migrated shells with empty Reviews → FILE_DATE stays
    missing (~570 rows in the FL sample).
  - Closed shells with blank Issue Date → PERMIT_DATE stays missing.
  - Closed shells without a usable Final*/CO inspection (expired /
    courtesy / rope-off only) → FINAL_DATE stays missing.
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
    r"final|fnl|close\s*out|certificate of occupancy|"
    r"elevation certificate finished|\bcoc\b|\bcofc\b|\bcc\b",
    re.IGNORECASE,
)

_EXCLUDE_FINAL_RE = re.compile(
    r"expired|courtesy|rope\s*off|reminder|lien\s*letter|"
    r"null\s*and\s*void|permit\s*canceled|permit\s*cancelled|"
    r"notice\s*of\s*commencement|180\s*day|"
    r"elevation certificate(?!\s*finished)|under construction",
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
}

_STATUS_MAP = {
    # Final
    "Closed": "Final",
    "Finaled": "Final",
    "Finaled - CO": "Final",
    "Finaled - CC": "Final",
    # Active
    "Issued": "Active",
    "Approved": "Active",
    # In Review
    "In Review": "In Review",
    "Under Review": "In Review",
    "Open": "In Review",
    "Approved for Payment/Ready to Issue": "In Review",
    "Online Application Received": "In Review",
    "Application Received": "In Review",
    "Revise and Resubmit": "In Review",
    "On Hold": "In Review",
    "Response Required": "In Review",
    # Inactive
    "Expired": "Inactive",
    "Denied": "Inactive",
    "Cancelled": "Inactive",
    "Canceled": "Inactive",
    "Withdrawn": "Inactive",
    "Void": "Inactive",
    "Abandoned": "Inactive",
}

# Post-issuance / payment / messaging — not application / submittal dates.
_NON_FILE_TASK_RE = re.compile(
    r"online document upload|online message|online resubmittal|"
    r"online payment|online inspection|certificate review|"
    r"admin co fee|issue permit",
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
    """Permit Details Issue Date (top-level Issue Date is always null)."""
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
    return token.startswith("pass") or token.startswith("approved") or token.startswith(
        "complete"
    )


def _final_insp_buckets(d: dict):
    """Return (admin_dates, inspector_dates, other_final_dates)."""
    admin, inspector, other = [], [], []
    insp = d.get("Inspections")
    if not isinstance(insp, list):
        return admin, inspector, other
    for item in insp:
        if not isinstance(item, dict):
            continue
        itype = str(item.get("Inspection Type") or "").strip()
        if not itype:
            continue
        if _EXCLUDE_FINAL_RE.search(itype):
            continue
        if not _FINAL_INSP_RE.search(itype):
            continue
        if not _is_pass_status(item.get("Status")):
            continue
        dt = _safe_to_datetime(item.get("Date"))
        if not _present(dt):
            continue
        if re.search(r"admin\.?\s*final", itype, re.IGNORECASE):
            admin.append(dt)
        elif re.search(r"inspector\s*final", itype, re.IGNORECASE):
            inspector.append(dt)
        else:
            other.append(dt)
    return admin, inspector, other


def _final_from_inspections(d: dict):
    admin, inspector, other = _final_insp_buckets(d)
    if admin:
        return max(admin)
    if inspector:
        return max(inspector)
    if other:
        return max(other)
    return pd.NaT


def _has_primary_final(d: dict) -> bool:
    admin, inspector, _other = _final_insp_buckets(d)
    return bool(admin or inspector)


def _has_passed_final(d: dict) -> bool:
    return _present(_final_from_inspections(d))


def _review_lists(d: dict):
    """Return early_starts, early_comps (excluding post-issuance tasks)."""
    early_starts = []
    early_comps = []
    reviews = d.get("Reviews")
    if not isinstance(reviews, list):
        return early_starts, early_comps
    for r in reviews:
        if not isinstance(r, dict):
            continue
        task = str(r.get("Task") or "")
        if _NON_FILE_TASK_RE.search(task):
            continue
        st = _safe_to_datetime(r.get("Start"))
        cp = _safe_to_datetime(r.get("Completion"))
        if _present(st):
            early_starts.append(st)
        if _present(cp):
            early_comps.append(cp)
    return early_starts, early_comps


def _on_or_before(candidate, issue) -> bool:
    if not _present(candidate):
        return False
    if not _present(issue):
        return True
    return pd.Timestamp(candidate).normalize() <= pd.Timestamp(issue).normalize()


def _file_date(d: dict):
    """Application / submittal date proxy.

    Prefer earliest Review Start on/before Issue; fall back to earliest
    Review Completion on/before Issue. Upstream FILE_DATE frequently
    equals Final Review Completion or a later resubmittal cycle.
    """
    issue = _issue_date(d)
    early_starts, early_comps = _review_lists(d)

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
    if "Type of Re-Roof" in keys or "Existing Roof Covering" in keys:
        return "portal_roof"
    if "Account Number" in keys or "Master Meter Water" in keys:
        return "portal_utility"
    if "Rezoning" in keys or "FLUM Amendement" in keys or "Variance" in keys:
        return "portal_planning"
    if (
        "ResidentialProject Type" in keys
        or "CommercialProject Type" in keys
        or "Special Permit Options (Residential)" in keys
    ):
        return "portal_building"
    extras = keys - _CORE_KEYS
    if not extras:
        return "portal_core"
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

    if raw is None:
        if has_final:
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
        if has_final:
            return "Final"
        if has_issue:
            return "Active"
        return "In Review"

    # Pre-issuance labels that already carry Issue Date → Active.
    if mapped == "In Review" and has_issue:
        return "Active"
    # Issued lagging behind whole-permit final inspections → Final.
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
    final = _final_from_inspections(d)

    # FILE_DATE ← earliest Review Start / Completion (≤ Issue).
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
    elif pd.notna(row["PERMIT_DATE"]) and not _has_usable_date(row["PERMIT_DATE"]):
        _clear_date(repairs, row, "PERMIT_DATE")

    # FINAL_DATE ← Final*/CO inspection for Final only.
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
    Putnam County permit records using the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Putnam County". Must contain
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
    from pathlib import Path

    from dotenv import load_dotenv

    repo_root = Path(__file__).resolve().parents[3]
    load_dotenv(repo_root / ".env")
    MY_DATA_PATH = os.getenv("MY_DATA_PATH")
    filepath = os.path.join(
        MY_DATA_PATH, "processed_data", "permits_fl_sample.parquet"
    )
    df = pd.read_parquet(filepath)
    city = df[
        (df["JURISDICTION"] == "Putnam County") & (df["STATE"] == "FL")
    ].copy()

    print(f"Putnam County records: {len(city):,}\n")

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
        if field != "STATUS_NORMALIZED":
            before_bad = 0
            for v in city[field].dropna():
                dt = pd.to_datetime(v, errors="coerce")
                if pd.isna(dt) or dt.year < _MIN_YEAR or dt.year > _MAX_YEAR:
                    before_bad += 1
            print(f"  Sentinel/OOR before: {before_bad:>4,}")
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

    print("\nIdeal coverage after repair:")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n = len(sub)
        if n == 0:
            continue
        file_n = sub["FILE_DATE"].notna().sum()
        perm_n = sub["PERMIT_DATE"].notna().sum()
        final_n = sub["FINAL_DATE"].notna().sum()
        print(
            f"  {status:10s} n={n:>4,}  "
            f"FILE {file_n:>4,}/{n:>4,}  "
            f"PERMIT {perm_n:>4,}/{n:>4,}  "
            f"FINAL {final_n:>4,}/{n:>4,}"
        )

    print("\nActive/Final PERMIT_DATE:", end=" ")
    af = repaired[repaired["STATUS_NORMALIZED"].isin(["Active", "Final"])]
    print(f"{af['PERMIT_DATE'].notna().sum():,} / {len(af):,}")
    print("Final FINAL_DATE:", end=" ")
    ff = repaired[repaired["STATUS_NORMALIZED"] == "Final"]
    print(f"{ff['FINAL_DATE'].notna().sum():,} / {len(ff):,}")

    # Write optional artifact
    agent = os.getenv("AGENT_DATA_PATH")
    if agent:
        out_path = os.path.join(
            agent, "putnam_county_fl_repaired_sample.parquet"
        )
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote {out_path}")

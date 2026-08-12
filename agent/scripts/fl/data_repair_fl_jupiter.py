"""Data repair for Jupiter (FL) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Jupiter DATA is a Tyler EnerGov-style payload with ``entity``,
``details``, ``fees``, ``contacts``, and ``processing_status``. A small
recent subset also carries ``reviews`` / ``holds`` / ``attachments`` /
``more_info`` (INFERRED_SCHEMA prefix ``energov_rich_`` vs
``energov_``).

Canonical fields:
  - entity.CaseStatus / details.PermitStatus      → STATUS_NORMALIZED
  - entity.ApplyDate (details fallback)           → FILE_DATE
  - entity.IssueDate (details fallback)           → PERMIT_DATE
  - entity.FinalDate / details.FinalizeDate;
    else latest Passed final-ish inspection
    (must not predate IssueDate)                  → FINAL_DATE

Known issues repaired:
  - 76 rows with unmapped CaseStatus (In Review*,
    Fees Due*, Received JCDS, NOC Required,
    Permit - CO/CC, Expired, Duplicate, …)
    → STATUS_NORMALIZED FILLED.
  - 4 rows with stale STATUS_ORIGINAL ``70 - issued``
    while CaseStatus is ``99 - Closed - JCDS``
    (Active, empty FINAL_DATE) → FIXED to Final;
    FINAL_DATE FILLED from FinalDate.
  - 2 Issued rows with IssueDate but null
    PERMIT_DATE (STATUS_ORIGINAL lagged Fees Due /
    In Review) → PERMIT_DATE FILLED.
  - 1 Closed-HTE Final row with blank FinalDate
    → FINAL_DATE FILLED from Passed Plumbing Final.

Not repairable from DATA:
  - FILE_DATE already matches ApplyDate for every
    sample row (0 missing).
  - 48 Closed-HTE/JCDS Final rows have blank
    IssueDate → PERMIT_DATE stays missing.
  - Cancelled / Expired / Duplicate FinalDate values
    are closure stamps, not finals → cleared when
    status is not Final.
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
    r"final|fnl|closeout|certificate|\bco\b|\bcc\b|\bcoc\b",
    re.IGNORECASE,
)
_PASS_OK = ("passed", "approved", "complete", "completed")

_INACTIVE_STATUSES = {
    "99 - Closed - Cancelled",
    "90 - Permit - Expired",
    "60 - Application - Expired",
    "97 - Closed - Duplicate",
}

# EnerGov CaseStatus (as stored in DATA) → STATUS_NORMALIZED
_STATUS_MAP = {
    "99 - Closed - HTE": "Final",
    "99 - Closed - JCDS": "Final",
    "76 - Permit - CO/CC": "Final",
    "70 - Issued": "Active",
    "NOC Required": "Active",
    "99 - Closed - Cancelled": "Inactive",
    "90 - Permit - Expired": "Inactive",
    "60 - Application - Expired": "Inactive",
    "97 - Closed - Duplicate": "Inactive",
    "30 - In Review": "In Review",
    "32 - In Review - Waiting Corrections": "In Review",
    "34 - In Review - with Corrections": "In Review",
    "39 - In Review - Revisions": "In Review",
    "16 - Pending Documents": "In Review",
    "10 - Received JCDS": "In Review",
    "18 - Pre-Review Verification": "In Review",
    "52 - Fees Due": "In Review",
    "12 - Fees Due - Initial Permit": "In Review",
    "50 - Fees Due - Calculations": "In Review",
    "54 - Sub - Permit - On Hold Master Not Issued": "In Review",
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
    """Parse a date value as UTC, returning pd.NaT on failure or implausible year."""
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return pd.NaT
    if isinstance(val, dict):
        return pd.NaT
    if isinstance(val, str) and not str(val).strip():
        return pd.NaT
    if not isinstance(val, str) and pd.isna(val):
        return pd.NaT
    text = str(val).strip()
    if text.upper() in {
        "TBD", "NONE", "N/A", "NA", "NULL", "NAN",
        "00/00/0000", "0/0/0000",
    }:
        return pd.NaT
    if text.startswith("0001-01-01"):
        return pd.NaT
    try:
        dt = pd.to_datetime(val, utc=True, errors="coerce")
    except (ValueError, TypeError, OverflowError):
        return pd.NaT
    if dt is pd.NaT or pd.isna(dt):
        return pd.NaT
    year = int(dt.year)
    if year < _MIN_YEAR or year > _MAX_YEAR:
        return pd.NaT
    return dt


def _dates_equal(a, b) -> bool:
    """Compare two datelike values at calendar-day resolution (UTC)."""
    da = _safe_to_datetime(a)
    db = _safe_to_datetime(b)
    if da is pd.NaT or db is pd.NaT or pd.isna(da) or pd.isna(db):
        return False
    return da.date() == db.date()


def _case_status(d: dict) -> Optional[str]:
    entity = d.get("entity") if isinstance(d.get("entity"), dict) else {}
    details = d.get("details") if isinstance(d.get("details"), dict) else {}
    status = entity.get("CaseStatus") or details.get("PermitStatus")
    if status is None:
        return None
    text = str(status).strip()
    return text or None


def _map_status(label: Optional[str]) -> Optional[str]:
    if not label:
        return None
    if label in _STATUS_MAP:
        return _STATUS_MAP[label]
    upper = re.sub(r"\s+", " ", label).strip().upper()
    for key, mapped in _STATUS_MAP.items():
        if key.upper() == upper:
            return mapped
    return None


def _entity_date(d: dict, entity_key: str, *detail_keys: str):
    entity = d.get("entity") if isinstance(d.get("entity"), dict) else {}
    dt = _safe_to_datetime(entity.get(entity_key))
    if dt is not pd.NaT:
        return dt
    details = d.get("details") if isinstance(d.get("details"), dict) else {}
    for key in detail_keys:
        dt = _safe_to_datetime(details.get(key))
        if dt is not pd.NaT:
            return dt
    return pd.NaT


def _is_rich(d: dict) -> bool:
    """Recent portal payloads include reviews/holds/attachments/more_info."""
    return any(k in d for k in ("reviews", "holds", "attachments", "more_info"))


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    if not isinstance(data_dict, dict):
        return "unknown"
    if not {"entity", "details"}.issubset(data_dict.keys()):
        return "unknown"

    prefix = "energov_rich" if _is_rich(data_dict) else "energov"
    applied = _entity_date(data_dict, "ApplyDate", "ApplyDate")
    issued = _entity_date(data_dict, "IssueDate", "IssueDate")
    finaled = _entity_date(data_dict, "FinalDate", "FinalizeDate")
    status = _case_status(data_dict) or ""
    has_issued = issued is not pd.NaT
    has_finaled = finaled is not pd.NaT
    has_applied = applied is not pd.NaT
    if has_issued and has_finaled:
        return f"{prefix}_issued_finaled"
    if has_issued:
        return f"{prefix}_issued"
    if has_finaled:
        return f"{prefix}_finaled"
    if has_applied:
        return f"{prefix}_applied"
    if status:
        return f"{prefix}_status_only"
    return f"{prefix}_shell"


def _inspection_final_date(d: dict, issue):
    """Latest Passed final-ish inspection on/after IssueDate."""
    ps = d.get("processing_status")
    if not isinstance(ps, list):
        return pd.NaT
    best = pd.NaT
    for item in ps:
        if not isinstance(item, dict):
            continue
        desc = str(item.get("description") or "")
        status = str(item.get("status") or "").strip().lower()
        if "partial" in status:
            continue
        if not any(tok in status for tok in _PASS_OK):
            continue
        if not _FINAL_INSP_RE.search(desc):
            continue
        dt = _safe_to_datetime(item.get("scheduled_date"))
        if dt is pd.NaT:
            dt = _safe_to_datetime(item.get("requested_date"))
        if dt is pd.NaT:
            continue
        if issue is not pd.NaT and dt.date() < issue.date():
            continue
        if best is pd.NaT or dt > best:
            best = dt
    return best


def _set_status(repairs: dict, current_status, expected: Optional[str]) -> None:
    if expected is None:
        return
    if pd.isna(current_status):
        repairs["STATUS_NORMALIZED"] = expected
        repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"
    elif current_status != expected:
        repairs["STATUS_NORMALIZED"] = expected
        repairs["STATUS_NORMALIZED_FLAG"] = "FIXED"


def _set_date_from_source(repairs: dict, field: str, current, source) -> None:
    if source is pd.NaT or pd.isna(source):
        return
    flag = f"{field}_FLAG"
    if pd.isna(current):
        repairs[field] = source
        repairs[flag] = "FILLED"
    elif not _dates_equal(current, source):
        repairs[field] = source
        repairs[flag] = "FIXED"


def _clear_date(repairs: dict, row, field: str) -> None:
    current = repairs.get(field, row[field])
    if pd.isna(current):
        return
    repairs[field] = pd.NaT
    repairs[f"{field}_FLAG"] = "FIXED"


def _expected_status(raw: Optional[str], issue, final_stamp) -> Optional[str]:
    expected = _map_status(raw)

    # Issued / NOC / In-Review-Revisions with a coherent FinalDate → Final
    # (portal status lag). Do not promote Inactive-family rows, and skip
    # FinalDate stamps that predate IssueDate (stale revision artifacts).
    if (
        final_stamp is not pd.NaT
        and raw not in _INACTIVE_STATUSES
        and expected in (None, "Active", "In Review")
    ):
        if issue is pd.NaT or final_stamp.date() >= issue.date():
            expected = "Final"

    # Issued permit sitting in revision review → Active.
    if expected == "In Review" and raw == "39 - In Review - Revisions" and issue is not pd.NaT:
        expected = "Active"

    return expected


# ── Per-record repair ────────────────────────────────────────────────────────

def _repair_record(row, d: dict, repairs: dict) -> None:
    current_status = row["STATUS_NORMALIZED"]
    raw = _case_status(d)
    issue = _entity_date(d, "IssueDate", "IssueDate")
    final_stamp = _entity_date(d, "FinalDate", "FinalizeDate")
    apply = _entity_date(d, "ApplyDate", "ApplyDate")

    expected = _expected_status(raw, issue, final_stamp)
    _set_status(repairs, current_status, expected)
    effective_status = repairs.get("STATUS_NORMALIZED", current_status)

    _set_date_from_source(repairs, "FILE_DATE", row["FILE_DATE"], apply)

    if issue is not pd.NaT:
        _set_date_from_source(repairs, "PERMIT_DATE", row["PERMIT_DATE"], issue)

    final_insp = _inspection_final_date(d, issue)
    final = final_stamp if final_stamp is not pd.NaT else final_insp

    if effective_status == "Final":
        _set_date_from_source(repairs, "FINAL_DATE", row["FINAL_DATE"], final)
    else:
        # Closure stamps on Cancelled / Expired / Duplicate are not finals.
        _clear_date(repairs, row, "FINAL_DATE")


# ── Main entry point ─────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Jupiter (FL) permit records using the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Jupiter".  Must contain
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
        if d is None:
            continue

        repairs: dict = {}
        if {"entity", "details"}.issubset(d.keys()):
            _repair_record(row, d, repairs)

        for key, value in repairs.items():
            out.at[idx, key] = value

    for col in ("FILE_DATE", "PERMIT_DATE", "FINAL_DATE"):
        out[col] = pd.to_datetime(out[col], errors="coerce", utc=True).dt.tz_localize(None)

    return out


# ── CLI: run standalone to preview repair stats ──────────────────────────────

if __name__ == "__main__":
    import os
    from collections import Counter
    from pathlib import Path

    from dotenv import load_dotenv

    repo_root = Path(__file__).resolve().parents[3]
    load_dotenv(repo_root / ".env")
    my_data_path = os.getenv("MY_DATA_PATH")
    agent_data_path = os.getenv("AGENT_DATA_PATH")
    filepath = os.path.join(my_data_path, "processed_data", "permits_fl_sample.parquet")
    df = pd.read_parquet(filepath)
    city = df[df["JURISDICTION"] == "Jupiter"].copy()

    print(f"Jupiter records: {len(city):,}\n")
    repaired = data_repair(city)

    print("INFERRED_SCHEMA:")
    print(repaired["INFERRED_SCHEMA"].value_counts(dropna=False).to_string())
    print()

    for field in ["STATUS_NORMALIZED", "FILE_DATE", "PERMIT_DATE", "FINAL_DATE"]:
        flag_col = f"{field}_FLAG"
        n_filled = (repaired[flag_col] == "FILLED").sum()
        n_fixed = (repaired[flag_col] == "FIXED").sum()
        before_missing = city[field].isna().sum()
        after_missing = repaired[field].isna().sum()
        print(f"{field}:")
        print(f"  FILLED: {n_filled:>4,}   FIXED: {n_fixed:>4,}")
        print(f"  Missing before: {before_missing:>4,}   Missing after: {after_missing:>4,}")
        print()

    print("STATUS_NORMALIZED distribution:")
    print("  Before:")
    for s, c in city["STATUS_NORMALIZED"].value_counts(dropna=False).items():
        print(f"    {str(s):15s}: {c:>4,}")
    print("  After:")
    for s, c in repaired["STATUS_NORMALIZED"].value_counts(dropna=False).items():
        print(f"    {str(s):15s}: {c:>4,}")

    print("\nSTATUS_NORMALIZED_FLAG breakdown:")
    for flag in ["FILLED", "FIXED"]:
        sub = repaired[repaired["STATUS_NORMALIZED_FLAG"] == flag]
        print(f"  {flag} ({len(sub)}):")
        labels = []
        for idx in sub.index:
            d = _safe_parse(city.loc[idx, "DATA"])
            label = _case_status(d) if d else None
            labels.append(
                (
                    repaired.loc[idx, "INFERRED_SCHEMA"],
                    label,
                    city.loc[idx, "STATUS_NORMALIZED"],
                    repaired.loc[idx, "STATUS_NORMALIZED"],
                )
            )
        for (schema, label, before, after), n in Counter(labels).most_common(30):
            print(f"    [{schema}] {label!r}: {before!r} → {after!r}  x{n}")

    print("\nFILE_DATE coverage by status (after):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FILE_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({(n_has / len(sub) if len(sub) else 0):.1%})")

    print("\nPERMIT_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["PERMIT_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({(n_has / len(sub) if len(sub) else 0):.1%})")

    print("\nFINAL_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FINAL_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({(n_has / len(sub) if len(sub) else 0):.1%})")

    r = repaired.copy()
    for c in ("FILE_DATE", "PERMIT_DATE", "FINAL_DATE"):
        r[c] = pd.to_datetime(r[c], errors="coerce")
    print("\nChronology after repair:")
    print(
        "  PERMIT < FILE:",
        (r.PERMIT_DATE.notna() & r.FILE_DATE.notna()
         & (r.PERMIT_DATE.dt.normalize() < r.FILE_DATE.dt.normalize())).sum(),
    )
    print(
        "  FINAL < PERMIT:",
        (r.FINAL_DATE.notna() & r.PERMIT_DATE.notna()
         & (r.FINAL_DATE.dt.normalize() < r.PERMIT_DATE.dt.normalize())).sum(),
    )
    print(
        "  FINAL on non-Final:",
        ((r.STATUS_NORMALIZED != "Final") & r.FINAL_DATE.notna()).sum(),
    )

    if agent_data_path:
        out_path = os.path.join(agent_data_path, "jupiter_repaired_sample.parquet")
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote {out_path}")

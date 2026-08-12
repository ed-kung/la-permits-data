"""Data repair for Miami Beach (FL) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Miami Beach DATA is a Tyler EnerGov payload (entity / details / contacts /
fees / processing_status, optionally reviews/holds/attachments/more_info).
Canonical fields:

  - entity.CaseStatus (fallback details.PermitStatus)
      → STATUS_NORMALIZED, with Issued/FinalDate overrides for
      stale Applied / Initial / Pending / Issued labels
  - entity.ApplyDate (fallback details.ApplyDate) → FILE_DATE
  - entity.IssueDate (fallback details.IssueDate) → PERMIT_DATE
  - entity.FinalDate (fallback details.FinalizeDate,
    else latest Passed/Approved final-ish inspection in
    processing_status)                     → FINAL_DATE

Key-set variants (INFERRED_SCHEMA prefixes):
  - energov_full: extra reviews/holds/attachments/more_info
  - energov:      fees present, no review extras

Content suffixes further split by which canonical dates are populated
(``_issued_finaled``, ``_issued``, ``_finaled``, ``_applied``,
``_status_only``).

Known issues repaired:
  - Missing STATUS_NORMALIZED on Initial (→ In Review) and
    Recertified (→ Final).
  - Suspended labeled In Review → FIXED to Inactive.
  - Stale CaseStatus Applied / Initial / Pending with IssueDate
    (and details.Issued) still In Review → FIXED to Active;
    Applied / Issued carrying FinalDate → FIXED to Final.
  - Spurious FINAL_DATE on Inactive / In Review / Active cleared —
    FinalDate there is a void/close/license stamp, not a completion
    date for a Final permit.
  - Missing PERMIT_DATE filled from IssueDate for Active / Final /
    Inactive; spurious PERMIT_DATE on remaining In Review cleared.

Not repairable from DATA:
  - FILE_DATE already matches ApplyDate for every sample row.
  - ~463 Final (mostly Closed) rows have Issued=false and null
    IssueDate → PERMIT_DATE stays missing.
  - 11 Final Closed ZZConverted rows have neither FinalDate nor
    processing_status → FINAL_DATE stays missing.
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
        if s.startswith("0001-01-01"):
            return pd.NaT
    try:
        dt = pd.to_datetime(val, utc=True, errors="coerce")
    except (ValueError, TypeError, OverflowError):
        return pd.NaT
    if pd.isna(dt):
        return pd.NaT
    year = int(dt.year)
    if year < _MIN_YEAR or year > _MAX_YEAR:
        return pd.NaT
    return dt.tz_convert("UTC").tz_localize(None)


def _dates_equal(a, b) -> bool:
    """Compare two datelike values at calendar-day resolution."""
    da = _safe_to_datetime(a)
    db = _safe_to_datetime(b)
    if da is pd.NaT or db is pd.NaT or pd.isna(da) or pd.isna(db):
        return False
    return pd.Timestamp(da).normalize() == pd.Timestamp(db).normalize()


def _case_status(d: dict) -> Optional[str]:
    entity = d.get("entity") if isinstance(d.get("entity"), dict) else {}
    details = d.get("details") if isinstance(d.get("details"), dict) else {}
    status = entity.get("CaseStatus") or details.get("PermitStatus")
    if status is None:
        return None
    status = str(status).strip()
    return status or None


def _entity_date(d: dict, entity_key: str, *detail_keys: str):
    """Naive-UTC datetime from entity.<key>, else first non-null details key."""
    entity = d.get("entity") if isinstance(d.get("entity"), dict) else {}
    dt = _safe_to_datetime(entity.get(entity_key))
    if dt is not pd.NaT and not pd.isna(dt):
        return dt
    details = d.get("details") if isinstance(d.get("details"), dict) else {}
    for key in detail_keys:
        dt = _safe_to_datetime(details.get(key))
        if dt is not pd.NaT and not pd.isna(dt):
            return dt
    return pd.NaT


def _is_issued_flag(d: dict) -> bool:
    details = d.get("details") if isinstance(d.get("details"), dict) else {}
    issued = details.get("Issued")
    return issued is True or str(issued).strip().lower() == "true"


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())
    if "entity" not in keys:
        return "unknown"

    has_extra = bool(keys & {"reviews", "holds", "attachments", "more_info"})
    if has_extra:
        base = "energov_full"
    elif "fees" in keys:
        base = "energov"
    else:
        base = "energov_basic"

    apply = _entity_date(data_dict, "ApplyDate", "ApplyDate")
    issue = _entity_date(data_dict, "IssueDate", "IssueDate")
    final = _entity_date(data_dict, "FinalDate", "FinalizeDate")
    has_apply = apply is not pd.NaT and not pd.isna(apply)
    has_issue = issue is not pd.NaT and not pd.isna(issue)
    has_final = final is not pd.NaT and not pd.isna(final)

    if has_issue and has_final:
        return f"{base}_issued_finaled"
    if has_issue:
        return f"{base}_issued"
    if has_final:
        return f"{base}_finaled"
    if has_apply:
        return f"{base}_applied"
    return f"{base}_status_only"


# ── Status mapping ───────────────────────────────────────────────────────────

_STATUS_MAP = {
    # Final
    "Finaled": "Final",
    "Closed": "Final",
    "Recertified": "Final",
    # Active
    "Issued": "Active",
    # Inactive
    "Expired": "Inactive",
    "Void": "Inactive",
    "Abandon": "Inactive",
    "Cancel": "Inactive",
    "Revoked": "Inactive",
    "Denied": "Inactive",
    "Suspended": "Inactive",
    # In Review
    "Applied": "In Review",
    "Initial": "In Review",
    "Pending": "In Review",
    "Notified": "In Review",
}


def _expected_status(d: dict) -> Optional[str]:
    """Map CaseStatus → STATUS_NORMALIZED, correcting stale labels via dates."""
    raw = _case_status(d)
    if raw is None:
        return None

    expected = _STATUS_MAP.get(raw)
    if expected is None:
        for key, val in _STATUS_MAP.items():
            if key.lower() == raw.lower():
                expected = val
                break

    if expected is None:
        return None

    issue = _entity_date(d, "IssueDate", "IssueDate")
    final = _entity_date(d, "FinalDate", "FinalizeDate")
    has_issue = issue is not pd.NaT and not pd.isna(issue)
    has_final = final is not pd.NaT and not pd.isna(final)

    # FinalDate on Issued / Applied means the case completed but CaseStatus
    # lagged (e.g. elevator license, short-term parking, demolition).
    if has_final and raw in ("Issued", "Applied", "Recertified"):
        return "Final"

    # Applied / Initial / Pending with a real IssueDate are issued permits
    # whose CaseStatus was never flipped to Issued.
    if (
        expected == "In Review"
        and has_issue
        and _is_issued_flag(d)
        and raw in ("Applied", "Initial", "Pending")
    ):
        return "Active"

    return expected


def _final_inspection_date(d: dict):
    """Latest Passed/Approved processing_status inspection that looks final."""
    ps = d.get("processing_status")
    if not isinstance(ps, list):
        return pd.NaT
    candidates = []
    for insp in ps:
        if not isinstance(insp, dict):
            continue
        status = str(insp.get("status") or "").strip().lower()
        if status not in ("approved", "passed"):
            continue
        desc = str(insp.get("description") or "")
        if not _FINAL_INSP_RE.search(desc):
            continue
        dt = _safe_to_datetime(insp.get("scheduled_date"))
        if dt is pd.NaT or pd.isna(dt):
            dt = _safe_to_datetime(insp.get("requested_date"))
        if dt is not pd.NaT and not pd.isna(dt):
            candidates.append(dt)
    return max(candidates) if candidates else pd.NaT


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
    if cand is pd.NaT or pd.isna(cand):
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

    apply = _entity_date(d, "ApplyDate", "ApplyDate")
    issue = _entity_date(d, "IssueDate", "IssueDate")
    final = _entity_date(d, "FinalDate", "FinalizeDate")

    # FILE_DATE ← ApplyDate
    if apply is not pd.NaT and not pd.isna(apply):
        _apply_date(repairs, row, "FILE_DATE", apply)

    # PERMIT_DATE ← IssueDate for issued / completed / inactive statuses.
    # Clear on In Review (stale Applied rows that still carry a date after
    # status overrides have been applied).
    if issue is not pd.NaT and not pd.isna(issue):
        if effective_status in ("Active", "Final", "Inactive"):
            _apply_date(repairs, row, "PERMIT_DATE", issue)
        elif effective_status == "In Review":
            _clear_date(repairs, row, "PERMIT_DATE")
    elif effective_status == "In Review":
        _clear_date(repairs, row, "PERMIT_DATE")

    # FINAL_DATE ← FinalDate / FinalizeDate, else Passed/Approved final insp.
    if (final is pd.NaT or pd.isna(final)) and effective_status == "Final":
        final = _final_inspection_date(d)

    if effective_status == "Final":
        if final is not pd.NaT and not pd.isna(final):
            _apply_date(repairs, row, "FINAL_DATE", final)
    else:
        _clear_date(repairs, row, "FINAL_DATE")


# ── Main entry point ─────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Miami Beach permit records using the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Miami Beach".  Must contain
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
        out[col] = pd.to_datetime(out[col], errors="coerce", utc=True).dt.tz_localize(None)
        out[col] = out[col].astype(object)

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
        out[col] = pd.to_datetime(out[col], errors="coerce", utc=True).dt.tz_localize(None)

    return out


# ── CLI: run standalone to preview repair stats ─────────────────────────────

if __name__ == "__main__":
    import os

    from dotenv import load_dotenv

    load_dotenv("/Users/ekung/projects/la-permits-data/.env")
    MY_DATA_PATH = os.getenv("MY_DATA_PATH")
    filepath = os.path.join(MY_DATA_PATH, "processed_data", "permits_fl_sample.parquet")
    df = pd.read_parquet(filepath)
    city = df[df["JURISDICTION"] == "Miami Beach"].copy()

    print(f"Miami Beach records: {len(city):,}\n")

    repaired = data_repair(city)

    print("INFERRED_SCHEMA:")
    for s, c in repaired["INFERRED_SCHEMA"].value_counts(dropna=False).items():
        print(f"  {str(s):35s}: {c:>4,}")
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

    print("\nSTATUS transitions (flagged):")
    flagged = repaired[repaired["STATUS_NORMALIZED_FLAG"].notna()]
    for (before, after), c in (
        pd.DataFrame({
            "before": city.loc[flagged.index, "STATUS_NORMALIZED"].astype(str),
            "after": flagged["STATUS_NORMALIZED"].astype(str),
        })
        .value_counts()
        .items()
    ):
        print(f"  {before:15s} → {after:15s}: {c:>4,}")

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

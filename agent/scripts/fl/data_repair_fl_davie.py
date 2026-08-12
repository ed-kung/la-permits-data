"""Data repair for Davie (FL) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Davie DATA is a Logos / TRAKiT-style portal payload. Almost all rows use
the nested key set (Permit Summary, Permit Details, Inspections, Notes,
Payment Summary, …); one sample row is a flatter sibling schema with
top-level Status / Paid On / Inspection.

Canonical fields:

  - Permit Summary.StatusValue (flat: Status)
      → STATUS_NORMALIZED (and often embeds a lifecycle date)
  - Status date for Permit/Application Created, else earliest
    non-archival Notes date bounded by the lifecycle date
      → FILE_DATE
  - Status date for Permit Issued                 → PERMIT_DATE
  - Status date for Permit Completed, else latest
    Completed+Pass final inspection               → FINAL_DATE

StatusValue forms observed:
  - "Permit Completed on MM/DD/YYYY" / bare "Permit Completed"
  - "Permit Issued on MM/DD/YYYY"
  - "Permit Expired" / "Permit Expired MM/DD/YYYY"
  - "Pending Payment as of MM/DD/YYYY"
  - "Permit Created as of MM/DD/YYYY"
  - "Application Created on MM/DD/YYYY"

Known issues repaired:
  - STATUS_NORMALIZED null when STATUS_ORIGINAL embeds an expiration
    date ("permit expired MM/DD/YYYY") → FILLED Inactive (35 rows).
  - FILE_DATE missing on Issued / Completed / Expired / Pending
    Payment rows that still have usable Notes → FILLED from earliest
    non-Microfilm/Historical note on or before the lifecycle date.
  - FINAL_DATE missing on bare "Permit Completed" rows with a
    Completed+Pass final inspection → FILLED (6 rows).

Not repairable from DATA:
  - No dedicated ApplyDate / IssueDate fields. FILE_DATE stays missing
    when there are no usable Notes (~1,286 rows after repair).
  - Final / Inactive rows never carry an issue date in StatusValue;
    Payment Summary.PaidValue is fee payment, not a reliable
    PERMIT_DATE → Active keeps 100% coverage, Final stays 0%.
  - 41 bare "Permit Completed" rows have neither a status date nor a
    Passed final inspection → FINAL_DATE stays missing.
"""

from __future__ import annotations

import json
import math
import re
from typing import Optional

import numpy as np
import pandas as pd


# Historic Davie permits in this sample go back to the 1960s.
_MIN_YEAR = 1960
_MAX_YEAR = 2035

_FINAL_INSP_RE = re.compile(
    r"final|fnl|closeout|certificate|\bco\b|\bcc\b|\bcoc\b",
    re.IGNORECASE,
)

_STATUS_MAP = {
    "Permit Completed": "Final",
    "Permit Issued": "Active",
    "Permit Expired": "Inactive",
    "Pending Payment": "In Review",
    "Permit Created": "In Review",
    "Application Created": "In Review",
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
    """Parse a date value, returning pd.NaT on failure / sentinels."""
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return pd.NaT
    if isinstance(val, dict):
        return pd.NaT
    if isinstance(val, str):
        s = val.strip()
        if not s or s.upper() in {
            "TBD", "NULL", "NONE", "N/A", "NA", "NAN", "NOT PAID",
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


def _status_value(d: dict) -> Optional[str]:
    summary = d.get("Permit Summary")
    if isinstance(summary, dict):
        sv = summary.get("StatusValue")
        if sv is not None and str(sv).strip():
            return str(sv).strip()
    sv = d.get("Status")
    if sv is not None and str(sv).strip():
        return str(sv).strip()
    return None


def _parse_status(sv: Optional[str]) -> tuple[Optional[str], object]:
    """Return (status base, embedded lifecycle date)."""
    if not sv:
        return None, pd.NaT
    s = str(sv).strip()

    m = re.match(
        r"^(.*?)\s+(?:on|as of)\s+(\d{1,2}/\d{1,2}/\d{2,4})\s*$",
        s,
        flags=re.IGNORECASE,
    )
    if m:
        return m.group(1).strip(), _safe_to_datetime(m.group(2))

    m = re.match(
        r"^(Permit Expired)\s+(\d{1,2}/\d{1,2}/\d{2,4})\s*$",
        s,
        flags=re.IGNORECASE,
    )
    if m:
        return "Permit Expired", _safe_to_datetime(m.group(2))

    base = re.sub(r"\s+\d{1,2}/\d{1,2}/\d{2,4}.*$", "", s).strip()
    return base or None, pd.NaT


def _earliest_note_date(d: dict, upper=None):
    """Earliest Logos note date, skipping archival Microfilm/Historical.

    When *upper* is provided, only notes on or before that calendar day
    are considered (keeps FILE_DATE from landing after issue/final/etc.).
    """
    notes = d.get("Notes")
    if not isinstance(notes, list):
        return pd.NaT

    upper_dt = _safe_to_datetime(upper)
    candidates = []
    for note in notes:
        if not isinstance(note, dict):
            continue
        subject = str(note.get("LogosNotesSubjectColumn") or "").strip().lower()
        if subject == "historical" or "microfilm" in subject:
            continue
        dt = _safe_to_datetime(note.get("LogosNotesDateColumn"))
        if dt is pd.NaT or pd.isna(dt):
            continue
        if upper_dt is not pd.NaT and not pd.isna(upper_dt):
            if pd.Timestamp(dt).normalize() > pd.Timestamp(upper_dt).normalize():
                continue
        candidates.append(dt)
    return min(candidates) if candidates else pd.NaT


def _final_inspection_date(d: dict):
    """Latest Completed+Pass inspection whose type looks final."""
    inspections = d.get("Inspections")
    if not isinstance(inspections, list):
        inspections = d.get("Inspection")
    if not isinstance(inspections, list):
        return pd.NaT

    candidates = []
    for insp in inspections:
        if not isinstance(insp, dict):
            continue
        status = str(insp.get("InspectionStatusColumn") or "").strip().lower()
        if status != "completed":
            continue
        result = str(insp.get("PassFailColumn") or "").strip().lower()
        if result and result != "pass":
            continue
        typ = str(insp.get("InspectionTypeColumn") or "")
        if not _FINAL_INSP_RE.search(typ):
            continue
        dt = _safe_to_datetime(insp.get("InspectionDateColumn"))
        if dt is not pd.NaT and not pd.isna(dt):
            candidates.append(dt)
    return max(candidates) if candidates else pd.NaT


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"

    keys = set(data_dict.keys())
    if "Permit Summary" in keys:
        base = "logos"
    elif "Status" in keys and ("Permit #" in keys or "Application #" in keys):
        base = "logos_flat"
    else:
        return "unknown"

    sv = _status_value(data_dict)
    status_base, status_dt = _parse_status(sv)
    has_status_dt = status_dt is not pd.NaT and not pd.isna(status_dt)
    final_insp = _final_inspection_date(data_dict)
    has_final_insp = final_insp is not pd.NaT and not pd.isna(final_insp)
    note_dt = _earliest_note_date(data_dict)
    has_note = note_dt is not pd.NaT and not pd.isna(note_dt)

    if status_base == "Permit Completed" and (has_status_dt or has_final_insp):
        return f"{base}_completed"
    if status_base == "Permit Issued" and has_status_dt:
        return f"{base}_issued"
    if status_base in ("Permit Created", "Application Created") and has_status_dt:
        return f"{base}_created"
    if status_base == "Permit Expired":
        return f"{base}_expired" if has_status_dt else f"{base}_expired_bare"
    if status_base == "Pending Payment" and has_status_dt:
        return f"{base}_pending"
    if has_note:
        return f"{base}_notes_only"
    return f"{base}_status_only"


def _expected_status(status_base: Optional[str]) -> Optional[str]:
    if status_base is None:
        return None
    if status_base in _STATUS_MAP:
        return _STATUS_MAP[status_base]
    for key, val in _STATUS_MAP.items():
        if key.lower() == status_base.lower():
            return val
    return None


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
    status_base, status_dt = _parse_status(_status_value(d))
    expected = _expected_status(status_base)
    effective_status = _apply_status(repairs, row["STATUS_NORMALIZED"], expected)

    # -- FILE_DATE --
    # Created / Application Created: status date is the application stamp.
    # Otherwise: earliest non-archival note on/before the lifecycle date.
    file_cand = pd.NaT
    if status_base in ("Permit Created", "Application Created"):
        file_cand = status_dt
    else:
        upper = pd.NaT
        if status_base == "Permit Issued":
            upper = status_dt
        elif status_base == "Permit Completed":
            upper = status_dt
            if upper is pd.NaT or pd.isna(upper):
                upper = _safe_to_datetime(row["FINAL_DATE"])
            if upper is pd.NaT or pd.isna(upper):
                upper = _final_inspection_date(d)
        elif status_base in ("Permit Expired", "Pending Payment"):
            upper = status_dt
        if upper is not pd.NaT and not pd.isna(upper):
            file_cand = _earliest_note_date(d, upper=upper)

    if file_cand is not pd.NaT and not pd.isna(file_cand):
        _apply_date(repairs, row, "FILE_DATE", file_cand)

    # -- PERMIT_DATE --
    # Only StatusValue "Permit Issued on …" is a true issuance stamp.
    # PaidValue is fee payment and is not used.
    if status_base == "Permit Issued" and status_dt is not pd.NaT and not pd.isna(status_dt):
        if effective_status in ("Active", "Final", "Inactive"):
            _apply_date(repairs, row, "PERMIT_DATE", status_dt)
        elif effective_status == "In Review":
            _clear_date(repairs, row, "PERMIT_DATE")
    elif effective_status == "In Review":
        _clear_date(repairs, row, "PERMIT_DATE")

    # -- FINAL_DATE --
    final_cand = pd.NaT
    if status_base == "Permit Completed":
        final_cand = status_dt
        if final_cand is pd.NaT or pd.isna(final_cand):
            final_cand = _final_inspection_date(d)

    if effective_status == "Final":
        if final_cand is not pd.NaT and not pd.isna(final_cand):
            _apply_date(repairs, row, "FINAL_DATE", final_cand)
    else:
        _clear_date(repairs, row, "FINAL_DATE")


# ── Main entry point ─────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Davie permit records using the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Davie".  Must contain
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
    city = df[df["JURISDICTION"] == "Davie"].copy()

    print(f"Davie records: {len(city):,}\n")

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

    print("\nFILE_DATE by STATUS_NORMALIZED (after repair):")
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

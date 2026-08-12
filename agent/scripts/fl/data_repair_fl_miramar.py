"""Data repair for Miramar (FL) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Miramar DATA has two portal families in this sample:

  - entity_fees_reviews: Tyler EnerGov-style payload with entity,
                         details, fees, contacts, processing_status,
                         reviews / holds / attachments / more_info
  - legacy_application:  older city portal with application,
                         application information, application_reference,
                         permit, and inspection blocks

Canonical mappings:
  entity_fees_reviews
    - CaseStatus / details.PermitStatus              → STATUS_NORMALIZED
    - entity.ApplyDate (details.ApplyDate fallback)  → FILE_DATE
    - entity.IssueDate (details.IssueDate fallback)  → PERMIT_DATE
    - entity.FinalDate / details.FinalizeDate;
      else latest Passed *Final* processing_status
      (ignored if before IssueDate)                  → FINAL_DATE

  legacy_application
    - application information.general.Status
      (fallback: application_reference.Status,
       then application.Status)                      → STATUS_NORMALIZED
    - Application Received Date                      → FILE_DATE
    - no issuance timestamp in DATA                  → PERMIT_DATE
    - latest PASS inspection whose type contains
      FINAL / FNL / CLOSEOUT                         → FINAL_DATE

Known issues repaired:
  - STATUS_NORMALIZED null on 248 legacy_application
    rows despite clear COMPLETE / ACTIVE / WITHDRAWN /
    EXPIRED / DENIED / ENTERED IN ERROR labels → FILLED.
  - FINAL_DATE missing on many Complete / Final rows
    that have Passed final inspections (or legacy PASS
    FINAL inspections) but null FinalDate → FILLED.

Not repairable / left as-is:
  - FILE_DATE already matches ApplyDate / Application
    Received Date for all sample records.
  - PERMIT_DATE already matches IssueDate whenever
    IssueDate exists; Complete/Final shells with
    Issued=False and all legacy_application rows have
    no issuance date → PERMIT_DATE stays missing.
  - Some Final rows have empty processing_status /
    inspection history and no FinalDate → FINAL_DATE
    stays missing.
"""

from __future__ import annotations

import json
import math
import re
from typing import Optional

import numpy as np
import pandas as pd


# Plausible calendar-year range for permit dates in this jurisdiction.
_MIN_YEAR = 1990
_MAX_YEAR = 2035

_FINAL_INSP_RE = re.compile(r"final|fnl|close\s*out|closeout", re.I)
_FINAL_INSPECTION_OK = ("passed", "approved", "complete", "completed")


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
    """Parse a date value as UTC, returning pd.NaT on failure or implausible year."""
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return pd.NaT
    if isinstance(val, str) and not str(val).strip():
        return pd.NaT
    if not isinstance(val, str) and pd.isna(val):
        return pd.NaT
    text = str(val).strip()
    if text.upper() in ("TBD", "NONE", "N/A", "NA", "NULL", "NAN", "00/00/0000", "0/0/0000"):
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
    if da is pd.NaT or db is pd.NaT:
        return False
    return da.date() == db.date()


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())
    if {"entity", "details"}.issubset(keys):
        has_fees = "fees" in keys
        has_reviews = bool(keys & {"reviews", "holds", "attachments", "more_info"})
        if has_fees and has_reviews:
            return "entity_fees_reviews"
        if has_fees:
            return "entity_fees"
        return "entity_basic"
    if "application" in keys or "application information" in keys:
        return "legacy_application"
    return "unknown"


# ── Status mapping ──────────────────────────────────────────────────────────

# entity.CaseStatus (Title Case, as in DATA) → STATUS_NORMALIZED
_ENTITY_STATUS_MAP = {
    "Complete": "Final",
    "Issued": "Active",
    "In Review": "In Review",
    "Submitted - Online": "In Review",
    "Withdrawn": "Inactive",
    "Expired": "Inactive",
    "Denied": "Inactive",
}

# legacy application information.general.Status → STATUS_NORMALIZED
_LEGACY_STATUS_MAP = {
    "COMPLETE / CLOSED": "Final",
    "COMPLETE / PERMIT READY TO ISSUE": "Final",
    "ACTIVE / OPEN": "Active",
    "ACTIVE / QUICK SERVICE": "Active",
    "ACTIVE / PROJECT READY TO CLOSE": "Active",
    "ACTIVE / CLOSED": "Final",
    "ACTIVE / DIGITAL REVIEW": "In Review",
    "ACTIVE / PERMIT READY TO ISSUE": "In Review",
    "WITHDRAWN / CANCELLED": "Inactive",
    "WITHDRAWN / CLOSED": "Inactive",
    "WITHDRAWN / WITHDRAWAL": "Inactive",
    "WITHDRAWN / ENTERED IN ERROR": "Inactive",
    "EXPIRED / EXPIRED": "Inactive",
    "EXPIRED / OPEN": "Inactive",
    "EXPIRED / QUICK SERVICE": "Inactive",
    "DENIED / CLOSED": "Inactive",
    "ENTERED IN ERROR / ENTERED IN ERROR": "Inactive",
    "ENTERED IN ERROR / CLOSED": "Inactive",
}

# Coarse application.Status fallback when detailed labels are absent
_LEGACY_APP_STATUS_MAP = {
    "COMPLETE": "Final",
    "ACTIVE": "Active",
    "WITHDRAWN": "Inactive",
    "EXPIRED": "Inactive",
    "DENIED": "Inactive",
    "ENTERED IN ERROR": "Inactive",
}


def _case_status(d: dict) -> Optional[str]:
    """Return CaseStatus from entity, falling back to details.PermitStatus."""
    entity = d.get("entity") if isinstance(d.get("entity"), dict) else {}
    details = d.get("details") if isinstance(d.get("details"), dict) else {}
    status = entity.get("CaseStatus") or details.get("PermitStatus")
    if status is None:
        return None
    status = str(status).strip()
    return status or None


def _legacy_status_label(d: dict) -> Optional[str]:
    """Prefer detailed general/reference Status; else coarse application.Status."""
    info = d.get("application information") if isinstance(d.get("application information"), dict) else {}
    general = info.get("general") if isinstance(info.get("general"), dict) else {}
    for raw in (
        general.get("Status"),
        (d.get("application_reference") or {}).get("Status")
        if isinstance(d.get("application_reference"), dict)
        else None,
    ):
        if raw is None:
            continue
        text = str(raw).strip()
        if text:
            return text
    app = d.get("application") if isinstance(d.get("application"), dict) else {}
    raw = app.get("Status")
    if raw is None:
        return None
    text = str(raw).strip()
    return text or None


def _map_legacy_status(label: Optional[str]) -> Optional[str]:
    if not label:
        return None
    if label in _LEGACY_STATUS_MAP:
        return _LEGACY_STATUS_MAP[label]
    if label in _LEGACY_APP_STATUS_MAP:
        return _LEGACY_APP_STATUS_MAP[label]
    # Tolerate odd spacing / case
    upper = re.sub(r"\s+", " ", label).strip().upper()
    for key, mapped in _LEGACY_STATUS_MAP.items():
        if key.upper() == upper:
            return mapped
    for key, mapped in _LEGACY_APP_STATUS_MAP.items():
        if key.upper() == upper:
            return mapped
    return None


def _entity_date(d: dict, entity_key: str, *detail_keys: str):
    """UTC datetime from entity.<key>, else first non-null details key."""
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


def _final_inspection_date_entity(d: dict):
    """Latest Passed/Approved Final* item in processing_status."""
    ps = d.get("processing_status")
    if not isinstance(ps, list):
        return pd.NaT
    best = pd.NaT
    for item in ps:
        if not isinstance(item, dict):
            continue
        desc = str(item.get("description") or "")
        status = str(item.get("status") or "").strip().lower()
        if not _FINAL_INSP_RE.search(desc):
            continue
        if not any(tok in status for tok in _FINAL_INSPECTION_OK):
            continue
        if "partial" in status:
            continue
        dt = _safe_to_datetime(item.get("scheduled_date"))
        if dt is pd.NaT:
            dt = _safe_to_datetime(item.get("requested_date"))
        if dt is pd.NaT:
            continue
        if best is pd.NaT or dt > best:
            best = dt
    return best


def _final_inspection_date_legacy(d: dict):
    """Latest PASS inspection whose type looks like a final / closeout."""
    insp = d.get("inspection") if isinstance(d.get("inspection"), dict) else {}
    rows = insp.get("inspection_data")
    if not isinstance(rows, list):
        return pd.NaT
    best = pd.NaT
    for item in rows:
        if not isinstance(item, dict):
            continue
        result = str(item.get("Result") or "").strip().upper()
        if result != "PASS":
            continue
        itype = str(item.get("Inspection Type") or "")
        if not _FINAL_INSP_RE.search(itype):
            continue
        dt = _safe_to_datetime(item.get("Scheduled"))
        if dt is pd.NaT:
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


def _set_date_from_source(repairs: dict, field: str, current, source, fill_ok: bool) -> None:
    """Overwrite *field* from *source* when missing (if fill_ok) or mismatched."""
    if source is pd.NaT:
        return
    flag = f"{field}_FLAG"
    if pd.isna(current):
        if fill_ok:
            repairs[field] = source
            repairs[flag] = "FILLED"
    elif not _dates_equal(current, source):
        repairs[field] = source
        repairs[flag] = "FIXED"


# ── Per-schema repair logic ─────────────────────────────────────────────────

def _repair_entity(row, d: dict, repairs: dict) -> None:
    current_status = row["STATUS_NORMALIZED"]
    raw_status = _case_status(d)
    expected = _ENTITY_STATUS_MAP.get(raw_status) if raw_status else None
    _set_status(repairs, current_status, expected)
    effective_status = repairs.get("STATUS_NORMALIZED", current_status)

    apply = _entity_date(d, "ApplyDate", "ApplyDate")
    _set_date_from_source(repairs, "FILE_DATE", row["FILE_DATE"], apply, fill_ok=True)

    issue = _entity_date(d, "IssueDate", "IssueDate")
    if not pd.isna(row["PERMIT_DATE"]):
        if issue is not pd.NaT and not _dates_equal(row["PERMIT_DATE"], issue):
            repairs["PERMIT_DATE"] = issue
            repairs["PERMIT_DATE_FLAG"] = "FIXED"
    elif effective_status in ("Active", "Final") and issue is not pd.NaT:
        repairs["PERMIT_DATE"] = issue
        repairs["PERMIT_DATE_FLAG"] = "FILLED"

    # Prefer FinalDate / FinalizeDate; fall back to Passed final inspection.
    # Inspection-only fills must not predate IssueDate (portal chronology noise).
    final_stamp = _entity_date(d, "FinalDate", "FinalizeDate")
    final = final_stamp
    if final is pd.NaT:
        insp_final = _final_inspection_date_entity(d)
        if insp_final is not pd.NaT:
            if issue is pd.NaT or insp_final.date() >= issue.date():
                final = insp_final
    current_final = row["FINAL_DATE"]
    if effective_status == "Final":
        _set_date_from_source(repairs, "FINAL_DATE", current_final, final, fill_ok=True)
    elif not pd.isna(current_final):
        repairs["FINAL_DATE"] = pd.NaT
        repairs["FINAL_DATE_FLAG"] = "FIXED"


def _repair_legacy(row, d: dict, repairs: dict) -> None:
    current_status = row["STATUS_NORMALIZED"]
    label = _legacy_status_label(d)
    expected = _map_legacy_status(label)
    _set_status(repairs, current_status, expected)
    effective_status = repairs.get("STATUS_NORMALIZED", current_status)

    info = d.get("application information") if isinstance(d.get("application information"), dict) else {}
    general = info.get("general") if isinstance(info.get("general"), dict) else {}
    recv = _safe_to_datetime(general.get("Application Received Date"))
    _set_date_from_source(repairs, "FILE_DATE", row["FILE_DATE"], recv, fill_ok=True)

    # No issuance timestamp exists in the legacy payload.
    # Leave PERMIT_DATE as-is (null in this sample).

    final = _final_inspection_date_legacy(d)
    current_final = row["FINAL_DATE"]
    if effective_status == "Final":
        _set_date_from_source(repairs, "FINAL_DATE", current_final, final, fill_ok=True)
    elif not pd.isna(current_final):
        repairs["FINAL_DATE"] = pd.NaT
        repairs["FINAL_DATE_FLAG"] = "FIXED"


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Miramar permit records using the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Miramar".  Must contain
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
        if schema.startswith("entity"):
            _repair_entity(row, d, repairs)
        elif schema == "legacy_application":
            _repair_legacy(row, d, repairs)

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
    AGENT_DATA_PATH = os.getenv("AGENT_DATA_PATH")
    filepath = os.path.join(MY_DATA_PATH, "processed_data", "permits_fl_sample.parquet")
    df = pd.read_parquet(filepath)
    city = df[df["JURISDICTION"] == "Miramar"].copy()

    print(f"Miramar records: {len(city):,}\n")

    repaired = data_repair(city)

    print("INFERRED_SCHEMA:")
    for s, c in repaired["INFERRED_SCHEMA"].value_counts(dropna=False).items():
        print(f"  {str(s):25s}: {c:>4,}")
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

    print("\nSTATUS_NORMALIZED_FLAG by schema / label:")
    for flag in ["FILLED", "FIXED"]:
        sub = repaired[repaired["STATUS_NORMALIZED_FLAG"] == flag]
        print(f"  {flag} ({len(sub)}):")
        labels = []
        for idx in sub.index:
            d = _safe_parse(city.loc[idx, "DATA"])
            schema = repaired.loc[idx, "INFERRED_SCHEMA"]
            if schema.startswith("entity"):
                label = _case_status(d) if d else None
            else:
                label = _legacy_status_label(d) if d else None
            labels.append((schema, label, city.loc[idx, "STATUS_NORMALIZED"], repaired.loc[idx, "STATUS_NORMALIZED"]))
        from collections import Counter

        for (schema, label, before, after), n in Counter(labels).most_common(30):
            print(f"    [{schema}] {label!r}: {before!r} → {after!r}  x{n}")

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

    # Chronology sanity
    r = repaired.copy()
    for c in ("FILE_DATE", "PERMIT_DATE", "FINAL_DATE"):
        r[c] = pd.to_datetime(r[c], errors="coerce")
    print("\nChronology after repair:")
    print(
        "  PERMIT < FILE:",
        (r.PERMIT_DATE.notna() & r.FILE_DATE.notna() & (r.PERMIT_DATE.dt.normalize() < r.FILE_DATE.dt.normalize())).sum(),
    )
    print(
        "  FINAL < PERMIT:",
        (r.FINAL_DATE.notna() & r.PERMIT_DATE.notna() & (r.FINAL_DATE.dt.normalize() < r.PERMIT_DATE.dt.normalize())).sum(),
    )
    print(
        "  FINAL on non-Final:",
        ((r.STATUS_NORMALIZED != "Final") & r.FINAL_DATE.notna()).sum(),
    )

    if AGENT_DATA_PATH:
        out_path = os.path.join(AGENT_DATA_PATH, "miramar_repaired_sample.parquet")
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote {out_path}")

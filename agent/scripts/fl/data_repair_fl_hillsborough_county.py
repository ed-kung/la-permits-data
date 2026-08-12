"""Data repair for Hillsborough County (FL) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Hillsborough County DATA comes from Accela Civic Access (same family as
Tampa). All rows share the same top-level keys; content sub-schemas:

  - accela_with_inspections: non-empty inspections list plus workflow tasks
  - accela_no_inspections:   workflow tasks / detail only (no inspections)

Canonical mappings:
  - DATA.status, overridden by Closure Complete → Final and
    Issuance Issued* → Active when portal status lags          → STATUS_NORMALIZED
  - DATA.date (fallback: search_data.Date)                     → FILE_DATE
  - Earliest Issuance Marked as Issued /
    Issued with Conditions / Revision Issued                   → PERMIT_DATE
  - Latest APPROVED inspection whose title contains "final";
    else first Inspection task Complete/Finished/Closed;
    else Closure Complete/Closed/Finished/Revision Complete;
    else Certification COC/COO Issued;
    else latest APPROVED inspection (Final rows only)          → FINAL_DATE

Known issues repaired:
  - 9 missing STATUS_NORMALIZED (empty portal status with Awaiting Plans,
    Velocity Hall I-ASSIGN / INPROCESS / E-NOCMP) → FILLED.
  - Stale In Review labels after Issuance Issued or Closure Complete
    → FIXED to Active / Final.
  - About to Expire mapped to Inactive upstream → FIXED to Active
    (permit still valid).
  - PERMIT_DATE mismatched vs Issuance Issued* on a handful of rows
    → FIXED; missing issuance-backed dates filled where present.
  - Missing FINAL_DATE on Complete rows filled from inspections /
    Inspection Complete / Closure / Certification.
  - Spurious FINAL_DATE on non-Final rows → cleared.

Not repairable / left as-is:
  - Active/Final rows with no Issuance Issued* event (esp. legacy
    ISSUED Velocity Hall and some Complete/Closed) → PERMIT_DATE stays
    missing.
  - Final rows with no inspections, Inspection-Complete, Closure-
    Complete, or Certification events → FINAL_DATE stays missing.
"""

from __future__ import annotations

import json
import math
from typing import Optional

import numpy as np
import pandas as pd


_MIN_YEAR = 1980
_MAX_YEAR = 2035


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
    """Parse a date value, returning pd.NaT on failure / blanks / sentinels."""
    if val is None:
        return pd.NaT
    if isinstance(val, float) and math.isnan(val):
        return pd.NaT
    if not isinstance(val, str) and pd.isna(val):
        return pd.NaT
    text = str(val).strip()
    if not text or text.upper() in {
        "TBD", "NONE", "N/A", "NA", "NULL", "NAN",
        "00/00/0000", "0/0/0000",
    }:
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


def _event_marked(event: dict) -> tuple[str, object]:
    """Return (Marked as, on-date) from an Accela task event."""
    marked = (event.get("Marked as ") or event.get("Marked as") or "").strip()
    on = event.get(" on ")
    if on is None:
        on = event.get(" on")
    return marked, on


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())
    if not ({"status", "date", "tasks", "inspections"} <= keys):
        return "unknown"
    inspections = data_dict.get("inspections")
    if isinstance(inspections, list) and len(inspections) > 0:
        return "accela_with_inspections"
    return "accela_no_inspections"


def _apply_status(repairs: dict, current, expected: Optional[str]) -> Optional[str]:
    """Apply expected STATUS_NORMALIZED; return effective status."""
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
    """Fill or fix *field* from *candidate* datetime (pd.NaT = no candidate)."""
    cand = _safe_to_datetime(candidate)
    if cand is pd.NaT or pd.isna(cand):
        return

    current = row[field]
    if pd.isna(current):
        repairs[field] = cand
        repairs[f"{field}_FLAG"] = "FILLED"
    elif not _dates_equal(current, cand):
        repairs[field] = cand
        repairs[f"{field}_FLAG"] = "FIXED"


def _clear_date(repairs: dict, row, field: str) -> None:
    """Clear a spurious date value."""
    current = repairs.get(field, row[field])
    if pd.isna(current):
        return
    repairs[field] = pd.NaT
    repairs[f"{field}_FLAG"] = "FIXED"


def _task_event_dates(d: dict, task_name: str, markers: set[str]):
    """Return datetimes for task events whose Marked-as is in *markers*."""
    dates = []
    for task in d.get("tasks") or []:
        if not isinstance(task, dict) or task.get("name") != task_name:
            continue
        for event in task.get("events") or []:
            if not isinstance(event, dict):
                continue
            marked, on = _event_marked(event)
            if marked not in markers:
                continue
            dt = _safe_to_datetime(on)
            if dt is not pd.NaT and not pd.isna(dt):
                dates.append(dt)
    return dates


def _issuance_date(d: dict):
    """Earliest Issuance Issued / Issued with Conditions / Revision Issued."""
    dates = _task_event_dates(
        d,
        "Issuance",
        {"Issued", "Issued with Conditions", "Revision Issued", "Issued - No Inspection"},
    )
    return min(dates) if dates else pd.NaT


def _approved_inspection_dates(d: dict, final_only: bool = False):
    dates = []
    for insp in d.get("inspections") or []:
        if not isinstance(insp, dict):
            continue
        status = (insp.get("Status") or "").strip().lower()
        if status not in ("approved", "passed", "complete", "completed"):
            continue
        title = insp.get("Title") or ""
        if final_only and "final" not in str(title).lower():
            continue
        dt = _safe_to_datetime(insp.get("Status Date"))
        if dt is pd.NaT or pd.isna(dt):
            dt = _safe_to_datetime(insp.get("Last Update Date"))
        if dt is not pd.NaT and not pd.isna(dt):
            dates.append(dt)
    return dates


def _final_date_candidate(d: dict):
    """Best available completion / finalization date from DATA."""
    final_insp = _approved_inspection_dates(d, final_only=True)
    if final_insp:
        return max(final_insp)

    insp_complete = _task_event_dates(
        d, "Inspection", {"Complete", "Finished", "Closed", "Approved"}
    )
    if insp_complete:
        # Upstream FINAL_DATE usually matches the first Inspection Complete.
        return min(insp_complete)

    closure = _task_event_dates(
        d,
        "Closure",
        {"Complete", "Closed", "Finished", "Revision Complete", "Revision Closed"},
    )
    if closure:
        return max(closure)

    cert = _task_event_dates(
        d, "Certification", {"COC Issued", "COO Issued", "TCO Issued"}
    )
    if cert:
        return max(cert)

    any_insp = _approved_inspection_dates(d, final_only=False)
    if any_insp:
        return max(any_insp)

    return pd.NaT


# ── Status map ───────────────────────────────────────────────────────────────

_STATUS_MAP = {
    # Final / completed / administratively closed
    "Complete": "Final",
    "Closed": "Final",
    # Active / issued / still-valid near expiry
    "Issued": "Active",
    "ISSUED": "Active",
    "About to Expire": "Active",
    # In review / pre-issuance / awaiting applicant
    "In Process": "In Review",
    "INPROCESS": "In Review",
    "Awaiting Client Reply": "In Review",
    "Open": "In Review",
    "Pending": "In Review",
    "I-ASSIGN": "In Review",
    # Inactive
    "Expired": "Inactive",
    "Withdrawn": "Inactive",
    "Cancel": "Inactive",
    "E-NOCMP": "Inactive",
}


def _has_awaiting_plans(d: dict) -> bool:
    for task in d.get("tasks") or []:
        if not isinstance(task, dict):
            continue
        for event in task.get("events") or []:
            if not isinstance(event, dict):
                continue
            marked, _ = _event_marked(event)
            if marked == "Awaiting Plans":
                return True
    return False


def _map_status(d: dict) -> Optional[str]:
    """Map DATA.status, with workflow overrides for stale portal labels.

    Live ``status`` sometimes lags the task history (e.g. still "In Process"
    after Issuance Issued or Closure Complete). Prefer terminal task
    evidence in those cases, but trust explicit Expired / Withdrawn /
    Cancel / E-NOCMP labels.
    """
    raw = d.get("status")
    text = str(raw).strip() if raw is not None else ""
    base = _STATUS_MAP.get(text) if text else None
    if base is None and text:
        # Case-insensitive fallback
        for key, val in _STATUS_MAP.items():
            if key.lower() == text.lower():
                base = val
                break

    if not text and _has_awaiting_plans(d):
        base = "In Review"

    if base == "Inactive":
        return base

    has_closure = bool(
        _task_event_dates(
            d,
            "Closure",
            {"Complete", "Closed", "Finished", "Revision Complete", "Revision Closed"},
        )
    )
    issue = _issuance_date(d)
    has_issued = issue is not pd.NaT and not pd.isna(issue)

    if has_closure:
        return "Final"
    if base == "Final":
        return "Final"
    if has_issued or base == "Active":
        return "Active"
    return base


# ── Repair logic ─────────────────────────────────────────────────────────────

def _repair_record(row, d: dict, repairs: dict) -> None:
    """Repair one Hillsborough County Accela record."""
    expected = _map_status(d)
    effective_status = _apply_status(repairs, row["STATUS_NORMALIZED"], expected)

    # FILE_DATE ← top-level date
    file_src = d.get("date")
    if _safe_to_datetime(file_src) is pd.NaT or pd.isna(_safe_to_datetime(file_src)):
        search = d.get("search_data") or {}
        if isinstance(search, dict):
            file_src = search.get("Date")
    _apply_date(repairs, row, "FILE_DATE", file_src)

    # PERMIT_DATE ← earliest Issuance Issued*
    issue = _issuance_date(d)
    if issue is not pd.NaT and not pd.isna(issue):
        if effective_status in ("Active", "Final", "Inactive"):
            _apply_date(repairs, row, "PERMIT_DATE", issue)
        elif effective_status == "In Review":
            # Issued workflow on an In Review label is inconsistent; still
            # prefer the issuance date over a stale near-final PERMIT_DATE.
            _apply_date(repairs, row, "PERMIT_DATE", issue)
    elif effective_status == "In Review":
        _clear_date(repairs, row, "PERMIT_DATE")

    # FINAL_DATE ← inspections / Inspection Complete / Closure / Certification
    final_src = _final_date_candidate(d)
    if effective_status == "Final":
        if final_src is not pd.NaT and not pd.isna(final_src):
            _apply_date(repairs, row, "FINAL_DATE", final_src)
    else:
        current_final = repairs.get("FINAL_DATE", row["FINAL_DATE"])
        if not pd.isna(current_final):
            _clear_date(repairs, row, "FINAL_DATE")


# ── Main entry point ─────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Hillsborough County permit records using the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Hillsborough County".  Must
        contain columns STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE,
        FINAL_DATE, and DATA.

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
        if schema in ("accela_with_inspections", "accela_no_inspections"):
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
    AGENT_DATA_PATH = os.getenv("AGENT_DATA_PATH")
    filepath = os.path.join(MY_DATA_PATH, "processed_data", "permits_fl_sample.parquet")
    df = pd.read_parquet(filepath)
    city = df[df["JURISDICTION"] == "Hillsborough County"].copy()

    print(f"Hillsborough County records: {len(city):,}\n")

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

    print("\nSTATUS fills/fixes detail:")
    changed = repaired[repaired["STATUS_NORMALIZED_FLAG"].notna()][
        ["STATUS_ORIGINAL", "STATUS_NORMALIZED"]
    ].copy()
    changed["BEFORE"] = city.loc[changed.index, "STATUS_NORMALIZED"]
    print(changed.groupby(["BEFORE", "STATUS_NORMALIZED", "STATUS_ORIGINAL"], dropna=False).size())

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

    both = repaired[repaired["PERMIT_DATE"].notna() & repaired["FINAL_DATE"].notna()]
    bad = both[
        both["PERMIT_DATE"].dt.normalize() > both["FINAL_DATE"].dt.normalize()
    ]
    print(f"\nPERMIT_DATE > FINAL_DATE after repair: {len(bad):,}")

    iss_match = 0
    iss_avail = 0
    for idx in repaired.index:
        d = _safe_parse(repaired.at[idx, "DATA"])
        if d is None:
            continue
        issue = _issuance_date(d)
        if issue is pd.NaT or pd.isna(issue):
            continue
        iss_avail += 1
        if _dates_equal(repaired.at[idx, "PERMIT_DATE"], issue):
            iss_match += 1
    print(f"PERMIT_DATE == Issuance Issued* (where available): {iss_match}/{iss_avail}")

    still_null = repaired[repaired["STATUS_NORMALIZED"].isna()]
    print(f"\nRemaining null STATUS_NORMALIZED: {len(still_null):,}")

    if AGENT_DATA_PATH:
        out_path = os.path.join(AGENT_DATA_PATH, "hillsborough_county_repaired_sample.parquet")
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote {out_path}")

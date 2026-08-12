"""Data repair for Tampa (FL) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Tampa DATA comes from the city's Accela Civic Access portal. All rows
share the same top-level keys; two content sub-schemas are distinguished:

  - accela_with_inspections: non-empty inspections list plus workflow tasks
  - accela_no_inspections:   workflow tasks / detail only (no inspections)

Canonical mappings:
  - DATA.status, overridden by Closure Complete → Final and
    Issuance Issued → Active when portal status lags          → STATUS_NORMALIZED
  - DATA.date (fallback: search_data.Date)                   → FILE_DATE
  - Earliest Issuance task marked Issued /
    Issued - No Inspection                                   → PERMIT_DATE
  - Latest APPROVED inspection whose title contains "final";
    else first Inspection task Complete/Finished/Closed;
    else Closure Complete/Closed/Finished/Revision Complete;
    else latest APPROVED inspection (Final rows only)        → FINAL_DATE

Known issues repaired:
  - STATUS_NORMALIZED was derived from a stale STATUS_ORIGINAL /
    search-list snapshot. Live DATA.status is often newer, and
    sometimes still lags task history (In Process after Issued
    or Closure Complete) → FIXED / FILLED.
  - PERMIT_DATE on some new-construction rows was near FINAL_DATE
    rather than the Issuance Issued date → FIXED to Issuance.
  - Missing PERMIT_DATE / FINAL_DATE filled from Issuance /
    inspections / Closure when present.
  - Spurious PERMIT_DATE on unissued In Review rows → cleared.
  - FINAL_DATE on non-Final rows → cleared.

Not repairable / left as-is:
  - Many Complete/Closed Final rows (esp. legacy AACONV, admin, and
    utility/license records) never record an Issuance Issued event →
    PERMIT_DATE stays missing.
  - Final rows with neither inspections, Inspection-Complete, nor
    Closure-Complete events → FINAL_DATE stays missing.
"""

from __future__ import annotations

import json
import math
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
    """Parse a date value, returning pd.NaT on failure / blanks."""
    if val is None or (isinstance(val, str) and not str(val).strip()):
        return pd.NaT
    if not isinstance(val, str) and pd.isna(val):
        return pd.NaT
    text = str(val).strip()
    if text.upper() in ("TBD", "NONE", "N/A", "NA", "NULL", "NAN", "00/00/0000", "0/0/0000"):
        return pd.NaT
    try:
        return pd.to_datetime(val)
    except (ValueError, TypeError, OverflowError):
        return pd.NaT


def _dates_equal(a, b) -> bool:
    """Compare two datelike values at calendar-day resolution."""
    da = _safe_to_datetime(a)
    db = _safe_to_datetime(b)
    if da is pd.NaT or db is pd.NaT:
        return False
    return da.normalize() == db.normalize()


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
        if pd.isna(current):
            return None
        return current

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


def _clear_date(repairs: dict, row, field: str) -> None:
    """Clear a spurious date value."""
    if not pd.isna(row[field]):
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
            marked = (event.get("Marked as ") or "").strip()
            if marked not in markers:
                continue
            dt = _safe_to_datetime(event.get(" on "))
            if dt is not pd.NaT:
                dates.append(dt)
    return dates


def _issuance_date(d: dict):
    """Earliest Issuance Issued / Issued - No Inspection date."""
    dates = _task_event_dates(
        d,
        "Issuance",
        {"Issued", "Issued - No Inspection"},
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
        if dt is pd.NaT:
            dt = _safe_to_datetime(insp.get("Last Update Date"))
        if dt is not pd.NaT:
            dates.append(dt)
    return dates


def _final_date_candidate(d: dict):
    """Best available completion / finalization date from DATA."""
    final_insp = _approved_inspection_dates(d, final_only=True)
    if final_insp:
        return max(final_insp)

    insp_complete = _task_event_dates(
        d, "Inspection", {"Complete", "Finished", "Closed"}
    )
    if insp_complete:
        # Upstream FINAL_DATE usually matches the first Inspection Complete.
        return min(insp_complete)

    closure = _task_event_dates(
        d,
        "Closure",
        {"Complete", "Closed", "Finished", "Revision Complete"},
    )
    if closure:
        return max(closure)

    any_insp = _approved_inspection_dates(d, final_only=False)
    if any_insp:
        return max(any_insp)

    return pd.NaT


# ── Status map ───────────────────────────────────────────────────────────────

_STATUS_MAP = {
    # Final / completed / administratively closed
    "Complete": "Final",
    "Closed": "Final",
    "Administrative Close": "Final",
    "Administrative Closed": "Final",
    # Active / issued
    "Issued": "Active",
    "About to Expire": "Active",
    # In review / pre-issuance / awaiting applicant
    "In Process": "In Review",
    "in Process": "In Review",
    "In Progress": "In Review",
    "Awaiting Client Reply": "In Review",
    "Client Scheduling Required": "In Review",
    "Open": "In Review",
    "Revision": "In Review",
    "Site Plan Review Complete": "In Review",
    # Inactive
    "Expired": "Inactive",
    "Withdrawn": "Inactive",
}


def _map_status(d: dict) -> Optional[str]:
    """Map DATA.status, with workflow overrides for stale portal labels.

    Live ``status`` sometimes lags the task history (e.g. still "In Process"
    after Issuance Issued or even Closure Complete). Prefer terminal task
    evidence in those cases, but trust explicit Expired / Withdrawn labels.
    """
    raw = d.get("status")
    text = str(raw).strip() if raw is not None else ""
    base = _STATUS_MAP.get(text) if text else None

    if base == "Inactive":
        return base

    has_closure = bool(
        _task_event_dates(
            d,
            "Closure",
            {"Complete", "Closed", "Finished", "Revision Complete"},
        )
    )
    has_issued = _issuance_date(d) is not pd.NaT

    if has_closure:
        return "Final"
    if base == "Final":
        return "Final"
    if has_issued or base == "Active":
        return "Active"
    return base


# ── Repair logic ─────────────────────────────────────────────────────────────

def _repair_record(row, d: dict, repairs: dict) -> None:
    """Repair one Tampa Accela record."""
    expected = _map_status(d)
    effective_status = _apply_status(repairs, row["STATUS_NORMALIZED"], expected)

    # FILE_DATE ← top-level date (same as search_data.Date when present)
    file_src = d.get("date")
    if _safe_to_datetime(file_src) is pd.NaT:
        search = d.get("search_data") or {}
        if isinstance(search, dict):
            file_src = search.get("Date")
    _apply_date(repairs, row, "FILE_DATE", file_src)

    # PERMIT_DATE ← earliest Issuance Issued*
    issue = _issuance_date(d)
    if issue is not pd.NaT:
        if effective_status in ("Active", "Final", "Inactive"):
            _apply_date(repairs, row, "PERMIT_DATE", issue)
        elif effective_status == "In Review":
            # Issued workflow on an In Review label is inconsistent; still
            # prefer the issuance date over a stale near-final PERMIT_DATE.
            _apply_date(repairs, row, "PERMIT_DATE", issue)
    elif effective_status == "In Review":
        _clear_date(repairs, row, "PERMIT_DATE")

    # FINAL_DATE ← inspections / Inspection Complete / Closure (Final only)
    final_src = _final_date_candidate(d)
    if effective_status == "Final":
        if final_src is not pd.NaT:
            _apply_date(repairs, row, "FINAL_DATE", final_src)
    elif not pd.isna(row["FINAL_DATE"]):
        _clear_date(repairs, row, "FINAL_DATE")


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Tampa permit records using information from the raw DATA JSON.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Tampa".  Must contain
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
        if schema in ("accela_with_inspections", "accela_no_inspections"):
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
    AGENT_DATA_PATH = os.getenv("AGENT_DATA_PATH")
    filepath = os.path.join(MY_DATA_PATH, "processed_data", "permits_fl_sample.parquet")
    df = pd.read_parquet(filepath)
    city = df[df["JURISDICTION"] == "Tampa"].copy()

    print(f"Tampa records: {len(city):,}\n")

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
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({n_has / len(sub) if len(sub) else 0:.1%})")

    print("\nPERMIT_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["PERMIT_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({n_has / len(sub) if len(sub) else 0:.1%})")

    print("\nFINAL_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FINAL_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({n_has / len(sub) if len(sub) else 0:.1%})")

    # Chronology checks
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
        if issue is pd.NaT:
            continue
        iss_avail += 1
        if _dates_equal(repaired.at[idx, "PERMIT_DATE"], issue):
            iss_match += 1
    print(f"PERMIT_DATE == Issuance Issued (where available): {iss_match}/{iss_avail}")

    still_null = repaired[repaired["STATUS_NORMALIZED"].isna()]
    print(f"\nRemaining null STATUS_NORMALIZED: {len(still_null):,}")

    if AGENT_DATA_PATH:
        out_path = os.path.join(AGENT_DATA_PATH, "tampa_repaired_sample.parquet")
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote {out_path}")

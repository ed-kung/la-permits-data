"""Data repair for Brownsville (TX) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Brownsville DATA is Accela Civic Platform. Two top-level key-set variants
appear in the sample:

  - accela:            full payload (status, date, tasks, inspections, …)
  - search_data_only:  temporary / incomplete shells with only search_data
                       (blank Status; FILE_DATE already from search_data.Date)

Canonical mappings:
  - status                                              → STATUS_NORMALIZED
  - date                                                → FILE_DATE
  - Permit Issuance marked Issued                       → PERMIT_DATE
  - Inspection* Final Inspection Complete;
    Certificate of Occupancy Final CO Issued /
    Certificate Issued; inspections Title contains
    Final + Status Passed; Modification Review
    Modification Request Approved                       → FINAL_DATE (Final only)

Known issues repaired:
  - STATUS_NORMALIZED null for Pending Contractor /
    Form Survey Required / Pending Fire Inspection → FILLED (In Review,
    or Active when Permit Issuance Issued is present).
  - About to Expire stored as Inactive → FIXED to Active.
  - Closed (cancelled / withdrawn shells, no issuance) stored as Final
    → FIXED to Inactive.
  - Post-issuance Accela holds still labeled In Review (e.g. Form Survey
    Required after Issued) → FIXED/FILLED to Active.
  - PERMIT_DATE incorrectly copied from FILE_DATE when Permit Issuance
    Issued is a later day → FIXED.
  - Spurious PERMIT_DATE (= FILE_DATE) on Ready to Issue / Withdrawn
    rows with no Issued event → cleared (FIXED).
  - Missing FINAL_DATE on Final rows when Final Inspection / CO /
    Final* Passed inspection / Modification Approved exists → FILLED.
  - FINAL_DATE using an earlier Final Inspection Complete when a later
    one exists → FIXED to latest.
  - Spurious FINAL_DATE on non-Final rows (mostly Permit Expired) →
    cleared (FIXED).

Not repairable / left as-is:
  - search_data_only rows with blank Status → STATUS_NORMALIZED stays
    null.
  - Active Inspection Phase / Approved rows with no Permit Issuance
    Issued event → PERMIT_DATE stays missing.
  - Final Closed - Complete shells with no final / CO / Final* Passed
    signal → FINAL_DATE stays missing.
  - FILE_DATE already complete and matches DATA.date / search_data.Date.
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
    if isinstance(val, dict):
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


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())
    if {"status", "date", "tasks"} <= keys:
        return "accela"
    if keys == {"search_data"} or (
        "search_data" in keys and "status" not in keys
    ):
        return "search_data_only"
    return "unknown"


# ── Status mapping ───────────────────────────────────────────────────────────

_STATUS_MAP = {
    # Final — completed / signed-off building work
    "Closed - Complete": "Final",
    "Closed - Completed": "Final",
    "Final Inspection Complete": "Final",
    # Closed - Approved: admin workflows (e.g. Add/Change Licensed
    # Professional) that finished successfully
    "Closed - Approved": "Final",
    # Active — issued / in construction / still valid
    "Inspection Phase": "Active",
    "Approved": "Active",
    "Issued": "Active",
    "About to Expire": "Active",
    # In Review — not yet issued
    "Ready to Issue": "In Review",
    "In Review": "In Review",
    "Additional Info Required": "In Review",
    "Pending": "In Review",
    "Revisions Required": "In Review",
    "Ready for Payment": "In Review",
    "Pending Contractor": "In Review",
    "Pending Fire Inspection": "In Review",
    "Form Survey Required": "In Review",
    # Inactive — expired / denied / cancelled / withdrawn
    # Plain "Closed" is used for cancelled applications (no issuance)
    "Closed": "Inactive",
    "Permit Expired": "Inactive",
    "Closed - Withdrawn": "Inactive",
    "Closed-Withdrawn": "Inactive",
    "Closed - Denied": "Inactive",
    "Closed - Cancelled": "Inactive",
    "Cancelled": "Inactive",
    "Denied": "Inactive",
}


def _apply_status(repairs: dict, current, expected: Optional[str]):
    """Apply expected STATUS_NORMALIZED; return effective status."""
    if expected is None:
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


def _event_marked(event: dict) -> Optional[str]:
    marked = event.get("Marked as ")
    if marked is None:
        marked = event.get("Marked as")
    if marked is None or (isinstance(marked, float) and math.isnan(marked)):
        return None
    text = str(marked).strip()
    return text or None


def _event_on(event: dict):
    dt = _safe_to_datetime(event.get(" on "))
    if dt is pd.NaT or pd.isna(dt):
        dt = _safe_to_datetime(event.get("on"))
    return dt


def _task_dates(d: dict, task_names: set, marked_values: set) -> list:
    """Collect event dates for named Accela tasks with given marks."""
    dates = []
    for task in d.get("tasks") or []:
        if not isinstance(task, dict) or task.get("name") not in task_names:
            continue
        for event in task.get("events") or []:
            if not isinstance(event, dict):
                continue
            if _event_marked(event) in marked_values:
                dt = _event_on(event)
                if dt is not pd.NaT and not pd.isna(dt):
                    dates.append(dt)
    return dates


def _earliest_task_date(d: dict, task_names: set, marked_values: set):
    dates = _task_dates(d, task_names, marked_values)
    return min(dates) if dates else pd.NaT


def _latest_task_date(d: dict, task_names: set, marked_values: set):
    dates = _task_dates(d, task_names, marked_values)
    return max(dates) if dates else pd.NaT


def _expected_status(d: dict) -> Optional[str]:
    raw = d.get("status")
    mapped = None
    if raw is not None and not (isinstance(raw, float) and math.isnan(raw)):
        text = str(raw).strip()
        if text:
            mapped = _STATUS_MAP.get(text)

    # Post-issuance holds (e.g. Form Survey Required) stay "In Review" in
    # Accela wording but the permit has already been issued → Active.
    issued = _permit_date(d)
    if mapped == "In Review" and issued is not pd.NaT and not pd.isna(issued):
        return "Active"

    return mapped


def _permit_date(d: dict):
    """Earliest Permit Issuance marked Issued."""
    return _earliest_task_date(d, {"Permit Issuance"}, {"Issued"})


def _final_inspection_passed_date(d: dict):
    """Latest inspections[] row with Final in the title and Status Passed."""
    dates = []
    for insp in d.get("inspections") or []:
        if not isinstance(insp, dict):
            continue
        title = str(insp.get("Title") or "")
        status = str(insp.get("Status") or "").strip().lower()
        if "final" not in title.lower():
            continue
        if status != "passed":
            continue
        dt = _safe_to_datetime(insp.get("Status Date"))
        if dt is pd.NaT or pd.isna(dt):
            dt = _safe_to_datetime(insp.get("Last Update Date"))
        if dt is not pd.NaT and not pd.isna(dt):
            dates.append(dt)
    return max(dates) if dates else pd.NaT


def _final_date(d: dict):
    """Best completion / sign-off date for Final records."""
    candidates = []

    for task_names, marks in (
        (
            {
                "Inspection",
                "Inspection Phase",
                "Building Inspection",
                "Building Inspections",
            },
            {"Final Inspection Complete", "Inspections Passed"},
        ),
        (
            {"Certificate of Occupancy", "Certificate Of occupancy"},
            {"Final CO Issued", "Certificate Issued"},
        ),
        (
            {"Modification Review"},
            {"Modification Request Approved"},
        ),
    ):
        dt = _latest_task_date(d, task_names, marks)
        if dt is not pd.NaT and not pd.isna(dt):
            candidates.append(dt)

    insp_passed = _final_inspection_passed_date(d)
    if insp_passed is not pd.NaT and not pd.isna(insp_passed):
        candidates.append(insp_passed)

    return max(candidates) if candidates else pd.NaT


# ── Per-row repair ───────────────────────────────────────────────────────────

def _repair_row(row, d: dict, repairs: dict) -> None:
    """Repair one Brownsville Accela record."""
    expected = _expected_status(d)
    effective_status = _apply_status(repairs, row["STATUS_NORMALIZED"], expected)

    # -- FILE_DATE ← top-level date (application / record open date) --
    _apply_date(repairs, row, "FILE_DATE", d.get("date"))

    # -- PERMIT_DATE ← Permit Issuance Issued --
    issued = _permit_date(d)
    if issued is not pd.NaT and not pd.isna(issued):
        _apply_date(repairs, row, "PERMIT_DATE", issued)
    else:
        # Upstream often copied FILE_DATE into PERMIT_DATE before issuance
        current_permit = row["PERMIT_DATE"]
        if pd.notna(current_permit) and _dates_equal(current_permit, row["FILE_DATE"]):
            _clear_date(repairs, row, "PERMIT_DATE")

    # -- FINAL_DATE ← final inspection / CO / mod approved (Final only) --
    if effective_status == "Final":
        _apply_date(repairs, row, "FINAL_DATE", _final_date(d))
    else:
        _clear_date(repairs, row, "FINAL_DATE")


def _repair_search_data_only(row, d: dict, repairs: dict) -> None:
    """Repair incomplete shells that only carry search_data."""
    sd = d.get("search_data") or {}
    if not isinstance(sd, dict):
        return

    # FILE_DATE ← search_data.Date when missing
    _apply_date(repairs, row, "FILE_DATE", sd.get("Date"))

    raw = sd.get("Status")
    if raw is not None and not (isinstance(raw, float) and math.isnan(raw)):
        text = str(raw).strip()
        if text:
            _apply_status(repairs, row["STATUS_NORMALIZED"], _STATUS_MAP.get(text))


# ── Main entry point ─────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Brownsville permit records using the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Brownsville".  Must contain
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
        if d is None:
            continue

        repairs: dict = {}
        if schema == "accela":
            _repair_row(row, d, repairs)
        elif schema == "search_data_only":
            _repair_search_data_only(row, d, repairs)

        for key, value in repairs.items():
            out.at[idx, key] = value

    return out


# ── CLI: run standalone to preview repair stats ─────────────────────────────

if __name__ == "__main__":
    import os

    from dotenv import load_dotenv

    load_dotenv("/Users/ekung/projects/la-permits-data/.env")
    MY_DATA_PATH = os.getenv("MY_DATA_PATH")
    AGENT_DATA_PATH = os.getenv("AGENT_DATA_PATH")
    filepath = os.path.join(MY_DATA_PATH, "processed_data", "permits_tx_sample.parquet")
    df = pd.read_parquet(filepath)
    city = df[(df["JURISDICTION"] == "Brownsville") & (df["STATE"] == "TX")].copy()

    print(f"Brownsville records: {len(city):,}\n")

    repaired = data_repair(city)

    print("INFERRED_SCHEMA distribution:")
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

    print("\nFILE_DATE overall (after): "
          f"{repaired['FILE_DATE'].notna().sum()}/{len(repaired)}")

    print("\nPERMIT_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        if len(sub) == 0:
            continue
        n_has = sub["PERMIT_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({n_has / len(sub):.1%})")

    print("\nFINAL_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        if len(sub) == 0:
            continue
        n_has = sub["FINAL_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({n_has / len(sub):.1%})")

    if AGENT_DATA_PATH:
        out_dir = os.path.join(AGENT_DATA_PATH, "repaired")
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, "permits_tx_brownsville_repaired.parquet")
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote {out_path}")

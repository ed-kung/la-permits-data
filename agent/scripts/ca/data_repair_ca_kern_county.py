"""Data repair for Kern County (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Kern County DATA is an Accela Citizen Access scrape. All sample rows share
the same top-level keys (date, status, tasks, inspections, search_data,
details, contacts, fees_details, more_details, etc.). Task event keys have
leading/trailing spaces ('Marked as ', ' on '), same as other Accela
portals. Workflow / content variants (used as INFERRED_SCHEMA):

  - building_permit:   has Permit Issuance task
  - code_enforcement:  has Case Intake / Close Case
  - planning:          has Issuance + Review Cycle (O&G / planning)
  - otc_simple:        Application Intake + Inspections, no Permit Issuance
  - other:             remaining Accela task shells

Canonical mappings:
  - DATA.status                                      → STATUS_NORMALIZED
  - DATA.date / search_data['Date']                  → FILE_DATE
  - Permit Issuance / Issued (fallback: Issued
    w/Revision; planning Issuance / Issued;
    OTC Application Intake / Accepted No PC)         → PERMIT_DATE
  - Inspections / Finaled|Close, Close Case / Close*,
    Closed / Closed, Investigation / Case Closed     → FINAL_DATE

Known issues repaired:
  - 29 unmapped DATA.status values (Notice and Order, Pending Initial
    Inspection, Closed, blank, etc.) → FILLED.
  - Stale STATUS_ORIGINAL-derived labels vs current DATA.status
    (Finaled labeled Active/In Review; Issued labeled In Review;
    Canceled labeled Active/In Review; Approved labeled In Review)
    → FIXED.
  - PERMIT_DATE set to C of O Issuance / C of O Issued instead of
    Permit Issuance / Issued → FIXED.
  - Active/Final rows missing PERMIT_DATE despite Issued /
    Issued w/Revision / planning Issuance / OTC Accepted No PC → FILLED.
  - Final rows missing FINAL_DATE despite Finaled / Close Case /
    Case Closed events → FILLED (including rows remapped to Final).
  - Spurious FINAL_DATE on non-Final rows → cleared (FIXED).

Not repairable / left as-is:
  - FILE_DATE already matches DATA.date for all sample rows.
  - Hundreds of Closed code-enforcement / planning shells and Approved
    OTC rows have no issuance-style event → PERMIT_DATE stays missing.
  - A handful of Closed / Withdrawn shells lack a dated closure event
    → FINAL_DATE stays missing.
"""

import json
import math
from typing import Optional

import pandas as pd
import numpy as np


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
        return json.loads(data)
    return data


def _safe_to_datetime(val):
    """Parse a date value, returning pd.NaT on failure or implausible year."""
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return pd.NaT
    if isinstance(val, str) and not str(val).strip():
        return pd.NaT
    if isinstance(val, str) and val.strip().upper() == "TBD":
        return pd.NaT
    try:
        dt = pd.to_datetime(val)
    except (ValueError, TypeError):
        return pd.NaT
    if dt is pd.NaT or pd.isna(dt):
        return pd.NaT
    year = int(dt.year)
    if year < _MIN_YEAR or year > _MAX_YEAR:
        return pd.NaT
    return dt


def _event_field(event: dict, *names: str):
    """Read an event field, tolerating leading/trailing spaces in keys."""
    targets = {n.strip() for n in names}
    for k, v in event.items():
        if isinstance(k, str) and k.strip() in targets:
            return v
    return None


def _iter_tasks(tasks: list):
    """Yield top-level tasks and nested subtasks."""
    for t in tasks or []:
        if not isinstance(t, dict):
            continue
        yield t
        for st in t.get("subtasks") or []:
            if isinstance(st, dict):
                yield st


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())
    if "tasks" not in keys or "status" not in keys:
        if "search_data" in keys and "status" in keys:
            return "search_data"
        return "unknown"

    names = {
        t.get("name")
        for t in (data_dict.get("tasks") or [])
        if isinstance(t, dict)
    }
    if "Permit Issuance" in names:
        return "building_permit"
    if "Case Intake" in names or "Close Case" in names:
        return "code_enforcement"
    if "Issuance" in names and "Review Cycle" in names:
        return "planning"
    if "Application Intake" in names and (
        "Inspections" in names or "Inspection" in names
    ):
        return "otc_simple"
    return "other"


def _event_dates(tasks: list, task_name: str, marked_as):
    """Dates for task_name events whose Marked-as matches *marked_as*.

    *marked_as* may be a string (exact) or a callable(str) -> bool.
    """
    dates = []
    for t in _iter_tasks(tasks):
        if t.get("name") != task_name:
            continue
        for e in t.get("events") or []:
            if not isinstance(e, dict):
                continue
            marked = _event_field(e, "Marked as")
            if marked is None:
                continue
            if callable(marked_as):
                if not marked_as(str(marked)):
                    continue
            elif marked != marked_as:
                continue
            dt = _safe_to_datetime(_event_field(e, "on"))
            if dt is not pd.NaT:
                dates.append(dt)
    return dates


def _first_event_date(tasks: list, task_name: str, marked_as):
    dates = _event_dates(tasks, task_name, marked_as)
    return min(dates) if dates else pd.NaT


def _latest_event_date(tasks: list, task_name: str, marked_as):
    dates = _event_dates(tasks, task_name, marked_as)
    return max(dates) if dates else pd.NaT


def _is_close_case_mark(marked: str) -> bool:
    """Close Case marks that represent case closure (not reopen / hold)."""
    m = marked.strip().lower()
    if m in {"tbd", "notes", "reopen case", "close - hold"}:
        return False
    return (
        m == "close"
        or m.startswith("close -")
        or m in {"duplicate case", "expungement"}
    )


def _issued_date(tasks: list):
    """Earliest true issuance date across Kern workflows."""
    issued = _first_event_date(tasks, "Permit Issuance", "Issued")
    if issued is not pd.NaT:
        return issued

    rev = _first_event_date(tasks, "Permit Issuance", "Issued w/Revision")
    if rev is not pd.NaT:
        return rev

    # Planning / O&G Accela shells use top-level Issuance / Issued.
    planning = _first_event_date(tasks, "Issuance", "Issued")
    if planning is not pd.NaT:
        return planning

    # OTC city permits often skip Permit Issuance and go Accepted No PC.
    otc = _first_event_date(tasks, "Application Intake", "Accepted No PC")
    if otc is not pd.NaT:
        return otc

    return pd.NaT


def _final_date_from_data(tasks: list):
    """Best available finaling / closure date for Kern Accela tasks."""
    for task_name in ("Inspections", "Inspection"):
        dt = _latest_event_date(tasks, task_name, "Finaled")
        if dt is not pd.NaT:
            return dt

    for task_name in ("Inspections", "Inspection"):
        dt = _latest_event_date(tasks, task_name, "Close")
        if dt is not pd.NaT:
            return dt

    dt = _latest_event_date(tasks, "Close Case", _is_close_case_mark)
    if dt is not pd.NaT:
        return dt

    for task_name, marked_as in (
        ("Closed", "Closed"),
        ("Close", "Closed"),
        ("Case Intake", "Case Closed"),
        ("Investigation", "Case Closed"),
        ("Initial Investigation", "Case Closed"),
        ("Follow-Up Investigation", "Case Closed"),
    ):
        dt = _latest_event_date(tasks, task_name, marked_as)
        if dt is not pd.NaT:
            return dt

    return pd.NaT


# ── Status mapping ──────────────────────────────────────────────────────────

# DATA.status (Title Case, as stored) → STATUS_NORMALIZED
_STATUS_MAP = {
    # Final
    "Finaled": "Final",
    "Closed": "Final",
    "Recorded": "Final",
    # Active — issued / approved / open enforcement
    "Issued": "Active",
    "Issued w/Revision": "Active",
    "Approved": "Active",
    "Active": "Active",
    "Notice and Order": "Active",
    "Vehicle Notice & Order": "Active",
    "Pending Initial Inspection": "Active",
    "Pending County Abatement": "Active",
    "Immediate Response": "Active",
    "Breakdown": "Active",
    # Inactive
    "Canceled": "Inactive",
    "Withdrawn": "Inactive",
    # In Review — application / plan check / pre-issuance
    "Applied": "In Review",
    "In Review": "In Review",
    "Accepted": "In Review",
    "Open": "In Review",
    "Processing": "In Review",
    "Prelim. Review": "In Review",
    "Review Complete": "In Review",
}


# ── Repair logic ────────────────────────────────────────────────────────────

def _repair_tasks(row, d: dict, repairs: dict):
    """Repair an Accela tasks-schema Kern County record."""
    tasks = d.get("tasks") or []
    data_status = d.get("status")
    if isinstance(data_status, str) and not data_status.strip():
        data_status = None

    # -- STATUS_NORMALIZED --
    current_status = row["STATUS_NORMALIZED"]
    if data_status is None:
        expected = "In Review"
    else:
        expected = _STATUS_MAP.get(data_status)

    if expected is not None:
        if pd.isna(current_status):
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"
        elif current_status != expected:
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FIXED"

    effective_status = repairs.get("STATUS_NORMALIZED", current_status)

    # -- FILE_DATE --
    file_date = _safe_to_datetime(d.get("date"))
    if file_date is pd.NaT:
        sd = d.get("search_data") or {}
        if isinstance(sd, dict):
            file_date = _safe_to_datetime(sd.get("Date"))

    if file_date is not pd.NaT:
        if pd.isna(row["FILE_DATE"]):
            repairs["FILE_DATE"] = file_date
            repairs["FILE_DATE_FLAG"] = "FILLED"
        else:
            current_fd = _safe_to_datetime(row["FILE_DATE"])
            if (
                current_fd is pd.NaT
                or current_fd.normalize() != file_date.normalize()
            ):
                repairs["FILE_DATE"] = file_date
                repairs["FILE_DATE_FLAG"] = "FIXED"

    # -- PERMIT_DATE --
    issued = _issued_date(tasks)

    if not pd.isna(row["PERMIT_DATE"]):
        current_pd = _safe_to_datetime(row["PERMIT_DATE"])
        # Only overwrite when we have a true Permit Issuance / Issued (or
        # Issued w/Revision / planning Issuance) date that disagrees.
        # Prefer canonical issuance over C of O / other milestones.
        canonical = _first_event_date(tasks, "Permit Issuance", "Issued")
        if canonical is pd.NaT:
            canonical = _first_event_date(
                tasks, "Permit Issuance", "Issued w/Revision"
            )
        if canonical is pd.NaT:
            canonical = _first_event_date(tasks, "Issuance", "Issued")
        if (
            canonical is not pd.NaT
            and current_pd is not pd.NaT
            and current_pd.normalize() != canonical.normalize()
        ):
            repairs["PERMIT_DATE"] = canonical
            repairs["PERMIT_DATE_FLAG"] = "FIXED"
    elif effective_status in ("Active", "Final") and issued is not pd.NaT:
        repairs["PERMIT_DATE"] = issued
        repairs["PERMIT_DATE_FLAG"] = "FILLED"

    # -- FINAL_DATE --
    if effective_status == "Final":
        final_date = _final_date_from_data(tasks)
        if final_date is not pd.NaT:
            if pd.isna(row["FINAL_DATE"]):
                repairs["FINAL_DATE"] = final_date
                repairs["FINAL_DATE_FLAG"] = "FILLED"
            else:
                current_final = _safe_to_datetime(row["FINAL_DATE"])
                if (
                    current_final is pd.NaT
                    or current_final.normalize() != final_date.normalize()
                ):
                    repairs["FINAL_DATE"] = final_date
                    repairs["FINAL_DATE_FLAG"] = "FIXED"
    elif not pd.isna(row["FINAL_DATE"]):
        repairs["FINAL_DATE"] = pd.NaT
        repairs["FINAL_DATE_FLAG"] = "FIXED"


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Kern County permit records using the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Kern County".  Must contain
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

        if schema != "unknown" and schema != "missing":
            _repair_tasks(row, d, repairs)

        for key, value in repairs.items():
            out.at[idx, key] = value

    for col in ("FILE_DATE", "PERMIT_DATE", "FINAL_DATE"):
        if col in out.columns:
            out[col] = pd.to_datetime(out[col], errors="coerce")

    return out


# ── CLI: run standalone to preview repair stats ─────────────────────────────

if __name__ == "__main__":
    import os
    from dotenv import load_dotenv

    load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".env"))
    if not os.getenv("MY_DATA_PATH"):
        load_dotenv(".env")

    MY_DATA_PATH = os.getenv("MY_DATA_PATH")
    filepath = os.path.join(MY_DATA_PATH, "processed_data", "permits_ca_sample.parquet")
    df = pd.read_parquet(filepath)
    kern = df[df["JURISDICTION"] == "Kern County"].copy()

    print(f"Kern County records: {len(kern):,}\n")

    repaired = data_repair(kern)

    print("INFERRED_SCHEMA:")
    for s, c in repaired["INFERRED_SCHEMA"].value_counts(dropna=False).items():
        print(f"  {str(s):20s}: {c:>4,}")
    print()

    for field in ["STATUS_NORMALIZED", "FILE_DATE", "PERMIT_DATE", "FINAL_DATE"]:
        flag_col = f"{field}_FLAG"
        n_filled = (repaired[flag_col] == "FILLED").sum()
        n_fixed = (repaired[flag_col] == "FIXED").sum()
        print(f"{field}:")
        print(f"  FILLED: {n_filled:>4,}   FIXED: {n_fixed:>4,}")

        before_missing = kern[field].isna().sum()
        after_missing = repaired[field].isna().sum()
        print(f"  Missing before: {before_missing:>4,}   Missing after: {after_missing:>4,}")
        print()

    print("STATUS_NORMALIZED distribution:")
    print("  Before:")
    for s, c in kern["STATUS_NORMALIZED"].value_counts(dropna=False).items():
        print(f"    {str(s):15s}: {c:>4,}")
    print("  After:")
    for s, c in repaired["STATUS_NORMALIZED"].value_counts(dropna=False).items():
        print(f"    {str(s):15s}: {c:>4,}")

    print("\nFINAL_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        if len(sub) == 0:
            continue
        n_has = sub["FINAL_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({n_has / len(sub):.1%})")

    print("\nPERMIT_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        if len(sub) == 0:
            continue
        n_has = sub["PERMIT_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({n_has / len(sub):.1%})")

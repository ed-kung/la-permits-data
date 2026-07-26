"""Data repair for Moreno Valley (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Moreno Valley DATA is an Accela Citizen Access scrape. All sample rows
share the same header keys (status, date, tasks, …); INFERRED_SCHEMA
distinguishes workflow richness:

  - tasks_inspections: non-empty tasks + non-empty inspections
  - tasks_only:        non-empty tasks, no inspections
  - inspections_only:  inspections present, no usable tasks
  - header_only:       status/date/search_data only (empty workflows)

Canonical mappings:
  - DATA.status                              → STATUS_NORMALIZED
  - DATA.date / search_data['Date']          → FILE_DATE
  - Ready to Issue|Permit Issuance|Issuance
      / Issued* (earliest); Ready to Issue
      Plans / Issued Plans                   → PERMIT_DATE
  - Inspections / Final*|Closed;
      Inspection / Closed|Final Inspection;
      Final Inspection / Final|C of O Issued;
      fire-annual Passed / Results OK;
      historical FINAL insp Status=A         → FINAL_DATE

Known issues repaired:
  - 102 STATUS_NORMALIZED gaps (Record Created, Passed Inspection,
    abatement completed, M_APRVD, etc.) → FILLED.
  - Mis-mapped statuses: RESOLVED weed cases as In Review (→ Final);
    Inspection Complete / lagged Issued labels that are already Final
    in DATA.status → FIXED.
  - Missing FINAL_DATE on Final rows with Closed / Final / Passed
    Inspection workflow or historical Status=A finals → FILLED.
  - Spurious FINAL_DATE on non-Final rows → cleared (FIXED).
  - Sparse PERMIT_DATE fills from Issued / Issued Plans events.

Not repairable / left as-is:
  - FILE_DATE already matches DATA.date for all sample rows.
  - Many Active/Final rows (code cases, historical shells, Approved
    entitlements) have no dated issuance event → PERMIT_DATE stays
    missing.
  - Historical FINAL/COMPLETE shells with no dated final inspection,
    and CLOSED planning shells with only Notes events → FINAL_DATE
    stays missing.
"""

import json
import math
import re
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
        return json.loads(data)
    return data


def _safe_to_datetime(val):
    """Parse a date value, returning pd.NaT on failure or implausible year."""
    if val is None or (isinstance(val, str) and not str(val).strip()):
        return pd.NaT
    if str(val).strip().upper() == "TBD":
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


def _dates_equal(a, b) -> bool:
    """Compare two datelike values at calendar-day resolution."""
    da = _safe_to_datetime(a)
    db = _safe_to_datetime(b)
    if da is pd.NaT or db is pd.NaT or pd.isna(da) or pd.isna(db):
        return False
    return da.normalize() == db.normalize()


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())
    if "status" not in keys and "date" not in keys and "search_data" not in keys:
        return "unknown"

    tasks = data_dict.get("tasks") or []
    inspections = data_dict.get("inspections") or []
    has_tasks = isinstance(tasks, list) and len(tasks) > 0
    has_insp = isinstance(inspections, list) and len(inspections) > 0

    if has_tasks and has_insp:
        return "tasks_inspections"
    if has_tasks:
        return "tasks_only"
    if has_insp:
        return "inspections_only"
    return "header_only"


def _event_field(event: dict, *names: str):
    """Read an event field, tolerating leading/trailing spaces in keys."""
    targets = {n.strip().lower() for n in names}
    for k, v in event.items():
        if isinstance(k, str) and k.strip().lower() in targets:
            return v
    return None


def _event_dates(tasks: list, task_names, marked_pred) -> list:
    """Return datetimes for task events matching marked_pred(marked)."""
    if isinstance(task_names, str):
        task_names = {task_names}
    dates = []
    for t in tasks or []:
        if not isinstance(t, dict) or t.get("name") not in task_names:
            continue
        for e in t.get("events") or []:
            if not isinstance(e, dict):
                continue
            marked = _event_field(e, "Marked as")
            marked = (marked or "").strip() if isinstance(marked, str) else marked
            if not marked_pred(marked):
                continue
            on_val = _event_field(e, "on")
            dt = _safe_to_datetime(on_val)
            if dt is not pd.NaT:
                dates.append(dt)
    return dates


# ── Status mapping ──────────────────────────────────────────────────────────

# DATA.status → STATUS_NORMALIZED. Lookup is case-insensitive via _map_status.
_STATUS_MAP = {
    # Final
    "Final": "Final",
    "FINAL": "Final",
    "Finaled": "Final",
    "Complete": "Final",
    "COMPLETE": "Final",
    "Completed": "Final",
    "Closed": "Final",
    "CLOSED": "Final",
    "C of O": "Final",
    "COFO": "Final",
    "Inspection Completed": "Final",
    "Inspection Complete": "Final",
    "Passed Inspection": "Final",
    "Recorded": "Final",
    "RESOLVED": "Final",
    "Owner Abatement Completed": "Final",
    "City Abatement Completed": "Final",
    "Unfounded": "Final",
    "Final Invoice": "Final",
    "Paid by Taxroll": "Final",
    # Active
    "Active": "Active",
    "ACTIVE": "Active",
    "Issued": "Active",
    "ISSUED": "Active",
    "Permit Issued": "Active",
    "Approved": "Active",
    "APPROVED": "Active",
    "M_APRVD": "Active",
    "Approved-Payment Received": "Active",
    "Inspection Deferred": "Active",
    "Inspection Scheduled": "Active",
    "Inspections in Process": "Active",
    "Invoice Billed": "Active",
    "INVOICE": "Active",
    "Initial Invoice": "Active",
    # Inactive
    "Expired": "Inactive",
    "EXPIRED": "Inactive",
    "EXPPC": "Inactive",
    "Void": "Inactive",
    "Withdrawn": "Inactive",
    "WITHDRWN": "Inactive",
    "WITHDRAW": "Inactive",
    "Inactive": "Inactive",
    "REVOKED": "Inactive",
    # In Review
    "In Review": "In Review",
    "Record Created": "In Review",
    "Additional Info Required": "In Review",
    "Out for Corrections": "In Review",
    "Corrections Pending": "In Review",
    "Submittal Received": "In Review",
    "Submittal Required": "In Review",
    "Application Submitted": "In Review",
    "Application Processed": "In Review",
    "Applied": "In Review",
    "APPLIED": "In Review",
    "Awaiting Submittal": "In Review",
    "Received": "In Review",
    "Signed Permit Required": "In Review",
    "On Hold": "In Review",
    "PENDING": "In Review",
    "Vacant": "In Review",
    "LIEN": "In Review",
    "Public Hearing": "In Review",
    "Payment Required": "In Review",
    "PAID": "In Review",
    "PLANCHCK": "In Review",
    "Reviewed Under Building Record": "In Review",
    "NOVLTR": "In Review",
    "PAL Log": "In Review",
    "Collections": "In Review",
    "TAXROLL": "In Review",
}

_STATUS_MAP_LOWER = {k.casefold(): v for k, v in _STATUS_MAP.items()}


def _map_status(raw) -> Optional[str]:
    if raw is None or (isinstance(raw, float) and math.isnan(raw)):
        return None
    key = str(raw).strip()
    if not key:
        return None
    return _STATUS_MAP.get(key) or _STATUS_MAP_LOWER.get(key.casefold())


_FINAL_TASK_MARKS = {
    "Final",
    "Final With CO",
    "Final No CO",
    "Work Completed",
    "Closed",
    "C of O Issued",
    "Passed Inspection",
    "Final Inspection",
    "Closed Priority One",
    "Complete",
    "Completed",
}


def _has_final_event(tasks: list) -> bool:
    """True if workflow shows a clear completion / close event."""
    for t in tasks or []:
        if not isinstance(t, dict):
            continue
        name = (t.get("name") or "").strip()
        for e in t.get("events") or []:
            if not isinstance(e, dict):
                continue
            marked = _event_field(e, "Marked as")
            marked = (marked or "").strip() if isinstance(marked, str) else ""
            if not marked or marked == "TBD":
                continue
            if name == "Inspections" and marked in {
                "Final", "Final With CO", "Final No CO", "Work Completed",
                "Closed", "Passed Inspection",
            }:
                return True
            if name == "Final Inspection" and marked in {
                "Final", "C of O Issued", "Passed Inspection",
            }:
                return True
            if name == "Inspection" and marked in {
                "Final Inspection", "Closed", "Closed Priority One",
                "Passed Inspection",
            }:
                return True
            if name in {"Supervisor Review", "Supervisory Review"} and marked == (
                "Inspection Results/Permits OK"
            ):
                return True
    return False


# ── Date extractors ─────────────────────────────────────────────────────────

def _file_date_from_data(d: dict):
    dt = _safe_to_datetime(d.get("date"))
    if dt is not pd.NaT:
        return dt
    sd = d.get("search_data")
    if isinstance(sd, dict):
        return _safe_to_datetime(sd.get("Date"))
    return pd.NaT


def _permit_date_from_tasks(tasks: list):
    """Earliest canonical issuance date from workflow tasks."""
    issued = _event_dates(
        tasks,
        {
            "Ready to Issue",
            "Permit Issuance",
            "Issuance",
            "Permit Issued",
        },
        lambda m: (m or "") in ("Issued", "Permit Issued", "Daily Permit Issued"),
    )
    if issued:
        return min(issued)

    issued = _event_dates(
        tasks,
        "City Traffic Engineer Approval",
        lambda m: (m or "") == "Permit Issued",
    )
    if issued:
        return min(issued)

    # Plan-check revisions: Issued Plans is the issuance stamp.
    issued = _event_dates(
        tasks,
        "Ready to Issue Plans",
        lambda m: (m or "") in ("Issued Plans", "Issued"),
    )
    if issued:
        return min(issued)

    # OTC / instant permits sometimes mark Application Submittal Issued.
    issued = _event_dates(
        tasks,
        "Application Submittal",
        lambda m: (m or "") in ("Issued", "Daily Permit Issued"),
    )
    return min(issued) if issued else pd.NaT


def _final_date_from_tasks(tasks: list):
    """Latest completion / close date from workflow tasks."""
    # Building Inspections Final* / Closed
    finals = _event_dates(
        tasks,
        "Inspections",
        lambda m: (m or "") in {
            "Final", "Final With CO", "Final No CO", "Work Completed", "Closed",
        },
    )
    if finals:
        return max(finals)

    finals = _event_dates(
        tasks,
        "Final Inspection",
        lambda m: (m or "") in {"Final", "C of O Issued", "Passed Inspection"},
    )
    if finals:
        return max(finals)

    # Code-enforcement / fire-permit Inspection task
    finals = _event_dates(
        tasks,
        "Inspection",
        lambda m: (m or "") in {
            "Final Inspection", "Closed", "Closed Priority One", "Passed Inspection",
        },
    )
    if finals:
        return max(finals)

    # Fire annual / NPDES: Passed Inspection on Inspections, or Results OK
    finals = _event_dates(
        tasks,
        "Inspections",
        lambda m: (m or "") == "Passed Inspection",
    )
    if finals:
        return max(finals)

    finals = _event_dates(
        tasks,
        {"Supervisor Review", "Supervisory Review"},
        lambda m: (m or "") == "Inspection Results/Permits OK",
    )
    if finals:
        return max(finals)

    # Code-enforcement Inspection Completed chain
    finals = _event_dates(
        tasks,
        {"Final Inspection", "Reinspection", "Initial Inspection"},
        lambda m: (m or "") == "Passed Inspection",
    )
    if finals:
        return max(finals)

    # Plan-check revisions marked Completed via Review Decisions
    finals = _event_dates(
        tasks,
        "Review Decisions",
        lambda m: (m or "") in {"Review Completed", "Review Complete"},
    )
    if finals:
        return max(finals)

    # Land-dev recorded
    finals = _event_dates(
        tasks,
        "Recorded by Title Company",
        lambda m: (m or "") == "Original Recorded",
    )
    if finals:
        return max(finals)

    finals = _event_dates(
        tasks,
        "Planner Review",
        lambda m: (m or "") == "Closed",
    )
    return max(finals) if finals else pd.NaT


_HIST_PASS_STATUSES = {"A", "PA", "CLOS", "PASSED INSPECTION", "PASSED", "FINAL"}


def _final_date_from_inspections(inspections: list):
    """Latest Status Date from final-titled passed / approved inspections."""
    dates = []
    for insp in inspections or []:
        if not isinstance(insp, dict):
            continue
        title = str(insp.get("Title") or "")
        if not re.search(
            r"final|certificate of occupancy|\bc of o\b|cofo|"
            r"sprinkler system final",
            title,
            re.I,
        ):
            continue
        if re.search(r"pre\s*[- ]?\s*final", title, re.I):
            continue
        status = str(insp.get("Status") or "").strip()
        status_u = status.upper()
        modern_ok = status in {
            "Passed Inspection", "Final", "Closed", "Complete", "Completed",
        }
        hist_ok = status_u in _HIST_PASS_STATUSES
        if not (modern_ok or hist_ok):
            continue
        dt = _safe_to_datetime(insp.get("Status Date"))
        if dt is not pd.NaT:
            dates.append(dt)
    return max(dates) if dates else pd.NaT


def _final_date_from_data(d: dict):
    """Prefer workflow finals; fall back to inspection Status Dates."""
    from_tasks = _final_date_from_tasks(d.get("tasks") or [])
    if from_tasks is not pd.NaT:
        return from_tasks
    return _final_date_from_inspections(d.get("inspections") or [])


# ── Per-record repair logic ─────────────────────────────────────────────────

def _repair_record(row, d: dict, repairs: dict):
    """Populate *repairs* with corrected values for one Moreno Valley record."""
    tasks = d.get("tasks") or []
    data_status = d.get("status")
    if isinstance(data_status, str):
        data_status = data_status.strip() or None
    else:
        data_status = None

    # -- STATUS_NORMALIZED --
    current_status = row["STATUS_NORMALIZED"]
    expected = _map_status(data_status)

    # Lagged Active label: workflow already finaled / closed → Final.
    if expected == "Active" and _has_final_event(tasks):
        expected = "Final"

    if expected is not None:
        if pd.isna(current_status):
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"
        elif current_status != expected:
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FIXED"

    effective_status = repairs.get("STATUS_NORMALIZED", current_status)
    if isinstance(effective_status, float) and math.isnan(effective_status):
        effective_status = None

    # -- FILE_DATE --
    file_src = _file_date_from_data(d)
    if file_src is not pd.NaT:
        if pd.isna(row["FILE_DATE"]):
            repairs["FILE_DATE"] = file_src
            repairs["FILE_DATE_FLAG"] = "FILLED"
        elif not _dates_equal(row["FILE_DATE"], file_src):
            repairs["FILE_DATE"] = file_src
            repairs["FILE_DATE_FLAG"] = "FIXED"

    # -- PERMIT_DATE --
    issued = _permit_date_from_tasks(tasks)
    current_permit = row["PERMIT_DATE"]

    if effective_status in ("Active", "Final"):
        if issued is not pd.NaT:
            if pd.isna(current_permit):
                repairs["PERMIT_DATE"] = issued
                repairs["PERMIT_DATE_FLAG"] = "FILLED"
            elif not _dates_equal(current_permit, issued):
                repairs["PERMIT_DATE"] = issued
                repairs["PERMIT_DATE_FLAG"] = "FIXED"

    # -- FINAL_DATE --
    final = _final_date_from_data(d)
    current_final = row["FINAL_DATE"]

    if effective_status == "Final":
        if final is not pd.NaT:
            if pd.isna(current_final):
                repairs["FINAL_DATE"] = final
                repairs["FINAL_DATE_FLAG"] = "FILLED"
            elif not _dates_equal(current_final, final):
                repairs["FINAL_DATE"] = final
                repairs["FINAL_DATE_FLAG"] = "FIXED"
    elif not pd.isna(current_final):
        repairs["FINAL_DATE"] = pd.NaT
        repairs["FINAL_DATE_FLAG"] = "FIXED"


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Moreno Valley permit records using the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Moreno Valley".
        Must contain columns STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE,
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
        if schema != "unknown":
            _repair_record(row, d, repairs)

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
    filepath = os.path.join(MY_DATA_PATH, "processed_data", "permits_ca_sample.parquet")
    df = pd.read_parquet(filepath)
    city = df[(df["JURISDICTION"] == "Moreno Valley") & (df["STATE"] == "CA")].copy()

    print(f"Moreno Valley records: {len(city):,}\n")

    repaired = data_repair(city)

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

    print("\nFILE_DATE coverage (after repair):")
    n_has = repaired["FILE_DATE"].notna().sum()
    print(f"  {n_has:>4,} / {len(repaired):>4,} ({n_has / len(repaired):.1%})")

    print("\nRemaining gaps:")
    for status in ["Active", "Final"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        print(
            f"  {status}: PERMIT miss={sub['PERMIT_DATE'].isna().sum()}, "
            f"FINAL miss={sub['FINAL_DATE'].isna().sum()} / {len(sub)}"
        )

    # Unmapped statuses remaining
    still_nan = repaired[repaired["STATUS_NORMALIZED"].isna()]
    if len(still_nan):
        print(f"\nStill missing STATUS ({len(still_nan)}):")
        from collections import Counter
        c = Counter()
        for _, row in still_nan.iterrows():
            d = _safe_parse(row["DATA"])
            c[None if d is None else d.get("status")] += 1
        for s, n in c.most_common():
            print(f"  {n:4d}  {s!r}")

    if AGENT_DATA_PATH:
        out_path = os.path.join(AGENT_DATA_PATH, "moreno_valley_repaired_sample.parquet")
        for col in ("FILE_DATE", "PERMIT_DATE", "FINAL_DATE"):
            repaired[col] = pd.to_datetime(repaired[col], errors="coerce")
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote {out_path}")

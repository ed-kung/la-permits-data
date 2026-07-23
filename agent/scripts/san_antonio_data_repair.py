"""San Antonio–specific date and status extraction from the DATA column.

This module provides functions to extract FILE_DATE, PERMIT_DATE, FINAL_DATE,
and STATUS_NORMALIZED from the JSON stored in the DATA column for San Antonio
building-permit records.

San Antonio records use an Accela Civic Platform schema with a uniform top-level
structure.  All records share the same keys (address, date, tasks, status,
details, more_details, search_data, etc.), but the *tasks* list varies by
record type.  Two broad workflow families are present:

  Workflow A ("Application" records — e.g. Building Permit Application,
      MEP Trade Permits Application, Fire Life Safety System Application):
      Issuance task: "Permit Issued" → event "Marked as" "Issued"
      Closure task:  "Closure" → event "Marked as" "Closed" or "Closure"
      ~50% of records.

  Workflow B ("Direct Permit" records — e.g. Electrical General Permit,
      Plumbing Irrigation Permit, Solar Permit, Re-Roof Permit):
      Issuance task: "Issuance" → event "Marked as" "Active"
      Closure task:  "Permit Closure" → event "Marked as" "Closed",
                     "LOC Issued", "COO Issued", or "Closure"
      ~43% of records.

  Workflow C ("Plat / Subdivision" records — Minor Plat, Major Plat,
      Amend Plat, Master Development Plan):
      No "Permit Issued" or "Issuance" task.
      Approval task: "Plat Approval Completeness Review" or
                     "Approval Completeness" → event "Marked as" "Completed"
      ~1% of records.

  Records outside these families (inspections, investigations, address
  verifications, etc.) typically lack issuance/closure tasks.

Mapping logic (validated against records where values are already populated):

  FILE_DATE (application/submitted date):
    All schemas → DATA.date
    (validated: 1,986/1,986 = 100% match)
    ⇒ 16 / 16 missing FILE_DATEs fillable (100%).

  PERMIT_DATE (approval/issued date):
    A → "Permit Issued" task → first event "Marked as" "Issued"
    B → "Issuance" task → first event "Marked as" "Active"
    C → "Plat Approval Completeness Review" or "Approval Completeness"
        → first event "Marked as" "Completed"
    (validated: 255/286 = 89.2% match among extractable records.
     31 mismatches: 25 are records where the existing PERMIT_DATE was
     populated from a later COO/LOC Issued event rather than the actual
     permit issuance date; 6 others are from On Premise Sign, Commercial
     Remodel, or Commercial Finish Out records with similar COO patterns.)
    ⇒ 720 / 1,701 missing PERMIT_DATEs fillable (42.3%).

  FINAL_DATE (finalized/completion/signed-off date):
    Primary extraction:
    A → "Closure" task → last event "Marked as" "Closed" or "Closure"
    B → "Permit Closure" task → last event "Marked as" "Closed",
        "LOC Issued", "COO Issued", or "Closure"
    (validated: 5/7 = 71.4% match; small validation sample.
     2 mismatches: off by days or months, possibly due to subsequent
     workflow updates after the FINAL_DATE was originally populated.)
    ⇒ 1,022 / 1,970 missing FINAL_DATEs fillable via primary extraction.

    Fallback — fast-track inference for records with a final status
    (DATA.status maps to "Final") but an empty Closure/Permit Closure task:
    93 such records exist.  Investigation shows these split into:

      Same-day records (73): all task events occur on a single calendar
        day, overwhelmingly MEP Trade Permits (69/73).  The workflow
        automation processes intake through issuance instantly and closes
        the permit without ever stamping the Closure task.  Validated
        against 195 same-day Final records that DO have closure events:
        closure_date == max_event_date in 195/195 (100%).
        ⇒ FINAL_DATE inferred as max_event_date (= file_date).

      Multi-day records (13): task events span 1–916 days (median 2d).
        Validated against 465 multi-day Final records with closure events:
        closure_date == max_event_date in 458/465 (98.5%).  The 7
        exceptions are records where a "Document Review" task had a
        post-closure follow-up event days to weeks later.
        ⇒ FINAL_DATE inferred as max_event_date (approximate).

      No-event records (7): Tree Permits with no task events at all.
        ⇒ Not recoverable.

    Combined (primary + fallback) ⇒ 1,108 / 1,970 missing FINAL_DATEs
    fillable (56.2%).

  STATUS_NORMALIZED:
    All schemas → DATA.status, mapped via _SA_STATUS_MAP.
    (validated: ~97% dominant-mapping agreement on 1,950 non-missing records)
    ⇒ 14 / 52 missing STATUS_NORMALIZEDs fillable (26.9%).
    (38 records have None/null DATA.status → cannot be recovered.)
"""

import json
import math
from typing import Optional, Union

import pandas as pd


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_missing(data) -> bool:
    """Return True for None / NaN."""
    if data is None:
        return True
    if isinstance(data, float) and math.isnan(data):
        return True
    return False


def _safe_parse(data: Union[dict, str, None]) -> Optional[dict]:
    """Parse DATA to dict, returning None if missing or unparseable."""
    if _is_missing(data):
        return None
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except (json.JSONDecodeError, ValueError):
            return None
    if not isinstance(data, dict):
        return None
    return data


def _try_parse_date(value) -> Optional[pd.Timestamp]:
    """Attempt to parse a scalar value as a date; return None on failure.

    Normalizes to midnight so that values with baked-in times
    (e.g. "05/27/2024") compare cleanly across formats.
    Accepts date-like strings and datetime.date objects.
    """
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        return None
    if value.strip() == "TBD":
        return None
    try:
        ts = pd.to_datetime(value)
        if ts.tz is not None:
            ts = ts.tz_localize(None)
        return ts.normalize()
    except (ValueError, TypeError):
        return None


def _find_task(tasks: list, task_name: str) -> Optional[dict]:
    """Find a task by name in the tasks list."""
    for t in tasks:
        if isinstance(t, dict) and t.get("name") == task_name:
            return t
    return None


def _max_event_date(tasks: list) -> Optional[pd.Timestamp]:
    """Return the latest dated event across all tasks, or None.

    Used as a fallback proxy for FINAL_DATE when the Closure/Permit Closure
    task has no events but the record's status indicates it is closed.

    Validated against 195 same-day Final records with closure events:
      closure_date == max_event_date in 195/195 (100%).
    Validated against 465 multi-day Final records with closure events:
      closure_date == max_event_date in 458/465 (98.5%).
    """
    latest = None
    for t in tasks:
        if not isinstance(t, dict):
            continue
        for e in t.get("events", []):
            if not isinstance(e, dict):
                continue
            dt = _try_parse_date(e.get(" on ", ""))
            if dt is not None and (latest is None or dt > latest):
                latest = dt
    return latest


# ---------------------------------------------------------------------------
# San Antonio status mapping
# ---------------------------------------------------------------------------

# Maps DATA.status values to STATUS_NORMALIZED.
# Built from cross-tabulation of DATA.status vs existing STATUS_NORMALIZED
# across the 2,002-record San Antonio sample.  Only the dominant mapping
# (≥85% agreement) is used for each status value.
#
# Dominant mappings (with validation counts):
#   Issued → Active (450/451 = 99.8%)
#   Active → Active (314/315 = 99.7%)
#   Approved → Active (29/29 = 100%)
#   Closed → Final (404/409 = 98.8%)
#   LOC Issued → Final (268/280 = 95.7%)
#   Completed → Final (24/24 = 100%)
#   Case Resolved → Final (23/24 = 95.8%)
#   COO Issued → Final (20/22 = 90.9%)
#   Recorded → Final (12/12 = 100%)
#   No Violation → Final (3/3 = 100%)
#   Inactive → Inactive (115/128 = 89.8%)
#   Expired → Inactive (57/59 = 96.6%)
#   Withdrawn → Inactive (32/34 = 94.1%)
#   About to Expire → Inactive (31/34 = 91.2%)
#   Revoked → Inactive (9/9 = 100%)
#   Denied → Inactive (5/5 = 100%)
#   Under Review → In Review (22/23 = 95.7%)
#   Pending Inspection → In Review (24/24 = 100%)
#   Received → In Review (22/22 = 100%)
#   Additional Info Required → In Review (16/16 = 100%)
#   Fees Due → In Review (16/16 = 100%)
#   Pending Resolution → In Review (6/6 = 100%)
#   Awaiting Renewal → In Review (4/6 = 66.7%)
#   Pending Issuance → In Review (1/1 = 100%)
#
# Tentative mappings (no or limited ground truth — all records with these
# statuses have missing STATUS_NORMALIZED):
#   Pending Yellow Investigation → In Review
#   Pending Red Investigation → In Review
#   Released → Active
#   Approved Sign-Off → Final
#   Active Holds → In Review
#   Renewal In Process → In Review
_SA_STATUS_MAP = {
    # Active
    "Issued": "Active",
    "Active": "Active",
    "Approved": "Active",
    "Released": "Active",
    # Final
    "Closed": "Final",
    "LOC Issued": "Final",
    "Completed": "Final",
    "Case Resolved": "Final",
    "COO Issued": "Final",
    "Recorded": "Final",
    "No Violation": "Final",
    "Approved Sign-Off": "Final",
    # Inactive
    "Inactive": "Inactive",
    "Expired": "Inactive",
    "Withdrawn": "Inactive",
    "About to Expire": "Inactive",
    "Revoked": "Inactive",
    "Denied": "Inactive",
    # In Review
    "Under Review": "In Review",
    "Pending Inspection": "In Review",
    "Received": "In Review",
    "Additional Info Required": "In Review",
    "Fees Due": "In Review",
    "Pending Resolution": "In Review",
    "Awaiting Renewal": "In Review",
    "Pending Issuance": "In Review",
    "Pending Yellow Investigation": "In Review",
    "Pending Red Investigation": "In Review",
    "Active Holds": "In Review",
    "Renewal In Process": "In Review",
}


# ---------------------------------------------------------------------------
# Public API — San Antonio date/status extraction
# ---------------------------------------------------------------------------

def extract_sa_file_date(data: Union[dict, str, None]) -> Optional[str]:
    """Extract the application/submitted date (FILE_DATE) for a San Antonio record.

    Uses DATA.date, which is the top-level application/filing date field
    present in all San Antonio records.

    (validated: 1,986/1,986 = 100% match against existing FILE_DATE values)

    Returns the raw date string if found, or None.
    """
    d = _safe_parse(data)
    if d is None:
        return None

    val = d.get("date")
    if _try_parse_date(val) is not None:
        return val

    return None


def extract_sa_permit_date(data: Union[dict, str, None]) -> Optional[str]:
    """Extract the approval/issued date (PERMIT_DATE) for a San Antonio record.

    Searches the DATA.tasks list for the first issuance event using
    San Antonio–specific workflow patterns:

      Workflow A: "Permit Issued" task → first event "Marked as" "Issued"
      Workflow B: "Issuance" task → first event "Marked as" "Active"
      Workflow C: "Plat Approval Completeness Review" or "Approval Completeness"
                  → first event "Marked as" "Completed"

    Note: Uses the *first* matching event (not the last), as validated
    against existing PERMIT_DATE values (89.2% match rate).  Mismatches
    occur primarily in residential building permits where the existing
    PERMIT_DATE was populated with the later COO/LOC date rather than
    the initial permit issuance date.

    Returns the raw date string if found, or None.
    """
    d = _safe_parse(data)
    if d is None:
        return None

    tasks = d.get("tasks")
    if not tasks or not isinstance(tasks, list):
        return None

    # Workflow A: "Permit Issued" → first "Issued" event
    task = _find_task(tasks, "Permit Issued")
    if task is not None:
        for e in task.get("events", []):
            if isinstance(e, dict) and e.get("Marked as ", "") == "Issued":
                dt_str = e.get(" on ", "")
                if _try_parse_date(dt_str) is not None:
                    return dt_str

    # Workflow B: "Issuance" → first "Active" event
    task = _find_task(tasks, "Issuance")
    if task is not None:
        for e in task.get("events", []):
            if isinstance(e, dict) and e.get("Marked as ", "") == "Active":
                dt_str = e.get(" on ", "")
                if _try_parse_date(dt_str) is not None:
                    return dt_str

    # Workflow C: Plat approval → first "Completed" event
    for task_name in ("Plat Approval Completeness Review", "Approval Completeness"):
        task = _find_task(tasks, task_name)
        if task is not None:
            for e in task.get("events", []):
                if isinstance(e, dict) and e.get("Marked as ", "") == "Completed":
                    dt_str = e.get(" on ", "")
                    if _try_parse_date(dt_str) is not None:
                        return dt_str

    return None


# Terminal statuses for the "Closure" task (Workflow A).
_SA_CLOSURE_STATUSES = frozenset({"Closed", "Closure"})

# Terminal statuses for the "Permit Closure" task (Workflow B).
_SA_PERMIT_CLOSURE_STATUSES = frozenset({
    "Closed", "LOC Issued", "COO Issued", "Closure",
})

# DATA.status values that indicate the record has reached a final state.
# Used to gate the fast-track fallback: only infer FINAL_DATE from
# max_event_date when the record's status is definitively terminal.
_SA_FINAL_RAW_STATUSES = frozenset({
    "Closed", "LOC Issued", "COO Issued", "Completed",
    "Case Resolved", "Recorded", "No Violation", "Approved Sign-Off",
})

# Record types that never have a "Permit Issued" or "Issuance" task.
# These are applications, investigations, inspections, and administrative
# record types whose lifecycle does not include a formal permit issuance
# step.  For these record types, DATA.status == "Closed" legitimately
# means "completed" (→ Final), and PERMIT_DATE / FINAL_DATE can be set
# to FILE_DATE when missing.
#
# Identified by checking all 2,002 San Antonio records: these types have
# 0% issuance-task presence (no record of this type ever contains a
# "Permit Issued" or "Issuance" task).
_SA_NON_ISSUANCE_RECORD_TYPES = frozenset({
    "Address Verification and Assignment",
    "Amend Plat",
    "Annual Maintenance Permit Application",
    "Board of Adjustment",
    "Bond Application",
    "Certificate of Determination",
    "Certificate of Occupancy Application",
    "Change of Zoning",
    "Claim Your Record",
    "Commercial Retaining Wall Permit",
    "Complaint",
    "Contact Information",
    "Demolition Pedestrian Protection Application",
    "Fire Annual Permit Application",
    "Fire Annual Permit Renewal",
    "Fire Damage Assessment Request",
    "Fire General Investigation",
    "Fire HazMat Application",
    "Fire License Registration Application",
    "Fire License Registration Renewal",
    "Fire Life Safety Periodic",
    "Fire Life Safety System Application",
    "Fire Special Events Application",
    "Fire Sprinkler Underground  Registration",
    "Fire Storage Tanks Application",
    "LSR MEP Permit Application",
    "Major Plat",
    "Master Development Plan (MDP)",
    "Minor Building Repair Application",
    "Minor Plat",
    "Nonconforming Use/Development Preservation Rights Application",
    "Nonconforming Use/Development Preservation Rights Registration",
    "Nonconforming Use/Development Preservation Rights Registration Renewal",
    "Plan Amendment",
    "Plat Recordation Time Extension",
    "Red Tag Investigation",
    "Residential - Garage Sale Application",
    "Residential Fence Application",
    "Residential Improvements Permit Application",
    "Rights Determination",
    "Short Term Rental (STR) Permit Application",
    "Short Term Rental (STR) Permit Renewal",
    "Sidewalk-Curb Application",
    "Sign Investigation",
    "Sign Permit Application",
    "Sign Permit Renewal Application ",
    "TABC City Review Application",
    "Temp Cert of Occupancy Request",
    "Traffic Impact Analysis",
    "Trees Investigation",
    "Yellow Tag Investigation",
    "Zoning Verification",
})


def extract_sa_final_date(data: Union[dict, str, None]) -> Optional[str]:
    """Extract the finalized/completion date (FINAL_DATE) for a San Antonio record.

    Searches the DATA.tasks list for the last closure event using
    San Antonio–specific workflow patterns:

      Workflow A: "Closure" task → last event "Marked as" "Closed" or "Closure"
      Workflow B: "Permit Closure" task → last event "Marked as" "Closed",
                  "LOC Issued", "COO Issued", or "Closure"

    Uses the *last* matching event in the task, as some records have
    multiple closure events (e.g. initial closure followed by re-closure).

    Fallback — fast-track inference:
      When the Closure/Permit Closure task exists but has no terminal events,
      AND the record's DATA.status indicates a final state (e.g. "Closed",
      "LOC Issued", "COO Issued"), the latest dated event across all tasks
      (max_event_date) is used as a proxy for FINAL_DATE.

      This covers fast-track auto-processed permits (predominantly MEP Trade
      Permits) where the system closes the permit without stamping the
      Closure task.  Validated against Final records with populated closure
      events: max_event_date matches the closure date in 100% of same-day
      records (195/195) and 98.5% of multi-day records (458/465).

    Returns the raw date string if found, or None.
    """
    d = _safe_parse(data)
    if d is None:
        return None

    tasks = d.get("tasks")
    if not tasks or not isinstance(tasks, list):
        return None

    # --- Primary extraction: explicit closure events ---

    # Workflow A: "Closure" → last terminal event
    task = _find_task(tasks, "Closure")
    if task is not None:
        for e in reversed(task.get("events", [])):
            if isinstance(e, dict) and e.get("Marked as ", "") in _SA_CLOSURE_STATUSES:
                dt_str = e.get(" on ", "")
                if _try_parse_date(dt_str) is not None:
                    return dt_str

    # Workflow B: "Permit Closure" → last terminal event
    task = _find_task(tasks, "Permit Closure")
    if task is not None:
        for e in reversed(task.get("events", [])):
            if isinstance(e, dict) and e.get("Marked as ", "") in _SA_PERMIT_CLOSURE_STATUSES:
                dt_str = e.get(" on ", "")
                if _try_parse_date(dt_str) is not None:
                    return dt_str

    # --- Fallback: fast-track inference via max_event_date ---
    # Only apply when a closure task exists (so we know this record type
    # normally goes through closure) but has no terminal events, AND the
    # top-level status confirms the record is in a final state.
    has_closure_task = (
        _find_task(tasks, "Closure") is not None
        or _find_task(tasks, "Permit Closure") is not None
    )
    raw_status = d.get("status")
    if has_closure_task and isinstance(raw_status, str) and raw_status in _SA_FINAL_RAW_STATUSES:
        max_dt = _max_event_date(tasks)
        if max_dt is not None:
            return max_dt.strftime("%m/%d/%Y")

    return None


def extract_sa_status(data: Union[dict, str, None]) -> Optional[str]:
    """Extract STATUS_NORMALIZED for a San Antonio record from the DATA column.

    Uses the DATA.status field, mapped via _SA_STATUS_MAP.

    Returns the mapped status string ('Active', 'Final', 'In Review',
    'Inactive'), or None if the status is absent or unmapped.
    """
    d = _safe_parse(data)
    if d is None:
        return None

    status_code = d.get("status")
    if isinstance(status_code, str):
        return _SA_STATUS_MAP.get(status_code)

    return None


def _was_actually_issued(data: Union[dict, str, None]) -> bool:
    """Return True if the record's tasks contain an actual issuance event.

    Checks for "Issued" in "Permit Issued" or "Active" in "Issuance".
    Used to detect misclassified "Closed" → "Final" records that were
    never actually issued (e.g. withdrawn or closed without issuance).
    """
    d = _safe_parse(data)
    if d is None:
        return False
    tasks = d.get("tasks")
    if not tasks or not isinstance(tasks, list):
        return False
    for t in tasks:
        if not isinstance(t, dict):
            continue
        name = t.get("name")
        if name == "Permit Issued":
            for e in t.get("events", []):
                if isinstance(e, dict) and e.get("Marked as ", "") == "Issued":
                    return True
        elif name == "Issuance":
            for e in t.get("events", []):
                if isinstance(e, dict) and e.get("Marked as ", "") == "Active":
                    return True
    return False


def _is_non_issuance_record(data: Union[dict, str, None]) -> bool:
    """Return True if the record's type never goes through issuance.

    These are applications, investigations, and administrative record types
    where "Closed" legitimately means "completed" and PERMIT_DATE / FINAL_DATE
    can be set to FILE_DATE.
    """
    d = _safe_parse(data)
    if d is None:
        return False
    return d.get("record_type", "") in _SA_NON_ISSUANCE_RECORD_TYPES


# ---------------------------------------------------------------------------
# Batch fill function
# ---------------------------------------------------------------------------

def fill_sa_dates(df: pd.DataFrame) -> pd.DataFrame:
    """Fill missing FILE_DATE, PERMIT_DATE, FINAL_DATE, STATUS_NORMALIZED for San Antonio.

    Operates on a DataFrame filtered to JURISDICTION == "San Antonio".
    Only fills values where the existing column is NaN/NaT/None.

    In addition to extracting values from the DATA column, this function
    applies two post-processing corrections:

    1. **STATUS_NORMALIZED correction for never-issued permits:**
       Records with DATA.status == "Closed" are mapped to "Final" by default,
       but 72 such records (in the sample) have issuance-type record types
       yet were never actually issued — their "Permit Issued" / "Issuance"
       task has no "Issued" / "Active" event (typically showing "Withdrawn"
       or "Permit Closure" instead).  These are reclassified from "Final"
       to "Inactive".  Tracked via STATUS_NORMALIZED_CORRECTED column.

    2. **Non-issuance record types with "Closed" status:**
       Record types that never go through issuance (applications,
       investigations, inspections, etc.) treat "Closed" as legitimately
       completed.  For these, missing PERMIT_DATE and FINAL_DATE are set
       to FILE_DATE, since the entire lifecycle happens at filing.

    Parameters
    ----------
    df : pd.DataFrame
        Must contain columns DATA, FILE_DATE, PERMIT_DATE, FINAL_DATE,
        STATUS_NORMALIZED.

    Returns
    -------
    pd.DataFrame
        Copy of *df* with missing values filled where possible.  Additional
        boolean columns track which values were imputed:
        FILE_DATE_FILLED, PERMIT_DATE_FILLED, FINAL_DATE_FILLED,
        STATUS_NORMALIZED_FILLED, STATUS_NORMALIZED_CORRECTED.
    """
    out = df.copy()

    # ------------------------------------------------------------------
    # Step 1: Fill date columns from task-level extraction
    # ------------------------------------------------------------------
    for col, extractor in [
        ("FILE_DATE", extract_sa_file_date),
        ("PERMIT_DATE", extract_sa_permit_date),
        ("FINAL_DATE", extract_sa_final_date),
    ]:
        was_missing = out[col].isna()
        if not was_missing.any():
            out[f"{col}_FILLED"] = False
            continue
        extracted = out.loc[was_missing, "DATA"].apply(extractor)
        extracted_parsed = extracted.apply(
            lambda v: _try_parse_date(v) if v is not None else None
        )
        extracted_parsed = pd.to_datetime(extracted_parsed, errors="coerce")
        out.loc[was_missing, col] = extracted_parsed
        out[f"{col}_FILLED"] = False
        out.loc[was_missing & extracted_parsed.notna(), f"{col}_FILLED"] = True

    # ------------------------------------------------------------------
    # Step 2: Fill STATUS_NORMALIZED from DATA.status mapping
    # ------------------------------------------------------------------
    status_missing = out["STATUS_NORMALIZED"].isna()
    if status_missing.any():
        extracted = out.loc[status_missing, "DATA"].apply(extract_sa_status)
        out.loc[status_missing, "STATUS_NORMALIZED"] = extracted
        out["STATUS_NORMALIZED_FILLED"] = False
        out.loc[status_missing & extracted.notna(), "STATUS_NORMALIZED_FILLED"] = True
    else:
        out["STATUS_NORMALIZED_FILLED"] = False

    # ------------------------------------------------------------------
    # Step 3: Correct misclassified "Closed" → "Final" for never-issued
    # permits.  Only applies to issuance-type record types (those that
    # normally go through "Permit Issued" or "Issuance").
    #
    # 72 records in the 2,002-record sample are affected: their "Permit
    # Issued" / "Issuance" task has no "Issued" / "Active" event (events
    # show "Withdrawn", "Permit Closure", or are empty).  These permits
    # were administratively closed without ever being approved/issued.
    # ------------------------------------------------------------------
    out["STATUS_NORMALIZED_CORRECTED"] = False

    is_final = out["STATUS_NORMALIZED"] == "Final"
    if is_final.any():
        is_non_issuance = out.loc[is_final, "DATA"].apply(_is_non_issuance_record)
        is_issuance_type = is_final & ~is_non_issuance
        if is_issuance_type.any():
            was_issued = out.loc[is_issuance_type, "DATA"].apply(_was_actually_issued)
            never_issued = is_issuance_type & ~was_issued
            if never_issued.any():
                # Check that DATA.status is "Closed" (not LOC/COO Issued etc.)
                def _raw_status_is_closed(data):
                    d = _safe_parse(data)
                    return d is not None and d.get("status") == "Closed"

                raw_closed = out.loc[never_issued, "DATA"].apply(_raw_status_is_closed)
                to_correct = never_issued & raw_closed
                out.loc[to_correct, "STATUS_NORMALIZED"] = "Inactive"
                out.loc[to_correct, "STATUS_NORMALIZED_CORRECTED"] = True

    # ------------------------------------------------------------------
    # Step 4: For non-issuance record types with "Closed" status, set
    # missing PERMIT_DATE and FINAL_DATE to FILE_DATE.
    #
    # These record types (applications, investigations, inspections, etc.)
    # never go through a formal issuance step.  "Closed" means the case
    # was completed, so the entire lifecycle effectively occurs at filing.
    # 207 PERMIT_DATE and 205 FINAL_DATE values are filled this way.
    # ------------------------------------------------------------------
    def _is_closed_non_issuance(data):
        d = _safe_parse(data)
        if d is None:
            return False
        return (
            d.get("record_type", "") in _SA_NON_ISSUANCE_RECORD_TYPES
            and d.get("status") == "Closed"
        )

    is_closed_non_iss = out["DATA"].apply(_is_closed_non_issuance)

    for col in ("PERMIT_DATE", "FINAL_DATE"):
        still_missing = out[col].isna() & is_closed_non_iss & out["FILE_DATE"].notna()
        if still_missing.any():
            out.loc[still_missing, col] = out.loc[still_missing, "FILE_DATE"]
            out.loc[still_missing, f"{col}_FILLED"] = True

    return out

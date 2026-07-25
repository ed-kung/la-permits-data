"""Data repair for San Diego permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

The San Diego DATA column has two sub-schemas:

  - tasks:  Accela-style workflow payload with top-level keys 'tasks',
            'date', 'status', 'search_data', etc.  Issuance and finaling
            dates live in task events (keys 'status' + ' on ').

  - approval_project: Project Status XML extract with top-level keys
            'approval' and 'project'.  Status and dates live under
            approval.Approval (Status, IssueDate, CompleteCancelDate)
            and project.ApplicationDate.

Known issues repaired:
  - STATUS_NORMALIZED lagged behind DATA.status / Approval.Status
    (e.g. Closed→Active, Issued→In Review, Completed→Active,
    Cancelled-Expired→Active).
  - Deemed Complete incorrectly mapped to Final (still in review).
  - PERMIT_DATE missing for Issued Active records whose issuance is
    recorded on Fees/Review tasks rather than Issuance/Permit Issuance.
  - PERMIT_DATE set to Invoice Paid instead of Issued (2 records).
  - FINAL_DATE missing for Closed Final records with Closeout/Closed
    or Inspections/Finaled events.
  - FILE_DATE missing on approval_project records with no
    ApplicationDate; filled from earliest InvoiceIssueDate (or
    ReviewCycle date) when available.
  - Spurious FINAL_DATE on Active tasks records cleared.
"""

import json
import math
from typing import Optional

import pandas as pd
import numpy as np


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
    """Parse a date value, returning pd.NaT on failure."""
    if val is None or (isinstance(val, str) and not val.strip()):
        return pd.NaT
    if isinstance(val, str) and val.strip().upper() == "TBD":
        return pd.NaT
    try:
        return pd.to_datetime(val)
    except (ValueError, TypeError):
        return pd.NaT


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())
    if "tasks" in keys:
        return "tasks"
    if "approval" in keys or "project" in keys:
        return "approval_project"
    return "unknown"


def _iter_task_events(tasks: list):
    """Yield (task_name, event_status, on_date_str) from Accela task events."""
    for t in tasks or []:
        if not isinstance(t, dict):
            continue
        name = t.get("name")
        for e in t.get("events") or []:
            if not isinstance(e, dict):
                continue
            on_val = e.get(" on ") or e.get("on")
            yield name, e.get("status"), on_val


def _first_event_date(tasks: list, task_names, statuses) -> pd.Timestamp:
    """Return the date of the first event matching task name(s) + status(es)."""
    if isinstance(task_names, str):
        task_names = [task_names]
    if isinstance(statuses, str):
        statuses = [statuses]
    name_set = set(task_names)
    status_set = set(statuses)
    for name, estatus, on_val in _iter_task_events(tasks):
        if name in name_set and estatus in status_set:
            dt = _safe_to_datetime(on_val)
            if dt is not pd.NaT:
                return dt
    return pd.NaT


def _set_status(repairs: dict, current, expected: str):
    if expected is None:
        return
    if pd.isna(current):
        repairs["STATUS_NORMALIZED"] = expected
        repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"
    elif current != expected:
        repairs["STATUS_NORMALIZED"] = expected
        repairs["STATUS_NORMALIZED_FLAG"] = "FIXED"


# ── Status mapping tables ────────────────────────────────────────────────────

# tasks schema: DATA.status → STATUS_NORMALIZED
_TASKS_STATUS_MAP = {
    # Final
    "Closed": "Final",
    # Active
    "Issued": "Active",
    "Approved": "Active",
    "Inspecting": "Active",
    "Inspection Followup": "Active",
    # Inactive
    "Cancelled": "Inactive",
    "Canceled": "Inactive",
    "Cancelled Application Expired": "Inactive",
    "Withdrawn": "Inactive",
    "Application Expired": "Inactive",
    "Failed Scout Validation": "Inactive",
    # In Review
    "Opened": "In Review",
    "Open": "In Review",
    "Created": "In Review",
    "In Review": "In Review",
    "In Queue": "In Review",
    "Review Phase Complete": "In Review",
    "Reviews Complete": "In Review",
    "Updates Required": "In Review",
    "Recheck Required": "In Review",
    "Ready for Submission": "In Review",
    "Pending Invoice Payment": "In Review",
    "Application Pending Payment": "In Review",
    "Approved Upon Final Payment": "In Review",
    "Issuance Checklist Requested": "In Review",
    "Issuance Checklist Submitted": "In Review",
    "All Fees Paid": "In Review",
    "Resubmitted": "In Review",
    # Completeness check, not permit final
    "Deemed Complete": "In Review",
}

# approval_project schema: Approval.Status → STATUS_NORMALIZED
_APPROVAL_STATUS_MAP = {
    "Completed": "Final",
    "Issued": "Active",
    "Created": "In Review",
    "Pending Invoice Payment": "In Review",
    "Cancelled - Expired": "Inactive",
    "Cancelled - Rescinded (Customer Request)": "Inactive",
    "Cancelled - Selected Approval in Error": "Inactive",
    "Cancelled - Abandoned": "Inactive",
    "Cancelled - Approval Uncancelled": "Inactive",
}


# ── Per-schema repair logic ─────────────────────────────────────────────────

def _extract_permit_date_tasks(tasks: list) -> pd.Timestamp:
    """Best available permit issuance date from task events."""
    # Prefer true issuance events
    dt = _first_event_date(tasks, ["Issuance", "Permit Issuance"], ["Issued"])
    if dt is not pd.NaT:
        return dt
    # OTC / simple permits often record issuance on Fees or Review
    dt = _first_event_date(tasks, ["Fees", "Review"], ["Issued"])
    if dt is not pd.NaT:
        return dt
    # Approved (no separate Issued step) — used for Approved-status permits
    dt = _first_event_date(
        tasks,
        ["Issuance", "Permit Issuance"],
        ["Approved"],
    )
    if dt is not pd.NaT:
        return dt
    return pd.NaT


def _extract_final_date_tasks(tasks: list) -> pd.Timestamp:
    """Best available final/completion date from task events.

    Prefer Inspections/Finaled (matches the 'finaled' semantics), then
    Closed/Closeout close events.
    """
    dt = _first_event_date(tasks, ["Inspections"], ["Finaled"])
    if dt is not pd.NaT:
        return dt
    dt = _first_event_date(tasks, ["Closed", "Closeout", "Closure"], ["Closed", "Close"])
    if dt is not pd.NaT:
        return dt
    dt = _first_event_date(tasks, ["Job Sign Off"], ["Completed"])
    if dt is not pd.NaT:
        return dt
    return pd.NaT


def _repair_tasks(row, d: dict, repairs: dict):
    """Repair a tasks-schema record."""
    tasks = d.get("tasks") or []
    data_status = d.get("status")

    # -- STATUS_NORMALIZED --
    current_status = row["STATUS_NORMALIZED"]
    expected = _TASKS_STATUS_MAP.get(data_status) if data_status else None
    _set_status(repairs, current_status, expected)
    effective_status = repairs.get("STATUS_NORMALIZED", current_status)

    # -- FILE_DATE --
    # Top-level 'date' is the application/opened date; all tasks records
    # already have FILE_DATE populated and matching. Fill only if missing.
    if pd.isna(row["FILE_DATE"]):
        fd = _safe_to_datetime(d.get("date"))
        if fd is pd.NaT:
            search = d.get("search_data") or {}
            if isinstance(search, dict):
                fd = _safe_to_datetime(search.get("Date") or search.get("Created Date"))
        if fd is not pd.NaT:
            repairs["FILE_DATE"] = fd
            repairs["FILE_DATE_FLAG"] = "FILLED"

    # -- PERMIT_DATE --
    issued = _extract_permit_date_tasks(tasks)
    current_pd = _safe_to_datetime(row["PERMIT_DATE"])

    if effective_status in ("Active", "Final"):
        if pd.isna(row["PERMIT_DATE"]):
            if issued is not pd.NaT:
                repairs["PERMIT_DATE"] = issued
                repairs["PERMIT_DATE_FLAG"] = "FILLED"
        elif issued is not pd.NaT and current_pd is not pd.NaT:
            # Prefer Issuance/Permit Issuance Issued over Invoice Paid etc.
            true_issued = _first_event_date(
                tasks, ["Issuance", "Permit Issuance"], ["Issued"]
            )
            if (
                true_issued is not pd.NaT
                and current_pd.normalize() != true_issued.normalize()
            ):
                repairs["PERMIT_DATE"] = true_issued
                repairs["PERMIT_DATE_FLAG"] = "FIXED"

    # -- FINAL_DATE --
    final_dt = _extract_final_date_tasks(tasks)
    if effective_status == "Final":
        if pd.isna(row["FINAL_DATE"]) and final_dt is not pd.NaT:
            repairs["FINAL_DATE"] = final_dt
            repairs["FINAL_DATE_FLAG"] = "FILLED"
        elif (
            not pd.isna(row["FINAL_DATE"])
            and final_dt is not pd.NaT
            and _safe_to_datetime(row["FINAL_DATE"]).normalize() != final_dt.normalize()
        ):
            # Only overwrite when current value is not the Inspections/Finaled
            # date (those are already correct under finaled semantics).
            insp = _first_event_date(tasks, ["Inspections"], ["Finaled"])
            cur = _safe_to_datetime(row["FINAL_DATE"])
            if insp is pd.NaT or cur.normalize() != insp.normalize():
                repairs["FINAL_DATE"] = final_dt
                repairs["FINAL_DATE_FLAG"] = "FIXED"
    elif not pd.isna(row["FINAL_DATE"]) and effective_status in (
        "Active",
        "In Review",
    ):
        # Spurious final date on non-Final open permits
        repairs["FINAL_DATE"] = pd.NaT
        repairs["FINAL_DATE_FLAG"] = "FIXED"


def _earliest_invoice_date(project: dict) -> pd.Timestamp:
    dates = []
    for inv in project.get("Invoices") or []:
        if isinstance(inv, dict):
            dt = _safe_to_datetime(inv.get("InvoiceIssueDate"))
            if dt is not pd.NaT:
                dates.append(dt)
    return min(dates) if dates else pd.NaT


def _earliest_review_cycle_date(project: dict) -> pd.Timestamp:
    dates = []
    for rc in project.get("ReviewCycles") or []:
        if not isinstance(rc, dict):
            continue
        for k in ("CloseDate", "DueDate"):
            dt = _safe_to_datetime(rc.get(k))
            if dt is not pd.NaT:
                dates.append(dt)
        for rev in rc.get("Reviews") or []:
            if isinstance(rev, dict):
                dt = _safe_to_datetime(rev.get("CompletedDate"))
                if dt is not pd.NaT:
                    dates.append(dt)
    return min(dates) if dates else pd.NaT


def _repair_approval_project(row, d: dict, repairs: dict):
    """Repair an approval_project-schema record."""
    approval_wrap = d.get("approval") or {}
    approval = approval_wrap.get("Approval") or {}
    project = d.get("project") or {}
    # Nested Project under approval often mirrors top-level project
    nested_project = approval_wrap.get("Project") or {}

    apr_status = approval.get("Status")
    app_date = _safe_to_datetime(
        project.get("ApplicationDate") or nested_project.get("ApplicationDate")
    )
    issue_date = _safe_to_datetime(approval.get("IssueDate"))
    complete_date = _safe_to_datetime(approval.get("CompleteCancelDate"))

    # -- STATUS_NORMALIZED --
    current_status = row["STATUS_NORMALIZED"]
    expected = _APPROVAL_STATUS_MAP.get(apr_status) if apr_status else None
    _set_status(repairs, current_status, expected)
    effective_status = repairs.get("STATUS_NORMALIZED", current_status)

    # -- FILE_DATE --
    if pd.isna(row["FILE_DATE"]):
        fd = app_date
        if fd is pd.NaT:
            fd = _earliest_invoice_date(project)
        if fd is pd.NaT:
            fd = _earliest_review_cycle_date(project)
        if fd is not pd.NaT:
            repairs["FILE_DATE"] = fd
            repairs["FILE_DATE_FLAG"] = "FILLED"

    # -- PERMIT_DATE --
    if effective_status in ("Active", "Final"):
        if pd.isna(row["PERMIT_DATE"]) and issue_date is not pd.NaT:
            repairs["PERMIT_DATE"] = issue_date
            repairs["PERMIT_DATE_FLAG"] = "FILLED"
        elif (
            not pd.isna(row["PERMIT_DATE"])
            and issue_date is not pd.NaT
            and _safe_to_datetime(row["PERMIT_DATE"]).normalize()
            != issue_date.normalize()
        ):
            repairs["PERMIT_DATE"] = issue_date
            repairs["PERMIT_DATE_FLAG"] = "FIXED"

    # -- FINAL_DATE --
    if effective_status == "Final":
        if pd.isna(row["FINAL_DATE"]) and complete_date is not pd.NaT:
            repairs["FINAL_DATE"] = complete_date
            repairs["FINAL_DATE_FLAG"] = "FILLED"
        elif (
            not pd.isna(row["FINAL_DATE"])
            and complete_date is not pd.NaT
            and _safe_to_datetime(row["FINAL_DATE"]).normalize()
            != complete_date.normalize()
        ):
            repairs["FINAL_DATE"] = complete_date
            repairs["FINAL_DATE_FLAG"] = "FIXED"
    elif not pd.isna(row["FINAL_DATE"]) and effective_status in (
        "Active",
        "In Review",
    ):
        repairs["FINAL_DATE"] = pd.NaT
        repairs["FINAL_DATE_FLAG"] = "FIXED"


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    San Diego permit records using information from the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "San Diego".  Must contain
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

        if schema == "tasks":
            _repair_tasks(row, d, repairs)
        elif schema == "approval_project":
            _repair_approval_project(row, d, repairs)

        for key, value in repairs.items():
            out.at[idx, key] = value

    return out


# ── CLI: run standalone to preview repair stats ─────────────────────────────

if __name__ == "__main__":
    import os
    from dotenv import load_dotenv, find_dotenv

    load_dotenv(find_dotenv())
    MY_DATA_PATH = os.getenv("MY_DATA_PATH")
    filepath = os.path.join(
        MY_DATA_PATH, "processed_data", "permits_ca_sample.parquet"
    )
    df = pd.read_parquet(filepath)
    sd = df[df["JURISDICTION"] == "San Diego"].copy()

    print(f"San Diego records: {len(sd):,}\n")

    repaired = data_repair(sd)

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

        before_missing = sd[field].isna().sum()
        after_missing = repaired[field].isna().sum()
        print(
            f"  Missing before: {before_missing:>4,}   "
            f"Missing after: {after_missing:>4,}"
        )
        print()

    print("STATUS_NORMALIZED distribution:")
    print("  Before:")
    for s, c in sd["STATUS_NORMALIZED"].value_counts(dropna=False).items():
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
        print(
            f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} "
            f"({n_has / len(sub):.1%})"
        )

    print("\nPERMIT_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        if len(sub) == 0:
            continue
        n_has = sub["PERMIT_DATE"].notna().sum()
        print(
            f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} "
            f"({n_has / len(sub):.1%})"
        )

    print("\nFILE_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        if len(sub) == 0:
            continue
        n_has = sub["FILE_DATE"].notna().sum()
        print(
            f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} "
            f"({n_has / len(sub):.1%})"
        )

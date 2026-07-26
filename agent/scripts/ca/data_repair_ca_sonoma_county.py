"""Data repair for Sonoma County (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Sonoma County DATA is an Accela Citizen Access scrape with two key-set
variants (same repair logic):

  - tasks_full:   top-level keys include ``tasks``, ``status``, ``date``,
                  ``search_data``, plus ``contacts``, ``fees_details``,
                  ``inspections``, ``conditions``, etc.
  - tasks_sparse: same core keys but without contacts / fees_details /
                  inspections / related_records / conditions

Canonical mappings:
  - DATA.status (with Closed-task fallback when status is blank)
                                             → STATUS_NORMALIZED
  - DATA.date / search_data['Date']          → FILE_DATE
  - Permit Issuance / Paid|Issued
      (HTML fallback when structured Marked-as fields are absent;
       then more_details KEY DATES 'Date Issued From')
                                             → PERMIT_DATE
  - Inspection / Finaled|Final|Inspection Complete|...,
    Closed / Closed|Complete|Finished|File Closed,
    Investigate / Complete*, Recordation / Recorded,
    Cashier / Certified                      → FINAL_DATE (latest)

Known issues repaired:
  - 44 unmapped / blank DATA.status rows → FILLED (Closed evidence →
    Final; ENTERED / Resubmittal Requested / Notice & Order / etc. →
    In Review or Active).
  - Done (OTC zoning/design review with Closed) wrongly labeled
    In Review → FIXED to Final.
  - Finished rows are expired legacy shells (Inspection Expired /
    Closed Finished) wrongly labeled Final → FIXED to Inactive.
  - ~45 Issued/Finaled rows missing PERMIT_DATE because Accela only
    put Marked-as / on dates in HTML (Assigned-to structured fields)
    → FILLED via HTML parse; 1 mismatched issuance day → FIXED.
  - ~240+ Final rows missing FINAL_DATE despite Closed / Inspection /
    Investigate completion events → FILLED.
  - Spurious FINAL_DATE on non-Final rows (e.g. Approved Well Study
    with Inspection Complete + Closed, before status stays Active)
    → cleared when effective status is not Final.

Not repairable / left as-is:
  - FILE_DATE already matches DATA.date for all sample rows.
  - Hundreds of Final Closed / Complete-* / Recorded / Certified /
    safety-assessment shells never received a Permit Issuance event
    → PERMIT_DATE stays missing.
  - Finished→Inactive and some Finaled / Complete-* shells lack a
    dated completion event → FINAL_DATE stays missing.
"""

import json
import math
import re
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
    """Parse a date value, returning pd.NaT on failure / TBD."""
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return pd.NaT
    if isinstance(val, str) and not str(val).strip():
        return pd.NaT
    if str(val).strip().upper() == "TBD":
        return pd.NaT
    try:
        return pd.to_datetime(val)
    except (ValueError, TypeError):
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
    if "tasks" in keys and "status" in keys:
        if {"contacts", "fees_details", "inspections", "conditions"} & keys:
            return "tasks_full"
        return "tasks_sparse"
    if "search_data" in keys and "tasks" not in keys:
        return "search_data_only"
    return "unknown"


def _event_field(event: dict, *names: str):
    """Read an event field, tolerating leading/trailing spaces in keys."""
    targets = {n.strip() for n in names}
    for k, v in event.items():
        if isinstance(k, str) and k.strip() in targets:
            return v
    return None


_MARKED_HTML_RE = re.compile(
    r"Marked as\s*<span>(?P<marked>[^<]+)</span>\s*on\s*"
    r"<span>(?P<on>[^<]+)</span>",
    re.IGNORECASE,
)


def _parse_event(event: dict):
    """Return (marked, datetime) from structured fields or HTML fallback.

    Some Sonoma Accela events only populate ``Assigned to`` as a structured
    key; the Marked-as / on values live inside ``html``.
    """
    marked = _event_field(event, "Marked as")
    on = _event_field(event, "on")
    if isinstance(marked, str):
        marked = marked.strip() or None
    if marked and on is not None and str(on).strip().upper() != "TBD":
        dt = _safe_to_datetime(on)
        if dt is not pd.NaT:
            return marked, dt

    html = event.get("html") or ""
    if isinstance(html, str) and html:
        m = _MARKED_HTML_RE.search(html)
        if m:
            return m.group("marked").strip(), _safe_to_datetime(m.group("on"))

    return marked, _safe_to_datetime(on)


def _iter_task_nodes(tasks: list):
    """Yield (task_name, task_dict) for top-level tasks and subtasks."""
    for t in tasks or []:
        if not isinstance(t, dict):
            continue
        yield t.get("name") or "", t
        for st in t.get("subtasks") or []:
            if isinstance(st, dict):
                yield st.get("name") or "", st


# ── Status mapping ──────────────────────────────────────────────────────────

# DATA.status (Title Case as scraped; lookup is case-insensitive)
_STATUS_MAP = {
    # Final — completed / closed / certified / recorded outcomes
    "Finaled": "Final",
    "Final": "Final",
    "Closed": "Final",
    "Complete": "Final",
    "Complete - Green": "Final",
    "Complete - Red": "Final",
    "Complete - Yellow": "Final",
    "Green": "Final",
    "File Closed": "Final",
    "Recorded": "Final",
    "Certified": "Final",
    "Done": "Final",
    # Active — issued / approved / open enforcement
    "Issued": "Active",
    "Approved": "Active",
    "Active": "Active",
    "Active Permit or Plan Check": "Active",
    "Pending Inspection Result": "Active",
    "Sent to Recorder": "Active",
    "Notice & Order": "Active",
    # Inactive — expired, voided, withdrawn, denied, finished-without-final
    "Expired": "Inactive",
    "Void": "Inactive",
    "Withdrawn": "Inactive",
    "Denied": "Inactive",
    "Plan Check Expired": "Inactive",
    "Finished": "Inactive",
    # In Review — pre-issuance / plan check / payment / intake
    "Application Accepted/In Review": "In Review",
    "Application Received": "In Review",
    "Approved for Plan Check": "In Review",
    "Awaiting Applicant Response": "In Review",
    "Complete for Processing": "In Review",
    "ENTERED": "In Review",
    "Incomplete": "In Review",
    "Paid": "In Review",
    "Payment Due": "In Review",
    "PC Approved": "In Review",
    "PENDINGL": "In Review",
    "PENDINGM": "In Review",
    "Pending Test Data": "In Review",
    "Plan Check": "In Review",
    "Plan Check Approved": "In Review",
    "Plan Check Comments Sent": "In Review",
    "Plans Received": "In Review",
    "Pre-Issue": "In Review",
    "Pre-Issue/Payment Due": "In Review",
    "Ready for Plan Check": "In Review",
    "Referrals Sent": "In Review",
    "Resubmittal Received": "In Review",
    "Resubmittal Requested": "In Review",
    "Review": "In Review",
    "Site Review": "In Review",
    "Started": "In Review",
    "Submitted": "In Review",
    "To Site Review": "In Review",
    "Waiting for Other Approvals": "In Review",
}

_STATUS_MAP_LOWER = {k.lower(): v for k, v in _STATUS_MAP.items()}


def _map_status(data_status: Optional[str]) -> Optional[str]:
    if not data_status or not isinstance(data_status, str):
        return None
    key = data_status.strip()
    if not key:
        return None
    return _STATUS_MAP.get(key) or _STATUS_MAP_LOWER.get(key.lower())


def _status_from_tasks(tasks: list) -> Optional[str]:
    """Infer STATUS_NORMALIZED when DATA.status is blank."""
    for name, t in _iter_task_nodes(tasks):
        if name != "Closed":
            continue
        for e in t.get("events") or []:
            if not isinstance(e, dict):
                continue
            marked, _dt = _parse_event(e)
            if marked == "Closed":
                return "Final"
    # Blank-status shells still in workflow (often Plan Check / Open TBD)
    return "In Review"


_ISSUE_MARKS = {"Paid", "Issued"}


def _is_issue_mark(marked: Optional[str]) -> bool:
    """Sonoma uses Permit Issuance / Paid as the primary issuance signal."""
    return isinstance(marked, str) and marked.strip() in _ISSUE_MARKS


def _is_final_mark(task_name: str, marked: Optional[str]) -> bool:
    if not marked or not isinstance(marked, str):
        return False
    m = marked.strip()
    if task_name == "Inspection" and m in (
        "Finaled",
        "Final",
        "Inspection Complete",
        "Final Paperwork Received",
    ):
        return True
    if task_name == "Closed" and m in (
        "Closed",
        "Complete",
        "Finished",
        "File Closed",
    ):
        return True
    if task_name == "Investigate" and (
        m == "Complete" or m.startswith("Complete -")
    ):
        return True
    if task_name == "Recordation" and m == "Recorded":
        return True
    if task_name == "Cashier" and m == "Certified":
        return True
    return False


def _permit_date_from_tasks(tasks: list):
    """Earliest Permit Issuance Paid/Issued date (structured or HTML)."""
    dates = []
    for name, t in _iter_task_nodes(tasks):
        if name != "Permit Issuance":
            continue
        for e in t.get("events") or []:
            if not isinstance(e, dict):
                continue
            marked, dt = _parse_event(e)
            if _is_issue_mark(marked) and dt is not pd.NaT:
                dates.append(dt)
    return min(dates) if dates else pd.NaT


def _permit_date_from_key_dates(d: dict):
    """Fallback: more_details Application Information KEY DATES."""
    md = d.get("more_details")
    if not isinstance(md, dict):
        return pd.NaT
    ai = md.get("Application Information")
    if not isinstance(ai, dict):
        return pd.NaT
    kd = ai.get("KEY DATES")
    if not isinstance(kd, dict):
        return pd.NaT
    return _safe_to_datetime(kd.get("Date Issued From"))


def _final_date_from_tasks(tasks: list):
    """Latest completion / finaling / close-out workflow date."""
    dates = []
    for name, t in _iter_task_nodes(tasks):
        for e in t.get("events") or []:
            if not isinstance(e, dict):
                continue
            marked, dt = _parse_event(e)
            if not _is_final_mark(name, marked):
                continue
            if dt is not pd.NaT:
                dates.append(dt)
    return max(dates) if dates else pd.NaT


# ── Per-record repair logic ─────────────────────────────────────────────────

def _repair_tasks(row, d: dict, repairs: dict):
    """Repair a tasks-schema (Accela Citizen Access) record."""
    tasks = d.get("tasks") or []
    data_status = d.get("status")
    if isinstance(data_status, str):
        data_status = data_status.strip() or None
    else:
        data_status = None

    # -- STATUS_NORMALIZED --
    current_status = row["STATUS_NORMALIZED"]
    expected = _map_status(data_status)
    if expected is None and data_status is None:
        expected = _status_from_tasks(tasks)

    if expected is not None:
        if pd.isna(current_status):
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"
        elif current_status != expected:
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FIXED"

    effective_status = repairs.get("STATUS_NORMALIZED", current_status)

    # -- FILE_DATE --
    file_src = _safe_to_datetime(d.get("date"))
    if file_src is pd.NaT:
        sd = d.get("search_data") if isinstance(d.get("search_data"), dict) else {}
        file_src = _safe_to_datetime(sd.get("Date") or sd.get("Created Date"))
    if file_src is not pd.NaT:
        if pd.isna(row["FILE_DATE"]):
            repairs["FILE_DATE"] = file_src
            repairs["FILE_DATE_FLAG"] = "FILLED"
        elif not _dates_equal(row["FILE_DATE"], file_src):
            repairs["FILE_DATE"] = file_src
            repairs["FILE_DATE_FLAG"] = "FIXED"

    # -- PERMIT_DATE --
    issued = _permit_date_from_tasks(tasks)
    if issued is pd.NaT:
        issued = _permit_date_from_key_dates(d)
    if issued is not pd.NaT:
        if pd.isna(row["PERMIT_DATE"]):
            if effective_status in ("Active", "Final"):
                repairs["PERMIT_DATE"] = issued
                repairs["PERMIT_DATE_FLAG"] = "FILLED"
        elif not _dates_equal(row["PERMIT_DATE"], issued):
            repairs["PERMIT_DATE"] = issued
            repairs["PERMIT_DATE_FLAG"] = "FIXED"

    # -- FINAL_DATE --
    final = _final_date_from_tasks(tasks)
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
        # Spurious FINAL_DATE on non-Final rows.
        repairs["FINAL_DATE"] = pd.NaT
        repairs["FINAL_DATE_FLAG"] = "FIXED"


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Sonoma County permit records using information from the raw DATA JSON
    column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Sonoma County".  Must
        contain columns STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE,
        FINAL_DATE, and DATA.

    Returns
    -------
    pd.DataFrame
        Copy of *df* with corrected field values, an INFERRED_SCHEMA column
        naming the DATA JSON schema identified for each record, and new
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
        if schema in ("tasks_full", "tasks_sparse"):
            _repair_tasks(row, d, repairs)

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
    filepath = os.path.join(
        MY_DATA_PATH, "processed_data", "permits_ca_sample.parquet"
    )
    df = pd.read_parquet(filepath)
    city = df[
        (df["JURISDICTION"] == "Sonoma County") & (df["STATE"] == "CA")
    ].copy()

    print(f"Sonoma County records: {len(city):,}\n")

    repaired = data_repair(city)

    if AGENT_DATA_PATH:
        out_path = os.path.join(
            AGENT_DATA_PATH,
            "processed_data",
            "permits_ca_sonoma_county_repaired.parquet",
        )
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        repaired.to_parquet(out_path, index=False)
        print(f"Wrote {out_path}\n")

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
        print(
            f"  Missing before: {before_missing:>4,}   "
            f"Missing after: {after_missing:>4,}"
        )
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
        n = len(sub)
        pct = n_has / n if n else 0.0
        print(f"  {status:15s}: {n_has:>4,} / {n:>4,} ({pct:.1%})")

    print("\nFINAL_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FINAL_DATE"].notna().sum()
        n = len(sub)
        pct = n_has / n if n else 0.0
        print(f"  {status:15s}: {n_has:>4,} / {n:>4,} ({pct:.1%})")

    print("\nFILE_DATE coverage (after repair):")
    n_has = repaired["FILE_DATE"].notna().sum()
    print(f"  {n_has:>4,} / {len(repaired):>4,} ({n_has / len(repaired):.1%})")

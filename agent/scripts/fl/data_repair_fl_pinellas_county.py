"""Data repair for Pinellas County (FL) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Pinellas County DATA is an Accela Citizen Access payload. Rows typically
include ``status``, ``date``, ``search_data``, ``tasks``, and usually
``inspections``. Legacy / migrated rows often have empty task event
histories (``accela_shell``). Express Building Permits commonly mark
issuance on the ``Permit Review`` task (Marked as Issued) rather than
``Permit Issuance``.

Canonical mappings:
  - DATA.status                                              → STATUS_NORMALIZED
  - DATA.date / search_data.Date                             → FILE_DATE
  - Earliest Permit Issuance Marked as Issued; else
    Permit Review Marked as Issued                           → PERMIT_DATE
  - CO/COC Verification certificate issued; else Inspections
    task Final Inspection Complete / Finaled; else approved
    Final inspection Status Date                             → FINAL_DATE

Known issues repaired:
  - STATUS_NORMALIZED derived from STATUS_ORIGINAL lags
    DATA.status (e.g. issued / in review while Accela shows
    Finaled / Expired / Closed - Finaled) → FIXED.
  - Unmapped statuses (Missing Documents, Verified,
    Closed - Supp-Rev Approved, Phase I Required) left null
    → FILLED from DATA.status.
  - Missing PERMIT_DATE filled from Permit Issuance / Permit
    Review Issued events for Active / Final rows.
  - Missing FINAL_DATE filled for Final rows from CO / Inspections
    task closeout / approved Final inspection Status Dates
    (including shell rows that only retain inspections).
  - Incorrect FINAL_DATE overwritten when a stronger Accela
    finalization signal differs → FIXED.
  - Spurious FINAL_DATE on non-Final rows → cleared (FIXED).

Not repairable / left as-is:
  - Empty DATA.status POS / registration stubs with no usable
    workflow status → STATUS_NORMALIZED stays missing.
  - Active / Final shell rows with no Permit Issuance or Permit
    Review Issued event → PERMIT_DATE stays missing.
  - Final rows with neither CO / Inspections closeout events nor
    a passed Final inspection → FINAL_DATE stays missing.
  - FILE_DATE already matches DATA.date for all sample rows →
    no FILE_DATE changes expected.
"""

from __future__ import annotations

import json
import math
import re
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
    """Parse a date value, returning pd.NaT on failure / sentinels."""
    if val is None or (isinstance(val, str) and not str(val).strip()):
        return pd.NaT
    if not isinstance(val, str) and pd.isna(val):
        return pd.NaT
    text = str(val).strip()
    if text.upper() in ("TBD", "NONE", "N/A", "NA", "00/00/0000", "0/0/0000"):
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


def _event_field(event: dict, *labels: str):
    """Read an Accela event field, tolerating leading/trailing spaces / NBSP."""
    for label in labels:
        for k, v in event.items():
            if not isinstance(k, str):
                continue
            if k.replace("\xa0", " ").strip().lower() == label.lower():
                if isinstance(v, str):
                    return v.replace("\xa0", " ").strip()
                return v
    return None


def _parse_event(event: dict):
    """Return (marked_as, on_date_str) from an Accela task event."""
    html = (event.get("html") or "").replace("\xa0", " ")
    m = re.search(
        r"Marked as\s*<span[^>]*>([^<]*)</span>\s*on\s*<span[^>]*>([^<]*)</span>",
        html,
        flags=re.I,
    )
    if m:
        return m.group(1).strip(), m.group(2).strip()

    marked = _event_field(event, "Marked as")
    on_val = _event_field(event, "on")
    return marked, on_val


def _iter_task_nodes(tasks: list):
    for t in tasks or []:
        if not isinstance(t, dict):
            continue
        yield (t.get("name") or "").replace("\xa0", " ").strip(), t
        for st in t.get("subtasks") or []:
            if isinstance(st, dict):
                yield (st.get("name") or "").replace("\xa0", " ").strip(), st


def _has_dated_task_event(tasks: list) -> bool:
    for _, t in _iter_task_nodes(tasks):
        for e in t.get("events") or []:
            if not isinstance(e, dict):
                continue
            _, on_val = _parse_event(e)
            if _safe_to_datetime(on_val) is not pd.NaT:
                return True
    return False


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())
    if "status" not in keys or "date" not in keys:
        return "unknown"

    tasks = data_dict.get("tasks") or []
    has_inspections = isinstance(data_dict.get("inspections"), list)
    has_dated_event = _has_dated_task_event(tasks)

    if has_inspections and has_dated_event:
        return "accela_full"
    if has_dated_event:
        return "accela_basic"
    return "accela_shell"


def _event_dates(tasks: list, task_names, marked_pred) -> list:
    if isinstance(task_names, str):
        task_names = {task_names}
    else:
        task_names = set(task_names)
    dates = []
    for name, t in _iter_task_nodes(tasks):
        if name not in task_names:
            continue
        for e in t.get("events") or []:
            if not isinstance(e, dict):
                continue
            marked, on_val = _parse_event(e)
            marked = (marked or "").strip() if isinstance(marked, str) else marked
            if not marked or not marked_pred(marked):
                continue
            dt = _safe_to_datetime(on_val)
            if dt is not pd.NaT:
                dates.append(dt)
    return dates


# ── Status mapping ──────────────────────────────────────────────────────────

# DATA.status → STATUS_NORMALIZED (lookup is case-insensitive)
_STATUS_MAP = {
    # Final — finaled / CO / closed complete
    "Finaled": "Final",
    "Closed - Finaled": "Final",
    "Closed": "Final",
    "CofO Issued": "Final",
    "CofC Issued": "Final",
    "Administrative Close": "Final",
    "Closed - Supp-Rev Approved": "Final",
    # Active — issued / ongoing
    "Issued": "Active",
    # In Review — intake / plan review / pending applicant
    "Submitted": "In Review",
    "In Review": "In Review",
    "Awaiting Plans": "In Review",
    "Plans Received": "In Review",
    "Missing Documents": "In Review",
    "Incomplete Submittal": "In Review",
    "Awaiting Applicant Action": "In Review",
    "Awaiting Payment": "In Review",
    "Plan Review": "In Review",
    "Revisions Required": "In Review",
    "Pending": "In Review",
    "Waiting on Applicant": "In Review",
    "Phase I Required": "In Review",
    "Verified": "In Review",
    # Inactive — expired / withdrawn / void
    "Expired": "Inactive",
    "Closed - Expired": "Inactive",
    "Closed - Withdrawn": "Inactive",
    "Void": "Inactive",
}

_STATUS_MAP_LOWER = {k.lower(): v for k, v in _STATUS_MAP.items()}


def _map_status(data_status: Optional[str]) -> Optional[str]:
    if not data_status or not isinstance(data_status, str):
        return None
    key = data_status.strip()
    if not key:
        return None
    return _STATUS_MAP.get(key) or _STATUS_MAP_LOWER.get(key.lower())


def _infer_status_from_tasks(tasks: list) -> Optional[str]:
    """Fallback status when DATA.status is empty but workflow marks exist."""
    # Prefer terminal marks if present.
    withdrawn = _event_dates(
        tasks,
        {"Application Intake", "Intake", "Permit Issuance", "Application"},
        lambda m: "withdrawn" in (m or "").lower() or (m or "").lower() == "void",
    )
    if withdrawn:
        return "Inactive"

    issued = _event_dates(
        tasks,
        {"Permit Issuance", "Permit Issued", "Issuance", "Permit Review"},
        lambda m: (m or "").strip().lower() in ("issued", "permit issued"),
    )
    if issued:
        return "Active"

    reviewish = _event_dates(
        tasks,
        {
            "Application Intake",
            "Intake",
            "Application",
            "Submittal Review and Fees",
            "Permit Review",
        },
        lambda m: (m or "").strip().lower()
        not in ("", "tbd", "na", "n/a"),
    )
    if reviewish:
        return "In Review"
    return None


def _file_date_from_data(d: dict):
    """Best available application / file date from Accela payload."""
    dt = _safe_to_datetime(d.get("date"))
    if dt is not pd.NaT:
        return dt

    sd = d.get("search_data") if isinstance(d.get("search_data"), dict) else {}
    dt = _safe_to_datetime(sd.get("Date"))
    if dt is not pd.NaT:
        return dt

    intake = _event_dates(
        d.get("tasks") or [],
        {"Application Intake", "Application", "Intake", "Submittal Review and Fees"},
        lambda m: (m or "").strip().lower()
        in {
            "accepted",
            "deemed complete",
            "plans received",
            "verified",
            "received",
        },
    )
    if intake:
        return min(intake)
    return pd.NaT


def _permit_date_from_tasks(tasks: list):
    """Earliest issuance date from Permit Issuance, else Permit Review Issued."""

    def _is_issued(m: str) -> bool:
        ml = (m or "").strip().lower()
        if "ready" in ml or "revision" in ml or "missing" in ml:
            return False
        return ml in ("issued", "permit issued")

    issued = _event_dates(
        tasks,
        {"Permit Issuance", "Permit Issued", "Issuance"},
        _is_issued,
    )
    if issued:
        return min(issued)

    # Express / short workflows mark issuance on Permit Review.
    review_issued = _event_dates(tasks, {"Permit Review"}, _is_issued)
    if review_issued:
        return min(review_issued)

    return pd.NaT


_INSP_PASS_STATUSES = {
    "approved unconditionally",
    "approved",
    "approved with conditions",
    "pass",
    "passed",
    "complied",
    "finaled",
}


def _inspection_status_dates(d: dict, *, final_title_only: bool) -> list:
    dates = []
    for insp in d.get("inspections") or []:
        if not isinstance(insp, dict):
            continue
        st = (insp.get("Status") or "").strip().lower()
        if st not in _INSP_PASS_STATUSES:
            continue
        title = (insp.get("Title") or "").lower()
        if final_title_only and "final" not in title:
            continue
        dt = _safe_to_datetime(insp.get("Status Date"))
        if dt is not pd.NaT:
            dates.append(dt)
    return dates


def _final_date_from_data(d: dict):
    """Best finalization date from CO / Inspections closeout / inspections."""
    tasks = d.get("tasks") or []

    def _is_co_issued(m: str) -> bool:
        ml = (m or "").strip().lower()
        if "required" in ml or "pending" in ml or "tbd" in ml:
            return False
        return "issued" in ml and (
            "certificate" in ml
            or "occupancy" in ml
            or "completeness" in ml
            or "cof" in ml
        )

    co = _event_dates(
        tasks,
        {"CO/COC Verification", "CO/CO Verification"},
        _is_co_issued,
    )
    if co:
        return max(co)

    def _is_insp_final(m: str) -> bool:
        ml = (m or "").strip().lower()
        if any(x in ml for x in ("tbd", "revision", "abandon", "expired", "required")):
            return False
        return ml in {
            "final inspection complete",
            "finaled",
            "closed - finaled",
        } or ("final" in ml and "complete" in ml)

    insp_task = _event_dates(tasks, {"Inspections", "Inspection"}, _is_insp_final)
    if insp_task:
        return max(insp_task)

    final_insp = _inspection_status_dates(d, final_title_only=True)
    if final_insp:
        return max(final_insp)

    # Last resort for shells with only a non-"Final"-titled trade Pass.
    insp_dates = _inspection_status_dates(d, final_title_only=False)
    if insp_dates:
        return max(insp_dates)

    return pd.NaT


# ── Per-record repair logic ─────────────────────────────────────────────────

def _repair_record(row, d: dict, repairs: dict):
    """Populate *repairs* with corrected values for one Pinellas County record."""
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
        expected = _infer_status_from_tasks(tasks)

    if expected is not None:
        if pd.isna(current_status):
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"
        elif current_status != expected:
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FIXED"

    effective_status = repairs.get("STATUS_NORMALIZED", current_status)

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
    if issued is not pd.NaT:
        if pd.isna(current_permit):
            if effective_status in ("Active", "Final"):
                repairs["PERMIT_DATE"] = issued
                repairs["PERMIT_DATE_FLAG"] = "FILLED"
        elif not _dates_equal(current_permit, issued):
            repairs["PERMIT_DATE"] = issued
            repairs["PERMIT_DATE_FLAG"] = "FIXED"

    # -- FINAL_DATE --
    final_src = _final_date_from_data(d)
    current_final = row["FINAL_DATE"]
    if effective_status == "Final":
        if final_src is not pd.NaT:
            if pd.isna(current_final):
                repairs["FINAL_DATE"] = final_src
                repairs["FINAL_DATE_FLAG"] = "FILLED"
            elif not _dates_equal(current_final, final_src):
                repairs["FINAL_DATE"] = final_src
                repairs["FINAL_DATE_FLAG"] = "FIXED"
    elif not pd.isna(current_final):
        # Spurious FINAL_DATE on non-Final rows.
        repairs["FINAL_DATE"] = pd.NaT
        repairs["FINAL_DATE_FLAG"] = "FIXED"


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Pinellas County permit records using the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Pinellas County".  Must contain
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
    filepath = os.path.join(MY_DATA_PATH, "processed_data", "permits_fl_sample.parquet")
    df = pd.read_parquet(filepath)
    pinellas = df[df["JURISDICTION"] == "Pinellas County"].copy()

    print(f"Pinellas County records: {len(pinellas):,}\n")

    repaired = data_repair(pinellas)

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

        before_missing = pinellas[field].isna().sum()
        after_missing = repaired[field].isna().sum()
        print(f"  Missing before: {before_missing:>4,}   Missing after: {after_missing:>4,}")
        print()

    print("STATUS_NORMALIZED distribution:")
    print("  Before:")
    for s, c in pinellas["STATUS_NORMALIZED"].value_counts(dropna=False).items():
        print(f"    {str(s):15s}: {c:>4,}")
    print("  After:")
    for s, c in repaired["STATUS_NORMALIZED"].value_counts(dropna=False).items():
        print(f"    {str(s):15s}: {c:>4,}")

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

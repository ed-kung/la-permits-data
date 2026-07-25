"""Data repair for Sacramento (CA city) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Sacramento (city) DATA is an Accela Citizen Access scrape with two key-set
variants (same repair logic):

  - tasks_full:   top-level keys include ``tasks``, ``status``, ``date``,
                  ``search_data``, plus ``contacts``, ``fees_details``,
                  ``inspections``, ``conditions``, etc. (n≈1,999)
  - tasks_sparse: same core keys but without contacts / fees_details /
                  inspections / related_records (n=1)

Canonical mappings:
  - DATA.status                                   → STATUS_NORMALIZED
  - DATA.date / search_data['Date'|'Created Date'] → FILE_DATE
  - Ready To Issue|Ready to Issue|Issue / Issued* → PERMIT_DATE
      (fallback: Application Submittal / Issued)
  - Issued|Issue / Finaled,
    Ready For Pickup / Complete,
    Approved FINAL inspection Status Date         → FINAL_DATE (latest)

Known issues repaired:
  - STATUS_NORMALIZED derived from stale STATUS_ORIGINAL disagrees with
    DATA.status (e.g. Finaled labeled Active via ORIG=issued; Abandoned
    labeled In Review via ORIG=accepted; Expired Permit labeled Active;
    Finaled labeled In Review) → FIXED.
  - Estimate (fee-estimate-only shells) remapped Inactive (was Final).
  - Missing PERMIT_DATE filled from Ready To Issue / Issued* when present.
  - FINAL_DATE entirely missing in sample; filled from Issued / Finaled,
    Ready For Pickup / Complete, or Approved inspections titled FINAL.
  - Spurious FINAL_DATE on non-Final rows cleared (none observed in sample).

Not repairable / left as-is:
  - FILE_DATE already matches DATA.date for all sample rows.
  - Hundreds of pre-~2010 Finaled / Closed migration stubs with empty
    task events and no FINAL inspection → PERMIT_DATE / FINAL_DATE stay
    missing.
  - Complete / certificate workflows without an Issued* event keep
    PERMIT_DATE missing (no dated issuance in DATA).
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
    """Parse a date value, returning pd.NaT on failure / TBD."""
    if val is None or (isinstance(val, str) and not str(val).strip()):
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
        if {"contacts", "fees_details", "inspections"} & keys:
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


def _iter_task_nodes(tasks: list):
    """Yield (task_name, task_dict) for top-level tasks and subtasks."""
    for t in tasks or []:
        if not isinstance(t, dict):
            continue
        yield t.get("name") or "", t
        for st in t.get("subtasks") or []:
            if isinstance(st, dict):
                yield st.get("name") or "", st


def _event_dates(tasks: list, task_names, marked_pred) -> list:
    """Return datetimes for matching task events (Marked as + on)."""
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
            marked = _event_field(e, "Marked as")
            marked = (marked or "").strip() if isinstance(marked, str) else marked
            if not marked_pred(marked):
                continue
            dt = _safe_to_datetime(_event_field(e, "on"))
            if dt is not pd.NaT:
                dates.append(dt)
    return dates


# ── Status mapping ──────────────────────────────────────────────────────────

# DATA.status (Title Case as scraped; lookup is case-insensitive)
_STATUS_MAP = {
    # Final
    "Finaled": "Final",
    "Complete": "Final",
    "Closed": "Final",
    "Certificate of Occupancy": "Final",
    "Certificate of Compliance": "Final",
    # Active
    "Issued": "Active",
    "Approved": "Active",
    "Active": "Active",
    # Inactive
    "Expired Permit": "Inactive",
    "Expired": "Inactive",
    "Expired Application": "Inactive",
    "Abandoned": "Inactive",
    "Revoked": "Inactive",
    "Failed": "Inactive",
    "Withdrawn": "Inactive",
    "Void": "Inactive",
    # Fee estimate only — not a real permit
    "Estimate": "Inactive",
    # In Review
    "Accepted": "In Review",
    "Applied": "In Review",
    "Open": "In Review",
    "Plan Check Target": "In Review",
    "Plan Check Wait": "In Review",
    "Planning Review": "In Review",
    "Process Wait": "In Review",
    "Processing": "In Review",
    "Ready to Issue": "In Review",
    "Ready-to-Issue": "In Review",
    "Submittal Incomplete": "In Review",
    "Submittal Pending Review": "In Review",
    "Verify Wait": "In Review",
    "In Progress": "In Review",
}

_STATUS_MAP_LOWER = {k.lower(): v for k, v in _STATUS_MAP.items()}


def _map_status(data_status: Optional[str]) -> Optional[str]:
    if not data_status or not isinstance(data_status, str):
        return None
    key = data_status.strip()
    if not key:
        return None
    return _STATUS_MAP.get(key) or _STATUS_MAP_LOWER.get(key.lower())


_ISSUED_MARKS = {
    "Issued",
    "Re-issued",
    "Re-Issued",
    "Isssued",  # typo seen in Accela
    "Change Issued",
    "Issued Partial",
}

_ISSUE_TASKS = {"Ready To Issue", "Ready to Issue", "Issue"}


def _is_issue_mark(marked: Optional[str]) -> bool:
    if not marked or not isinstance(marked, str):
        return False
    return marked.strip() in _ISSUED_MARKS


def _permit_date_from_tasks(tasks: list):
    """Earliest Ready To Issue / Issued* date; OTC Application Submittal fallback."""
    dates = _event_dates(tasks, _ISSUE_TASKS, _is_issue_mark)
    if dates:
        return min(dates)
    otc = _event_dates(tasks, "Application Submittal", lambda m: m == "Issued")
    if otc:
        return min(otc)
    return pd.NaT


def _final_date_from_tasks(tasks: list):
    """Latest completion / finaling workflow date from tasks."""
    dates = []
    for name, t in _iter_task_nodes(tasks):
        for e in t.get("events") or []:
            if not isinstance(e, dict):
                continue
            marked = _event_field(e, "Marked as")
            marked = (marked or "").strip() if isinstance(marked, str) else marked
            is_final = False
            if name in ("Issued", "Issue") and marked == "Finaled":
                is_final = True
            elif name == "Ready For Pickup" and marked == "Complete":
                is_final = True
            elif name == "Certificate Status" and marked == "Issued":
                is_final = True
            if not is_final:
                continue
            dt = _safe_to_datetime(_event_field(e, "on"))
            if dt is not pd.NaT:
                dates.append(dt)
    return max(dates) if dates else pd.NaT


def _final_date_from_inspections(inspections) -> pd.Timestamp:
    """Latest Status Date among Approved inspections titled FINAL.

    Used as a fallback for legacy Accela migrations where Issued / Finaled
    task events were never stored but final inspection results remain.
    """
    if not isinstance(inspections, list):
        return pd.NaT
    dates = []
    for item in inspections:
        if not isinstance(item, dict):
            continue
        title = str(item.get("Title") or "")
        status = str(item.get("Status") or "").strip().lower()
        if "FINAL" not in title.upper():
            continue
        if status not in ("approved", "passed", "complete", "completed"):
            continue
        dt = _safe_to_datetime(
            item.get("Status Date") or item.get("Last Update Date")
        )
        if dt is not pd.NaT:
            dates.append(dt)
    return max(dates) if dates else pd.NaT


def _final_date_from_data(d: dict):
    """Prefer task finaling events; fall back to FINAL inspections."""
    final = _final_date_from_tasks(d.get("tasks") or [])
    if final is not pd.NaT:
        return final
    return _final_date_from_inspections(d.get("inspections"))


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
        file_src = _safe_to_datetime(sd.get("Created Date") or sd.get("Date"))
    if file_src is not pd.NaT:
        if pd.isna(row["FILE_DATE"]):
            repairs["FILE_DATE"] = file_src
            repairs["FILE_DATE_FLAG"] = "FILLED"
        elif not _dates_equal(row["FILE_DATE"], file_src):
            repairs["FILE_DATE"] = file_src
            repairs["FILE_DATE_FLAG"] = "FIXED"

    # -- PERMIT_DATE --
    issued = _permit_date_from_tasks(tasks)
    if issued is not pd.NaT:
        if pd.isna(row["PERMIT_DATE"]):
            if effective_status in ("Active", "Final"):
                repairs["PERMIT_DATE"] = issued
                repairs["PERMIT_DATE_FLAG"] = "FILLED"
        elif not _dates_equal(row["PERMIT_DATE"], issued):
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
        # Spurious FINAL_DATE on non-Final rows.
        repairs["FINAL_DATE"] = pd.NaT
        repairs["FINAL_DATE_FLAG"] = "FIXED"


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Sacramento (city) permit records using information from the raw DATA
    JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Sacramento".  Must contain
        columns STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, FINAL_DATE,
        and DATA.

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
        (df["JURISDICTION"] == "Sacramento") & (df["STATE"] == "CA")
    ].copy()

    print(f"Sacramento records: {len(city):,}\n")

    repaired = data_repair(city)

    if AGENT_DATA_PATH:
        out_path = os.path.join(
            AGENT_DATA_PATH,
            "processed_data",
            "permits_ca_sacramento_repaired.parquet",
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

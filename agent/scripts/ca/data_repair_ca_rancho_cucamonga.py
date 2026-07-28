"""Data repair for Rancho Cucamonga (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Rancho Cucamonga DATA is an Accela Citizen Access scrape. Nearly all rows
share the same top-level keys (``status``, ``tasks``, ``search_data``,
``more_details``, ``inspections``, …); a minority lack ``tasks`` /
``inspections``. Content variants (used as INFERRED_SCHEMA) differ by
which date sources are populated:

  - accela_tasks:       dated workflow events under ``tasks``
  - accela_shell:       task shells present but no dated events
  - accela_search_only: no tasks; dates only in ``search_data`` /
                        ``more_details`` / top-level ``date``

Canonical mappings:
  - DATA.status                                      → STATUS_NORMALIZED
  - search_data['Date']; else DATA.date; else
    earliest Application Submittal event             → FILE_DATE
  - Permit Issuance / Issued; else more_details
    'Permit Issued'                                  → PERMIT_DATE
  - Inspections / Final Inspection Complete; else
    Closed / Finalized|Finalize Permit|Closed; else
    Permit Closure / Closed; else more_details
    'Permit Final' / 'Final'; else final-approved
    inspection Status Date                           → FINAL_DATE

Known issues repaired:
  - STATUS_ORIGINAL lagged DATA.status for Issued / Finalized /
    Expired / Inspection Phase rows (~19 FIXED) and 11 null
    STATUS_NORMALIZED rows FILLED (BPR Review, typos In Reivew /
    Withdrwan, Released, Fee Paid, RTI Pending, 1-YR Maint. Period).
  - PERMIT_DATE missing for Active/Final rows with Permit Issuance
    Issued or KEY DATES Permit Issued → FILLED; a few Issued dates
    that disagree with the workflow event → FIXED.
  - FINAL_DATE missing for Final rows with Closed / Permit Closure /
    Permit Final sources → FILLED; stale FINAL_DATE earlier/later
    than the best finaling event → FIXED; spurious FINAL_DATE on
    non-Final rows → cleared (FIXED).

Not repairable / left as-is:
  - Most Approved (Active) rows have no Issued event or Permit Issued
    field → PERMIT_DATE stays missing.
  - ~70–80 Final shells (esp. Finaled / Closed) lack any finaling
    workflow mark or Permit Final field → FINAL_DATE stays missing.
  - Expired / Withdrawn / Void rows may retain historical PERMIT_DATE
    values (not cleared).
"""

from __future__ import annotations

import json
import math
from typing import Optional

import numpy as np
import pandas as pd


_MIN_YEAR = 1990
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
    if isinstance(val, dict):
        return pd.NaT
    if isinstance(val, str):
        s = val.strip()
        if not s or s.upper() == "TBD":
            return pd.NaT
    try:
        dt = pd.to_datetime(val, errors="coerce")
    except (ValueError, TypeError):
        return pd.NaT
    if dt is pd.NaT or pd.isna(dt):
        return pd.NaT
    if getattr(dt, "tzinfo", None) is not None:
        dt = dt.tz_convert("UTC").tz_localize(None)
    year = int(dt.year)
    if year < _MIN_YEAR or year > _MAX_YEAR:
        return pd.NaT
    return dt


def _dates_equal(a, b) -> bool:
    da = _safe_to_datetime(a)
    db = _safe_to_datetime(b)
    if da is pd.NaT or db is pd.NaT:
        return False
    return da.normalize() == db.normalize()


def _event_field(event: dict, *names: str):
    """Read an event field, tolerating leading/trailing spaces in keys."""
    targets = {n.strip() for n in names}
    for k, v in event.items():
        if isinstance(k, str) and k.strip() in targets:
            return v
    return None


def _event_status(event: dict):
    """RC Accela events use ``Marked as``; tolerate ``status`` / ``Status``."""
    return _event_field(event, "status", "Marked as", "Status")


def _iter_tasks(tasks: list):
    for t in tasks or []:
        if not isinstance(t, dict):
            continue
        yield t
        for st in t.get("subtasks") or []:
            if isinstance(st, dict):
                yield st


def _walk_leaves(obj, prefix: str = ""):
    """Yield (path, value) for leaf values in nested dict/list structures."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            path = f"{prefix}.{k}" if prefix else str(k)
            if isinstance(v, (dict, list)):
                yield from _walk_leaves(v, path)
            else:
                yield path, v
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _walk_leaves(v, f"{prefix}[{i}]")


def _has_dated_events(d: dict) -> bool:
    for t in _iter_tasks(d.get("tasks") or []):
        for e in t.get("events") or []:
            if not isinstance(e, dict):
                continue
            if _safe_to_datetime(_event_field(e, "on")) is not pd.NaT:
                return True
    return False


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())
    if "status" not in keys:
        return "unknown"

    tasks = data_dict.get("tasks") or []
    has_tasks = isinstance(tasks, list) and len(tasks) > 0
    has_events = _has_dated_events(data_dict)

    if has_events:
        return "accela_tasks"
    if has_tasks:
        return "accela_shell"
    return "accela_search_only"


def _event_dates(tasks: list, task_names, statuses):
    """Collect event dates for matching task name(s) and status value(s)."""
    if isinstance(task_names, str):
        task_names = {task_names}
    if isinstance(statuses, str):
        statuses = {statuses}
    dates = []
    for t in _iter_tasks(tasks):
        if t.get("name") not in task_names:
            continue
        for e in t.get("events") or []:
            if not isinstance(e, dict):
                continue
            if _event_status(e) not in statuses:
                continue
            dt = _safe_to_datetime(_event_field(e, "on"))
            if dt is not pd.NaT:
                dates.append(dt)
    return dates


def _first_event_date(tasks: list, task_names, statuses):
    dates = _event_dates(tasks, task_names, statuses)
    return min(dates) if dates else pd.NaT


def _latest_event_date(tasks: list, task_names, statuses):
    dates = _event_dates(tasks, task_names, statuses)
    return max(dates) if dates else pd.NaT


def _md_date(d: dict, *labels: str):
    """First parseable more_details leaf whose key matches *labels*."""
    want = {lab.lower() for lab in labels}
    md = d.get("more_details")
    if not isinstance(md, dict):
        return pd.NaT
    for path, v in _walk_leaves(md):
        leaf = path.split(".")[-1].lower()
        if leaf in want:
            dt = _safe_to_datetime(v)
            if dt is not pd.NaT:
                return dt
    return pd.NaT


# ── Status mapping ──────────────────────────────────────────────────────────

_STATUS_MAP = {
    # Final
    "Finalized": "Final",
    "Finaled": "Final",
    "Closed": "Final",
    "Final Inspection Complete": "Final",
    "Recorded at County": "Final",
    "Temp C of O Issued": "Final",
    "Complete": "Final",
    "Released": "Final",
    "1-YR Maint. Period": "Final",
    # Active — issued / open construction / approved entitlements
    "Issued": "Active",
    "Approved": "Active",
    "Inspection Phase": "Active",
    "Pre-Inspection": "Active",
    # In Review — application / plan check / pre-issuance
    "In Review": "In Review",
    "In Reivew": "In Review",  # typo in source
    "Pending": "In Review",
    "Incomplete": "In Review",
    "Invoiced": "In Review",
    "Out for Corrections": "In Review",
    "Ready to Issue": "In Review",
    "Corrections Letter Sent": "In Review",
    "Plan Review": "In Review",
    "Accepted": "In Review",
    "Corrections": "In Review",
    "Note": "In Review",
    "RTI Pending Releases": "In Review",
    "Corrections Required": "In Review",
    "BPR Review": "In Review",
    "Fee Paid": "In Review",
    "RTI Pending": "In Review",
    "Submitted": "In Review",
    "Revisions Required": "In Review",
    # Inactive
    "Expired": "Inactive",
    "Withdrawn": "Inactive",
    "Withdrwan": "Inactive",  # typo in source
    "Void": "Inactive",
    "Inactive": "Inactive",
    "Withdrawn-Closed": "Inactive",
}


def _expected_status(d: dict) -> Optional[str]:
    """Map DATA.status → STATUS_NORMALIZED; fall back to task marks."""
    raw = d.get("status")
    if isinstance(raw, str) and raw.strip():
        mapped = _STATUS_MAP.get(raw.strip())
        if mapped is not None:
            return mapped

    marks = set()
    for t in _iter_tasks(d.get("tasks") or []):
        for e in t.get("events") or []:
            if isinstance(e, dict):
                m = _event_status(e)
                if m:
                    marks.add(m)
    if marks & {"Void", "Withdrawn", "Expired", "Withdrwan"}:
        return "Inactive"
    if marks & {
        "Finalized",
        "Finalize Permit",
        "Final Inspection Complete",
        "Finaled",
        "Final",
    }:
        return "Final"
    if "Closed" in marks and (
        any(
            t.get("name") in ("Closed", "Permit Closure")
            for t in _iter_tasks(d.get("tasks") or [])
        )
    ):
        # Closed mark on closure tasks implies Final.
        for t in _iter_tasks(d.get("tasks") or []):
            if t.get("name") not in ("Closed", "Permit Closure"):
                continue
            for e in t.get("events") or []:
                if isinstance(e, dict) and _event_status(e) == "Closed":
                    return "Final"
    if "Issued" in marks:
        return "Active"
    if marks:
        return "In Review"
    return None


def _file_date_from_data(d: dict):
    """Application / opened date."""
    sd = d.get("search_data")
    if isinstance(sd, dict):
        for key in ("Date Opened", "Date", "Application Date"):
            opened = _safe_to_datetime(sd.get(key))
            if opened is not pd.NaT:
                return opened

    top = _safe_to_datetime(d.get("date"))
    if top is not pd.NaT:
        return top

    tasks = d.get("tasks") or []
    app_dates = []
    for t in _iter_tasks(tasks):
        if t.get("name") != "Application Submittal":
            continue
        for e in t.get("events") or []:
            if not isinstance(e, dict):
                continue
            dt = _safe_to_datetime(_event_field(e, "on"))
            if dt is not pd.NaT:
                app_dates.append(dt)
    if app_dates:
        return min(app_dates)
    return pd.NaT


def _permit_date_from_data(d: dict):
    """Earliest Permit Issuance / Issued date; else KEY DATES Permit Issued."""
    tasks = d.get("tasks") or []
    issued = _first_event_date(tasks, "Permit Issuance", "Issued")
    if issued is not pd.NaT:
        return issued

    # Rare alternate issuance task names.
    issued = _first_event_date(
        tasks, {"Issue Permit", "C of O Issuance"}, {"Issued", "Temp C of O Issued"}
    )
    if issued is not pd.NaT:
        return issued

    return _md_date(d, "Permit Issued", "Issued Date", "Issue Date")


def _final_date_from_data(d: dict):
    """Best available finaling / closure / CO date."""
    tasks = d.get("tasks") or []

    for cand in (
        _latest_event_date(
            tasks, {"Inspections", "Inspection"}, "Final Inspection Complete"
        ),
        _latest_event_date(tasks, "Closed", {"Finalized", "Finalize Permit"}),
        _latest_event_date(tasks, "Permit Closure", {"Closed", "Finalized", "Complete"}),
        _latest_event_date(tasks, "Closed", {"Closed", "Complete"}),
        _latest_event_date(
            tasks,
            {"Certificate of Occupancy", "C of O Issuance"},
            {"Issued", "Final", "Finaled", "Temp C of O Issued"},
        ),
    ):
        if cand is not pd.NaT:
            return cand

    md = _md_date(d, "Permit Final", "Final", "Finaled", "Final Date", "Finaled Date")
    if md is not pd.NaT:
        return md

    # Fallback: latest approved final inspection Status Date.
    dates = []
    for item in d.get("inspections") or []:
        if not isinstance(item, dict):
            continue
        title = str(item.get("Title") or "").lower()
        status = str(item.get("Status") or "")
        if "final" not in title:
            continue
        if status not in {"Approved", "Passed", "Complete", "Final"}:
            continue
        dt = _safe_to_datetime(item.get("Status Date"))
        if dt is not pd.NaT:
            dates.append(dt)
    return max(dates) if dates else pd.NaT


# ── Repair logic ────────────────────────────────────────────────────────────

def _repair_record(row, d: dict, repairs: dict):
    # -- STATUS_NORMALIZED --
    current_status = row["STATUS_NORMALIZED"]
    expected = _expected_status(d)
    if expected is not None:
        if pd.isna(current_status):
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"
        elif current_status != expected:
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FIXED"

    effective_status = repairs.get("STATUS_NORMALIZED", current_status)

    # -- FILE_DATE --
    file_date = _file_date_from_data(d)
    if file_date is not pd.NaT:
        if pd.isna(row["FILE_DATE"]):
            repairs["FILE_DATE"] = file_date
            repairs["FILE_DATE_FLAG"] = "FILLED"
        elif not _dates_equal(row["FILE_DATE"], file_date):
            repairs["FILE_DATE"] = file_date
            repairs["FILE_DATE_FLAG"] = "FIXED"

    # -- PERMIT_DATE --
    issued = _permit_date_from_data(d)
    if not pd.isna(row["PERMIT_DATE"]):
        if issued is not pd.NaT and not _dates_equal(row["PERMIT_DATE"], issued):
            repairs["PERMIT_DATE"] = issued
            repairs["PERMIT_DATE_FLAG"] = "FIXED"
    elif effective_status in ("Active", "Final") and issued is not pd.NaT:
        repairs["PERMIT_DATE"] = issued
        repairs["PERMIT_DATE_FLAG"] = "FILLED"

    # -- FINAL_DATE --
    if effective_status == "Final":
        final_date = _final_date_from_data(d)
        if final_date is not pd.NaT:
            if pd.isna(row["FINAL_DATE"]):
                repairs["FINAL_DATE"] = final_date
                repairs["FINAL_DATE_FLAG"] = "FILLED"
            elif not _dates_equal(row["FINAL_DATE"], final_date):
                repairs["FINAL_DATE"] = final_date
                repairs["FINAL_DATE_FLAG"] = "FIXED"
    elif not pd.isna(row["FINAL_DATE"]):
        # Spurious final date on non-Final records.
        repairs["FINAL_DATE"] = pd.NaT
        repairs["FINAL_DATE_FLAG"] = "FIXED"


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Rancho Cucamonga permit records using information from the raw DATA JSON
    column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Rancho Cucamonga".  Must
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

    return out


# ── CLI: run standalone to preview repair stats ─────────────────────────────

if __name__ == "__main__":
    import os
    from dotenv import load_dotenv

    load_dotenv("/Users/ekung/projects/la-permits-data/.env")
    MY_DATA_PATH = os.getenv("MY_DATA_PATH")
    filepath = os.path.join(
        MY_DATA_PATH, "processed_data", "permits_ca_sample.parquet"
    )
    df = pd.read_parquet(filepath)
    city = df[df["JURISDICTION"] == "Rancho Cucamonga"].copy()

    print(f"Rancho Cucamonga records: {len(city):,}\n")

    repaired = data_repair(city)

    print("INFERRED_SCHEMA:")
    for s, c in repaired["INFERRED_SCHEMA"].value_counts(dropna=False).items():
        print(f"  {str(s):30s}: {c:>4,}")
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

    print("\nFILE_DATE coverage:")
    print(
        f"  Before: {city['FILE_DATE'].notna().sum():>4,} / {len(city):>4,}  "
        f"After: {repaired['FILE_DATE'].notna().sum():>4,} / {len(repaired):>4,}"
    )

    print("\nPERMIT_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["PERMIT_DATE"].notna().sum()
        pct = n_has / len(sub) if len(sub) else 0.0
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({pct:.1%})")

    print("\nFINAL_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FINAL_DATE"].notna().sum()
        pct = n_has / len(sub) if len(sub) else 0.0
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({pct:.1%})")

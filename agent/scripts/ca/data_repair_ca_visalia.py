"""Data repair for Visalia (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Visalia DATA is an Accela Citizen Access scrape. All sample rows share
the same top-level keys (``status``, ``date``, ``tasks``, ``search_data``,
``inspections``, ``more_details``, …); a minority lack ``tasks``.
Content variants (used as INFERRED_SCHEMA) differ by which date sources
are populated:

  - accela_tasks:       dated workflow events under ``tasks``
  - accela_shell:       task shells present but no dated events
                        (common on pre-~2018 converted records)
  - accela_search_only: no tasks; dates only in ``search_data`` /
                        top-level ``date``
  - unknown / missing

Canonical mappings:
  - DATA.status / search_data['Status']              → STATUS_NORMALIZED
  - search_data['Date']; else DATA.date; else
    earliest Application Submittal event             → FILE_DATE
  - Pending Issuance / Issued|Issued Deferred; else
    Permit Issuance / Issued; else
    Application Submittal / Issued|Issued Deferred   → PERMIT_DATE
  - Inspections|Inspection / Finaled|Finaled - ATMC|
    Final - ATMC; else latest approved final
    inspection Status Date (AP/Approved/PA)          → FINAL_DATE

Known issues repaired:
  - STATUS_NORMALIZED null for unmapped portal labels
    (FINALMST, Final - ATMC, Issued Deferred, CR) → FILLED.
  - PERMIT_DATE missing on Active/Final when an Issued
    workflow mark exists → FILLED.
  - FINAL_DATE missing on Final when Inspections/Finaled
    or an approved FINAL inspection exists → FILLED;
    stale FINAL_DATE that is not the latest Finaled mark
    → FIXED to the latest finaling date.
  - Spurious FINAL_DATE on non-Final rows → cleared (FIXED).

Not repairable from DATA:
  - FILE_DATE already matches search_data.Date / DATA.date for
    every sample row (0 missing, 0 mismatches).
  - Most older Final shells (accela_shell) have no Issued workflow
    event → PERMIT_DATE stays missing.
  - Some Final rows (esp. FINALMST shells) lack Finaled marks and
    approved final inspections → FINAL_DATE stays missing.
  - Issued Deferred rows are Active but not yet Issued → PERMIT_DATE
    correctly remains missing until an Issued event appears.
"""

from __future__ import annotations

import json
import math
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
    """Read an event field by *names* priority (first match wins).

    Visalia Accela events often have both ``Status`` (``Due on``) and
    ``Marked as`` (the workflow result). Callers must put ``Marked as``
    before ``Status`` when reading the workflow mark.
    """
    normalized = {k.strip(): v for k, v in event.items() if isinstance(k, str)}
    for name in names:
        if name.strip() in normalized:
            return normalized[name.strip()]
    return None


def _event_status(event: dict):
    """Visalia Accela events use ``Marked as``; tolerate ``status`` / ``Status``."""
    return _event_field(event, "Marked as", "status", "Status")

def _iter_tasks(tasks: list):
    for t in tasks or []:
        if not isinstance(t, dict):
            continue
        yield t
        for st in t.get("subtasks") or []:
            if isinstance(st, dict):
                yield st


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


# ── Status mapping ──────────────────────────────────────────────────────────

_STATUS_MAP = {
    # Final
    "FINAL": "Final",
    "Finaled": "Final",
    "FINALMST": "Final",  # master / production finaled
    "Final - ATMC": "Final",  # appears to meet code
    # Active — issued / deferred issuance / approved
    "ISSUED": "Active",
    "Issued": "Active",
    "Issued Deferred": "Active",
    "APPROVED": "Active",
    # In Review — application / plan check / pre-issuance
    "In Review": "In Review",
    "Ready to Issue": "In Review",
    "Pending Resubmittal": "In Review",
    "Pending Issuance": "In Review",
    "CR": "In Review",  # rare unlabeled code; applied-only shell
    # Inactive
    "Expired": "Inactive",
    "EXPIRED": "Inactive",
    "Permit Expired": "Inactive",
    "CANCEL": "Inactive",
    "Withdrawn": "Inactive",
    "Closed - Withdrawn": "Inactive",
    "WITHDRWN": "Inactive",
    "Void": "Inactive",
    "DENIED": "Inactive",
    "Denied": "Inactive",
}

_ISSUED_MARKS = {"Issued", "Issued Deferred"}
_FINALED_MARKS = {"Finaled", "Finaled - ATMC", "Final - ATMC"}
_APPROVED_INSP = {"AP", "Approved", "PA"}  # PA = legacy pass/approved code


def _expected_status(d: dict) -> Optional[str]:
    """Map DATA.status → STATUS_NORMALIZED; fall back to task marks."""
    raw = d.get("status")
    if isinstance(raw, str) and raw.strip():
        mapped = _STATUS_MAP.get(raw.strip())
        if mapped is not None:
            return mapped

    sd = d.get("search_data")
    if isinstance(sd, dict):
        sd_status = sd.get("Status")
        if isinstance(sd_status, str) and sd_status.strip():
            mapped = _STATUS_MAP.get(sd_status.strip())
            if mapped is not None:
                return mapped

    marks = set()
    for t in _iter_tasks(d.get("tasks") or []):
        for e in t.get("events") or []:
            if isinstance(e, dict):
                m = _event_status(e)
                if m:
                    marks.add(m)

    if marks & {"Void", "Withdrawn", "Expired", "Denied", "CANCEL"}:
        return "Inactive"
    if marks & _FINALED_MARKS:
        return "Final"
    if marks & _ISSUED_MARKS:
        return "Active"
    if marks - {"TBD"}:
        return "In Review"
    return None


def _file_date_from_data(d: dict):
    """Application / opened date."""
    sd = d.get("search_data")
    if isinstance(sd, dict):
        for key in ("Date", "Date Opened", "Application Date"):
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
    """Earliest issuance workflow date."""
    tasks = d.get("tasks") or []

    for task_names in (
        "Pending Issuance",
        "Permit Issuance",
        "Application Submittal",
    ):
        issued = _first_event_date(tasks, task_names, _ISSUED_MARKS)
        if issued is not pd.NaT:
            return issued
    return pd.NaT


def _final_insp_date(d: dict):
    """Latest approved inspection whose Title contains FINAL."""
    dates = []
    for item in d.get("inspections") or []:
        if not isinstance(item, dict):
            continue
        title = str(item.get("Title") or "")
        if "FINAL" not in title.upper():
            continue
        status = str(item.get("Status") or "")
        if status not in _APPROVED_INSP:
            continue
        dt = _safe_to_datetime(item.get("Status Date"))
        if dt is not pd.NaT:
            dates.append(dt)
    return max(dates) if dates else pd.NaT


def _final_date_from_data(d: dict):
    """Best available finaling / sign-off date."""
    tasks = d.get("tasks") or []

    finaled = _latest_event_date(
        tasks, {"Inspections", "Inspection"}, _FINALED_MARKS
    )
    if finaled is not pd.NaT:
        return finaled

    return _final_insp_date(d)


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
    Visalia permit records using information from the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Visalia".  Must contain
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

    # Normalize date columns to datetime64 so parquet write succeeds even
    # when some cells were overwritten with Timestamps amid object/None.
    for col in ("FILE_DATE", "PERMIT_DATE", "FINAL_DATE"):
        if col in out.columns:
            out[col] = pd.to_datetime(out[col], errors="coerce")

    return out


# ── CLI: run standalone to preview repair stats ─────────────────────────────

if __name__ == "__main__":
    import os
    from pathlib import Path

    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[3] / ".env")
    MY_DATA_PATH = os.getenv("MY_DATA_PATH")
    AGENT_DATA_PATH = os.getenv("AGENT_DATA_PATH")
    filepath = os.path.join(
        MY_DATA_PATH, "processed_data", "permits_ca_sample.parquet"
    )
    df = pd.read_parquet(filepath)
    city = df[df["JURISDICTION"] == "Visalia"].copy()

    print(f"Visalia records: {len(city):,}\n")

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

    print("\nFINAL_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FINAL_DATE"].notna().sum()
        n = len(sub)
        pct = n_has / n if n else 0.0
        print(f"  {status:15s}: {n_has:>4,} / {n:>4,} ({pct:.1%})")

    print("\nPERMIT_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["PERMIT_DATE"].notna().sum()
        n = len(sub)
        pct = n_has / n if n else 0.0
        print(f"  {status:15s}: {n_has:>4,} / {n:>4,} ({pct:.1%})")

    # Chronology checks
    fd = pd.to_datetime(repaired["FILE_DATE"], errors="coerce")
    pd_ = pd.to_datetime(repaired["PERMIT_DATE"], errors="coerce")
    ff = pd.to_datetime(repaired["FINAL_DATE"], errors="coerce")
    both_fp = fd.notna() & pd_.notna()
    both_pf = pd_.notna() & ff.notna()
    print("\nChronology inversions:")
    print(f"  FILE > PERMIT: {(both_fp & (fd > pd_)).sum()}")
    print(f"  PERMIT > FINAL: {(both_pf & (pd_ > ff)).sum()}")

    if AGENT_DATA_PATH:
        out_dir = Path(AGENT_DATA_PATH) / "repaired"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "permits_ca_visalia_repaired.parquet"
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote {out_path}")

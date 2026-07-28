"""Data repair for Ontario (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Ontario DATA is an Accela Citizen Access scrape. All rows share the same
top-level keys (``status``, ``tasks``, ``search_data``, ``more_details``,
…); a minority also carry ``attachments`` / unpaid-fee keys. Content
variants (used as INFERRED_SCHEMA) differ by which date sources are
populated:

  - accela_tasks:       dated workflow events under ``tasks``
  - accela_shell:       task shells present but no dated events
  - accela_search_only: no tasks; dates only in ``search_data``
    (or empty stubs with only top-level status)

Canonical mappings:
  - DATA.status                              → STATUS_NORMALIZED
  - search_data['Date Opened']; else earliest
    Application Submittal event; else
    parseable DATA.date                      → FILE_DATE
  - Issue Permit / Issued (or Marked as)     → PERMIT_DATE
  - Construction / Final|Finaled|CO Issued   → FINAL_DATE

Known issues repaired:
  - STATUS_ORIGINAL lagged DATA.status for Issued / Final / Under Review /
    OTC rows (~8 FIXED) and 2 null STATUS_NORMALIZED rows FILLED
    (Plan Check Fees Invoiced; empty-status shell → In Review).
  - FILE_DATE missing on ~96% of rows despite Date Opened in search_data
    → FILLED.
  - PERMIT_DATE missing for Active/Final rows with Issue Permit / Issued
    events → FILLED.
  - FINAL_DATE missing for Final rows with Construction Final/Finaled/
    CO Issued events → FILLED; stale FINAL_DATE earlier than Construction
    finaling event → FIXED.

Not repairable / left as-is:
  - Hundreds of legacy Final / Issued shells have empty or absent task
    events → PERMIT_DATE / FINAL_DATE stay missing.
  - A few recent attachment scrapes lack Date Opened and a parseable
    DATA.date → FILE_DATE stays missing when already null.
  - Expired / Withdrawn / Ready to Issue rows may retain historical
    PERMIT_DATE values (not cleared).
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
        # Accela template junk, e.g. {'B{year:04}{idx:05}': [2025, 7769]}
        return pd.NaT
    if isinstance(val, str):
        s = val.strip()
        if not s or s.upper() == "TBD":
            return pd.NaT
        # Permit IDs sometimes land in DATA.date (e.g. B200002515).
        if len(s) >= 2 and s[0].isalpha() and s[1:].isdigit():
            return pd.NaT
    try:
        dt = pd.to_datetime(val)
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
    """Ontario events use ``status``; newer scrapes use ``Marked as``."""
    return _event_field(event, "status", "Marked as", "Status")


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
    # No task shells: legacy / thin Accela rows driven by search_data
    # (or an empty stub with only top-level status).
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
    "Final": "Final",
    "Finaled": "Final",
    # Active — issued / open construction
    "Issued": "Active",
    "Active": "Active",
    # In Review — application / plan check / OTC pathway / pre-issuance
    "Under Review": "In Review",
    "OTC": "In Review",
    "Applied": "In Review",
    "Ready to Issue": "In Review",
    "In P/R": "In Review",
    "Plan Check Fees Invoiced": "In Review",
    # Inactive
    "Expired": "Inactive",
    "Void": "Inactive",
    "Withdrawn": "Inactive",
}


def _expected_status(d: dict) -> Optional[str]:
    """Map DATA.status → STATUS_NORMALIZED; fall back to task marks."""
    raw = d.get("status")
    if isinstance(raw, str) and raw.strip():
        return _STATUS_MAP.get(raw.strip())

    # Null / empty status: infer from workflow marks when present.
    marks = set()
    for t in _iter_tasks(d.get("tasks") or []):
        for e in t.get("events") or []:
            if isinstance(e, dict):
                m = _event_status(e)
                if m:
                    marks.add(m)
    if "Void" in marks or "Withdrawn" in marks or "Expired" in marks:
        return "Inactive"
    if "Final" in marks or "Finaled" in marks or "CO Issued" in marks:
        return "Final"
    if "Issued" in marks:
        return "Active"
    if marks:
        return "In Review"
    # Empty shell with no usable marks — treat as still in process.
    return "In Review"


def _file_date_from_data(d: dict):
    """Application / opened date."""
    sd = d.get("search_data")
    if isinstance(sd, dict):
        opened = _safe_to_datetime(sd.get("Date Opened"))
        if opened is not pd.NaT:
            return opened

    # Earliest dated Application Submittal event (OTC / Accepted / …).
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

    return _safe_to_datetime(d.get("date"))


def _permit_date_from_data(d: dict):
    """Earliest Issue Permit / Issued date."""
    tasks = d.get("tasks") or []
    issued = _first_event_date(tasks, "Issue Permit", "Issued")
    if issued is not pd.NaT:
        return issued

    # Any Issued mark elsewhere (rare).
    dates = []
    for t in _iter_tasks(tasks):
        for e in t.get("events") or []:
            if not isinstance(e, dict):
                continue
            if _event_status(e) != "Issued":
                continue
            dt = _safe_to_datetime(_event_field(e, "on"))
            if dt is not pd.NaT:
                dates.append(dt)
    return min(dates) if dates else pd.NaT


def _final_date_from_data(d: dict):
    """Best available finaling / CO date from Construction events."""
    tasks = d.get("tasks") or []
    finaled = _latest_event_date(
        tasks, "Construction", {"Final", "Finaled", "CO Issued"}
    )
    if finaled is not pd.NaT:
        return finaled

    # Fallback: any Final / Finaled / CO Issued mark on other tasks.
    dates = []
    for t in _iter_tasks(tasks):
        for e in t.get("events") or []:
            if not isinstance(e, dict):
                continue
            if _event_status(e) not in {"Final", "Finaled", "CO Issued"}:
                continue
            dt = _safe_to_datetime(_event_field(e, "on"))
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
        if (
            issued is not pd.NaT
            and not _dates_equal(row["PERMIT_DATE"], issued)
        ):
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
    Ontario permit records using information from the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Ontario".  Must contain
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
    city = df[df["JURISDICTION"] == "Ontario"].copy()

    print(f"Ontario records: {len(city):,}\n")

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

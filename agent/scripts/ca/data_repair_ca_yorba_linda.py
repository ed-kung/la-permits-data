"""Data repair for Yorba Linda (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Yorba Linda DATA is an Accela Citizen Access scrape. Sample rows share
the same top-level keys (``status``, ``date``, ``tasks``, ``inspections``,
``search_data``, ``more_details``, …). Content variants (INFERRED_SCHEMA):

  - accela_tasks: dated workflow events under ``tasks``
  - accela_shell: task shells present but no dated events
  - accela_search_only: only ``search_data`` populated (TMP solar shells)
  - unknown / missing

Canonical mappings:
  - DATA.status / search_data['Status'] (+ Final Inspection upgrade)
                                                      → STATUS_NORMALIZED
  - search_data['Date'] / valid DATA.date /
    Application Submittal|Accepted*                   → FILE_DATE
  - Permit Issuance|Issued / Permit Issued            → PERMIT_DATE
  - Inspections|Final Inspection Complete
    (else Complete|Close for Finaled/Closed only)     → FINAL_DATE

Known issues repaired:
  - Approved incorrectly mapped to Active (no issuance)
    → FIXED to In Review.
  - Transfer / Code Enforcement with issuance left as
    In Review → FIXED to Active; Final Inspection
    Complete → FIXED to Final.
  - Expired / Issued rows that already carry Final
    Inspection Complete → FIXED to Final.
  - FILE_DATE missing on most rows though Application
    Submittal Accepted (or search_data.Date) exists
    → FILLED. Top-level DATA.date is often a record id
    (YL-*), not a date — ignored unless parseable.
  - Spurious FINAL_DATE from Pre-Site Inspection Completed
    on still-Issued / Transfer rows (often FINAL < PERMIT)
    → cleared (FIXED) unless status upgrades to Final.
  - Finaled missing FINAL_DATE when Final Inspection
    Complete or Complete|Close exists → FILLED.
  - Active/Final missing PERMIT_DATE when Permit Issuance
    Issued exists → FILLED.

Not repairable from DATA:
  - ~4 TMP solar shells with blank Status →
    STATUS_NORMALIZED stays missing.
  - ~12 shells with no Application Submittal date and no
    search_data.Date → FILE_DATE stays missing.
  - Finaled rows with only TBD inspection shells and no
    Close / Final Inspection marks → FINAL_DATE stays
    missing.
  - Complete|Close alone is NOT treated as final evidence
    for status upgrades (fires on expired Issued permits
    and even before issuance).
"""

from __future__ import annotations

import json
import math
from typing import Optional

import numpy as np
import pandas as pd


_MIN_YEAR = 1900
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
        # Yorba Linda often puts record ids (YL-0074960) in DATA.date
        if s.upper().startswith("YL-"):
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
    """Read an event field by *names* priority (first match wins)."""
    if not isinstance(event, dict):
        return None
    normalized = {k.strip(): v for k, v in event.items() if isinstance(k, str)}
    for name in names:
        if name.strip() in normalized:
            return normalized[name.strip()]
    return None


def _event_status(event: dict):
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
    if keys <= {"search_data"} and "search_data" in keys:
        return "accela_search_only"
    if "status" not in keys and "search_data" not in keys:
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
    statuses_l = {s.lower() for s in statuses}
    dates = []
    for t in _iter_tasks(tasks):
        if t.get("name") not in task_names:
            continue
        for e in t.get("events") or []:
            if not isinstance(e, dict):
                continue
            mark = _event_status(e)
            if not isinstance(mark, str) or mark.strip().lower() not in statuses_l:
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
    "Finaled": "Final",
    "Closed": "Final",
    "Final": "Final",
    "Completed": "Final",
    # Active
    "Issued": "Active",
    "Permit Issued": "Active",
    "Renewed": "Active",
    "Code Enforcement": "Active",
    # In Review — includes values previously mis-mapped
    "Approved": "In Review",
    "In Plan Check": "In Review",
    "Pending": "In Review",
    "Transfer": "In Review",
    "Applied": "In Review",
    "In Review": "In Review",
    # Inactive
    "Expired": "Inactive",
    "Void": "Inactive",
    "Withdrawn": "Inactive",
}

_APP_ACCEPT_MARKS = {
    "Accepted",
    "Accepted - No Pre-App",
    "Accepted - Pre-App",
}

_ISSUANCE_MARKS = {
    "Issued",
    "Permit Issued",
}

_FINAL_INSPECTION_MARKS = {
    "Final Inspection Complete",
    "Finaled",
    "Final",
    "Work Complete",
}

_FINAL_CLOSE_MARKS = {
    "Close",
    "Closed",
    "Complete",
    "Completed",
    "Finaled",
}


def _raw_status(d: dict) -> Optional[str]:
    raw = d.get("status")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    sd = d.get("search_data")
    if isinstance(sd, dict):
        sd_status = sd.get("Status")
        if isinstance(sd_status, str) and sd_status.strip():
            return sd_status.strip()
    return None


def _map_raw_status(raw: str) -> Optional[str]:
    mapped = _STATUS_MAP.get(raw)
    if mapped is not None:
        return mapped
    for k, v in _STATUS_MAP.items():
        if k.lower() == raw.lower():
            return v
    return None


def _has_final_inspection(d: dict) -> bool:
    tasks = d.get("tasks") or []
    return bool(_event_dates(tasks, {"Inspections", "Inspection"}, _FINAL_INSPECTION_MARKS))


def _expected_status(d: dict) -> Optional[str]:
    """Map DATA.status → STATUS_NORMALIZED, upgrading on final inspection."""
    raw = _raw_status(d)
    mapped = _map_raw_status(raw) if raw else None

    # Final Inspection Complete is decisive even over Expired / Issued /
    # Transfer / Code Enforcement. Void / Withdrawn stay Inactive.
    if mapped == "Inactive" and raw and raw.lower() in ("void", "withdrawn"):
        return mapped

    if _has_final_inspection(d):
        return "Final"

    # Transfer with issuance (but no final) → Active
    if raw and raw.lower() == "transfer" and _has_issuance_evidence(d):
        return "Active"

    return mapped


def _file_date_from_data(d: dict):
    """Application / opened date.

    Prefer Accela search_data.Date (opened / submitted), then a parseable
    top-level DATA.date, then the earliest Application Submittal Accepted
    mark (staff acceptance can lag the opened date by a few days).
    """
    sd = d.get("search_data")
    if isinstance(sd, dict):
        for key in ("Date", "Submitted Date", "Date Opened", "Application Date"):
            opened = _safe_to_datetime(sd.get(key))
            if opened is not pd.NaT:
                return opened

    top = _safe_to_datetime(d.get("date"))
    if top is not pd.NaT:
        return top

    tasks = d.get("tasks") or []
    accepted = _first_event_date(tasks, {"Application Submittal"}, _APP_ACCEPT_MARKS)
    if accepted is not pd.NaT:
        return accepted
    return pd.NaT


def _permit_date_from_data(d: dict):
    """Earliest Permit Issuance Issued / Permit Issued date."""
    tasks = d.get("tasks") or []
    return _first_event_date(
        tasks, {"Permit Issuance", "Issuance", "Permit Issued"}, _ISSUANCE_MARKS
    )


def _has_issuance_evidence(d: dict) -> bool:
    return _permit_date_from_data(d) is not pd.NaT


def _final_date_from_data(d: dict, on_or_after=None, allow_close_fallback: bool = False):
    """Best finaling / sign-off date.

    Prefer Inspections|Final Inspection Complete. Complete|Close is only
    used as a fallback for records already known to be Finaled/Closed,
    because Close also fires on expired Issued permits and sometimes
    before issuance.
    """
    tasks = d.get("tasks") or []
    candidates = []

    insp = _event_dates(tasks, {"Inspections", "Inspection"}, _FINAL_INSPECTION_MARKS)
    if insp:
        candidates.append(max(insp))

    if not candidates and allow_close_fallback:
        close = _event_dates(tasks, {"Complete", "Closed", "Closure"}, _FINAL_CLOSE_MARKS)
        if close:
            candidates.append(max(close))

    if not candidates:
        return pd.NaT

    floor = _safe_to_datetime(on_or_after)
    if floor is not pd.NaT:
        filtered = [dt for dt in candidates if dt.normalize() >= floor.normalize()]
        if filtered:
            candidates = filtered
        elif insp:
            # Keep inspection final even if it somehow precedes permit
            candidates = [max(insp)]
        else:
            return pd.NaT
    return max(candidates)


# ── Repair logic ────────────────────────────────────────────────────────────

def _repair_record(row, d: dict, repairs: dict):
    raw = _raw_status(d)

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
    current_permit = row["PERMIT_DATE"]
    if not pd.isna(current_permit):
        if issued is not pd.NaT and not _dates_equal(current_permit, issued):
            repairs["PERMIT_DATE"] = issued
            repairs["PERMIT_DATE_FLAG"] = "FIXED"
        elif (
            effective_status == "In Review"
            and not _has_issuance_evidence(d)
        ):
            repairs["PERMIT_DATE"] = pd.NaT
            repairs["PERMIT_DATE_FLAG"] = "FIXED"
    elif effective_status in ("Active", "Final") and issued is not pd.NaT:
        repairs["PERMIT_DATE"] = issued
        repairs["PERMIT_DATE_FLAG"] = "FILLED"

    # -- FINAL_DATE --
    raw_l = (raw or "").lower()
    allow_close = raw_l in ("finaled", "closed", "final", "completed")
    if effective_status == "Final":
        permit_for_final = repairs.get("PERMIT_DATE", row["PERMIT_DATE"])
        final_date = _final_date_from_data(
            d, on_or_after=permit_for_final, allow_close_fallback=allow_close
        )
        if final_date is not pd.NaT:
            if pd.isna(row["FINAL_DATE"]):
                repairs["FINAL_DATE"] = final_date
                repairs["FINAL_DATE_FLAG"] = "FILLED"
            elif not _dates_equal(row["FINAL_DATE"], final_date):
                repairs["FINAL_DATE"] = final_date
                repairs["FINAL_DATE_FLAG"] = "FIXED"
    elif not pd.isna(row["FINAL_DATE"]):
        # Clear spurious finals (commonly Pre-Site Inspection Completed
        # dates on still-Issued / Transfer rows where FINAL < PERMIT).
        repairs["FINAL_DATE"] = pd.NaT
        repairs["FINAL_DATE_FLAG"] = "FIXED"


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Yorba Linda permit records using the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Yorba Linda".  Must contain
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
    AGENT_DATA_PATH = os.getenv("AGENT_DATA_PATH")
    filepath = os.path.join(
        MY_DATA_PATH, "processed_data", "permits_ca_sample.parquet"
    )
    df = pd.read_parquet(filepath)
    yl = df[df["JURISDICTION"] == "Yorba Linda"].copy()

    print(f"Yorba Linda records: {len(yl):,}\n")

    repaired = data_repair(yl)

    print("INFERRED_SCHEMA:")
    print(repaired["INFERRED_SCHEMA"].value_counts(dropna=False).to_string())
    print()

    for field in ["STATUS_NORMALIZED", "FILE_DATE", "PERMIT_DATE", "FINAL_DATE"]:
        flag_col = f"{field}_FLAG"
        n_filled = (repaired[flag_col] == "FILLED").sum()
        n_fixed = (repaired[flag_col] == "FIXED").sum()
        print(f"{field}:")
        print(f"  FILLED: {n_filled:>4,}   FIXED: {n_fixed:>4,}")

        before_missing = yl[field].isna().sum()
        after_missing = repaired[field].isna().sum()
        print(
            f"  Missing before: {before_missing:>4,}   "
            f"Missing after: {after_missing:>4,}"
        )
        print()

    print("STATUS_NORMALIZED distribution:")
    print("  Before:")
    for s, c in yl["STATUS_NORMALIZED"].value_counts(dropna=False).items():
        print(f"    {str(s):15s}: {c:>4,}")
    print("  After:")
    for s, c in repaired["STATUS_NORMALIZED"].value_counts(dropna=False).items():
        print(f"    {str(s):15s}: {c:>4,}")

    print("\nFINAL_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FINAL_DATE"].notna().sum()
        print(
            f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} "
            f"({n_has / len(sub) if len(sub) else 0:.1%})"
        )

    print("\nPERMIT_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["PERMIT_DATE"].notna().sum()
        print(
            f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} "
            f"({n_has / len(sub) if len(sub) else 0:.1%})"
        )

    print("\nFILE_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FILE_DATE"].notna().sum()
        print(
            f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} "
            f"({n_has / len(sub) if len(sub) else 0:.1%})"
        )

    # Chronology checks
    bad_pf = bad_fp = 0
    for idx in repaired.index:
        f = _safe_to_datetime(repaired.at[idx, "FILE_DATE"])
        p = _safe_to_datetime(repaired.at[idx, "PERMIT_DATE"])
        fin = _safe_to_datetime(repaired.at[idx, "FINAL_DATE"])
        if f is not pd.NaT and p is not pd.NaT and p.normalize() < f.normalize():
            bad_pf += 1
        if p is not pd.NaT and fin is not pd.NaT and fin.normalize() < p.normalize():
            bad_fp += 1
    print(f"\nChronology: PERMIT<FILE={bad_pf}  FINAL<PERMIT={bad_fp}")

    if AGENT_DATA_PATH:
        out_path = os.path.join(
            AGENT_DATA_PATH, "yorba_linda_repaired_sample.parquet"
        )
        to_write = repaired.copy()
        for col in ("FILE_DATE", "PERMIT_DATE", "FINAL_DATE"):
            to_write[col] = pd.to_datetime(to_write[col], errors="coerce")
        to_write.to_parquet(out_path, index=False)
        print(f"\nWrote repaired sample to {out_path}")

"""Data repair for Palo Alto (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Palo Alto DATA is an Accela Citizen Access scrape. Sample rows share the
same top-level keys (``status``, ``date``, ``tasks``, ``search_data``,
``inspections``, …). Content variants (used as INFERRED_SCHEMA):

  - accela_tasks:       dated workflow events under ``tasks``
  - accela_shell:       task shells present but no dated events
                        (common on older converted records with blank Status)
  - accela_search_only: no tasks; dates only in ``search_data`` /
                        top-level ``date``
  - unknown / missing

Canonical mappings:
  - DATA.status / search_data['Status']; else workflow / inspection
    marks                                                → STATUS_NORMALIZED
  - DATA.date / search_data['Date']; else earliest
    Application Submittal event                          → FILE_DATE
  - Permit Issuance / Permit Issued|Issued; else
    Ready To Issue / Approved|Ready to Issue; else
    Approval / Approved*                                 → PERMIT_DATE
  - Inspection task Finaled|Final Approved|Complete; else
    inspections with Final* status or final-titled
    Approved/Passed                                      → FINAL_DATE

Known issues repaired:
  - STATUS_NORMALIZED null when DATA.status is blank on older Accela
    conversions → FILLED from Permit Issued / final inspection / other
    marks (or left missing if uninferable).
  - STATUS_NORMALIZED null for Approved Inspection Required, Meeting
    Scheduled, Over the Counter Approved, Decision Effective → FILLED.
  - Stale STATUS_NORMALIZED (Approved With Conditions / FIR|PLN|WGW
    Approved labeled In Review; Not Required labeled In Review) → FIXED.
  - PERMIT_DATE set to Fees Paid instead of Issued → FIXED.
  - PERMIT_DATE missing on Active/Final when Ready To Issue / Approval
    marks exist → FILLED.
  - FINAL_DATE almost always missing on Finaled → FILLED from final
    inspections (title or status).

Not repairable from DATA:
  - FILE_DATE already matches DATA.date for every sample row.
  - Many Active ``Permit Issued`` shells have empty task events →
    PERMIT_DATE stays missing.
  - A few Final / Closed records lack issuance and final inspection
    marks → dates stay missing.
  - Blank-Status shells with no dated events / inspections remain
    STATUS_NORMALIZED missing.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
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
    """Read an event field by *names* priority (first match wins)."""
    normalized = {k.strip(): v for k, v in event.items() if isinstance(k, str)}
    for name in names:
        if name.strip() in normalized:
            return normalized[name.strip()]
    return None


def _event_status(event: dict):
    """Accela events use ``Marked as``; tolerate ``status`` / ``Status``."""
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


def _collect_marks(d: dict) -> set:
    marks = set()
    for t in _iter_tasks(d.get("tasks") or []):
        for e in t.get("events") or []:
            if isinstance(e, dict):
                m = _event_status(e)
                if isinstance(m, str) and m.strip():
                    marks.add(m.strip())
    return marks


# ── Status mapping ──────────────────────────────────────────────────────────

_STATUS_MAP = {
    # Final
    "Finaled": "Final",
    "Complete": "Final",
    "Closed": "Final",
    # Active — issued / approved / inspection phase
    "Permit Issued": "Active",
    "Issued": "Active",
    "Approved": "Active",
    "Approved Inspection Required": "Active",
    "GB - Appd Inspection Required": "Active",
    "FIR - Approved": "Active",
    "PLN - Approved": "Active",
    "WGW - Approved": "Active",
    "Approved With Conditions": "Active",
    "Over the Counter Approved": "Active",
    "Active": "Active",
    "Decision Effective": "Active",
    # In Review
    "Pending Resubmittal": "In Review",
    "In Plan Check": "In Review",
    "In Review": "In Review",
    "Under Review": "In Review",
    "Incomplete": "In Review",
    "Meeting Scheduled": "In Review",
    "Submitted": "In Review",
    "Ready to Issue": "In Review",
    "Open": "In Review",
    "FIR - Routed": "In Review",
    # Inactive
    "Expired": "Inactive",
    "Permit Expired": "Inactive",
    "VOID": "Inactive",
    "Void": "Inactive",
    "BLD - Not Required": "Inactive",
    "FIR - Not Required": "Inactive",
}

_ISSUED_MARKS = {
    "Permit Issued",
    "Issued",
    "Permit Issued Mitigation Required",
}
_RTI_MARKS = {"Approved", "Ready to Issue"}
_APPROVAL_MARKS = {
    "Approved",
    "Approved - Emailed",
    "Approved With Conditions",
}
_FINAL_TASK_MARKS = {"Finaled", "Final Approved", "Complete", "Final Approval"}
_FINAL_INSP_STATUSES = {
    "Final Approval",
    "Approved - Final",
    "Final Approved",
    "Finaled",
}
_FINAL_INSP_OK = {
    "Approved",
    "Final Approval",
    "Approved - Final",
    "Final Approved",
    "Passed",
    "Complete",
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


def _has_final_inspection(d: dict) -> bool:
    return _final_date_from_inspections(d) is not pd.NaT


def _expected_status(d: dict) -> Optional[str]:
    """Map DATA.status → STATUS_NORMALIZED; fall back via workflow marks."""
    raw = _raw_status(d)
    if raw is not None:
        mapped = _STATUS_MAP.get(raw)
        if mapped is not None:
            return mapped
        for k, v in _STATUS_MAP.items():
            if k.lower() == raw.lower():
                return v

    marks = _collect_marks(d)
    marks_l = {m.lower() for m in marks}

    if any(
        tok in m
        for m in marks_l
        for tok in ("void", "expired", "cancelled")
    ):
        return "Inactive"
    if marks & _FINAL_TASK_MARKS or _has_final_inspection(d):
        return "Final"
    if marks & _ISSUED_MARKS:
        return "Active"
    if marks - {"TBD"}:
        return "In Review"
    return None


def _file_date_from_data(d: dict):
    """Application / submitted date."""
    top = _safe_to_datetime(d.get("date"))
    if top is not pd.NaT:
        return top

    sd = d.get("search_data")
    if isinstance(sd, dict):
        for key in ("Date", "Submitted Date", "Date Opened", "Application Date"):
            opened = _safe_to_datetime(sd.get(key))
            if opened is not pd.NaT:
                return opened

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
    """Earliest true issuance (or approval) workflow date."""
    tasks = d.get("tasks") or []

    for task_names, statuses in (
        ("Permit Issuance", _ISSUED_MARKS),
        ("Ready To Issue", _RTI_MARKS),
        ("Approval", _APPROVAL_MARKS),
        ("Revision Complete", {"Ready to Issue"}),
    ):
        issued = _first_event_date(tasks, task_names, statuses)
        if issued is not pd.NaT:
            return issued
    return pd.NaT


def _final_date_from_inspections(d: dict, on_or_after=None):
    """Latest inspection date that indicates finaling / sign-off.

    When *on_or_after* is set (typically PERMIT_DATE), only accept finals
    on/after that date so optional finals from a prior cycle do not precede
    issuance. Returns NaT if none qualify under that floor.
    """
    dates = []
    for item in d.get("inspections") or []:
        if not isinstance(item, dict):
            continue
        st = item.get("Status")
        if not isinstance(st, str):
            continue
        st = st.strip()
        title = item.get("Title") or ""
        title_l = title.lower() if isinstance(title, str) else ""
        is_final_status = st in _FINAL_INSP_STATUSES
        is_final_title = "final" in title_l and st in _FINAL_INSP_OK
        if is_final_status or is_final_title:
            dt = _safe_to_datetime(item.get("Status Date"))
            if dt is not pd.NaT:
                dates.append(dt)
    if not dates:
        return pd.NaT
    floor = _safe_to_datetime(on_or_after)
    if floor is not pd.NaT:
        dates = [dt for dt in dates if dt.normalize() >= floor.normalize()]
        if not dates:
            return pd.NaT
    return max(dates)


def _final_date_from_data(d: dict, on_or_after=None):
    """Best available finaling / sign-off date."""
    tasks = d.get("tasks") or []
    task_final = _latest_event_date(
        tasks, {"Inspection", "Final Permit Status"}, _FINAL_TASK_MARKS
    )
    insp_final = _final_date_from_inspections(d, on_or_after=on_or_after)
    candidates = [c for c in (task_final, insp_final) if c is not pd.NaT]
    floor = _safe_to_datetime(on_or_after)
    if floor is not pd.NaT:
        candidates = [
            c for c in candidates if c.normalize() >= floor.normalize()
        ]
    return max(candidates) if candidates else pd.NaT


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
        permit_for_final = repairs.get("PERMIT_DATE", row["PERMIT_DATE"])
        final_date = _final_date_from_data(d, on_or_after=permit_for_final)
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
    Palo Alto permit records using information from the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Palo Alto".  Must contain
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

    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[3] / ".env")
    MY_DATA_PATH = os.getenv("MY_DATA_PATH")
    AGENT_DATA_PATH = os.getenv("AGENT_DATA_PATH")
    filepath = os.path.join(
        MY_DATA_PATH, "processed_data", "permits_ca_sample.parquet"
    )
    df = pd.read_parquet(filepath)
    city = df[df["JURISDICTION"] == "Palo Alto"].copy()

    print(f"Palo Alto records: {len(city):,}\n")

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
        out_path = out_dir / "permits_ca_palo_alto_repaired.parquet"
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote {out_path}")

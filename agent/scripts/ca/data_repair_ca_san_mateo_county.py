"""Data repair for San Mateo County (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

San Mateo County DATA is an Accela Citizen Access scrape. All sample rows
share the same top-level keys (status / date / tasks / search_data /
inspections / …). INFERRED_SCHEMA distinguishes workflow richness:

  - tasks_ready_to_issue: Ready to Issue* tasks present (building)
  - tasks_dpw:            Application Submitted + Final Processing
  - tasks_other:          other task trees with dated events
  - tasks_empty_events:   tasks present but no usable dated events
  - header_only:          status/date/search_data only
  - unknown / missing

Canonical mappings:
  - DATA.status (= search_data Status)     → STATUS_NORMALIZED
      (upgrade Active / In Review → Final when a finalization
       task/inspection signal is present; Inactive terminals win)
  - DATA.date / search_data Date|
    Date Submitted                         → FILE_DATE
  - Ready to Issue*|Issued|Permit Issued|
    Permit Re-Issued|Revision Issued
    else Application Submitted|Permit Issued
    else Application Submittal|Issued
    else Enforcement|Permit Issued         → PERMIT_DATE (earliest
                                              within best tier)
  - Inspections|Finaled|Final Processing|
    Final Certificate of Occupancy (latest)
    else Final Processing / Project Close
    Out|Closed|Finaled|Recorded|
    Permit Finaled
    else closeout|Workflow Closed
    else Enforcement/Investigation|Finaled
    else Final* inspection Pass            → FINAL_DATE

Known issues repaired:
  - 81 blank / unmapped STATUS_NORMALIZED rows (Confirmation shells,
    ACA Update, Map Check, Project Closeout, …) → FILLED from
    DATA.status or In Review default for empty Confirmation shells.
  - Stale STATUS_NORMALIZED vs DATA.status (Finaled mislabeled Active /
    In Review / Inactive; Issued mislabeled In Review; Expired
    mislabeled Active) → FIXED.
  - Active / In Review with Inspections Finaled / Final Processing
    Closed signals → Final.
  - PERMIT_DATE missing on Active/Final when issuance task events exist
    (DPW Application Submitted / Permit Issued; OTC Application
    Submittal / Issued) → FILLED.
  - PERMIT_DATE set to Ready Letter / plan-prep dates instead of later
    Permit Issued → FIXED to true issuance.
  - FINAL_DATE missing on Final when Final Processing Recorded/Closed
    or Workflow Closed exists → FILLED.
  - FINAL_DATE using an earlier Finaled when a later Finaled / Final
    Certificate of Occupancy exists → FIXED to latest.
  - Spurious FINAL_DATE on non-Final rows → cleared (FIXED).

Not repairable from DATA:
  - FILE_DATE already matches DATA.date for every sample row.
  - Hundreds of Finaled lean shells have empty task events →
    PERMIT_DATE / FINAL_DATE stay missing despite Final status.
  - Confirmation shells with blank Status and TBD-only events stay
    In Review with no PERMIT_DATE / FINAL_DATE.
"""

from __future__ import annotations

import json
import math
import re
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
    if isinstance(val, str) and not str(val).strip():
        return pd.NaT
    if str(val).strip().upper() == "TBD":
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
    """Compare two datelike values at calendar-day resolution."""
    da = _safe_to_datetime(a)
    db = _safe_to_datetime(b)
    if da is pd.NaT or db is pd.NaT or pd.isna(da) or pd.isna(db):
        return False
    return da.normalize() == db.normalize()


def _event_field(event: dict, *names: str):
    """Read an event field, tolerating leading/trailing spaces in keys."""
    targets = {n.strip().lower() for n in names}
    for k, v in event.items():
        if isinstance(k, str) and k.strip().lower() in targets:
            return v
    return None


def _task_names(tasks: list) -> set:
    names = set()
    for t in tasks or []:
        if isinstance(t, dict) and t.get("name"):
            names.add(str(t.get("name")))
    return names


def _has_dated_events(tasks: list) -> bool:
    for t in tasks or []:
        if not isinstance(t, dict):
            continue
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
    if "status" not in keys and "date" not in keys and "search_data" not in keys:
        return "unknown"

    tasks = data_dict.get("tasks") or []
    has_tasks = isinstance(tasks, list) and len(tasks) > 0
    if not has_tasks:
        return "header_only"

    names = {n.casefold() for n in _task_names(tasks)}
    has_events = _has_dated_events(tasks)

    if any(n.startswith("ready to issue") for n in names):
        return "tasks_ready_to_issue"
    if "application submitted" in names and "final processing" in names:
        return "tasks_dpw"
    if has_events:
        return "tasks_other"
    return "tasks_empty_events"


# ── Status mapping ──────────────────────────────────────────────────────────

_STATUS_MAP = {
    # Final
    "Finaled": "Final",
    "Permit Finaled": "Final",
    "Closed": "Final",
    "Recorded": "Final",
    "Project Closeout": "Final",
    # Active
    "Issued": "Active",
    "Permit Issued": "Active",
    "Approved": "Active",
    "Approved Pending Appeal": "Active",
    "Enforcement": "Active",
    "In Violation": "Active",
    "Final Processing": "Active",
    # Inactive
    "Cancelled": "Inactive",
    "Expired": "Inactive",
    "Expired Status 1": "Inactive",
    "Expired Status 2": "Inactive",
    "Expired Status 3": "Inactive",
    "Withdrawn": "Inactive",
    "Denied": "Inactive",
    "Inactive": "Inactive",
    "SWN Posted": "Inactive",
    "SWN Issued": "Inactive",
    "NOI Issued": "Inactive",
    "Info Notice Posted": "Inactive",
    "NOV recorded": "Inactive",
    "Notice of Violation Recorded": "Inactive",
    "Complaint Received": "Inactive",
    "Violation Notice Sent": "Inactive",
    "Reinstatement Declined": "Inactive",
    # In Review
    "Received": "In Review",
    "In Review": "In Review",
    "Resubmittal Required": "In Review",
    "Submitted": "In Review",
    "New": "In Review",
    "Additional Info Required": "In Review",
    "Revision Requested": "In Review",
    "Payment Received": "In Review",
    "Pending": "In Review",
    "Planning Review": "In Review",
    "Ready Letter Issued": "In Review",
    "Incomplete": "In Review",
    "Revision Issued": "In Review",
    "Application Accepted": "In Review",
    "Permit Applied For": "In Review",
    "Hold": "In Review",
    "On Hold": "In Review",
    "Review Consolidation": "In Review",
    "ACA Update": "In Review",
    "Project Analysis": "In Review",
    "Map Check": "In Review",
    "Agency Referrals": "In Review",
    "Project Decision": "In Review",
    "CEQA Preparation": "In Review",
    "Completeness Review": "In Review",
    "Investigation": "In Review",
}

_STATUS_MAP_LOWER = {k.casefold(): v for k, v in _STATUS_MAP.items()}

_READY_TO_ISSUE_TASKS = {
    "ready to issue",
    "ready to issue permit",
}
_ISSUED_MARKS = {
    "issued",
    "permit issued",
    "permit re-issued",
    "revision issued",
}
_FINAL_INSPECTION_MARKS = {
    "finaled",
    "final processing",
    "final certificate of occupancy",
}
_FINAL_CLOSEOUT_MARKS = {
    "closed",
    "finaled",
    "recorded",
    "permit finaled",
}
_FINAL_INSPECTION_PASS = {
    "pass",
    "passed",
    "approved",
    "approve",
    "approved with conditions",
    "finaled",
    "complete",
    "completed",
}


def _map_status(data_status: Optional[str]) -> Optional[str]:
    if not data_status or not isinstance(data_status, str):
        return None
    key = data_status.strip()
    if not key:
        return None
    return _STATUS_MAP_LOWER.get(key.casefold())


def _data_status(d: dict) -> Optional[str]:
    raw = d.get("status")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    sd = d.get("search_data") if isinstance(d.get("search_data"), dict) else {}
    sd_status = sd.get("Status")
    if isinstance(sd_status, str) and sd_status.strip():
        return sd_status.strip()
    return None


def _collect_tiered_dates(tasks: list, pred) -> list:
    """Return (tier, datetime) pairs where pred(task_name, marked) → tier|None."""
    out = []
    for t in tasks or []:
        if not isinstance(t, dict):
            continue
        name = (t.get("name") or "").strip()
        for e in t.get("events") or []:
            if not isinstance(e, dict):
                continue
            marked = _event_field(e, "Marked as")
            marked = marked.strip() if isinstance(marked, str) else ""
            tier = pred(name, marked)
            if tier is None:
                continue
            dt = _safe_to_datetime(_event_field(e, "on"))
            if dt is not pd.NaT:
                out.append((tier, dt))
    return out


def _best_earliest(tiered: list):
    if not tiered:
        return pd.NaT
    best = min(t for t, _ in tiered)
    return min(dt for t, dt in tiered if t == best)


def _best_latest(tiered: list):
    if not tiered:
        return pd.NaT
    best = min(t for t, _ in tiered)
    return max(dt for t, dt in tiered if t == best)


def _permit_date_tier(name: str, marked: str) -> Optional[int]:
    ncf = name.casefold()
    mcf = marked.casefold()
    if ncf in _READY_TO_ISSUE_TASKS and mcf in _ISSUED_MARKS:
        return 1
    if ncf == "application submitted" and mcf == "permit issued":
        return 2
    if ncf == "application submittal" and mcf == "issued":
        return 3
    if ncf == "enforcement" and mcf == "permit issued":
        return 4
    return None


def _final_date_tier(name: str, marked: str) -> Optional[int]:
    ncf = name.casefold()
    mcf = marked.casefold()
    if ncf == "inspections" and mcf in _FINAL_INSPECTION_MARKS:
        return 1
    if ncf in {"final processing", "project close out"} and mcf in _FINAL_CLOSEOUT_MARKS:
        return 2
    if ncf in {"final processing", "project close out", "project closeout"} and mcf == "workflow closed":
        return 3
    if ncf in {"enforcement", "investigation"} and mcf == "finaled":
        return 4
    return None


def _file_date_from_data(d: dict):
    header = _safe_to_datetime(d.get("date"))
    if header is not pd.NaT:
        return header
    sd = d.get("search_data") if isinstance(d.get("search_data"), dict) else {}
    return _safe_to_datetime(sd.get("Date Submitted") or sd.get("Date") or sd.get("File Date"))


def _permit_date_from_tasks(tasks: list):
    return _best_earliest(_collect_tiered_dates(tasks, _permit_date_tier))


def _final_date_from_inspections(inspections: list):
    dates = []
    for insp in inspections or []:
        if not isinstance(insp, dict):
            continue
        title = str(insp.get("Title") or "")
        if not re.search(r"\bfinal\b", title, flags=re.IGNORECASE):
            continue
        status = str(insp.get("Status") or "").strip().casefold()
        if status not in _FINAL_INSPECTION_PASS:
            continue
        dt = _safe_to_datetime(insp.get("Status Date") or insp.get("Last Update Date"))
        if dt is not pd.NaT:
            dates.append(dt)
    return max(dates) if dates else pd.NaT


def _final_date_from_data(tasks: list, inspections: list):
    tiered = _collect_tiered_dates(tasks, _final_date_tier)
    task_final = _best_latest(tiered)
    if task_final is not pd.NaT:
        return task_final
    return _final_date_from_inspections(inspections)


def _has_final_signal(tasks: list, inspections: list) -> bool:
    return _final_date_from_data(tasks, inspections) is not pd.NaT


# ── Per-record repair ───────────────────────────────────────────────────────

def _repair_accela(row, d: dict, repairs: dict):
    """Repair a San Mateo County Accela Citizen Access record."""
    tasks = d.get("tasks") or []
    inspections = d.get("inspections") or []

    data_status = _data_status(d)

    # -- STATUS_NORMALIZED --
    current_status = row["STATUS_NORMALIZED"]
    expected = _map_status(data_status)

    # Empty Confirmation / TBD shells → In Review.
    if expected is None and not data_status:
        if _safe_to_datetime(d.get("date")) is not pd.NaT or (
            isinstance(d.get("search_data"), dict)
            and (d["search_data"].get("Date Submitted") or d["search_data"].get("Date"))
        ):
            expected = "In Review"

    # Upgrade Active / In Review when a finalization signal is present.
    # Do not override Inactive terminals (Expired / Cancelled / Denied / …).
    if expected in ("Active", "In Review") and _has_final_signal(tasks, inspections):
        expected = "Final"
    elif expected is None and _has_final_signal(tasks, inspections):
        expected = "Final"

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
    final = _final_date_from_data(tasks, inspections)
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
    San Mateo County permit records using information from the raw DATA JSON.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "San Mateo County".  Must
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
        if schema in (
            "tasks_ready_to_issue",
            "tasks_dpw",
            "tasks_other",
            "tasks_empty_events",
            "header_only",
        ):
            _repair_accela(row, d, repairs)

        for key, value in repairs.items():
            if key in ("FILE_DATE", "PERMIT_DATE", "FINAL_DATE"):
                if value is not pd.NaT and not pd.isna(value):
                    value = _safe_to_datetime(value)
                    if value is not pd.NaT:
                        value = value.normalize()
            out.at[idx, key] = value

    for col in ("FILE_DATE", "PERMIT_DATE", "FINAL_DATE"):
        out[col] = pd.to_datetime(out[col], errors="coerce")

    return out


# ── CLI: run standalone to preview repair stats ─────────────────────────────

if __name__ == "__main__":
    import os
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[3] / ".env")
    MY_DATA_PATH = os.getenv("MY_DATA_PATH")
    AGENT_DATA_PATH = os.getenv("AGENT_DATA_PATH")
    filepath = os.path.join(MY_DATA_PATH, "processed_data", "permits_ca_sample.parquet")
    df = pd.read_parquet(filepath)
    city = df[(df["JURISDICTION"] == "San Mateo County") & (df["STATE"] == "CA")].copy()

    print(f"San Mateo County records: {len(city):,}\n")

    repaired = data_repair(city)

    if AGENT_DATA_PATH:
        out_dir = Path(AGENT_DATA_PATH) / "repaired"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "permits_ca_san_mateo_county_repaired.parquet"
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
        print(f"  Missing before: {before_missing:>4,}   Missing after: {after_missing:>4,}")
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

    both_fp = repaired["FILE_DATE"].notna() & repaired["PERMIT_DATE"].notna()
    both_pf = repaired["PERMIT_DATE"].notna() & repaired["FINAL_DATE"].notna()
    inv_fp = (repaired.loc[both_fp, "FILE_DATE"] > repaired.loc[both_fp, "PERMIT_DATE"]).sum()
    inv_pf = (repaired.loc[both_pf, "PERMIT_DATE"] > repaired.loc[both_pf, "FINAL_DATE"]).sum()
    print(f"\nChronology inversions: FILE>PERMIT={inv_fp}, PERMIT>FINAL={inv_pf}")

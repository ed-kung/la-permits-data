"""Data repair for Chula Vista (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Chula Vista DATA is an Accela Citizen Access scrape. All sample rows share
the same top-level keys (``status``, ``date``, ``tasks``, ``inspections``,
``search_data``, ``more_details``, …). Content variants (INFERRED_SCHEMA):

  - accela_tasks:       dated workflow events under ``tasks``
  - accela_shell:       task shells present but no dated events
                        (common on older converted / KEY DATES-only rows)
  - unknown / missing

Canonical mappings:
  - DATA.status / search_data['Status']              → STATUS_NORMALIZED
  - DATA.date / search_data['Date']; else earliest
    Application Submittal event                      → FILE_DATE
  - Permit Issuance|Issuance Marked as Issued /
    Permit Issued / Plan Change Issued; else
    more_details KEY DATES / KEY DATE INFORMATION
    'Issued'                                         → PERMIT_DATE
  - Closed Marked as Closed; else Inspections
    Final Inspection Complete / Final - No C of O /
    Inspections Complete; else KEY DATES 'Final';
    else C of O Issued; else final-titled inspections → FINAL_DATE

Known issues repaired:
  - STATUS_NORMALIZED null for Primary Review, No Comment, Final Letter
    Sent, Securities Released, Public Notice Sent, Meeting Complete,
    Hold, CONVERTD (upstream mapper missed these) → FILLED as In Review
    or Final as appropriate.
  - Stale STATUS_NORMALIZED vs DATA (Issued still In Review; Closed still
    Active; Withdrawn/TEST still In Review; Approved wrongly Active with
    no issuance; Ready to Issue after Issued mark → Active) → FIXED.
  - FILE_DATE already matches DATA.date for every sample row.
  - PERMIT_DATE often copied from Ready To Issue (one day before Issued)
    or from C of O Issued → FIXED to actual Issued; Active/Final missing
    Issued in KEY DATES with no task event → FILLED from KEY DATES.
  - FINAL_DATE missing on Final when KEY DATES Final or Closed mark
    exists → FILLED; spurious FINAL_DATE on Active/Expired → cleared.

Not repairable / left as-is:
  - 15 rows with blank DATA.status / search_data Status (mostly contractor
    info / micro-cell shells) → STATUS_NORMALIZED stays null.
  - Older Final shells with neither dated Closed/Final-inspection events
    nor KEY DATES Final → FINAL_DATE stays missing.
  - Active/Final shells with no Issued task event and no KEY DATES Issued
    → PERMIT_DATE stays missing.
  - Permit Expires is a validity window, not a completion date.
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
    """Parse a date value as UTC, returning pd.NaT on failure."""
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return pd.NaT
    if isinstance(val, dict):
        return pd.NaT
    if isinstance(val, str):
        s = val.strip()
        if not s or s.upper() in {"TBD", "N/A", "NA", "NONE", "NULL"}:
            return pd.NaT
    try:
        dt = pd.to_datetime(val, utc=True, errors="coerce")
    except (ValueError, TypeError):
        return pd.NaT
    if dt is pd.NaT or pd.isna(dt):
        return pd.NaT
    year = int(dt.year)
    if year < _MIN_YEAR or year > _MAX_YEAR:
        return pd.NaT
    return dt


def _dates_equal(a, b) -> bool:
    da = _safe_to_datetime(a)
    db = _safe_to_datetime(b)
    if da is pd.NaT or db is pd.NaT:
        return False
    return da.date() == db.date()


def _event_field(event: dict, *names: str):
    """Read an Accela event field; keys are often padded with spaces."""
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
    if "status" not in keys and "search_data" not in keys:
        return "unknown"

    tasks = data_dict.get("tasks") or []
    has_tasks = isinstance(tasks, list) and len(tasks) > 0
    if _has_dated_events(data_dict):
        return "accela_tasks"
    if has_tasks:
        return "accela_shell"
    return "accela_search_only"


def _event_dates(tasks: list, task_names, statuses):
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


def _key_dates(d: dict) -> dict:
    """Return KEY DATES / KEY DATE INFORMATION dict under more_details."""
    md = d.get("more_details")
    if not isinstance(md, dict):
        return {}
    app = md.get("Application Information")
    if not isinstance(app, dict):
        return {}
    for section in ("KEY DATES", "KEY DATE INFORMATION"):
        block = app.get(section)
        if isinstance(block, dict):
            return block
    return {}


# ── Status mapping ──────────────────────────────────────────────────────────

# DATA.status (case-insensitive match) → STATUS_NORMALIZED
_STATUS_MAP = {
    # Final
    "Closed": "Final",
    "Final Inspection Complete": "Final",
    "Finaled": "Final",
    "Complete": "Final",
    "Final Letter Sent": "Final",
    "Securities Released": "Final",
    # Active (issued / under construction)
    "Issued": "Active",
    "Active": "Active",
    # Inactive
    "Expired": "Inactive",
    "Void": "Inactive",
    "Withdrawn": "Inactive",
    "TEST": "Inactive",
    # In Review (pre-issuance, including plan-approved-but-not-issued)
    "Applied": "In Review",
    "In Review": "In Review",
    "In-Review": "In Review",
    "Corrections Letter Sent": "In Review",
    "Correction Letter Sent": "In Review",
    "Corrections Required": "In Review",
    "Ready to Issue": "In Review",
    "Ready To Issue": "In Review",
    "Incomplete Submittal": "In Review",
    "Primary Review": "In Review",
    "PENDING": "In Review",
    "Pending": "In Review",
    "Received": "In Review",
    "In Process for Issuance": "In Review",
    "No Comment": "In Review",
    "FILED": "In Review",
    "Filed": "In Review",
    "Routed": "In Review",
    "Submitted": "In Review",
    "Public Notice Sent": "In Review",
    "hold": "In Review",
    "Hold": "In Review",
    "Resubmitted": "In Review",
    "Meeting Complete": "In Review",
    "Open": "In Review",
    "Approved": "In Review",
    "APPROVED": "In Review",
    "CONVERTD": "In Review",
}


_ISSUE_TASKS = {"Permit Issuance", "Issuance"}
_ISSUE_MARKS = {"Issued", "Permit Issued", "Plan Change Issued"}

_FINAL_CLOSED_MARKS = {"Closed"}
_FINAL_INSP_MARKS = {
    "Final Inspection Complete",
    "Final - No C of O",
    "Inspections Complete",
}
_CO_MARKS = {"C of O Issued"}


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


def _expected_status(d: dict) -> Optional[str]:
    raw = _raw_status(d)
    if raw is None:
        return None
    mapped = _STATUS_MAP.get(raw)
    if mapped is None:
        for k, v in _STATUS_MAP.items():
            if k.lower() == raw.lower():
                mapped = v
                break
    if mapped is None:
        return None
    # Accela status string can lag the workflow: Ready to Issue after an
    # Issued mark should count as Active.
    if mapped == "In Review" and _has_issuance_evidence(d):
        return "Active"
    return mapped


def _file_date_from_data(d: dict):
    """Application / opened date from Accela top-level date."""
    top = _safe_to_datetime(d.get("date"))
    if top is not pd.NaT:
        return top

    sd = d.get("search_data")
    if isinstance(sd, dict):
        for key in ("Date", "Opened Date", "Submitted Date", "Application Date"):
            opened = _safe_to_datetime(sd.get(key))
            if opened is not pd.NaT:
                return opened

    tasks = d.get("tasks") or []
    app = _first_event_date(
        tasks,
        {
            "Application Submittal",
            "Application Submitttal",
            "Application Acceptance",
        },
        {"Submitted", "Resubmitted", "Accepted - Plan Review Required", "Complete"},
    )
    return app


def _permit_date_from_data(d: dict):
    """Earliest true issuance date (not Ready To Issue)."""
    tasks = d.get("tasks") or []
    issued = _first_event_date(tasks, _ISSUE_TASKS, _ISSUE_MARKS)
    if issued is not pd.NaT:
        return issued

    kd = _key_dates(d)
    return _safe_to_datetime(kd.get("Issued"))


def _has_issuance_evidence(d: dict) -> bool:
    return _permit_date_from_data(d) is not pd.NaT


def _final_date_from_inspections(d: dict):
    """Latest final-titled inspection with an approved/pass status."""
    dates = []
    ok = {"approved", "passed", "pass", "complete", "done", "final", "cmpt"}
    for item in d.get("inspections") or []:
        if not isinstance(item, dict):
            continue
        title = str(item.get("Title") or "")
        if "FINAL" not in title.upper():
            continue
        st = item.get("Status")
        if not isinstance(st, str) or st.strip().lower() not in ok:
            continue
        dt = _safe_to_datetime(item.get("Status Date"))
        if dt is not pd.NaT:
            dates.append(dt)
    return max(dates) if dates else pd.NaT


def _final_date_from_data(d: dict):
    """Best available finaling / sign-off date."""
    tasks = d.get("tasks") or []

    for cand in (
        _latest_event_date(tasks, "Closed", _FINAL_CLOSED_MARKS),
        _latest_event_date(
            tasks, {"Inspections", "Inspection"}, _FINAL_INSP_MARKS
        ),
        _safe_to_datetime(_key_dates(d).get("Final")),
        _latest_event_date(tasks, "C of O Issuance", _CO_MARKS),
        _final_date_from_inspections(d),
    ):
        if cand is not pd.NaT:
            return cand
    return pd.NaT


# ── Per-record repair logic ─────────────────────────────────────────────────

def _repair_record(row, d: dict, repairs: dict):
    current_status = row["STATUS_NORMALIZED"]
    expected = _expected_status(d)

    # -- STATUS_NORMALIZED --
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
        elif effective_status == "In Review" and not _has_issuance_evidence(d):
            repairs["PERMIT_DATE"] = pd.NaT
            repairs["PERMIT_DATE_FLAG"] = "FIXED"
    elif effective_status in ("Active", "Final") and issued is not pd.NaT:
        repairs["PERMIT_DATE"] = issued
        repairs["PERMIT_DATE_FLAG"] = "FILLED"

    # -- FINAL_DATE --
    current_final = row["FINAL_DATE"]
    if effective_status == "Final":
        final_date = _final_date_from_data(d)
        if final_date is not pd.NaT:
            if pd.isna(current_final):
                repairs["FINAL_DATE"] = final_date
                repairs["FINAL_DATE_FLAG"] = "FILLED"
            elif not _dates_equal(current_final, final_date):
                repairs["FINAL_DATE"] = final_date
                repairs["FINAL_DATE_FLAG"] = "FIXED"
    elif not pd.isna(current_final):
        repairs["FINAL_DATE"] = pd.NaT
        repairs["FINAL_DATE_FLAG"] = "FIXED"


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Chula Vista permit records using information from the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Chula Vista".  Must contain
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
        _repair_record(row, d, repairs)

        for key, value in repairs.items():
            out.at[idx, key] = value

    for col in ("FILE_DATE", "PERMIT_DATE", "FINAL_DATE"):
        if col in out.columns:
            out[col] = pd.to_datetime(out[col], utc=True, errors="coerce")

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
    city = df[(df["JURISDICTION"] == "Chula Vista") & (df["STATE"] == "CA")].copy()

    print(f"Chula Vista records: {len(city):,}\n")

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

    fd = pd.to_datetime(repaired["FILE_DATE"], utc=True, errors="coerce")
    pd_ = pd.to_datetime(repaired["PERMIT_DATE"], utc=True, errors="coerce")
    ff = pd.to_datetime(repaired["FINAL_DATE"], utc=True, errors="coerce")
    both_fp = fd.notna() & pd_.notna()
    both_pf = pd_.notna() & ff.notna()
    print("\nChronology inversions:")
    print(f"  FILE > PERMIT: {(both_fp & (fd.dt.normalize() > pd_.dt.normalize())).sum()}")
    print(f"  PERMIT > FINAL: {(both_pf & (pd_.dt.normalize() > ff.dt.normalize())).sum()}")

    if AGENT_DATA_PATH:
        out_path = os.path.join(AGENT_DATA_PATH, "chula_vista_repaired_sample.parquet")
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote repaired sample → {out_path}")

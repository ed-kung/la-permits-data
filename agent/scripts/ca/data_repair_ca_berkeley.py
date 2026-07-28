"""Data repair for Berkeley (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Berkeley DATA is an Accela Citizen Access scrape. All sample rows share
the same portal shape (status / date / tasks / search_data / …);
INFERRED_SCHEMA distinguishes workflow richness:

  - tasks_inspections: non-empty tasks + non-empty inspections
  - tasks_only:        non-empty tasks, no inspections
                       (mostly Closed Complete lean shells)
  - inspections_only:  inspections present, no usable tasks
  - header_only:       status/date/search_data only
  - unknown / missing

Canonical mappings:
  - DATA.status (= search_data Status)       → STATUS_NORMALIZED
      (upgrade Active / In Review → Final when Inspection is Finaled
       or a Final* inspection is Approved)
  - DATA.date / search_data Date             → FILE_DATE
  - Issuance / Issued|Issue                  → PERMIT_DATE
  - Inspection / Finaled|Final               → FINAL_DATE
      (fallback: latest Final* inspection Status Date with
       Approved / Approve / Approved with Conditions)

Known issues repaired:
  - STATUS_NORMALIZED stale vs DATA.status (Finaled mislabeled Active /
    Inactive; Issued mislabeled In Review; Closed Expired mislabeled
    In Review) → FIXED.
  - Active / In Review rows with a Finaled inspection signal → Final.
  - PERMIT_DATE missing on Active/Final when Issuance/Issued is present
    (typically after correcting Issued → Active) → FILLED.
  - FINAL_DATE missing on Final when Inspection/Finaled or an approved
    Final* inspection exists → FILLED.
  - FINAL_DATE using the first of multiple Finaled events instead of the
    latest → FIXED.
  - Spurious FINAL_DATE on non-Final rows → cleared (FIXED).

Not repairable from DATA:
  - FILE_DATE already matches DATA.date for every sample row.
  - ~447 Closed Complete lean shells have empty Issuance / Inspection
    events and no inspections array → PERMIT_DATE / FINAL_DATE stay
    missing despite Final status.
  - Many Finaled / Closed rows lack dated Issuance events → PERMIT_DATE
    stays missing.
  - Closed Expired rows with a Finaled inspection remain Inactive
    (expired terminal status takes precedence over the final signal).
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
    if val is None or (isinstance(val, str) and not str(val).strip()):
        return pd.NaT
    if str(val).strip().upper() == "TBD":
        return pd.NaT
    try:
        dt = pd.to_datetime(val)
    except (ValueError, TypeError):
        return pd.NaT
    if dt is pd.NaT or pd.isna(dt):
        return pd.NaT
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


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())
    if "status" not in keys and "date" not in keys and "search_data" not in keys:
        return "unknown"

    tasks = data_dict.get("tasks") or []
    inspections = data_dict.get("inspections") or []
    has_tasks = isinstance(tasks, list) and len(tasks) > 0
    has_insp = isinstance(inspections, list) and len(inspections) > 0

    if has_tasks and has_insp:
        return "tasks_inspections"
    if has_tasks:
        return "tasks_only"
    if has_insp:
        return "inspections_only"
    return "header_only"


def _event_field(event: dict, *names: str):
    """Read an event field, tolerating leading/trailing spaces in keys."""
    targets = {n.strip().lower() for n in names}
    for k, v in event.items():
        if isinstance(k, str) and k.strip().lower() in targets:
            return v
    return None


def _event_dates(tasks: list, task_name: str, marked_pred) -> list:
    """Return datetimes for task_name events matching marked_pred(marked)."""
    dates = []
    for t in tasks or []:
        if not isinstance(t, dict) or t.get("name") != task_name:
            continue
        for e in t.get("events") or []:
            if not isinstance(e, dict):
                continue
            marked = _event_field(e, "Marked as")
            marked = (marked or "").strip() if isinstance(marked, str) else marked
            if not marked_pred(marked):
                continue
            on_val = _event_field(e, "on")
            dt = _safe_to_datetime(on_val)
            if dt is not pd.NaT:
                dates.append(dt)
    return dates


# ── Status mapping ──────────────────────────────────────────────────────────

# DATA.status → STATUS_NORMALIZED (case-insensitive via _map_status).
_STATUS_MAP = {
    # Final
    "Finaled": "Final",
    "Closed Complete": "Final",
    "Closed": "Final",
    # Active
    "Issued": "Active",
    # Inactive
    "Closed Expired": "Inactive",
    "Closed Error": "Inactive",
    "Closed Cancelled": "Inactive",
    "Denied": "Inactive",
    # In Review
    "Documents Required": "In Review",
    "Corrections List Issued": "In Review",
    "Under Review": "In Review",
    "Waiting for Review": "In Review",
    "Approved w/Conditions": "In Review",
    "Ready to Issue": "In Review",
    "Ready To Issue": "In Review",
    "Open": "In Review",
    "Received": "In Review",
    "Pending Payment": "In Review",
    "Documents Uploaded": "In Review",
}

_STATUS_MAP_LOWER = {k.casefold(): v for k, v in _STATUS_MAP.items()}


def _map_status(data_status: Optional[str]) -> Optional[str]:
    if not data_status or not isinstance(data_status, str):
        return None
    key = data_status.strip()
    if not key:
        return None
    return _STATUS_MAP_LOWER.get(key.casefold())


def _is_issued_marked(m) -> bool:
    if not isinstance(m, str):
        return False
    return m.strip().casefold() in {"issued", "issue"}


def _is_final_task_marked(m) -> bool:
    if not isinstance(m, str):
        return False
    s = m.strip().casefold()
    return s in {"finaled", "final"}


_FINAL_INSPECTION_PASS = {
    "approved",
    "approve",
    "approved with conditions",
    "passed",
    "finaled",
    "complete",
    "completed",
}


def _file_date_from_data(d: dict):
    """Accela header date (matches FILE_DATE for all Berkeley sample rows)."""
    header = _safe_to_datetime(d.get("date"))
    if header is not pd.NaT:
        return header
    sd = d.get("search_data") if isinstance(d.get("search_data"), dict) else {}
    return _safe_to_datetime(sd.get("Date") or sd.get("File Date"))


def _permit_date_from_tasks(tasks: list):
    """Earliest Issuance / Issued|Issue event."""
    dates = _event_dates(tasks, "Issuance", _is_issued_marked)
    return min(dates) if dates else pd.NaT


def _final_date_from_inspections(inspections: list):
    """Latest Final* inspection with a passing / approved result."""
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
    """Latest completion / sign-off date from Inspection task or inspections."""
    finals = _event_dates(tasks, "Inspection", _is_final_task_marked)
    if finals:
        return max(finals)

    insp_final = _final_date_from_inspections(inspections)
    if insp_final is not pd.NaT:
        return insp_final

    return pd.NaT


def _has_final_signal(tasks: list, inspections: list) -> bool:
    return _final_date_from_data(tasks, inspections) is not pd.NaT


# ── Per-record repair ───────────────────────────────────────────────────────

def _repair_accela(row, d: dict, repairs: dict):
    """Repair a Berkeley Accela Citizen Access record."""
    tasks = d.get("tasks") or []
    inspections = d.get("inspections") or []

    data_status = d.get("status")
    if isinstance(data_status, str):
        data_status = data_status.strip() or None
    else:
        data_status = None
    if data_status is None:
        sd = d.get("search_data") if isinstance(d.get("search_data"), dict) else {}
        sd_status = sd.get("Status")
        if isinstance(sd_status, str) and sd_status.strip():
            data_status = sd_status.strip()

    # -- STATUS_NORMALIZED --
    current_status = row["STATUS_NORMALIZED"]
    expected = _map_status(data_status)

    # Upgrade Active / In Review when a Finaled inspection signal is present.
    # Do not override Inactive terminals (Closed Expired / Cancelled / Denied).
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
    if issued is not pd.NaT:
        if pd.isna(row["PERMIT_DATE"]):
            if effective_status in ("Active", "Final"):
                repairs["PERMIT_DATE"] = issued
                repairs["PERMIT_DATE_FLAG"] = "FILLED"
        elif not _dates_equal(row["PERMIT_DATE"], issued):
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
    Berkeley permit records using information from the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Berkeley".  Must contain
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
        if schema in (
            "tasks_inspections",
            "tasks_only",
            "inspections_only",
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
    city = df[(df["JURISDICTION"] == "Berkeley") & (df["STATE"] == "CA")].copy()

    print(f"Berkeley records: {len(city):,}\n")

    repaired = data_repair(city)

    if AGENT_DATA_PATH:
        out_dir = Path(AGENT_DATA_PATH) / "repaired"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "permits_ca_berkeley_repaired.parquet"
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

    # Chronology checks
    both_fp = repaired["FILE_DATE"].notna() & repaired["PERMIT_DATE"].notna()
    both_pf = repaired["PERMIT_DATE"].notna() & repaired["FINAL_DATE"].notna()
    inv_fp = (repaired.loc[both_fp, "FILE_DATE"] > repaired.loc[both_fp, "PERMIT_DATE"]).sum()
    inv_pf = (repaired.loc[both_pf, "PERMIT_DATE"] > repaired.loc[both_pf, "FINAL_DATE"]).sum()
    print(f"\nChronology inversions: FILE>PERMIT={inv_fp}, PERMIT>FINAL={inv_pf}")

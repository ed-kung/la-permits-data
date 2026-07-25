"""Data repair for Torrance (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Torrance DATA is an Accela Citizen Access payload. Nearly all sample rows
share one schema (tasks_full): top-level keys include tasks, status, date,
inspections, search_data, fees_details, contacts, etc. One row has
tasks=None (tasks_null) while retaining status/date/search_data.

Canonical mappings:
  - DATA.status                              → STATUS_NORMALIZED
  - DATA.date / search_data['Created Date']  → FILE_DATE
  - Permit Issuance / Issued                 → PERMIT_DATE
      (fallback: Permit Issuance / Revision Issued)
  - Inspection / Finaled (latest)            → FINAL_DATE
      (fallback: Closed or Close File / Finaled)

Known issues repaired:
  - Archiving mapped to In Review (758+) → Final. Archiving is the
    Accela close-out status after finaling (Closed/Archiving or
    Close File/Archiving).
  - Final Routing / Final Routing Complete mapped to In Review → Active
    (post-issuance inspection phase; all have Permit Issuance / Issued).
  - Stale STATUS_ORIGINAL vs DATA.status (e.g. issued while DATA says
    Finaled) → STATUS_NORMALIZED follows DATA.status.
  - 4 blank DATA.status rows (early-stage electrical/plumbing, only TBD
    Application Submittal) → STATUS filled as In Review.
  - Missing PERMIT_DATE on Active/Final rows with Issued (or Revision
    Issued) → FILLED.
  - FINAL_DATE set to Inspection / Final Routing* while a later
    Inspection / Finaled exists → FIXED to latest Finaled.
  - Spurious FINAL_DATE on non-Final rows (Final Routing*, Issued) →
    cleared (FIXED).

Not repairable / left as-is:
  - FILE_DATE already matches DATA.date for all sample rows.
  - Approved Active rows (mostly Underground Utility Waiver) have no
    Permit Issuance event → PERMIT_DATE stays missing.
  - Archiving Final rows that expired / withdrew without Finaled →
    FINAL_DATE stays missing (Archiving date is not a completion date).
  - One tasks_null Archiving row has no workflow events → dates kept.
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
    """Parse a date value, returning pd.NaT on failure."""
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
    if "tasks" not in keys:
        if "search_data" in keys:
            return "search_data_only"
        return "unknown"
    tasks = data_dict.get("tasks")
    if tasks is None:
        return "tasks_null"
    has_inspections = "inspections" in keys
    has_fees = "fees_details" in keys
    if has_inspections and has_fees:
        return "tasks_full"
    if "contacts" in keys and not has_inspections:
        return "tasks_contacts"
    return "tasks_basic"


def _event_field(event: dict, *names: str):
    """Read an event field, tolerating leading/trailing spaces in keys."""
    targets = {n.strip() for n in names}
    for k, v in event.items():
        if isinstance(k, str) and k.strip() in targets:
            return v
    return None


def _event_dates(tasks: list, task_name: str, marked_pred) -> list:
    """Return all datetimes for task_name events matching marked_pred(marked)."""
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

_STATUS_MAP = {
    # Final — completed / closed out
    "Final": "Final",
    "Finaled": "Final",
    "Archiving": "Final",
    # Active — issued or approved / in inspection
    "Issued": "Active",
    "Approved": "Active",
    "Final Routing": "Active",
    "Final Routing Complete": "Active",
    # Inactive
    "Expired": "Inactive",
    "Withdrawn": "Inactive",
    "Cancelled": "Inactive",
    # In Review — pre-issuance
    "Received": "In Review",
    "Received - OTC": "In Review",
    "Received OTC": "In Review",
    "In Review": "In Review",
    "Submitted": "In Review",
    "Out for Corrections": "In Review",
    "Corrections Needed": "In Review",
    "Ready to Issue": "In Review",
    "In Process": "In Review",
}


def _map_status(data_status: Optional[str]) -> Optional[str]:
    if data_status is None:
        return None
    if not isinstance(data_status, str):
        return None
    key = data_status.strip()
    if not key:
        return None
    return _STATUS_MAP.get(key)


def _permit_date_from_tasks(tasks: list):
    """Earliest issuance date from Permit Issuance workflow."""
    dates = _event_dates(tasks, "Permit Issuance", lambda m: m == "Issued")
    if dates:
        return min(dates)
    dates = _event_dates(tasks, "Permit Issuance", lambda m: m == "Revision Issued")
    if dates:
        return min(dates)
    return pd.NaT


def _final_date_from_tasks(tasks: list):
    """Latest completion / sign-off date from workflow tasks.

    Prefer Inspection / Finaled. Do not use Final Routing* or Archiving
    dates — those are intermediate routing or file-close events, not
    permit completion.
    """
    finals = _event_dates(tasks, "Inspection", lambda m: m == "Finaled")
    if finals:
        return max(finals)

    for task_name in ("Closed", "Close File"):
        dates = _event_dates(tasks, task_name, lambda m: m == "Finaled")
        if dates:
            return max(dates)

    return pd.NaT


# ── Per-schema repair logic ─────────────────────────────────────────────────

def _repair_record(row, d: dict, repairs: dict):
    """Populate *repairs* with corrected values for a single Torrance record."""
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
        # Blank Accela status with early-stage workflow → In Review
        expected = "In Review"

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
    final = _final_date_from_tasks(tasks)
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
        # Spurious FINAL_DATE on non-Final rows (e.g. Final Routing*).
        repairs["FINAL_DATE"] = pd.NaT
        repairs["FINAL_DATE_FLAG"] = "FIXED"


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Torrance permit records using information from the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Torrance".  Must contain
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
        if schema in ("tasks_full", "tasks_contacts", "tasks_basic", "tasks_null"):
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
    filepath = os.path.join(MY_DATA_PATH, "processed_data", "permits_la_sample.parquet")
    df = pd.read_parquet(filepath)
    city = df[(df["JURISDICTION"] == "Torrance") & (df["STATE"] == "CA")].copy()

    print(f"Torrance records: {len(city):,}\n")

    repaired = data_repair(city)

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
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({n_has / max(len(sub), 1):.1%})")

    print("\nFINAL_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FINAL_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({n_has / max(len(sub), 1):.1%})")

    print("\nFILE_DATE coverage (after repair):")
    n_has = repaired["FILE_DATE"].notna().sum()
    print(f"  {n_has:>4,} / {len(repaired):>4,} ({n_has / len(repaired):.1%})")

    if AGENT_DATA_PATH:
        out_path = os.path.join(AGENT_DATA_PATH, "torrance_repaired_sample.parquet")
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote {out_path}")

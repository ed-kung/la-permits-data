"""Data repair for Fresno (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Fresno DATA is Accela Citizen Access with two closely related schemas:
  - tasks_full:     tasks + inspections/fees_details/conditions/related_records
  - tasks_basic:    tasks present, without the inspections/fees blocks

Canonical mappings:
  - DATA.status                              → STATUS_NORMALIZED
      (override to Final when Inspection/Final Inspection Complete or
       Certificate of Occupancy/Final CO Issued exists, unless status is
       Rejected/Reject)
  - DATA.date / search_data['Applied On']    → FILE_DATE
  - Permit Issuance / Issued (earliest)      → PERMIT_DATE
  - Inspection / Final Inspection Complete   → FINAL_DATE (latest)
      (fallback: Certificate of Occupancy / Final CO Issued;
       then Inspection / Final Inspection; then TCO Issued)

Known issues repaired:
  - 12 blank DATA.status rows → STATUS filled (In Review, or Active when
    a non-issuance Approved workflow event is present).
  - ~25 Issued (and 1 Comments Delivered) rows with Final Inspection
    Complete events while DATA.status never advanced → STATUS FIXED to
    Final.
  - FINAL_DATE stored the earliest Final Inspection Complete when multiple
    exist → FIXED to the latest (~295 records).
  - Final rows missing FINAL_DATE but with Final CO Issued events → FILLED.
  - Spurious FINAL_DATE on non-Final rows (Rejected / residual Issued
    after not promoting) → cleared (FIXED).

Not repairable / left as-is:
  - FILE_DATE already matches DATA.date for all sample rows.
  - ~35 Active/Final rows lack any Permit Issuance / Issued event
    (mostly Sign / Grading) → PERMIT_DATE stays missing.
  - ~630 Final rows have only TBD (or empty) Inspection events and no
    Certificate of Occupancy date → FINAL_DATE stays missing.
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
    if str(val).strip() == "TBD":
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
    has_inspections = "inspections" in keys
    has_fees = "fees_details" in keys
    if has_inspections and has_fees:
        return "tasks_full"
    return "tasks_basic"


def _event_field(event: dict, *names: str):
    """Read an event field, tolerating leading/trailing spaces in keys."""
    targets = {n.strip() for n in names}
    for k, v in event.items():
        if isinstance(k, str) and k.strip() in targets:
            return v
    return None


def _event_dates(tasks: list, task_name: str, marked_values) -> list:
    """Return all datetimes for task_name events whose Marked-as is in marked_values."""
    if isinstance(marked_values, str):
        marked_values = {marked_values}
    dates = []
    for t in tasks or []:
        if not isinstance(t, dict) or t.get("name") != task_name:
            continue
        for e in t.get("events") or []:
            if not isinstance(e, dict):
                continue
            marked = _event_field(e, "Marked as")
            marked = (marked or "").strip() if isinstance(marked, str) else marked
            if marked not in marked_values:
                continue
            dt = _safe_to_datetime(_event_field(e, "on"))
            if dt is not pd.NaT:
                dates.append(dt)
    return dates


def _has_completion_event(tasks: list) -> bool:
    """True if workflow shows final inspection complete or final CO issued."""
    if _event_dates(tasks, "Inspection", "Final Inspection Complete"):
        return True
    if _event_dates(tasks, "Certificate of Occupancy", "Final CO Issued"):
        return True
    return False


def _has_approved_workflow(tasks: list) -> bool:
    """True if any non-placeholder Approved/Issued mark exists in tasks."""
    for t in tasks or []:
        if not isinstance(t, dict):
            continue
        for e in t.get("events") or []:
            if not isinstance(e, dict):
                continue
            marked = _event_field(e, "Marked as")
            marked = (marked or "").strip() if isinstance(marked, str) else ""
            if marked in ("Approved", "Issued", "Approved without additional permitting"):
                return True
    return False


# ── Status mapping ──────────────────────────────────────────────────────────

_STATUS_MAP = {
    # Final
    "Final Inspection Complete": "Final",
    "Final CO Issued": "Final",
    "Final Inspection": "Final",
    "TCO Issued": "Final",
    # Active
    "Issued": "Active",
    "Approved": "Active",
    # Inactive
    "Rejected": "Inactive",
    "Reject": "Inactive",
    # In Review
    "In Review": "In Review",
    "Addendum Approved": "In Review",
    "Comments Delivered": "In Review",
    "Applicant Notified": "In Review",
    "Add'l Info Requested": "In Review",
    "Routed for Review": "In Review",
    "Accepted": "In Review",
    "Resubmittal Required": "In Review",
    "Additional Info Required": "In Review",
    "Review Complete": "In Review",
    "Approved w/o add'l permitting": "In Review",
}

_INACTIVE_STATUSES = {"Rejected", "Reject"}


def _map_status(data_status: Optional[str], tasks: list) -> Optional[str]:
    """Map DATA.status to STATUS_NORMALIZED, with completion-event override."""
    if data_status is None or not str(data_status).strip():
        # Blank Accela status: Active if any Approved/Issued workflow mark,
        # otherwise early-stage → In Review.
        if _has_approved_workflow(tasks):
            return "Active"
        return "In Review"

    key = str(data_status).strip()
    if key in _INACTIVE_STATUSES:
        return "Inactive"

    # Stale Accela status (e.g. Issued) after final inspection / CO → Final.
    if _has_completion_event(tasks):
        return "Final"

    return _STATUS_MAP.get(key)


def _permit_date_from_tasks(tasks: list):
    """Earliest Permit Issuance / Issued date."""
    dates = _event_dates(tasks, "Permit Issuance", "Issued")
    if dates:
        return min(dates)
    return pd.NaT


def _final_date_from_tasks(tasks: list):
    """Latest completion / sign-off date from workflow tasks."""
    finals = _event_dates(tasks, "Inspection", "Final Inspection Complete")
    cos = _event_dates(tasks, "Certificate of Occupancy", "Final CO Issued")
    combined = finals + cos
    if combined:
        return max(combined)

    fi = _event_dates(tasks, "Inspection", "Final Inspection")
    if fi:
        return max(fi)

    tco = _event_dates(tasks, "Certificate of Occupancy", "TCO Issued")
    if tco:
        return max(tco)

    return pd.NaT


# ── Per-schema repair logic ─────────────────────────────────────────────────

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
    expected = _map_status(data_status, tasks)

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
        file_src = _safe_to_datetime(sd.get("Applied On"))
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
        # Spurious FINAL_DATE on non-Final rows (e.g. Rejected with a
        # historical Final Inspection Complete event).
        repairs["FINAL_DATE"] = pd.NaT
        repairs["FINAL_DATE_FLAG"] = "FIXED"


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Fresno permit records using information from the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Fresno".  Must contain
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

    # Normalize date columns so FILLED/FIXED Timestamps and clears (NaT)
    # do not produce mixed object dtypes (datetime.date vs Timestamp).
    for col in ("FILE_DATE", "PERMIT_DATE", "FINAL_DATE"):
        out[col] = pd.to_datetime(out[col], errors="coerce")

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
        if schema in ("tasks_full", "tasks_basic"):
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
    filepath = os.path.join(MY_DATA_PATH, "processed_data", "permits_ca_sample.parquet")
    df = pd.read_parquet(filepath)
    city = df[(df["JURISDICTION"] == "Fresno") & (df["STATE"] == "CA")].copy()

    print(f"Fresno records: {len(city):,}\n")

    repaired = data_repair(city)

    if AGENT_DATA_PATH:
        out_path = os.path.join(AGENT_DATA_PATH, "fresno_repaired_sample.parquet")
        repaired.to_parquet(out_path, index=False)
        print(f"Wrote {out_path}\n")

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

    print("\nFILE_DATE coverage:")
    n_has = repaired["FILE_DATE"].notna().sum()
    print(f"  all rows: {n_has:>4,} / {len(repaired):>4,} ({n_has / max(len(repaired), 1):.1%})")

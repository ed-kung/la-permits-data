"""Data repair for Santa Monica (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Santa Monica DATA is an Accela Citizen Access scrape with three key-set
variants (same repair logic):

  - tasks_full:     tasks + inspections + fees_details + conditions +
                    related_records (+ contacts, address_lines)
  - tasks_contacts: tasks + contacts + address_lines (no inspections /
                    fees bundle)
  - tasks_basic:    tasks + status + date + search_data (no inspections /
                    fees / contacts)

Canonical mappings:
  - DATA.status                         → STATUS_NORMALIZED
  - DATA.date / search_data.Date        → FILE_DATE
  - Ready to Issue / Issued|Re-Issue    → PERMIT_DATE
      (fallback: Permit Issuance / Permit Issued;
       Application Submittal / Issued;
       Issue Notice / Notice Issued for seismic notices;
       Application Review|Review / Approved for Approved rows;
       Request Review / Issued for city reports)
  - Inspections / Finaled (latest)      → FINAL_DATE
      (fallback: C of O / C of O Issued;
       Closed / Closed*;
       Application Submittal / Complete for Express Complete)

Known issues repaired:
  - STATUS_NORMALIZED from stale STATUS_ORIGINAL disagrees with
    DATA.status (e.g. issued→Finaled/Expired/C of O; received→Issued;
    vacant→In Review) → FIXED.
  - Seismic Retrofit ``Notice Issued`` / ``Retrofit Notice Issued``
    incorrectly labeled Final → FIXED to Active.
  - FINAL_DATE using an earlier Inspections / Finaled when a later
    Finaled exists → FIXED to the latest Finaled.
  - Missing PERMIT_DATE on Active/Final rows with Ready to Issue /
    Issued or Application Submittal / Issued → FILLED.
  - Missing FINAL_DATE on Closed seismic rows → FILLED from Closed /
    Closed* events; Express ``Complete`` rows filled from Application
    Submittal / Complete.
  - Spurious FINAL_DATE on non-Final rows → cleared (FIXED).

Not repairable / left as-is:
  - FILE_DATE already matches DATA.date for all sample rows.
  - 17 rows with blank DATA.status / search_data Status →
    STATUS_NORMALIZED stays missing.
  - Pre-2015 migrated FINAL/COMPLETE/CLOSED stubs and many Finaled
    rows have empty workflow events → PERMIT_DATE / FINAL_DATE stay
    missing.
  - Some Received / Review Completed rows show Inspections / Finaled
    events while DATA.status was never advanced → status left as
    In Review (DATA.status trusted); FINAL_DATE cleared if present.
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
    has_contacts = "contacts" in keys
    if has_inspections and has_fees:
        return "tasks_full"
    if has_contacts and not has_inspections:
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
    # Final
    "Finaled": "Final",
    "FINAL": "Final",
    "COMPLETE": "Final",
    "Complete": "Final",
    "C of O": "Final",
    "Closed": "Final",
    "CLOSED": "Final",
    # Active
    "Issued": "Active",
    "Approved": "Active",
    "Notice Issued": "Active",
    "Retrofit Notice Issued": "Active",
    # Inactive
    "Expired": "Inactive",
    "EXPIRED": "Inactive",
    "WITHDRAW": "Inactive",
    "Denied": "Inactive",
    "VACANT": "Inactive",
    # In Review
    "Review Completed": "In Review",
    "Received": "In Review",
    "In Review": "In Review",
    "Resubmittal Required": "In Review",
    "PAID": "In Review",
    "PENDING": "In Review",
    "Plans Approved": "In Review",
    "Ready to Issue": "In Review",
}


def _map_status(data_status: Optional[str]) -> Optional[str]:
    if not data_status or not isinstance(data_status, str):
        return None
    key = data_status.strip()
    return _STATUS_MAP.get(key) if key else None


def _permit_date_from_tasks(tasks: list, data_status: Optional[str]):
    """Earliest canonical issuance / approval date from workflow tasks."""
    # Primary building-permit path: Ready to Issue marked Issued.
    dates = _event_dates(
        tasks, "Ready to Issue", lambda m: m in ("Issued", "Re-Issue")
    )
    if dates:
        return min(dates)

    dates = _event_dates(tasks, "Permit Issuance", lambda m: m == "Permit Issued")
    if dates:
        return min(dates)

    # Some finaled jobs only record issuance on Application Submittal.
    dates = _event_dates(tasks, "Application Submittal", lambda m: m == "Issued")
    if dates:
        return min(dates)

    # Seismic retrofit notices: "issuance" is the notice itself.
    if data_status == "Retrofit Notice Issued":
        dates = _event_dates(
            tasks,
            "Issue Building Officer Determination",
            lambda m: isinstance(m, str) and m.endswith("Notice Issued"),
        )
        if dates:
            return min(dates)
    if data_status in ("Notice Issued", "Retrofit Notice Issued", "Closed"):
        dates = _event_dates(tasks, "Issue Notice", lambda m: m == "Notice Issued")
        if dates:
            return min(dates)

    # Discretionary / address assignment / special inspector approvals.
    if data_status == "Approved":
        for task_name in ("Application Review", "Review"):
            dates = _event_dates(tasks, task_name, lambda m: m == "Approved")
            if dates:
                return min(dates)

    # City reports use Request Review / Issued.
    dates = _event_dates(tasks, "Request Review", lambda m: m == "Issued")
    if dates:
        return min(dates)

    return pd.NaT


def _final_date_from_tasks(tasks: list, data_status: Optional[str]):
    """Latest completion / sign-off date from workflow tasks."""
    finals = _event_dates(tasks, "Inspections", lambda m: m == "Finaled")
    if finals:
        return max(finals)

    cos = _event_dates(tasks, "C of O", lambda m: m == "C of O Issued")
    if cos:
        return max(cos)

    closed = _event_dates(
        tasks,
        "Closed",
        lambda m: isinstance(m, str) and m.startswith("Closed"),
    )
    if closed:
        return max(closed)

    # Express permits marked Complete only update Application Submittal.
    if data_status == "Complete":
        dates = _event_dates(
            tasks, "Application Submittal", lambda m: m == "Complete"
        )
        if dates:
            return max(dates)

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
    expected = _map_status(data_status)
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
        file_src = _safe_to_datetime(sd.get("Date"))
    if file_src is not pd.NaT:
        if pd.isna(row["FILE_DATE"]):
            repairs["FILE_DATE"] = file_src
            repairs["FILE_DATE_FLAG"] = "FILLED"
        elif not _dates_equal(row["FILE_DATE"], file_src):
            repairs["FILE_DATE"] = file_src
            repairs["FILE_DATE_FLAG"] = "FIXED"

    # -- PERMIT_DATE --
    issued = _permit_date_from_tasks(tasks, data_status)
    if issued is not pd.NaT:
        if pd.isna(row["PERMIT_DATE"]):
            if effective_status in ("Active", "Final"):
                repairs["PERMIT_DATE"] = issued
                repairs["PERMIT_DATE_FLAG"] = "FILLED"
        elif not _dates_equal(row["PERMIT_DATE"], issued):
            # Only overwrite when a canonical issuance event disagrees.
            repairs["PERMIT_DATE"] = issued
            repairs["PERMIT_DATE_FLAG"] = "FIXED"

    # -- FINAL_DATE --
    final = _final_date_from_tasks(tasks, data_status)
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
    Santa Monica permit records using information from the raw DATA JSON
    column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Santa Monica".  Must contain
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
        if schema in ("tasks_full", "tasks_contacts", "tasks_basic"):
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
    filepath = os.path.join(MY_DATA_PATH, "processed_data", "permits_la_sample.parquet")
    df = pd.read_parquet(filepath)
    city = df[(df["JURISDICTION"] == "Santa Monica") & (df["STATE"] == "CA")].copy()

    print(f"Santa Monica records: {len(city):,}\n")

    repaired = data_repair(city)

    if AGENT_DATA_PATH:
        out_path = os.path.join(
            AGENT_DATA_PATH, "processed_data", "permits_ca_santa_monica_repaired.parquet"
        )
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
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
    print(f"  {n_has:>4,} / {len(repaired):>4,} ({n_has/len(repaired):.1%})")

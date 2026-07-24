"""Data repair for Monterey Park (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Monterey Park DATA is Accela Citizen Access with top-level keys
``date``, ``status``, ``tasks``, ``search_data``, etc. Task event keys
have leading/trailing spaces (``'Marked as '``, ``' on '``), same as
Downey / Inglewood.

Three key-set variants appear in the sample:

  - tasks_full:       tasks + inspections + fees_details + conditions +
                      related_records (+ contacts, address_lines)
  - tasks_contacts:   tasks + contacts + address_lines (no inspections /
                      fees bundle)
  - tasks_basic:      tasks + status + date + search_data (no inspections /
                      fees / contacts)

Canonical fields:
  - DATA.status                         → STATUS_NORMALIZED
  - DATA.date / search_data.Date        → FILE_DATE
  - Permit Issuance / Issued            → PERMIT_DATE
    (fallback: Certificate / Issued*; for status Approved:
    Determination or Planning Review / Approved)
  - Inspections / Final (last event);
    fallback Closed / Close             → FINAL_DATE

Known issues repaired:
  - STATUS_NORMALIZED derived from stale STATUS_ORIGINAL while DATA.status
    advanced (e.g. ORIGINAL=issued but status=Final / Expired Permit) →
    FIXED (~25 records). Missing STATUS for Reported / Unfounded → FILLED.
  - PERMIT_DATE missing for Certificate of Occupancy / Issued Temporary
    rows that use Certificate task events instead of Permit Issuance →
    FILLED. Approved discretionary rows (yard sale, etc.) filled from
    Determination / Planning Review approval dates.
  - FINAL_DATE missing for Final rows with Closed / Close or Inspections /
    Final → FILLED. A few Final rows used the first Final event while a
    later re-final exists → FIXED to the last Final / Close.
  - Spurious FINAL_DATE on one Expired Permit row → cleared.

Not repairable / left as-is:
  - FILE_DATE already matches DATA.date for all sample rows.
  - Historical Documents (status Closed) have no issuance event →
    PERMIT_DATE stays missing.
  - A handful of Final fire-suppression rows lack Final / Close events →
    FINAL_DATE stays missing.
  - Fire Violation (In Violation) rows have empty workflow dates →
    PERMIT_DATE stays missing.
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
        if k.strip() in targets:
            return v
    return None


def _event_dates(tasks: list, task_name: str, marked_pred) -> list:
    """Return all datetimes for task_name events matching marked_pred(marked)."""
    dates = []
    for t in tasks or []:
        if t.get("name") != task_name:
            continue
        for e in t.get("events") or []:
            if not isinstance(e, dict):
                continue
            marked = _event_field(e, "Marked as")
            marked = (marked or "").strip()
            if not marked_pred(marked):
                continue
            on_val = _event_field(e, "on")
            dt = _safe_to_datetime(on_val)
            if dt is not pd.NaT:
                dates.append(dt)
    return dates


def _first_event_date(tasks: list, task_name: str, marked_as: str):
    dates = _event_dates(tasks, task_name, lambda m: m == marked_as)
    return min(dates) if dates else pd.NaT


def _last_event_date(tasks: list, task_name: str, marked_as: str):
    dates = _event_dates(tasks, task_name, lambda m: m == marked_as)
    return max(dates) if dates else pd.NaT


def _dates_equal(a, b) -> bool:
    da = _safe_to_datetime(a)
    db = _safe_to_datetime(b)
    if da is pd.NaT or db is pd.NaT:
        return False
    return da.normalize() == db.normalize()


# ── Status mapping ──────────────────────────────────────────────────────────

_STATUS_MAP = {
    # Final
    "Final": "Final",
    "Closed": "Final",
    "Closed-Compliant": "Final",
    # Active
    "Issued": "Active",
    "Approved": "Active",
    "Active": "Active",
    "Issued Temporary": "Active",
    "In Violation": "Active",
    # Inactive
    "Expired Permit": "Inactive",
    "Expired Plan Check": "Inactive",
    "Expired": "Inactive",
    "Withdrawn": "Inactive",
    "Void": "Inactive",
    "Revoked": "Inactive",
    "Unfounded": "Inactive",
    # In Review
    "Pending": "In Review",
    "Plan Check": "In Review",
    "Applied": "In Review",
    "Ready to Issue": "In Review",
    "Corrections": "In Review",
    "Reported": "In Review",
    "Investigate": "In Review",
}


def _permit_date_from_tasks(tasks: list, data_status: Optional[str]):
    """Issuance / approval date from Accela workflow tasks."""
    issued = _event_dates(
        tasks,
        "Permit Issuance",
        lambda m: m in ("Issued", "Issued Temporary"),
    )
    if issued:
        return min(issued)

    # Certificate of Occupancy / temporary CO use Certificate task
    cert = _event_dates(
        tasks,
        "Certificate",
        lambda m: m.startswith("Issued"),
    )
    if cert:
        return min(cert)

    # Discretionary "Approved" records never hit Permit Issuance
    if data_status == "Approved":
        for task_name in (
            "Determination",
            "Planning Review",
            "Engineering Review",
            "Building Review",
        ):
            dt = _first_event_date(tasks, task_name, "Approved")
            if dt is not pd.NaT:
                return dt

    return pd.NaT


def _final_date_from_tasks(tasks: list):
    """Completion / sign-off date: last Inspections/Final, else last Closed/Close."""
    final = _last_event_date(tasks, "Inspections", "Final")
    if final is not pd.NaT:
        return final
    return _last_event_date(tasks, "Closed", "Close")


# ── Per-record repair logic ─────────────────────────────────────────────────

def _repair_record(row, d: dict, repairs: dict):
    """Populate *repairs* with corrected values for a single Monterey Park record."""
    tasks = d.get("tasks") or []
    data_status = d.get("status")
    if isinstance(data_status, str):
        data_status = data_status.strip() or None

    # -- STATUS_NORMALIZED --
    current_status = row["STATUS_NORMALIZED"]
    expected = _STATUS_MAP.get(data_status) if data_status else None
    if expected is not None:
        if pd.isna(current_status):
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"
        elif current_status != expected:
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FIXED"

    effective_status = repairs.get("STATUS_NORMALIZED", current_status)

    # -- FILE_DATE (application / DATA.date) --
    apply = _safe_to_datetime(d.get("date"))
    if apply is pd.NaT:
        search = d.get("search_data") if isinstance(d.get("search_data"), dict) else {}
        apply = _safe_to_datetime(search.get("Date"))
    if apply is not pd.NaT:
        if pd.isna(row["FILE_DATE"]):
            repairs["FILE_DATE"] = apply
            repairs["FILE_DATE_FLAG"] = "FILLED"
        elif not _dates_equal(row["FILE_DATE"], apply):
            repairs["FILE_DATE"] = apply
            repairs["FILE_DATE_FLAG"] = "FIXED"

    # -- PERMIT_DATE --
    permit = _permit_date_from_tasks(tasks, data_status)
    if not pd.isna(row["PERMIT_DATE"]):
        # Prefer Permit Issuance when present and mismatched
        issued_only = _event_dates(
            tasks,
            "Permit Issuance",
            lambda m: m in ("Issued", "Issued Temporary"),
        )
        if issued_only and not _dates_equal(row["PERMIT_DATE"], min(issued_only)):
            repairs["PERMIT_DATE"] = min(issued_only)
            repairs["PERMIT_DATE_FLAG"] = "FIXED"
    elif effective_status in ("Active", "Final") and permit is not pd.NaT:
        repairs["PERMIT_DATE"] = permit
        repairs["PERMIT_DATE_FLAG"] = "FILLED"

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
        # Spurious FINAL_DATE on non-Final rows
        repairs["FINAL_DATE"] = pd.NaT
        repairs["FINAL_DATE_FLAG"] = "FIXED"


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Monterey Park permit records using information from the raw DATA JSON.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Monterey Park".  Must contain
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

    return out


# ── CLI: run standalone to preview repair stats ─────────────────────────────

if __name__ == "__main__":
    import os
    from dotenv import load_dotenv

    load_dotenv("/Users/ekung/projects/la-permits-data/.env")
    MY_DATA_PATH = os.getenv("MY_DATA_PATH")
    filepath = os.path.join(MY_DATA_PATH, "processed_data", "permits_la_sample.parquet")
    df = pd.read_parquet(filepath)
    city = df[(df["JURISDICTION"] == "Monterey Park") & (df["STATE"] == "CA")].copy()

    print(f"Monterey Park records: {len(city):,}\n")

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

"""Data repair for Santa Clarita (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Santa Clarita DATA is an Accela Citizen Access scrape with two key-set
variants (same repair logic):

  - tasks_full:   top-level keys include ``tasks``, ``status``, ``date``,
                  ``search_data``, plus ``contacts``, ``fees_details``,
                  ``inspections``, ``conditions``, etc.
  - tasks_sparse: same core keys but without contacts / fees_details /
                  inspections / related_records (mostly older Finaled
                  stubs with empty task event lists).

Canonical mappings:
  - DATA.status                         → STATUS_NORMALIZED
  - DATA.date / search_data.Date        → FILE_DATE
  - Permit Issuance / Issue*            → PERMIT_DATE
      (``Issue MEP Permit``, ``Issue BLD Permit``, ``Issued``;
       NOT ``Ready to Issue``)
  - Inspections / Finaled (latest)      → FINAL_DATE
      (fallback: C of O / Approved)

Known issues repaired:
  - STATUS_NORMALIZED derived from stale STATUS_ORIGINAL disagrees with
    DATA.status on 8 rows (e.g. Finaled labeled Active; Issued labeled
    In Review; Expired labeled In Review; X_Re-Activated labeled
    In Review) → FIXED.
  - PERMIT_DATE set to Permit Issuance / Ready to Issue instead of the
    later Issue BLD Permit event (1 row) → FIXED.
  - Missing PERMIT_DATE on Issued rows remapped to Active → FILLED from
    Permit Issuance / Issue*.
  - Missing FINAL_DATE on Finaled rows remapped from Active → FILLED
    from Inspections / Finaled.
  - FINAL_DATE matching an earlier Inspections / Finaled when a later
    Finaled event exists (1 row) → FIXED to the latest Finaled date.

Not repairable / left as-is:
  - FILE_DATE already matches DATA.date for all sample rows.
  - 8 Special Inspector rows have blank DATA.status and search_data
    Status → STATUS_NORMALIZED stays missing.
  - ~1,170+ Finaled / Active rows (mostly pre-2018 migrations and
    sparse stubs) have empty task events → PERMIT_DATE / FINAL_DATE
    stay missing. Fee invoice dates are not used as issuance proxies.
  - One Finaled row has empty ``tasks`` but pre-populated PERMIT_DATE /
    FINAL_DATE with no workflow events to validate → left unchanged.
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
    if "tasks" in keys and "status" in keys:
        # Full ACA detail scrape vs sparse listing-detail hybrid.
        if {"contacts", "fees_details", "inspections"} & keys:
            return "tasks_full"
        return "tasks_sparse"
    if "search_data" in keys and "tasks" not in keys:
        return "search_data_only"
    return "unknown"


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


def _is_issue_mark(marked: Optional[str]) -> bool:
    """True for Permit Issuance marks that mean the permit was issued."""
    if not marked or not isinstance(marked, str):
        return False
    m = marked.strip()
    if not m or m == "Ready to Issue":
        return False
    # "Issue MEP Permit", "Issue BLD Permit", "Issued", …
    return m == "Issued" or m.lower().startswith("issue ")


# ── Status mapping ──────────────────────────────────────────────────────────

_STATUS_MAP = {
    # Final
    "Finaled": "Final",
    "Closed": "Final",
    # Active
    "Issued": "Active",
    "Permit Issued": "Active",
    "X_Active": "Active",
    "X_Re-Activated": "Active",
    # Inactive
    "Expired": "Inactive",
    "Application Expired": "Inactive",
    "Inactive": "Inactive",
    "Cancelled": "Inactive",
    "Canceled": "Inactive",
    "Denied": "Inactive",
    "Void": "Inactive",
    "Withdrawn": "Inactive",
    # In Review
    "In Prescreen Review": "In Review",
    "In Plan Review": "In Review",
    "Ready for Fee Assessment": "In Review",
    "Ready for Plans Distribution": "In Review",
    "Returned to Applicant": "In Review",
    "Submitted": "In Review",
    "All Agencies Approved": "In Review",
    "OTC Comments Issued": "In Review",
    "Plan/Document Approved": "In Review",
    "Transferred": "In Review",
}


def _map_status(data_status: Optional[str]) -> Optional[str]:
    if not data_status or not isinstance(data_status, str):
        return None
    key = data_status.strip()
    return _STATUS_MAP.get(key) if key else None


def _permit_date_from_tasks(tasks: list):
    """Earliest Permit Issuance / Issue* date (excludes Ready to Issue)."""
    dates = _event_dates(tasks, "Permit Issuance", _is_issue_mark)
    return min(dates) if dates else pd.NaT


def _final_date_from_tasks(tasks: list):
    """Latest Inspections / Finaled, else C of O / Approved."""
    finals = _event_dates(tasks, "Inspections", lambda m: m == "Finaled")
    if finals:
        return max(finals)
    co = _event_dates(tasks, "C of O", lambda m: m == "Approved")
    if co:
        return max(co)
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
        # Spurious FINAL_DATE on non-Final rows.
        repairs["FINAL_DATE"] = pd.NaT
        repairs["FINAL_DATE_FLAG"] = "FIXED"


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Santa Clarita permit records using information from the raw DATA JSON
    column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Santa Clarita".  Must contain
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
        if schema in ("tasks_full", "tasks_sparse"):
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
    city = df[(df["JURISDICTION"] == "Santa Clarita") & (df["STATE"] == "CA")].copy()

    print(f"Santa Clarita records: {len(city):,}\n")

    repaired = data_repair(city)

    if AGENT_DATA_PATH:
        out_path = os.path.join(
            AGENT_DATA_PATH, "processed_data", "permits_ca_santa_clarita_repaired.parquet"
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

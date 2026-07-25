"""Data repair for Alameda (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Alameda DATA is an Accela Citizen Access scrape. Nearly all sample rows
share the same top-level key set; INFERRED_SCHEMA distinguishes workflow
richness:

  - tasks_inspections: non-empty tasks + non-empty inspections
  - tasks_only:        non-empty tasks, no inspections
  - inspections_only:  inspections present, no usable tasks
  - header_only:       status/date/search_data only (empty workflows)

Canonical mappings:
  - DATA.status                              → STATUS_NORMALIZED
  - DATA.date / search_data Date             → FILE_DATE
      (override: Application / APPLIED|RECEIVED when Accela date is a
       later migration/import stamp)
  - Ready to Issue / Issued                  → PERMIT_DATE
      (fallback: Application / Issued|ISSUED; Applied / Issued;
       for Approved rows: earliest * / Approved task event)
  - Inspection / Finaled|Final|Inspection Complete → FINAL_DATE
      (fallback: Final* inspections with Approved/PASSED;
       Certificate of Occupancy / Issued;
       Application / FINALED|FINAL)

Known issues repaired:
  - 14 Application Complete (Building - Pre Application) rows wrongly
    mapped to Final → FIXED to In Review.
  - 1 Finaled row mapped to Active → FIXED to Final.
  - Unmapped fire-safety / entitlement statuses (OK to Inspect,
    Initial Inspection Passed, Fee Payment Required, etc.) → FILLED.
  - ~55 FILE_DATE values that are Accela import stamps (often 2006–2008)
    while Application/APPLIED preserves the historical filing date → FIXED.
  - Missing PERMIT_DATE on Active/Final rows with Applied/Issued or
    Application/Issued events (existing populated values already match
    Ready to Issue / Issued) → FILLED.
  - Missing FINAL_DATE on Final rows with final inspection / Inspection
    Finaled / Application FINALED history → FILLED.

Not repairable / left as-is:
  - 18 rows with blank DATA.status and blank search_data Status →
    STATUS_NORMALIZED stays missing.
  - Active/Final rows with no dated issuance event (workflow stuck at
    TBD / Routing / Fees Due) → PERMIT_DATE stays missing.
  - Final rows with no final inspection, Inspection/Finaled, or
    Application/FINALED signal (many Closed / project shells) →
    FINAL_DATE stays missing.
"""

import json
import math
import re
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


def _any_event_dates(tasks: list, marked_pred) -> list:
    """Return datetimes for any task event matching marked_pred(marked)."""
    dates = []
    for t in tasks or []:
        if not isinstance(t, dict):
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

# DATA.status → STATUS_NORMALIZED. Lookup is case-insensitive via _map_status.
_STATUS_MAP = {
    # Final
    "Finaled": "Final",
    "FINALED": "Final",
    "Final": "Final",
    "FINAL": "Final",
    "Closed": "Final",
    "Complete": "Final",
    "Compliant": "Final",
    # Active
    "Issued": "Active",
    "Approved": "Active",
    "APPROVED": "Active",
    "OK to Inspect": "Active",
    "Initial Inspection Passed": "Active",
    "First Re-Inspection Passed": "Active",
    # Inactive
    "Expired": "Inactive",
    "EXPIRED": "Inactive",
    "Canceled": "Inactive",
    "CANCELED": "Inactive",
    "Cancelled": "Inactive",
    "Void": "Inactive",
    "VOID": "Inactive",
    "Revoked": "Inactive",
    "Withdrawn": "Inactive",
    "WITHDRAWN": "Inactive",
    "WITHDRWN": "Inactive",
    "Denied": "Inactive",
    "FAILED": "Inactive",
    "Failed": "Inactive",
    "DUPLICATE": "Inactive",
    "DUPLCATE": "Inactive",
    # In Review
    "Applied": "In Review",
    "Plan Review": "In Review",
    "Hold": "In Review",
    "Ready to Issue": "In Review",
    "Under Review": "In Review",
    "Received": "In Review",
    "INCOMPLETE": "In Review",
    "Incomplete Submittal": "In Review",
    "Exempt": "In Review",
    "Designated Soft Story": "In Review",
    "Non Essential Construction": "In Review",
    # Pre-application intake complete — not a finaled permit.
    "Application Complete": "In Review",
    "Fee Payment Required": "In Review",
    "10-day Public Notice": "In Review",
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
    return m.strip().casefold() == "issued"


def _is_final_task_marked(m) -> bool:
    if not isinstance(m, str):
        return False
    s = m.strip().casefold()
    return s.startswith("final") or s == "inspection complete"


_FINAL_INSPECTION_PASS = {
    "pass",
    "passed",
    "approved",
    "partial approval",
}


def _file_date_from_data(d: dict):
    """Prefer historical Application/APPLIED over Accela import stamp."""
    tasks = d.get("tasks") or []

    applied = _event_dates(
        tasks,
        "Application",
        lambda m: isinstance(m, str) and m.strip().upper() in ("APPLIED", "RECEIVED"),
    )
    accepted = _event_dates(
        tasks,
        "Applied",
        lambda m: isinstance(m, str)
        and m.strip() in ("Application Accepted", "Application Complete"),
    )

    header = _safe_to_datetime(d.get("date"))
    if header is pd.NaT:
        sd = d.get("search_data") if isinstance(d.get("search_data"), dict) else {}
        header = _safe_to_datetime(sd.get("File Date") or sd.get("Date"))

    # Historical migrations: Application/APPLIED is years earlier than DATA.date.
    if applied:
        earliest = min(applied)
        if header is pd.NaT or earliest.normalize() <= header.normalize():
            return earliest

    if accepted:
        earliest = min(accepted)
        if header is pd.NaT or earliest.normalize() <= header.normalize():
            return earliest

    return header


def _permit_date_from_tasks(tasks: list, data_status: Optional[str]):
    """Earliest canonical issuance / approval date from workflow tasks."""
    # Primary path used by already-populated PERMIT_DATE values.
    dates = _event_dates(tasks, "Ready to Issue", _is_issued_marked)
    if dates:
        return min(dates)

    # Legacy / simple Accela shells stamp issuance on Application.
    dates = _event_dates(
        tasks,
        "Application",
        lambda m: isinstance(m, str) and m.strip().casefold() == "issued",
    )
    if dates:
        return min(dates)

    # OTC / Public Works path: Applied marked Issued (often same-day as file).
    dates = _event_dates(tasks, "Applied", _is_issued_marked)
    if dates:
        return min(dates)

    # Zoning / discretionary approvals never hit Ready to Issue.
    if data_status and data_status.strip().casefold() == "approved":
        dates = _any_event_dates(
            tasks,
            lambda m: isinstance(m, str) and m.strip().casefold() == "approved",
        )
        if dates:
            return min(dates)

    return pd.NaT


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
    """Latest completion / sign-off date from tasks and inspections."""
    finals = _event_dates(tasks, "Inspection", _is_final_task_marked)
    if finals:
        return max(finals)

    insp_final = _final_date_from_inspections(inspections)
    if insp_final is not pd.NaT:
        return insp_final

    cos = _event_dates(
        tasks,
        "Certificate of Occupancy",
        lambda m: isinstance(m, str)
        and m.strip().casefold() in {"issued", "complete", "approved"},
    )
    if cos:
        return max(cos)

    # Legacy shells (esp. pre-Accela electrical) only stamp Application FINALED.
    app_final = _event_dates(
        tasks,
        "Application",
        lambda m: isinstance(m, str) and m.strip().upper() in ("FINALED", "FINAL"),
    )
    if app_final:
        return max(app_final)

    return pd.NaT


# ── Per-schema repair logic ─────────────────────────────────────────────────

def _repair_accela(row, d: dict, repairs: dict):
    """Repair an Accela Citizen Access Alameda record."""
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
    issued = _permit_date_from_tasks(tasks, data_status)
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
    Alameda permit records using information from the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Alameda".  Must contain
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

    load_dotenv("/Users/ekung/projects/la-permits-data/.env")
    MY_DATA_PATH = os.getenv("MY_DATA_PATH")
    AGENT_DATA_PATH = os.getenv("AGENT_DATA_PATH")
    filepath = os.path.join(MY_DATA_PATH, "processed_data", "permits_ca_sample.parquet")
    df = pd.read_parquet(filepath)
    city = df[(df["JURISDICTION"] == "Alameda") & (df["STATE"] == "CA")].copy()

    print(f"Alameda records: {len(city):,}\n")

    repaired = data_repair(city)

    if AGENT_DATA_PATH:
        out_path = os.path.join(
            AGENT_DATA_PATH, "processed_data", "permits_ca_alameda_repaired.parquet"
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
    print(f"  {n_has:>4,} / {len(repaired):>4,} ({n_has / len(repaired):.1%})")

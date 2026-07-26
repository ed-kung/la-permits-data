"""Data repair for Fremont (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Fremont DATA is an Accela Citizen Access payload. Sample rows share
top-level keys ``date``, ``tasks``, ``status``, ``address``,
``details``, ``job_value``, ``valuation``, ``total_fees``,
``record_type``, ``search_data``, and ``more_details``. Two content
variants appear:

  - accela_full:  also has ``inspections`` (and usually conditions /
                  fees_details / related_records / contacts)
  - accela_basic: workflow / search fields only (no inspections block)

Canonical mappings:

  - DATA.status                                              → STATUS_NORMALIZED
  - search_data.Date / DATA.date                             → FILE_DATE
  - Ready to Issue / Issued|Revision Issued
    (fallback: Application Submittal / Issued)               → PERMIT_DATE
  - Inspections / Finaled*
    (fallback: Final Admin Processing / Closed|Archived;
     then Pass/DONE *Final* inspections)                     → FINAL_DATE

Known issues repaired:
  - Revision Issued was labeled In Review (67 rows) despite an
    issued revision → FIXED to Active.
  - UNK historical shells were labeled Final (29 rows) with no
    completion evidence → FIXED (cleared).
  - One Issued row with Inspections Finaled + Admin Closed still
    labeled Active → FIXED to Final (lagged DATA.status).
  - Missing PERMIT_DATE on Active / Final rows with Ready to Issue
    or Application Submittal Issued events → FILLED.
  - Missing FINAL_DATE on Final rows from Finaled events, Closed
    admin events, or non-migration Final inspections → FILLED.
  - Spurious PERMIT_DATE on Ready to Issue (In Review) rows that
    used a pre-issuance Ready to Issue date → cleared (FIXED).
  - Spurious FINAL_DATE on non-Final rows → cleared (FIXED).

Not repairable / left as-is:
  - FILE_DATE already matches search_data.Date / DATA.date for all
    2,001 sample rows.
  - 352 Historical Project rows with blank DATA.status remain
    STATUS_NORMALIZED null (no status signal in DATA).
  - Active / Final rows with empty task events and no usable
    issuance / final inspection remain date-missing.
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
    """Parse a date value, returning pd.NaT on failure / TBD / sentinel years."""
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return pd.NaT
    if isinstance(val, str) and not str(val).strip():
        return pd.NaT
    s = str(val).strip()
    if s.upper() in ("TBD", "NONE", "NULL", "N/A", "NA"):
        return pd.NaT
    if "9999" in s:
        return pd.NaT
    try:
        dt = pd.to_datetime(s)
    except (ValueError, TypeError):
        return pd.NaT
    if dt is pd.NaT or pd.isna(dt):
        return pd.NaT
    if int(dt.year) >= 9999:
        return pd.NaT
    return dt


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
    if "tasks" not in keys or "status" not in keys:
        return "unknown"
    if "inspections" in keys:
        return "accela_full"
    return "accela_basic"


def _parse_event(event: dict):
    """Return (marked_as, on_date_str) from an Accela task event."""
    marked = event.get("Marked as ")
    on_val = event.get(" on ")
    if marked is None or on_val is None:
        for k, v in event.items():
            if k == "html" or not isinstance(k, str):
                continue
            ks = k.replace("\xa0", " ").strip().lower()
            if marked is None and ("marked as" in ks or "updated as" in ks):
                marked = v
            elif on_val is None and ks == "on":
                on_val = v
    if isinstance(marked, str):
        marked = marked.strip()
    if on_val is not None:
        on_val = str(on_val).strip()
    return marked, on_val


def _event_dates(tasks: list, task_names, marked_pred) -> list:
    """Return datetimes for task events matching marked_pred(marked)."""
    if isinstance(task_names, str):
        task_names = {task_names}
    else:
        task_names = set(task_names)
    dates = []
    for t in tasks or []:
        if not isinstance(t, dict):
            continue
        name = (t.get("name") or "").strip()
        if name not in task_names:
            continue
        for e in t.get("events") or []:
            if not isinstance(e, dict):
                continue
            marked, on_val = _parse_event(e)
            if not marked_pred(marked):
                continue
            dt = _safe_to_datetime(on_val)
            if dt is not pd.NaT:
                dates.append(dt)
    return dates


def _has_finaled_event(tasks: list) -> bool:
    """True if Inspections workflow was marked Finaled*."""
    return bool(
        _event_dates(
            tasks,
            "Inspections",
            lambda m: isinstance(m, str) and m.startswith("Finaled"),
        )
    )


# ── Status mapping ──────────────────────────────────────────────────────────

# DATA.status → STATUS_NORMALIZED (lookup is case-insensitive)
_STATUS_MAP = {
    # Final — completed / closed out
    "Finaled": "Final",
    "Final": "Final",
    "Closed": "Final",
    "Complete": "Final",
    "Completed": "Final",
    # Active — issued / revision issued (in force)
    "Issued": "Active",
    "Issued - Revision Pending": "Active",
    "Revision Issued": "Active",
    "Approved": "Active",
    "Active": "Active",
    # Inactive — expired / cancelled / withdrawn / void
    "Expired": "Inactive",
    "Cancelled": "Inactive",
    "Cancel": "Inactive",
    "Void": "Inactive",
    "Withdrawn": "Inactive",
    "Denied": "Inactive",
    "Inactive": "Inactive",
    # In Review — pre-issuance / plan check cycles
    "Cycle 1": "In Review",
    "Cycle 2": "In Review",
    "Incomplete Submittal": "In Review",
    "Out to Applicant": "In Review",
    "Pending Payment": "In Review",
    "Prep for Issuance": "In Review",
    "Ready to Assign": "In Review",
    "Ready to Issue": "In Review",
    "Ready to Issue - Docs Pending": "In Review",
    "Received": "In Review",
    "In Review": "In Review",
    "Submitted": "In Review",
    "Pending": "In Review",
    # Explicitly unmapped historical shells (do not treat as Final)
    # "UNK" intentionally omitted
}

_STATUS_MAP_LOWER = {k.lower(): v for k, v in _STATUS_MAP.items()}


def _map_status(data_status: Optional[str]) -> Optional[str]:
    if not data_status or not isinstance(data_status, str):
        return None
    key = data_status.strip()
    if not key:
        return None
    # UNK / unknown — explicitly unmapped
    if key.upper() in ("UNK", "UNKNOWN", "N/A", "NA", "NONE"):
        return None
    return _STATUS_MAP.get(key) or _STATUS_MAP_LOWER.get(key.lower())


# ── Date extractors ─────────────────────────────────────────────────────────

def _file_date_from_data(d: dict):
    """Official Accela file / open date from search_data or top-level date."""
    sd = d.get("search_data") if isinstance(d.get("search_data"), dict) else {}
    for key in ("Date", "File Date", "Created Date"):
        dt = _safe_to_datetime(sd.get(key))
        if dt is not pd.NaT:
            return dt
    return _safe_to_datetime(d.get("date"))


def _permit_date_from_tasks(tasks: list):
    """Earliest Ready to Issue issuance; fallback Application Submittal Issued."""
    issued = _event_dates(
        tasks,
        {"Ready to Issue", "Permit Issuance"},
        lambda m: (m or "") in ("Issued", "Revision Issued"),
    )
    if issued:
        return min(issued)
    # Instant / OTC permits often mark Application Submittal as Issued.
    issued = _event_dates(
        tasks,
        "Application Submittal",
        lambda m: (m or "") in ("Issued", "Revision Issued"),
    )
    return min(issued) if issued else pd.NaT


def _final_date_from_tasks(tasks: list):
    """Prefer Inspections Finaled*; else Final Admin Processing Closed/Archive."""
    finals = _event_dates(
        tasks,
        "Inspections",
        lambda m: isinstance(m, str)
        and (m.startswith("Finaled") or m in ("Final", "Complete", "Completed")),
    )
    if finals:
        return max(finals)

    def _is_close_mark(m):
        s = (m or "").strip().lower()
        return (
            s.startswith("close")
            or "archiv" in s
            or s in ("final", "finaled", "complete", "completed")
        )

    closed = _event_dates(
        tasks,
        {"Final Admin Processing", "Final Processing", "Closed"},
        _is_close_mark,
    )
    return max(closed) if closed else pd.NaT


_PASS_INSPECTION_STATUSES = {
    "done",
    "pass",
    "passed",
    "approved",
    "finaled",
    "complete",
    "completed",
    "appr",
    "pass - co not required",
}


def _is_migration_date(dt) -> bool:
    """Fremont Accela cutover stamped many historical inspections 2017-07-01."""
    if dt is pd.NaT or pd.isna(dt):
        return False
    return int(dt.year) == 2017 and int(dt.month) == 7 and int(dt.day) == 1


def _final_date_from_inspections(inspections: list):
    """Latest Status Date from Final-titled passed inspections.

    Prefers ``999 Permit Final``, then ``199 Building Final``, then any
    other *Final* title. Skips pre-final titles and the 2017-07-01
    migration sentinel when a non-sentinel date exists.
    """
    permit, building, other = [], [], []
    for insp in inspections or []:
        if not isinstance(insp, dict):
            continue
        title = str(insp.get("Title") or "")
        if re.search(r"pre\s*[- ]?\s*final", title, re.I):
            continue
        if not re.search(r"\bfinal\b", title, re.I):
            continue
        status = str(insp.get("Status") or "").strip().lower()
        if status not in _PASS_INSPECTION_STATUSES:
            continue
        dt = _safe_to_datetime(insp.get("Status Date"))
        if dt is pd.NaT:
            continue
        if re.search(r"999\s*permit\s*final|permit\s*final", title, re.I):
            permit.append(dt)
        elif re.search(r"199\s*building\s*final|building\s*final", title, re.I):
            building.append(dt)
        else:
            other.append(dt)

    for pool in (permit, building, other):
        if not pool:
            continue
        non_migr = [d for d in pool if not _is_migration_date(d)]
        use = non_migr if non_migr else pool
        return max(use)
    return pd.NaT


def _final_date_from_data(d: dict):
    """Prefer Finaled workflow; else Closed admin; else Final inspections."""
    from_tasks = _final_date_from_tasks(d.get("tasks") or [])
    if from_tasks is not pd.NaT:
        return from_tasks
    return _final_date_from_inspections(d.get("inspections") or [])


# ── Per-record repair logic ─────────────────────────────────────────────────

def _repair_record(row, d: dict, repairs: dict):
    """Populate *repairs* with corrected values for one Fremont record."""
    tasks = d.get("tasks") or []
    data_status = d.get("status")
    if isinstance(data_status, str):
        data_status = data_status.strip() or None
    else:
        data_status = None

    # -- STATUS_NORMALIZED --
    current_status = row["STATUS_NORMALIZED"]
    expected = _map_status(data_status)

    # Lagged Issued status: workflow already Finaled → treat as Final.
    if expected == "Active" and _has_finaled_event(tasks):
        expected = "Final"

    if expected is not None:
        if pd.isna(current_status):
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"
        elif current_status != expected:
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FIXED"
    elif data_status and str(data_status).strip().upper() in (
        "UNK",
        "UNKNOWN",
        "N/A",
        "NA",
        "NONE",
    ):
        # Incorrect Final (or other) label on unmapped historical shell.
        if not pd.isna(current_status):
            repairs["STATUS_NORMALIZED"] = np.nan
            repairs["STATUS_NORMALIZED_FLAG"] = "FIXED"

    effective_status = repairs.get("STATUS_NORMALIZED", current_status)
    if isinstance(effective_status, float) and math.isnan(effective_status):
        effective_status = None

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

    if effective_status in ("Active", "Final"):
        if issued is not pd.NaT:
            if pd.isna(current_permit):
                repairs["PERMIT_DATE"] = issued
                repairs["PERMIT_DATE_FLAG"] = "FILLED"
            elif not _dates_equal(current_permit, issued):
                repairs["PERMIT_DATE"] = issued
                repairs["PERMIT_DATE_FLAG"] = "FIXED"
    elif not pd.isna(current_permit):
        # Spurious PERMIT_DATE on pre-issuance / inactive rows (e.g. Ready
        # to Issue date stored as PERMIT_DATE).
        if issued is pd.NaT or not _dates_equal(current_permit, issued):
            repairs["PERMIT_DATE"] = pd.NaT
            repairs["PERMIT_DATE_FLAG"] = "FIXED"
        # If a true Issued event exists but status is still In Review,
        # keep the issuance date (status repair should have caught it).

    # -- FINAL_DATE --
    final = _final_date_from_data(d)
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
    Fremont permit records using the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Fremont".
        Must contain columns STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE,
        FINAL_DATE, and DATA.

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
        if schema in ("accela_full", "accela_basic"):
            _repair_record(row, d, repairs)

        for key, value in repairs.items():
            out.at[idx, key] = value

    return out


# ── CLI: run standalone to preview repair stats ─────────────────────────────

if __name__ == "__main__":
    import os
    from dotenv import load_dotenv, find_dotenv

    load_dotenv(find_dotenv())
    MY_DATA_PATH = os.getenv("MY_DATA_PATH")
    AGENT_DATA_PATH = os.getenv("AGENT_DATA_PATH")
    filepath = os.path.join(MY_DATA_PATH, "processed_data", "permits_ca_sample.parquet")
    df = pd.read_parquet(filepath)
    city = df[(df["JURISDICTION"] == "Fremont") & (df["STATE"] == "CA")].copy()

    print(f"Fremont records: {len(city):,}\n")

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

    print("\nRemaining gaps:")
    for status in ["Active", "Final"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        print(
            f"  {status}: PERMIT miss={sub['PERMIT_DATE'].isna().sum()}, "
            f"FINAL miss={sub['FINAL_DATE'].isna().sum()} / {len(sub)}"
        )

    if AGENT_DATA_PATH:
        out_path = os.path.join(AGENT_DATA_PATH, "fremont_repaired_sample.parquet")
        for col in ("FILE_DATE", "PERMIT_DATE", "FINAL_DATE"):
            repaired[col] = pd.to_datetime(repaired[col], errors="coerce")
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote {out_path}")

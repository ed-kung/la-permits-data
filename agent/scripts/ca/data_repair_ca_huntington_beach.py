"""Data repair for Huntington Beach (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Huntington Beach DATA is an Accela Citizen Access payload. All sample
rows share top-level keys ``date``, ``tasks``, ``status``, ``address``,
``details``, ``contacts``, ``job_value``, ``valuation``, ``total_fees``,
``record_type``, ``search_data``, ``more_details``, and
``address_lines``. Two content variants appear:

  - accela_full:  also has ``conditions``, ``inspections``,
                  ``fees_details``, ``related_records``
  - accela_basic: workflow / search fields only (no inspections block)

Canonical mappings:

  - DATA.status                                              → STATUS_NORMALIZED
  - search_data.Date / DATA.date                             → FILE_DATE
  - Permit Issuance / Issued (fallback: Open / Issued)       → PERMIT_DATE
  - Closed / Close* (fallback: Approved Final* inspections)  → FINAL_DATE

Known issues repaired:
  - STATUS_ORIGINAL lagged DATA.status for 12 Finaled rows still labeled
    Active (STATUS_ORIGINAL=issued) → FIXED to Final.
  - Two Issued rows still labeled In Review (STATUS_ORIGINAL=incomplete
    / pending payment) → FIXED to Active.
  - 41 unmapped Accela statuses (Do Not Inspect, Enrolled, Pending
    Self-Correct, Plans Routed, Released) left STATUS_NORMALIZED null
    → FILLED.
  - Archived was labeled In Review → FIXED to Inactive.
  - Missing PERMIT_DATE on Active / Final rows with Permit Issuance /
    Issued (or Open / Issued) → FILLED.
  - Missing FINAL_DATE on Final rows with Closed / Close or Approved
    Final* inspections (incl. Approved - Issue CofO) → FILLED.
  - Spurious FINAL_DATE on Active Issued rows that still carry a Closed
    task date while DATA.status remains Issued → cleared (FIXED).

Not repairable / left as-is:
  - FILE_DATE already matches search_data.Date / DATA.date for all
    1,999 sample rows (Application Submittal / Accepted can differ by
    a day or two and is not used to overwrite).
  - ~200 Active / Final rows (Approved, Active occupancy shells, Closed
    environmental / CofO records, etc.) have no Permit Issuance event
    → PERMIT_DATE left missing.
  - ~260 Final / Finaled rows with empty Closed events and no usable
    Final* inspection, plus Completed rows whose Closed date is the
    sentinel 12/31/9999 → FINAL_DATE left missing.
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
        # Fall back to NBSP-padded / HTML variants seen in other Accela cities.
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


# ── Status mapping ──────────────────────────────────────────────────────────

# DATA.status → STATUS_NORMALIZED (lookup is case-insensitive)
_STATUS_MAP = {
    # Final — completed / closed out / recorded
    "Finaled": "Final",
    "Final": "Final",
    "Closed": "Final",
    "Complete": "Final",
    "Completed": "Final",
    "Granted": "Final",
    "Recorded": "Final",
    "Released": "Final",
    # Active — issued / approved / enrolled in force
    "Issued": "Active",
    "Approved": "Active",
    "Active": "Active",
    "Enrolled": "Active",
    # Inactive — expired / cancelled / archived / do-not-inspect
    "Expired": "Inactive",
    "Expired - Hold": "Inactive",
    "Expired - NOC": "Inactive",
    "Expired Plan Review": "Inactive",
    "Cancelled": "Inactive",
    "Cancel": "Inactive",
    "Void": "Inactive",
    "Denied": "Inactive",
    "Inactive": "Inactive",
    "Archived": "Inactive",
    "Do Not Inspect": "Inactive",
    # In Review — pre-issuance / pending action
    "Pending": "In Review",
    "Submitted": "In Review",
    "Incomplete": "In Review",
    "Application Incomplete": "In Review",
    "Accepted": "In Review",
    "In Review": "In Review",
    "Pending Payment": "In Review",
    "Pending Document": "In Review",
    "Pending Self-Correct": "In Review",
    "Plans Routed": "In Review",
}

_STATUS_MAP_LOWER = {k.lower(): v for k, v in _STATUS_MAP.items()}


def _map_status(data_status: Optional[str]) -> Optional[str]:
    if not data_status or not isinstance(data_status, str):
        return None
    key = data_status.strip()
    if not key:
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
    """Earliest Permit Issuance / Issued; fallback Open / Issued."""
    issued = _event_dates(tasks, "Permit Issuance", lambda m: (m or "") == "Issued")
    if issued:
        return min(issued)
    opened = _event_dates(tasks, "Open", lambda m: (m or "") == "Issued")
    return min(opened) if opened else pd.NaT


def _final_date_from_tasks(tasks: list):
    """Latest Closed task date marked Close / Final / Complete*."""
    def _is_close_mark(m):
        s = (m or "").strip().lower()
        return (
            s.startswith("close")
            or "final" in s
            or s in ("complete", "completed")
        )

    dates = _event_dates(tasks, "Closed", _is_close_mark)
    return max(dates) if dates else pd.NaT


def _final_date_from_inspections(inspections: list):
    """Latest Status Date from Final-titled approved inspections."""
    dates = []
    for insp in inspections or []:
        if not isinstance(insp, dict):
            continue
        title = str(insp.get("Title") or "")
        if re.search(r"pre\s*[- ]?\s*final", title, re.I):
            continue
        if not re.search(r"\bfinal\b", title, re.I):
            continue
        status = str(insp.get("Status") or "").strip().lower()
        if status not in (
            "approved",
            "approved - issue cofo",
            "passed",
            "finaled",
            "complete",
            "completed",
        ):
            continue
        dt = _safe_to_datetime(insp.get("Status Date"))
        if dt is not pd.NaT:
            dates.append(dt)
    return max(dates) if dates else pd.NaT


def _final_date_from_data(d: dict):
    """Prefer Closed / Close; else Approved Final* inspections."""
    closed = _final_date_from_tasks(d.get("tasks") or [])
    if closed is not pd.NaT:
        return closed
    return _final_date_from_inspections(d.get("inspections") or [])


# ── Per-record repair logic ─────────────────────────────────────────────────

def _repair_record(row, d: dict, repairs: dict):
    """Populate *repairs* with corrected values for one Huntington Beach record."""
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
        # Spurious FINAL_DATE on non-Final rows (e.g. Issued with Closed).
        repairs["FINAL_DATE"] = pd.NaT
        repairs["FINAL_DATE_FLAG"] = "FIXED"


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Huntington Beach permit records using the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Huntington Beach".
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
    city = df[
        (df["JURISDICTION"] == "Huntington Beach") & (df["STATE"] == "CA")
    ].copy()

    print(f"Huntington Beach records: {len(city):,}\n")

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
        out_path = os.path.join(
            AGENT_DATA_PATH, "huntington_beach_repaired_sample.parquet"
        )
        for col in ("FILE_DATE", "PERMIT_DATE", "FINAL_DATE"):
            repaired[col] = pd.to_datetime(repaired[col], errors="coerce")
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote {out_path}")

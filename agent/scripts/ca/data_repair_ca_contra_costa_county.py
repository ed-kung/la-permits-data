"""Data repair for Contra Costa County (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Contra Costa County DATA is an Accela Citizen Access payload. Nearly all
rows share the tasks + inspections + fees_details key set; many legacy
converted records have empty task event histories (``tasks_shell``).

Canonical mappings:
  - DATA.status                                         → STATUS_NORMALIZED
  - search_data['File Date'] / DATA.date (when date-like)
    / earliest Application|Intake|Initialized event     → FILE_DATE
  - Permit Issuance / Issued                            → PERMIT_DATE
  - latest Inspections / Finaled, else Final*-titled
    Approved inspections[].Status Date                  → FINAL_DATE

Known issues repaired:
  - 27 unmapped Accela workflow statuses (Plan Check Distribution
    Begin, Send Payment Email, Sent Rider Issuance Email, etc.) left
    STATUS_NORMALIZED null → FILLED.
  - Approved 5 Year Cert labeled In Review → FIXED to Active (RRIP
    certificate in force).
  - Closed - Code Enforcement / Ent. Dec. Withdrawn / Recorded Lien
    previously null → FILLED as Final / Inactive / Inactive.
  - Missing FILE_DATE filled from Application Submittal / Intake /
    Initialized workflow events when DATA.date holds a record ID.
  - FINAL_DATE often stores the first Finaled date when a later
    Finaled exists → FIXED to the latest.
  - Missing FINAL_DATE on Final rows with Approved Final* inspections
    but empty Inspections/Finaled task marks → FILLED.
  - Spurious FINAL_DATE on Inactive rows → cleared (FIXED).

Not repairable / left as-is:
  - ~760 FILE_DATE gaps on legacy shells where DATA.date is a record
    number (e.g. BI326185) and task events are empty / TBD-only.
  - Active / Final rows with no Permit Issuance / Issued event →
    PERMIT_DATE stays missing (common on converted Finaled / Completed
    records).
  - 14 rows with blank DATA.status and no search_data.Status stay
    unmapped.
  - Final rows with neither Finaled task events nor Approved Final*
    inspections → FINAL_DATE stays missing.
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
    """Parse a date value, returning pd.NaT on failure / TBD / record IDs."""
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


_HTML_EVENT_RE = re.compile(
    r"updated as\s*<span>(.*?)</span>\s*on\s*<span>(.*?)</span>",
    re.I | re.S,
)


def _parse_event(event: dict):
    """Return (marked_as, on_date_str) from an Accela task event.

    Contra Costa event keys are often NBSP-padded variants such as
    ``Task updated as\\xa0``, ``\\xa0updated as\\xa0``, and ``\\xa0on\\xa0``.
    Prefer the HTML snippet when present.
    """
    html = (event.get("html") or "").replace("\xa0", " ")
    m = _HTML_EVENT_RE.search(html)
    if m:
        return m.group(1).strip(), m.group(2).strip().rstrip(".")

    marked = None
    on_val = None
    for k, v in event.items():
        if k == "html" or not isinstance(k, str):
            continue
        ks = k.replace("\xa0", " ").strip().lower()
        if "updated as" in ks or ks == "marked as":
            marked = v.strip() if isinstance(v, str) else v
        elif ks == "on":
            on_val = str(v).rstrip(".") if v is not None else None
    return marked, on_val


def _iter_task_nodes(tasks: list):
    """Yield (task_name, task_dict) for top-level tasks and subtasks."""
    for t in tasks or []:
        if not isinstance(t, dict):
            continue
        yield (t.get("name") or "").strip(), t
        for st in t.get("subtasks") or []:
            if isinstance(st, dict):
                yield (st.get("name") or "").strip(), st


def _has_dated_task_event(tasks: list) -> bool:
    for _, t in _iter_task_nodes(tasks):
        for e in t.get("events") or []:
            if not isinstance(e, dict):
                continue
            _, on_val = _parse_event(e)
            if _safe_to_datetime(on_val) is not pd.NaT:
                return True
    return False


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
    has_dated_event = _has_dated_task_event(tasks or [])

    if has_inspections and has_fees:
        return "tasks_full" if has_dated_event else "tasks_shell"
    if "contacts" in keys and not has_inspections:
        return "tasks_contacts"
    return "tasks_basic"


def _event_dates(tasks: list, task_names, marked_pred) -> list:
    """Return datetimes for task events matching marked_pred(marked)."""
    if isinstance(task_names, str):
        task_names = {task_names}
    else:
        task_names = set(task_names)
    dates = []
    for name, t in _iter_task_nodes(tasks):
        if name not in task_names:
            continue
        for e in t.get("events") or []:
            if not isinstance(e, dict):
                continue
            marked, on_val = _parse_event(e)
            marked = (marked or "").strip() if isinstance(marked, str) else marked
            if not marked_pred(marked):
                continue
            dt = _safe_to_datetime(on_val)
            if dt is not pd.NaT:
                dates.append(dt)
    return dates


def _all_dated_events(tasks: list, task_names) -> list:
    """All parseable event dates under the given task names (any mark)."""
    if isinstance(task_names, str):
        task_names = {task_names}
    else:
        task_names = set(task_names)
    dates = []
    for name, t in _iter_task_nodes(tasks):
        if name not in task_names:
            continue
        for e in t.get("events") or []:
            if not isinstance(e, dict):
                continue
            _, on_val = _parse_event(e)
            dt = _safe_to_datetime(on_val)
            if dt is not pd.NaT:
                dates.append(dt)
    return dates


# ── Status mapping ──────────────────────────────────────────────────────────

# DATA.status → STATUS_NORMALIZED (lookup is case-insensitive)
_STATUS_MAP = {
    # Final — completed / closed out
    "Finaled": "Final",
    "Final": "Final",
    "Completed": "Final",
    "Complete": "Final",
    "Closed": "Final",
    "CLOSED": "Final",
    "Closed - Code Enforcement": "Final",
    "OWN OCCU": "Final",
    # Active — issued or approved certificate in force
    "Issued": "Active",
    "Approved": "Active",
    "ACTIVE": "Active",
    "Active": "Active",
    "Approved 5 Year Cert": "Active",
    # Inactive
    "Expired": "Inactive",
    "Expired-NPI": "Inactive",
    "Withdrawn": "Inactive",
    "Withdrawn - No Activity": "Inactive",
    "Cancelled": "Inactive",
    "Void": "Inactive",
    "Closed - Incomplete": "Inactive",
    "Ent. Dec. Withdrawn": "Inactive",
    "Recorded Lien": "Inactive",
    # In Review — pre-issuance / pending agency or applicant action
    "Permit Review Initiated": "In Review",
    "BI Plan Check": "In Review",
    "PLAN CHK": "In Review",
    "Applied": "In Review",
    "Applied-Pending": "In Review",
    "Open": "In Review",
    "OPEN": "In Review",
    "Pending Applicant Response": "In Review",
    "PC OK'ed": "In Review",
    "Approved OTC": "In Review",
    "Approved OTC with Review": "In Review",
    "Payment received": "In Review",
    "Plan Check Distribution Begin": "In Review",
    "Intake Submittal": "In Review",
    "Intake Completed": "In Review",
    "Send Payment Email": "In Review",
    "Send payment email for renewal": "In Review",
    "Sent Rider Issuance Email": "In Review",
    "BI Approved": "In Review",
    "CD Approved": "In Review",
    "Assigned to Plans Examiner": "In Review",
    "Assigned To Planner": "In Review",
    "Assigned to Planner": "In Review",
    "Assign Intake to Planner": "In Review",
    "Assignment In Progress - Resid": "In Review",
    "Pending Distribution OTC": "In Review",
    "PC ONLY": "In Review",
    "Official permit filed": "In Review",
    "Application Accepted": "In Review",
    "Application Submitted": "In Review",
    "Planning Review": "In Review",
    "Revision Complete": "In Review",
    "Revision Submitted": "In Review",
    "Revision Needed": "In Review",
    "Pending Public Works Fee": "In Review",
    "Review for Completeness": "In Review",
    "Response Uploaded": "In Review",
    "Structural-Misc": "In Review",
}

_STATUS_MAP_LOWER = {k.lower(): v for k, v in _STATUS_MAP.items()}


def _map_status(data_status: Optional[str]) -> Optional[str]:
    if not data_status or not isinstance(data_status, str):
        return None
    key = data_status.strip()
    if not key:
        return None
    return _STATUS_MAP.get(key) or _STATUS_MAP_LOWER.get(key.lower())


_FILE_TASKS = {
    "Application Submittal",
    "Intake Submittal",
    "Intake Completed",
    "Initialized",
}


def _file_date_from_data(d: dict):
    """Best available application / file date from Accela payload."""
    sd = d.get("search_data") if isinstance(d.get("search_data"), dict) else {}
    for key in ("File Date", "Created Date", "Date"):
        dt = _safe_to_datetime(sd.get(key))
        if dt is not pd.NaT:
            return dt

    # DATA.date is often a record ID (BI326185); only use when date-like.
    dt = _safe_to_datetime(d.get("date"))
    if dt is not pd.NaT:
        return dt

    app_dates = _all_dated_events(d.get("tasks") or [], _FILE_TASKS)
    if app_dates:
        return min(app_dates)

    return pd.NaT


def _permit_date_from_tasks(tasks: list):
    """Earliest Permit Issuance / Issued date."""
    issued = _event_dates(tasks, "Permit Issuance", lambda m: m == "Issued")
    return min(issued) if issued else pd.NaT


def _final_date_from_tasks(tasks: list):
    """Latest Inspections / Finaled workflow date."""
    finals = _event_dates(
        tasks, ["Inspections", "Inspection"], lambda m: m == "Finaled"
    )
    return max(finals) if finals else pd.NaT


def _final_date_from_inspections(inspections: list):
    """Latest Status Date from Final-titled approved inspections.

    Excludes 'Pre Final' titles. Accepts Approved / Passed / Finaled /
    Complete(d) statuses (including single-letter 'F' used on some
    legacy Final Building rows).
    """
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
            "passed",
            "finaled",
            "complete",
            "completed",
            "f",
        ):
            continue
        dt = _safe_to_datetime(insp.get("Status Date"))
        if dt is not pd.NaT:
            dates.append(dt)
    return max(dates) if dates else pd.NaT


def _final_date_from_data(d: dict):
    """Prefer Inspections/Finaled task mark; else Final* inspections."""
    task_final = _final_date_from_tasks(d.get("tasks") or [])
    if task_final is not pd.NaT:
        return task_final
    return _final_date_from_inspections(d.get("inspections") or [])


# ── Per-record repair logic ─────────────────────────────────────────────────

def _repair_record(row, d: dict, repairs: dict):
    """Populate *repairs* with corrected values for one Contra Costa record."""
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
        # Spurious FINAL_DATE on non-Final rows (e.g. Expired with a
        # leftover Finaled mark, Closed - Incomplete).
        repairs["FINAL_DATE"] = pd.NaT
        repairs["FINAL_DATE_FLAG"] = "FIXED"


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Contra Costa County permit records using the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Contra Costa County".
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
        if schema in (
            "tasks_full",
            "tasks_shell",
            "tasks_contacts",
            "tasks_basic",
            "tasks_null",
        ):
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
    filepath = os.path.join(MY_DATA_PATH, "processed_data", "permits_ca_sample.parquet")
    df = pd.read_parquet(filepath)
    city = df[
        (df["JURISDICTION"] == "Contra Costa County") & (df["STATE"] == "CA")
    ].copy()

    print(f"Contra Costa County records: {len(city):,}\n")

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
        out_path = os.path.join(
            AGENT_DATA_PATH, "contra_costa_county_repaired_sample.parquet"
        )
        for col in ("FILE_DATE", "PERMIT_DATE", "FINAL_DATE"):
            repaired[col] = pd.to_datetime(repaired[col], errors="coerce")
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote {out_path}")

"""Data repair for Santa Clara County (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Santa Clara County DATA is an Accela Citizen Access scrape. Sample rows
share the same top-level keys (``status``, ``date``, ``tasks``,
``inspections``, ``search_data``, ``more_details``, …). Content variants
(INFERRED_SCHEMA):

  - accela_tasks:       dated workflow events under ``tasks``
  - accela_shell:       task shells present but no dated events
                        (common on older converted records)
  - accela_search_only: status/date/search_data only
  - unknown / missing

Canonical mappings:
  - DATA.status / search_data['Status']                   → STATUS_NORMALIZED
  - DATA.date / search_data['Date']                       → FILE_DATE
  - Issuance|Issued* / Permit Issuance|Permit Issued;
    else Submittal|Issued (online / minor)                → PERMIT_DATE
  - Inspections|Final Inspection Complete;
    Closeout|Project Complete / Final Permit Issued;
    Map Recording|Corner Record Filed / ROS Recorded;
    Final Review|Stamped and Signed;
    else inspections titled *FINAL* with pass/approved    → FINAL_DATE

Known issues repaired:
  - STATUS_NORMALIZED follows stale STATUS_ORIGINAL when
    DATA.status has advanced (Finaled/Closed still Active or
    In Review; Expired still Active; Issued still In Review)
    → FIXED.
  - FILE_DATE already matches DATA.date for every sample row;
    no changes expected unless a future mismatch appears.
  - PERMIT_DATE often set to Staff Determination / Ready to
    Issue (or adjacent review dates) instead of Issuance /
    Issued* → FIXED to the true issuance date.
  - PERMIT_DATE missing on Active/Final online & minor permits
    that use Submittal / Issued → FILLED.
  - FINAL_DATE frequently copied from the issuance date
    (~200 Final rows) → FIXED to Final Inspection Complete /
    Closeout / final inspection / survey recording marks.
  - FINAL_DATE missing on Final when those marks exist → FILLED.
  - Spurious FINAL_DATE on non-Final rows → cleared (FIXED).

Not repairable from DATA:
  - 45 Survey Review shells with blank status and empty task
    events → STATUS_NORMALIZED stays missing.
  - Most pre-event Accela shells (and many Application Request /
    Public Record Request / Survey closed records) lack Issuance
    and final marks → PERMIT_DATE / FINAL_DATE stay missing.
"""

from __future__ import annotations

import json
import math
from typing import Optional

import numpy as np
import pandas as pd


_MIN_YEAR = 1900
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
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return pd.NaT
    if isinstance(val, dict):
        return pd.NaT
    if isinstance(val, str):
        s = val.strip()
        if not s or s.upper() == "TBD":
            return pd.NaT
    try:
        dt = pd.to_datetime(val, errors="coerce")
    except (ValueError, TypeError):
        return pd.NaT
    if dt is pd.NaT or pd.isna(dt):
        return pd.NaT
    if getattr(dt, "tzinfo", None) is not None:
        dt = dt.tz_convert("UTC").tz_localize(None)
    year = int(dt.year)
    if year < _MIN_YEAR or year > _MAX_YEAR:
        return pd.NaT
    return dt


def _dates_equal(a, b) -> bool:
    da = _safe_to_datetime(a)
    db = _safe_to_datetime(b)
    if da is pd.NaT or db is pd.NaT:
        return False
    return da.normalize() == db.normalize()


def _event_field(event: dict, *names: str):
    """Read an event field by *names* priority (first match wins).

    Accela ACA scrapes use padded keys such as ``Marked as `` and `` on ``.
    """
    normalized = {k.strip(): v for k, v in event.items() if isinstance(k, str)}
    for name in names:
        if name.strip() in normalized:
            return normalized[name.strip()]
    return None


def _event_status(event: dict):
    return _event_field(event, "Marked as", "status", "Status")


def _iter_tasks(tasks: list):
    for t in tasks or []:
        if not isinstance(t, dict):
            continue
        yield t
        for st in t.get("subtasks") or []:
            if isinstance(st, dict):
                yield st


def _has_dated_events(d: dict) -> bool:
    for t in _iter_tasks(d.get("tasks") or []):
        for e in t.get("events") or []:
            if not isinstance(e, dict):
                continue
            if _safe_to_datetime(_event_field(e, "on")) is not pd.NaT:
                return True
    return False


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())
    if "status" not in keys and "search_data" not in keys:
        return "unknown"

    tasks = data_dict.get("tasks") or []
    has_tasks = isinstance(tasks, list) and len(tasks) > 0
    has_events = _has_dated_events(data_dict)

    if has_events:
        return "accela_tasks"
    if has_tasks:
        return "accela_shell"
    return "accela_search_only"


def _event_dates(tasks: list, task_names, statuses):
    """Collect event dates for matching task name(s) and status value(s)."""
    if isinstance(task_names, str):
        task_names = {task_names}
    if isinstance(statuses, str):
        statuses = {statuses}
    statuses_l = {s.lower() for s in statuses}
    dates = []
    for t in _iter_tasks(tasks):
        if t.get("name") not in task_names:
            continue
        for e in t.get("events") or []:
            if not isinstance(e, dict):
                continue
            mark = _event_status(e)
            if not isinstance(mark, str) or mark.strip().lower() not in statuses_l:
                continue
            dt = _safe_to_datetime(_event_field(e, "on"))
            if dt is not pd.NaT:
                dates.append(dt)
    return dates


def _first_event_date(tasks: list, task_names, statuses):
    dates = _event_dates(tasks, task_names, statuses)
    return min(dates) if dates else pd.NaT


def _latest_event_date(tasks: list, task_names, statuses):
    dates = _event_dates(tasks, task_names, statuses)
    return max(dates) if dates else pd.NaT


# ── Status mapping ──────────────────────────────────────────────────────────

_STATUS_MAP = {
    # Final
    "Final": "Final",
    "Finaled": "Final",
    "Final (Renewed)": "Final",
    "Closed": "Final",
    "Closed - DEV Application": "Final",
    "Closed - DEV Revision": "Final",
    "Closed - DEV Deferred": "Final",
    "Closed - PLN Application": "Final",
    "Closed - NA": "Final",
    "Closed - WEB Revision": "Final",
    "Complete": "Final",
    "Recorded": "Final",
    "No Responsive Records - Closed": "Final",
    "Records Provide - Closed": "Final",
    "Records Provided - Closed": "Final",
    "Tract Number Issued": "Final",
    "Duplicate - Closed": "Inactive",
    # Active
    "Issued": "Active",
    "Active": "Active",
    "Reinspection Pending": "Active",
    "Issue OK": "Active",
    # In Review
    "Received": "In Review",
    "In Review": "In Review",
    "Pending Resubmittal": "In Review",
    "Pending Additional Submittal": "In Review",
    "Pending Addintional Submittal": "In Review",
    "Planning Screening Review": "In Review",
    "Resubmittal In Review": "In Review",
    "Received - Pending Fee Payment": "In Review",
    "Reviewing Records": "In Review",
    "County Counsel Review": "In Review",
    "Approved for DEV Application": "In Review",
    "Final Processing": "In Review",
    "Plng PC": "In Review",
    "Ready to Issue": "In Review",
    # Inactive
    "Expired": "Inactive",
    "Void": "Inactive",
    "Withdrawn": "Inactive",
    "Application Expired": "Inactive",
    "Duplicate": "Inactive",
    "Closed - No Activity": "Inactive",
}

_ISSUED_MARKS = {
    "Issued",
    "Issued - Construction",
    "Issued - Grading or Drainage",
    "Issued - Operations",
    "Permit Issued",
}

_FINAL_TASK_RULES = (
    # (task_names, mark_set)
    ({"Inspections", "Inspection"}, {"Final Inspection Complete"}),
    ({"Closeout"}, {"Project Complete", "Final Permit Issued"}),
    ({"Development"}, {"Development Complete"}),
    (
        {"Map Recording"},
        {"Corner Record Filed", "ROS Recorded", "Tract or Parcel Map Recorded"},
    ),
    ({"Final Review"}, {"Stamped and Signed"}),
)

_FINAL_INSP_OK = {
    "pass",
    "done",
    "approved",
    "passed",
    "passed final",
    "pass meter release",
}


def _raw_status(d: dict) -> Optional[str]:
    raw = d.get("status")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    sd = d.get("search_data")
    if isinstance(sd, dict):
        sd_status = sd.get("Status")
        if isinstance(sd_status, str) and sd_status.strip():
            return sd_status.strip()
    return None


def _expected_status(d: dict) -> Optional[str]:
    """Map DATA.status → STATUS_NORMALIZED."""
    raw = _raw_status(d)
    if raw is None:
        return None
    mapped = _STATUS_MAP.get(raw)
    if mapped is not None:
        return mapped
    for k, v in _STATUS_MAP.items():
        if k.lower() == raw.lower():
            return v
    return None


def _file_date_from_data(d: dict):
    """Application / submitted date."""
    top = _safe_to_datetime(d.get("date"))
    if top is not pd.NaT:
        return top

    sd = d.get("search_data")
    if isinstance(sd, dict):
        for key in ("Date", "Submitted Date", "Date Opened", "Application Date"):
            opened = _safe_to_datetime(sd.get(key))
            if opened is not pd.NaT:
                return opened
    return pd.NaT


def _permit_date_from_data(d: dict):
    """Earliest true issuance date.

    Prefer Issuance / Permit Issuance Issued* marks. Fall back to
    Submittal / Issued used by On-Line and Minor permits.
    """
    tasks = d.get("tasks") or []

    # Tier 1: Issuance workflow
    dates = []
    for t in _iter_tasks(tasks):
        name = t.get("name")
        if name not in ("Issuance", "Permit Issuance"):
            continue
        for e in t.get("events") or []:
            if not isinstance(e, dict):
                continue
            mark = _event_status(e)
            if not isinstance(mark, str):
                continue
            m = mark.strip()
            if m in _ISSUED_MARKS or m.startswith("Issued -"):
                dt = _safe_to_datetime(_event_field(e, "on"))
                if dt is not pd.NaT:
                    dates.append(dt)
    if dates:
        return min(dates)

    # Tier 2: online / minor Submittal → Issued
    return _first_event_date(tasks, "Submittal", {"Issued"})


def _has_issuance_evidence(d: dict) -> bool:
    return _permit_date_from_data(d) is not pd.NaT


def _final_date_from_inspections(d: dict, on_or_after=None):
    """Latest final-titled inspection with a passing status."""
    dates = []
    for item in d.get("inspections") or []:
        if not isinstance(item, dict):
            continue
        st = item.get("Status")
        if not isinstance(st, str):
            continue
        title = item.get("Title") or ""
        if not isinstance(title, str) or "FINAL" not in title.upper():
            continue
        if st.strip().lower() not in _FINAL_INSP_OK:
            continue
        dt = _safe_to_datetime(item.get("Status Date"))
        if dt is not pd.NaT:
            dates.append(dt)
    if not dates:
        return pd.NaT
    floor = _safe_to_datetime(on_or_after)
    if floor is not pd.NaT:
        dates = [dt for dt in dates if dt.normalize() >= floor.normalize()]
        if not dates:
            return pd.NaT
    return max(dates)


def _final_date_from_tasks(d: dict):
    tasks = d.get("tasks") or []
    dates = []
    for task_names, marks in _FINAL_TASK_RULES:
        dates.extend(_event_dates(tasks, task_names, marks))
    return max(dates) if dates else pd.NaT


def _final_date_from_data(d: dict, on_or_after=None):
    """Best available finaling / sign-off / recording date."""
    task_final = _final_date_from_tasks(d)
    insp_final = _final_date_from_inspections(d, on_or_after=None)
    candidates = [x for x in (task_final, insp_final) if x is not pd.NaT]
    if not candidates:
        return pd.NaT

    floor = _safe_to_datetime(on_or_after)
    if floor is not pd.NaT:
        filtered = [dt for dt in candidates if dt.normalize() >= floor.normalize()]
        if filtered:
            candidates = filtered
    return max(candidates)


# ── Repair logic ────────────────────────────────────────────────────────────

def _repair_record(row, d: dict, repairs: dict):
    # -- STATUS_NORMALIZED --
    current_status = row["STATUS_NORMALIZED"]
    expected = _expected_status(d)
    if expected is not None:
        if pd.isna(current_status):
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"
        elif current_status != expected:
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FIXED"

    effective_status = repairs.get("STATUS_NORMALIZED", current_status)

    # -- FILE_DATE --
    file_date = _file_date_from_data(d)
    if file_date is not pd.NaT:
        if pd.isna(row["FILE_DATE"]):
            repairs["FILE_DATE"] = file_date
            repairs["FILE_DATE_FLAG"] = "FILLED"
        elif not _dates_equal(row["FILE_DATE"], file_date):
            repairs["FILE_DATE"] = file_date
            repairs["FILE_DATE_FLAG"] = "FIXED"

    # -- PERMIT_DATE --
    issued = _permit_date_from_data(d)
    current_permit = row["PERMIT_DATE"]
    if not pd.isna(current_permit):
        if issued is not pd.NaT and not _dates_equal(current_permit, issued):
            repairs["PERMIT_DATE"] = issued
            repairs["PERMIT_DATE_FLAG"] = "FIXED"
        elif (
            effective_status == "In Review"
            and not _has_issuance_evidence(d)
        ):
            # Spurious permit date before issuance.
            repairs["PERMIT_DATE"] = pd.NaT
            repairs["PERMIT_DATE_FLAG"] = "FIXED"
    elif effective_status in ("Active", "Final") and issued is not pd.NaT:
        repairs["PERMIT_DATE"] = issued
        repairs["PERMIT_DATE_FLAG"] = "FILLED"

    # -- FINAL_DATE --
    if effective_status == "Final":
        permit_for_final = repairs.get("PERMIT_DATE", row["PERMIT_DATE"])
        final_date = _final_date_from_data(d, on_or_after=permit_for_final)
        if final_date is not pd.NaT:
            if pd.isna(row["FINAL_DATE"]):
                repairs["FINAL_DATE"] = final_date
                repairs["FINAL_DATE_FLAG"] = "FILLED"
            elif not _dates_equal(row["FINAL_DATE"], final_date):
                repairs["FINAL_DATE"] = final_date
                repairs["FINAL_DATE_FLAG"] = "FIXED"
    elif not pd.isna(row["FINAL_DATE"]):
        repairs["FINAL_DATE"] = pd.NaT
        repairs["FINAL_DATE_FLAG"] = "FIXED"


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Santa Clara County permit records using the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Santa Clara County".  Must
        contain columns STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE,
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
    filepath = os.path.join(
        MY_DATA_PATH, "processed_data", "permits_ca_sample.parquet"
    )
    df = pd.read_parquet(filepath)
    scc = df[df["JURISDICTION"] == "Santa Clara County"].copy()

    print(f"Santa Clara County records: {len(scc):,}\n")

    repaired = data_repair(scc)

    print("INFERRED_SCHEMA:")
    print(repaired["INFERRED_SCHEMA"].value_counts(dropna=False).to_string())
    print()

    for field in ["STATUS_NORMALIZED", "FILE_DATE", "PERMIT_DATE", "FINAL_DATE"]:
        flag_col = f"{field}_FLAG"
        n_filled = (repaired[flag_col] == "FILLED").sum()
        n_fixed = (repaired[flag_col] == "FIXED").sum()
        print(f"{field}:")
        print(f"  FILLED: {n_filled:>4,}   FIXED: {n_fixed:>4,}")

        before_missing = scc[field].isna().sum()
        after_missing = repaired[field].isna().sum()
        print(
            f"  Missing before: {before_missing:>4,}   "
            f"Missing after: {after_missing:>4,}"
        )
        print()

    print("STATUS_NORMALIZED distribution:")
    print("  Before:")
    for s, c in scc["STATUS_NORMALIZED"].value_counts(dropna=False).items():
        print(f"    {str(s):15s}: {c:>4,}")
    print("  After:")
    for s, c in repaired["STATUS_NORMALIZED"].value_counts(dropna=False).items():
        print(f"    {str(s):15s}: {c:>4,}")

    print("\nFINAL_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FINAL_DATE"].notna().sum()
        print(
            f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} "
            f"({n_has / len(sub) if len(sub) else 0:.1%})"
        )

    print("\nPERMIT_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["PERMIT_DATE"].notna().sum()
        print(
            f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} "
            f"({n_has / len(sub) if len(sub) else 0:.1%})"
        )

    print("\nFILE_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FILE_DATE"].notna().sum()
        print(
            f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} "
            f"({n_has / len(sub) if len(sub) else 0:.1%})"
        )

    if AGENT_DATA_PATH:
        out_path = os.path.join(
            AGENT_DATA_PATH, "santa_clara_county_repaired_sample.parquet"
        )
        to_write = repaired.copy()
        for col in ("FILE_DATE", "PERMIT_DATE", "FINAL_DATE"):
            to_write[col] = pd.to_datetime(to_write[col], errors="coerce")
        to_write.to_parquet(out_path, index=False)
        print(f"\nWrote repaired sample → {out_path}")

"""Data repair for Babcock Ranch (FL) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Babcock Ranch DATA is an Accela Citizen Access payload for Permanent /
Temporary Utility Service records. Rows share top-level keys ``status``,
``date``, ``search_data``, ``tasks``, ``inspections``, ``more_details``,
etc.

Content variants (INFERRED_SCHEMA):

  - accela_full:     dated task events + non-empty inspections list
  - accela_basic:    dated task events, no inspections
  - accela_shell:    portal payload but no dated task events
  - missing / unknown

Canonical mappings:
  - DATA.status (else search_data.Status)              → STATUS_NORMALIZED
  - search_data.Date else DATA.date else earliest
    Installation Request / Submitted workflow event    → FILE_DATE
  - Earliest Installation ``Meter Install Scheduled``;
    else Installation ``Meter Installed``;
    else more_details Meter Install Info.Install Date  → PERMIT_DATE
    (Active / Final fill; any status corrected if wrong)
  - Closure ``In Service`` (latest)                    → FINAL_DATE
    (Final only; cleared on non-Final)

Known issues repaired:
  - 1,064 unmapped STATUS_ORIGINAL values (meter account /
    install workflow) → FILLED from DATA.status.
  - 903 ``In Service`` rows wrongly mapped to Active → FIXED to Final.
  - 30 ``Meter Removed`` rows wrongly mapped to In Review → FIXED
    to Inactive.
  - All PERMIT_DATE values missing → FILLED for Active/Final when an
    install-authorization / install date exists in tasks or
    more_details.
  - FINAL_DATE missing on Final (In Service) rows → FILLED from
    Closure ``In Service``.
  - FINAL_DATE that equals Connection Inspections Completed / Meter
    Installed while a Closure ``In Service`` date exists → FIXED.
  - Spurious FINAL_DATE on non-Final rows → cleared (FIXED).

Not repairable from DATA:
  - ~42 Final (In Service) rows with no Meter Install Scheduled,
    Meter Installed task event, or Meter Install Info.Install Date
    → PERMIT_DATE stays missing (legacy conversion shells with only
    a Closure event).
  - Active rows with no install-schedule / install signal (rare)
    → PERMIT_DATE stays missing.
"""

from __future__ import annotations

import json
import math
import re
from typing import Optional

import numpy as np
import pandas as pd


_MIN_YEAR = 1980
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
    """Parse a date value, returning pd.NaT on failure / sentinels."""
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return pd.NaT
    if isinstance(val, dict):
        return pd.NaT
    if isinstance(val, str):
        s = val.strip()
        if not s or s.upper() in {
            "TBD", "NULL", "NONE", "N/A", "NA", "NAN",
            "00/00/0000", "0/0/0000",
        }:
            return pd.NaT
    try:
        dt = pd.to_datetime(val, errors="coerce")
    except (ValueError, TypeError, OverflowError):
        return pd.NaT
    if pd.isna(dt):
        return pd.NaT
    year = int(dt.year)
    if year < _MIN_YEAR or year > _MAX_YEAR:
        return pd.NaT
    if getattr(dt, "tzinfo", None) is not None:
        dt = dt.tz_convert("UTC").tz_localize(None)
    return dt


def _dates_equal(a, b) -> bool:
    """Compare two datelike values at calendar-day resolution."""
    da = _safe_to_datetime(a)
    db = _safe_to_datetime(b)
    if da is pd.NaT or db is pd.NaT or pd.isna(da) or pd.isna(db):
        return False
    return pd.Timestamp(da).normalize() == pd.Timestamp(db).normalize()


def _event_field(event: dict, *labels: str):
    """Read an Accela event field, tolerating leading/trailing spaces / NBSP."""
    for label in labels:
        for k, v in event.items():
            if not isinstance(k, str):
                continue
            if k.replace("\xa0", " ").strip().lower() == label.lower():
                if isinstance(v, str):
                    return v.replace("\xa0", " ").strip()
                return v
    return None


def _parse_event(event: dict):
    """Return (marked_as, on_date_str) from an Accela task event."""
    html = (event.get("html") or "").replace("\xa0", " ")
    m = re.search(
        r"Marked as\s*<span[^>]*>([^<]*)</span>\s*on\s*<span[^>]*>([^<]*)</span>",
        html,
        flags=re.I,
    )
    if m:
        return m.group(1).strip(), m.group(2).strip()

    marked = _event_field(event, "Marked as")
    on_val = _event_field(event, "on")
    return marked, on_val


def _iter_task_nodes(tasks: list):
    for t in tasks or []:
        if not isinstance(t, dict):
            continue
        yield (t.get("name") or "").replace("\xa0", " ").strip(), t
        for st in t.get("subtasks") or []:
            if isinstance(st, dict):
                yield (st.get("name") or "").replace("\xa0", " ").strip(), st


def _has_dated_task_event(tasks: list) -> bool:
    for _, t in _iter_task_nodes(tasks):
        for e in t.get("events") or []:
            if not isinstance(e, dict):
                continue
            _, on_val = _parse_event(e)
            if _safe_to_datetime(on_val) is not pd.NaT:
                return True
    return False


def _event_dates(tasks: list, task_names, marked_pred) -> list:
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
            if not marked or not marked_pred(marked):
                continue
            dt = _safe_to_datetime(on_val)
            if dt is not pd.NaT and not pd.isna(dt):
                dates.append(dt)
    return dates


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    if not isinstance(data_dict, dict):
        return "unknown"

    keys = set(data_dict.keys())
    if "tasks" not in keys and "status" not in keys and "search_data" not in keys:
        return "unknown"

    tasks = data_dict.get("tasks") or []
    inspections = data_dict.get("inspections")
    has_inspections = isinstance(inspections, list) and len(inspections) > 0
    has_dated_event = _has_dated_task_event(tasks)

    if has_dated_event and has_inspections:
        return "accela_full"
    if has_dated_event:
        return "accela_basic"
    if "tasks" in keys or "status" in keys:
        return "accela_shell"
    if "search_data" in keys:
        return "search_only"
    return "unknown"


# ── Status mapping ───────────────────────────────────────────────────────────

# Utility-service Accela workflow statuses → STATUS_NORMALIZED
_STATUS_MAP = {
    # Final — service fully closed out / energized
    "In Service": "Final",
    # Active — install authorized or work underway
    "Installation Scheduled": "Active",
    "Meter Installed": "Active",
    "Connect Inspections Completed": "Active",
    # In Review — application / account setup
    "Submitted": "In Review",
    "Meter Account Requested": "In Review",
    "Service Account Created": "In Review",
    # Inactive
    "Withdrawn": "Inactive",
    "Meter Removed": "Inactive",
    "Account Terminated": "Inactive",
}

_STATUS_MAP_LOWER = {k.lower(): v for k, v in _STATUS_MAP.items()}


def _raw_status(d: dict) -> str:
    status = d.get("status")
    if isinstance(status, str) and status.strip():
        return status.strip()
    sd = d.get("search_data") if isinstance(d.get("search_data"), dict) else {}
    sd_status = sd.get("Status")
    if isinstance(sd_status, str):
        return sd_status.strip()
    return ""


def _map_status(data_status: str) -> Optional[str]:
    if not data_status:
        return None
    return _STATUS_MAP.get(data_status) or _STATUS_MAP_LOWER.get(data_status.lower())


# ── Date extractors ──────────────────────────────────────────────────────────

def _file_date_from_data(d: dict):
    """Best available application / file date from Accela payload."""
    sd = d.get("search_data") if isinstance(d.get("search_data"), dict) else {}
    dt = _safe_to_datetime(sd.get("Date"))
    if dt is not pd.NaT and not pd.isna(dt):
        return dt

    dt = _safe_to_datetime(d.get("date"))
    if dt is not pd.NaT and not pd.isna(dt):
        return dt

    # Fallback: earliest Installation Request / application-ish event
    tasks = d.get("tasks") or []
    intake = _event_dates(
        tasks,
        {"Installation Request", "First Meter Checklist"},
        lambda m: (m or "").strip().lower()
        in {
            "meter account requested",
            "submitted",
            "initiate notification to amcobi",
        },
    )
    if intake:
        return min(intake)
    return pd.NaT


def _meter_install_info_date(d: dict):
    """Install Date nested under more_details['Meter Install Info']."""
    md = d.get("more_details")
    if not isinstance(md, dict):
        return pd.NaT
    stack = [md.get("Meter Install Info")]
    while stack:
        obj = stack.pop()
        if isinstance(obj, dict):
            for k, v in obj.items():
                if isinstance(k, str) and k.replace("\xa0", " ").strip().lower() == "install date":
                    dt = _safe_to_datetime(v)
                    if dt is not pd.NaT and not pd.isna(dt):
                        return dt
                stack.append(v)
        elif isinstance(obj, list):
            stack.extend(obj)
    return pd.NaT


def _permit_date_from_data(d: dict):
    """Authorization / issuance proxy for utility-service Accela workflow.

    Preference order:
      1. Installation marked Meter Install Scheduled (approved to install)
      2. Installation marked Meter Installed (implies prior authorization)
      3. more_details Meter Install Info.Install Date (legacy CONV rows)
    """
    tasks = d.get("tasks") or []

    scheduled = _event_dates(
        tasks,
        {"Installation"},
        lambda m: (m or "").strip().lower() == "meter install scheduled",
    )
    if scheduled:
        return min(scheduled)

    installed = _event_dates(
        tasks,
        {"Installation"},
        lambda m: (m or "").strip().lower() == "meter installed",
    )
    if installed:
        return min(installed)

    return _meter_install_info_date(d)


def _final_date_from_data(d: dict):
    """Closure marked In Service is the utility-service finalization date."""
    tasks = d.get("tasks") or []
    closure = _event_dates(
        tasks,
        {"Closure"},
        lambda m: (m or "").strip().lower() == "in service",
    )
    if closure:
        return max(closure)
    return pd.NaT


# ── Per-record repair ────────────────────────────────────────────────────────

def _apply_date(repairs: dict, row, field: str, candidate, *, allow_fill: bool = True) -> None:
    cand = _safe_to_datetime(candidate)
    if cand is pd.NaT or pd.isna(cand):
        return
    current = row[field]
    if pd.isna(current):
        if allow_fill:
            repairs[field] = cand
            repairs[f"{field}_FLAG"] = "FILLED"
    elif not _dates_equal(current, cand):
        repairs[field] = cand
        repairs[f"{field}_FLAG"] = "FIXED"


def _clear_date(repairs: dict, row, field: str) -> None:
    current = repairs.get(field, row[field])
    if pd.isna(current):
        return
    repairs[field] = pd.NaT
    repairs[f"{field}_FLAG"] = "FIXED"


def _repair_record(row, d: dict, repairs: dict) -> None:
    # -- STATUS_NORMALIZED --
    current_status = row["STATUS_NORMALIZED"]
    expected = _map_status(_raw_status(d))
    if expected is not None:
        if pd.isna(current_status):
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"
        elif current_status != expected:
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FIXED"

    effective_status = repairs.get("STATUS_NORMALIZED", current_status)

    # -- FILE_DATE --
    _apply_date(repairs, row, "FILE_DATE", _file_date_from_data(d))

    # -- PERMIT_DATE --
    issued = _permit_date_from_data(d)
    current_permit = row["PERMIT_DATE"]
    if issued is not pd.NaT and not pd.isna(issued):
        if pd.isna(current_permit):
            if effective_status in ("Active", "Final"):
                repairs["PERMIT_DATE"] = issued
                repairs["PERMIT_DATE_FLAG"] = "FILLED"
        elif not _dates_equal(current_permit, issued):
            repairs["PERMIT_DATE"] = issued
            repairs["PERMIT_DATE_FLAG"] = "FIXED"

    # -- FINAL_DATE --
    final_src = _final_date_from_data(d)
    if effective_status == "Final":
        _apply_date(repairs, row, "FINAL_DATE", final_src)
    else:
        _clear_date(repairs, row, "FINAL_DATE")


# ── Main entry point ─────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Babcock Ranch permit records using information from the raw DATA JSON.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Babcock Ranch".  Must contain
        columns STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, FINAL_DATE,
        and DATA.

    Returns
    -------
    pd.DataFrame
        Copy of *df* with corrected field values, an INFERRED_SCHEMA
        column naming the DATA JSON sub-schema identified for each
        record, and flag columns: STATUS_NORMALIZED_FLAG, FILE_DATE_FLAG,
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

    for col in ("FILE_DATE", "PERMIT_DATE", "FINAL_DATE"):
        out[col] = pd.to_datetime(out[col], errors="coerce")

    return out


# ── CLI: run standalone to preview repair stats ──────────────────────────────

if __name__ == "__main__":
    import os
    from pathlib import Path

    from dotenv import load_dotenv

    repo_root = Path(__file__).resolve().parents[3]
    load_dotenv(repo_root / ".env")
    my_data_path = os.getenv("MY_DATA_PATH")
    agent_data_path = os.getenv("AGENT_DATA_PATH")
    filepath = os.path.join(my_data_path, "processed_data", "permits_fl_sample.parquet")
    df = pd.read_parquet(filepath)
    city = df[
        (df["JURISDICTION"] == "Babcock Ranch") & (df["STATE"] == "FL")
    ].copy()

    print(f"Babcock Ranch records: {len(city):,}\n")
    repaired = data_repair(city)

    print("INFERRED_SCHEMA:")
    print(repaired["INFERRED_SCHEMA"].value_counts(dropna=False).to_string())
    print()

    for field in ["STATUS_NORMALIZED", "FILE_DATE", "PERMIT_DATE", "FINAL_DATE"]:
        flag_col = f"{field}_FLAG"
        n_filled = (repaired[flag_col] == "FILLED").sum()
        n_fixed = (repaired[flag_col] == "FIXED").sum()
        before_missing = city[field].isna().sum()
        after_missing = repaired[field].isna().sum()
        print(f"{field}:")
        print(f"  FILLED: {n_filled:>4,}   FIXED: {n_fixed:>4,}")
        print(f"  Missing before: {before_missing:>4,}   Missing after: {after_missing:>4,}")
        print()

    print("STATUS_NORMALIZED distribution:")
    print("  Before:")
    for s, c in city["STATUS_NORMALIZED"].value_counts(dropna=False).items():
        print(f"    {str(s):15s}: {c:>4,}")
    print("  After:")
    for s, c in repaired["STATUS_NORMALIZED"].value_counts(dropna=False).items():
        print(f"    {str(s):15s}: {c:>4,}")

    print("\nSTATUS_ORIGINAL → STATUS_NORMALIZED (after):")
    ct = (
        repaired.groupby(["STATUS_ORIGINAL", "STATUS_NORMALIZED"], dropna=False)
        .size()
        .reset_index(name="n")
        .sort_values("n", ascending=False)
    )
    print(ct.to_string(index=False))

    print("\nFILE_DATE coverage by status (after):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FILE_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({(n_has/len(sub) if len(sub) else 0):.1%})")

    print("\nPERMIT_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["PERMIT_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({(n_has/len(sub) if len(sub) else 0):.1%})")

    print("\nFINAL_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FINAL_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({(n_has/len(sub) if len(sub) else 0):.1%})")

    if agent_data_path:
        out_path = os.path.join(agent_data_path, "babcock_ranch_repaired_sample.parquet")
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote repaired sample → {out_path}")

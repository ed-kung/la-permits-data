"""Data repair for Fort Lauderdale (FL) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Fort Lauderdale DATA is an Accela Citizen Access payload. Rows typically
include ``status``, ``search_data``, ``tasks``, and ``inspections``. A
newer scrape variant also carries a top-level ``date`` (equal to
``search_data.Date``). Two rows are search-result stubs with only
``search_data``.

Content variants (INFERRED_SCHEMA):

  - accela_full:     dated task events + inspections list present
  - accela_basic:    dated task events, no inspections list
  - accela_shell:    portal payload but no dated task events
  - search_only:     only ``search_data`` key
  - missing / unknown

Canonical mappings:
  - DATA.status (else search_data.Status)              → STATUS_NORMALIZED
  - search_data.Date else DATA.date else earliest
    Application Submittal / Intake event               → FILE_DATE
  - Earliest Permit Issuance / Issuance / Revision
    Issuance / Registration Issuance ``Issued``
    (Registration also accepts Renewal Complete)       → PERMIT_DATE
  - Certification CC/CO/Final CO Issued; else
    Inspection Final Inspection Complete; else
    inspections[] Pass on FINAL title                  → FINAL_DATE

Known issues repaired:
  - 40 rows with unmapped STATUS_ORIGINAL values
    (Awaiting Permit Issuance, Plan Set Submitted,
    Pending Master, Purged, etc.) → FILLED from DATA.status.
  - 1 Inactive void row missing FILE_DATE (empty
    search_data) → FILLED from Application Submittal Void date.
  - Missing FINAL_DATE on Final rows filled from Certification
    CC/CO Issued (and, rarely, passed FINAL inspections).
  - FINAL_DATE that equals Final Inspection Complete while a
    later CC/CO Issued exists → FIXED to the certificate date.
  - Spurious FINAL_DATE on non-Final rows → cleared (FIXED).

Not repairable from DATA:
  - 2 search_only TMP stubs with blank Status →
    STATUS_NORMALIZED stays missing.
  - ~70 Final rows with no issuance workflow event
    (property records, intake-only Complete, etc.) →
    PERMIT_DATE stays missing.
  - Final rows with neither Certification closeout nor
    Final Inspection Complete nor a passed FINAL inspection
    → FINAL_DATE stays missing.
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
    if keys == {"search_data"} or (keys <= {"search_data"} and "tasks" not in keys and "status" not in keys):
        if "search_data" in keys and "tasks" not in keys:
            return "search_only"

    if "tasks" not in keys and "status" not in keys and "search_data" not in keys:
        return "unknown"

    tasks = data_dict.get("tasks") or []
    has_inspections = isinstance(data_dict.get("inspections"), list)
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

# DATA.status → STATUS_NORMALIZED (case-insensitive lookup)
_STATUS_MAP = {
    # Final
    "Complete": "Final",
    "Completed": "Final",
    # Active
    "Issued": "Active",
    "Extension Approved": "Active",
    # In Review
    "Awaiting Client Reply": "In Review",
    "Open": "In Review",
    "In Process": "In Review",
    "In Review": "In Review",
    "Corrections Received": "In Review",
    "Awaiting Permit Issuance": "In Review",
    "Plan Set Submitted": "In Review",
    "Pending Master": "In Review",
    "Pending Master Corrections": "In Review",
    "Awaiting Initial Fee Payment": "In Review",
    "More Information Required": "In Review",
    "Issuance Fees Paid": "In Review",
    "Awaiting Revision Issuance": "In Review",
    # Inactive
    "Void": "Inactive",
    "Disapproved": "Inactive",
    "Expired": "Inactive",
    "Withdrawn": "Inactive",
    "Purged": "Inactive",
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

    # Fallback: earliest Application Submittal / Intake workflow date
    # (covers voided shells with empty search_data).
    tasks = d.get("tasks") or []
    intake = _event_dates(
        tasks,
        {"Application Submittal", "Intake", "Document Submittal"},
        lambda m: (m or "").strip().lower() not in {"", "tbd", "na", "n/a"},
    )
    if intake:
        return min(intake)
    return pd.NaT


def _permit_date_from_tasks(tasks: list):
    """Earliest issuance date from Accela issuance-family tasks."""

    def _is_issued(m: str) -> bool:
        ml = (m or "").strip().lower()
        return ml == "issued"

    for task_names in (
        {"Permit Issuance"},
        {"Issuance"},
        {"Revision Issuance"},
    ):
        issued = _event_dates(tasks, task_names, _is_issued)
        if issued:
            return min(issued)

    reg = _event_dates(
        tasks,
        {"Registration Issuance"},
        lambda m: (m or "").strip().lower() in {"issued", "renewal complete"},
    )
    if reg:
        return min(reg)

    return pd.NaT


_INSP_PASS_STATUSES = {
    "approved unconditionally",
    "approved",
    "approved with conditions",
    "pass",
    "passed",
    "complied",
    "finaled",
}


def _inspection_final_dates(d: dict) -> list:
    dates = []
    for insp in d.get("inspections") or []:
        if not isinstance(insp, dict):
            continue
        st = (insp.get("Status") or "").strip().lower()
        if st not in _INSP_PASS_STATUSES:
            continue
        title = (insp.get("Title") or "")
        if not re.search(r"final|fnl|\bco\b|cert", title, re.I):
            continue
        dt = _safe_to_datetime(insp.get("Status Date"))
        if dt is not pd.NaT and not pd.isna(dt):
            dates.append(dt)
        for h in insp.get("Status History") or []:
            if not isinstance(h, dict):
                continue
            hst = (h.get("Status") or "").strip().lower()
            if hst not in _INSP_PASS_STATUSES:
                continue
            hdt = _safe_to_datetime(h.get("Status Date") or h.get("Update Time"))
            if hdt is not pd.NaT and not pd.isna(hdt):
                dates.append(hdt)
    return dates


def _final_date_from_data(d: dict):
    """Best finalization date: certificate closeout > final insp task > inspections."""
    tasks = d.get("tasks") or []

    def _is_cert_issued(m: str) -> bool:
        ml = (m or "").strip().lower()
        return ml in {"cc issued", "co issued", "final co issued"}

    cert = _event_dates(tasks, {"Certification"}, _is_cert_issued)
    if cert:
        return max(cert)

    def _is_insp_final(m: str) -> bool:
        ml = (m or "").strip().lower()
        return ml == "final inspection complete" or (
            "final" in ml and "complete" in ml
            and not any(x in ml for x in ("tbd", "revision", "required"))
        )

    insp_task = _event_dates(tasks, {"Inspection", "Inspections"}, _is_insp_final)
    if insp_task:
        return max(insp_task)

    final_insp = _inspection_final_dates(d)
    if final_insp:
        return max(final_insp)

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
    tasks = d.get("tasks") or []

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
    issued = _permit_date_from_tasks(tasks)
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
    Fort Lauderdale permit records using information from the raw DATA JSON.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Fort Lauderdale".  Must contain
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
        (df["JURISDICTION"] == "Fort Lauderdale") & (df["STATE"] == "FL")
    ].copy()

    print(f"Fort Lauderdale records: {len(city):,}\n")
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
        out_path = os.path.join(agent_data_path, "fort_lauderdale_repaired_sample.parquet")
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote repaired sample → {out_path}")

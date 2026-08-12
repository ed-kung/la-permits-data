"""Data repair for Plantation (FL) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Plantation DATA is an Accela Citizen Access payload with top-level keys
``status``, ``date``, ``search_data``, ``tasks``, and usually
``inspections`` / ``fees_details`` / ``related_records`` / ``conditions``.
A minority of rows omit the inspection/fee blocks (``accela_basic``).

Canonical mappings:
  - DATA.status (else search_data.Status)              → STATUS_NORMALIZED
  - DATA.date / search_data.Date (else earliest
    Application Submittal Accepted)                    → FILE_DATE
  - Earliest Issued on Permit Issuance Review /
    Registration Issuance / Issue Permit               → PERMIT_DATE
  - Latest Inspections Complete; else Close
    Closed/Complete; else Certificate Review Approved;
    else Approved final-ish inspection Status Date     → FINAL_DATE

Known issues repaired:
  - 10 unmapped statuses (Pickup, Sent) → STATUS_NORMALIZED FILLED
    as In Review.
  - 8 Code/Building Enforcement ``Complied`` rows labeled
    In Review → FIXED to Final.
  - Missing FINAL_DATE on Final rows filled from Close Closed /
    Complete when Inspections Complete is absent (legacy shells).
  - 2 Final rows that used an earlier Inspections Complete while a
    later Complete exists → FIXED to the latest Complete.
  - Spurious FINAL_DATE on Cancelled (Inactive) rows that were
    closed then cancelled → cleared (FIXED).

Not repairable from DATA:
  - FILE_DATE already matches DATA.date for every sample row.
  - ~135 Active/Final rows (mostly History Permits) have no Issued
    workflow event → PERMIT_DATE stays missing.
  - ~138 Final rows (empty task events / Close still TBD) have no
    closeout stamp → FINAL_DATE stays missing.
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

_FINAL_INSP_RE = re.compile(
    r"final|fnl|certificate|\bco\b|\bcc\b",
    re.IGNORECASE,
)

_INSP_PASS = {
    "approved",
    "complete",
    "passed",
    "pass",
    "fast track approval",
    "complied",
    "finaled",
}


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
        try:
            parsed = json.loads(data)
        except (json.JSONDecodeError, TypeError):
            return None
        return parsed if isinstance(parsed, dict) else None
    return data if isinstance(data, dict) else None


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
        if s.startswith("0001-01-01"):
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


def _iter_task_events(tasks: list):
    """Yield (task_name, status, on_date) for tasks and nested subtasks."""
    for t in tasks or []:
        if not isinstance(t, dict):
            continue
        name = str(t.get("name") or "").replace("\xa0", " ").strip()
        for e in t.get("events") or []:
            if not isinstance(e, dict):
                continue
            status = e.get("status")
            if isinstance(status, str):
                status = status.replace("\xa0", " ").strip()
            else:
                status = ""
            on_val = e.get("on")
            yield name, status, _safe_to_datetime(on_val)
        for st in t.get("subtasks") or []:
            if not isinstance(st, dict):
                continue
            sn = str(st.get("name") or "").replace("\xa0", " ").strip()
            full = f"{name}/{sn}" if name else sn
            for e in st.get("events") or []:
                if not isinstance(e, dict):
                    continue
                status = e.get("status")
                if isinstance(status, str):
                    status = status.replace("\xa0", " ").strip()
                else:
                    status = ""
                on_val = e.get("on")
                yield full, status, _safe_to_datetime(on_val)


def _has_dated_task_event(tasks: list) -> bool:
    for _, _, dt in _iter_task_events(tasks):
        if dt is not pd.NaT and not pd.isna(dt):
            return True
    return False


# ── Status mapping ───────────────────────────────────────────────────────────

_STATUS_MAP = {
    # Final / completed
    "Closed": "Final",
    "Finaled": "Final",
    "Complete": "Final",
    "Complied": "Final",  # code / building enforcement resolved
    # Active / issued / in-force
    "Issued": "Active",
    "Active": "Active",
    "Approved": "Active",
    "Delinquent": "Active",
    "Inspections": "Active",
    # In review / pre-issuance / ready
    "Applied": "In Review",
    "Review": "In Review",
    "Paid": "In Review",
    "Hold": "In Review",
    "In Progress": "In Review",
    "Pending": "In Review",
    "Preliminary": "In Review",
    "Ready for Issuance": "In Review",
    "Investigate": "In Review",
    "Pickup": "In Review",
    "Sent": "In Review",
    # Inactive
    "Cancelled": "Inactive",
    "Canceled": "Inactive",
    "Withdrawn": "Inactive",
    "Void": "Inactive",
    "Expired": "Inactive",
    "Violation": "Inactive",
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
    """Application / file date: top-level date, search_data.Date, or intake."""
    dt = _safe_to_datetime(d.get("date"))
    if dt is not pd.NaT and not pd.isna(dt):
        return dt

    sd = d.get("search_data") if isinstance(d.get("search_data"), dict) else {}
    dt = _safe_to_datetime(sd.get("Date"))
    if dt is not pd.NaT and not pd.isna(dt):
        return dt

    intake = []
    for name, status, on_dt in _iter_task_events(d.get("tasks") or []):
        if on_dt is pd.NaT or pd.isna(on_dt):
            continue
        nl = name.lower()
        if nl in {"application submittal", "intake", "permit application"}:
            if status.lower() not in {"", "tbd", "na", "n/a"}:
                intake.append(on_dt)
    return min(intake) if intake else pd.NaT


_ISSUANCE_TASKS = {
    "permit issuance review",
    "registration issuance",
    "issue permit",
    "issue",
}


def _permit_date_from_tasks(tasks: list):
    """Earliest Issued stamp on issuance-family tasks."""
    dates = []
    for name, status, on_dt in _iter_task_events(tasks):
        if on_dt is pd.NaT or pd.isna(on_dt):
            continue
        if status.lower() != "issued":
            continue
        if name.lower() in _ISSUANCE_TASKS or "issuance" in name.lower():
            dates.append(on_dt)
    return min(dates) if dates else pd.NaT


def _inspection_final_dates(d: dict) -> list:
    dates = []
    for insp in d.get("inspections") or []:
        if not isinstance(insp, dict):
            continue
        st = str(insp.get("Status") or "").strip().lower()
        if st not in _INSP_PASS:
            continue
        title = str(
            insp.get("Title")
            or insp.get("Type")
            or insp.get("Inspection")
            or insp.get("name")
            or ""
        )
        if not _FINAL_INSP_RE.search(title):
            continue
        dt = _safe_to_datetime(insp.get("Status Date"))
        if dt is not pd.NaT and not pd.isna(dt):
            dates.append(dt)
    return dates


def _final_date_from_data(d: dict):
    """Best finalization date from Accela workflow / inspections."""
    insp_complete = []
    close_dates = []
    cert_dates = []

    for name, status, on_dt in _iter_task_events(d.get("tasks") or []):
        if on_dt is pd.NaT or pd.isna(on_dt):
            continue
        nl = name.lower()
        sl = status.strip().lower()
        if nl == "inspections" and sl == "complete":
            insp_complete.append(on_dt)
        elif nl == "close" and sl in {"closed", "complete"}:
            close_dates.append(on_dt)
        elif "certificate" in nl and sl == "approved":
            cert_dates.append(on_dt)

    if insp_complete:
        return max(insp_complete)
    if close_dates:
        return max(close_dates)
    if cert_dates:
        return max(cert_dates)

    final_insp = _inspection_final_dates(d)
    if final_insp:
        return max(final_insp)
    return pd.NaT


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    if not isinstance(data_dict, dict):
        return "unknown"

    keys = set(data_dict.keys())
    if "status" not in keys and "tasks" not in keys and "search_data" not in keys:
        return "unknown"

    has_inspections = isinstance(data_dict.get("inspections"), list)
    has_dated = _has_dated_task_event(data_dict.get("tasks") or [])

    if has_dated and has_inspections:
        base = "accela_full"
    elif has_dated:
        base = "accela_basic"
    elif "tasks" in keys or "status" in keys:
        base = "accela_shell"
    else:
        return "unknown"

    applied = _file_date_from_data(data_dict)
    issued = _permit_date_from_tasks(data_dict.get("tasks") or [])
    finaled = _final_date_from_data(data_dict)
    has_applied = applied is not pd.NaT and not pd.isna(applied)
    has_issued = issued is not pd.NaT and not pd.isna(issued)
    has_finaled = finaled is not pd.NaT and not pd.isna(finaled)

    if has_issued and has_finaled:
        return f"{base}_issued_finaled"
    if has_issued:
        return f"{base}_issued"
    if has_finaled:
        return f"{base}_finaled"
    if has_applied:
        return f"{base}_applied"
    return f"{base}_status_only"


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
    Plantation permit records using information from the raw DATA JSON.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Plantation".  Must contain
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
        (df["JURISDICTION"] == "Plantation") & (df["STATE"] == "FL")
    ].copy()

    print(f"Plantation records: {len(city):,}\n")
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

    # Consistency checks
    violations = 0
    for idx in repaired.index:
        row = repaired.loc[idx]
        d = _safe_parse(row["DATA"])
        if d is None:
            continue
        expected = _map_status(_raw_status(d))
        if expected is not None and row["STATUS_NORMALIZED"] != expected:
            violations += 1
        if not _dates_equal(row["FILE_DATE"], _file_date_from_data(d)) and not (
            pd.isna(row["FILE_DATE"]) and pd.isna(_file_date_from_data(d))
        ):
            # allow equal-missing
            if not (pd.isna(row["FILE_DATE"]) and (_file_date_from_data(d) is pd.NaT or pd.isna(_file_date_from_data(d)))):
                if pd.notna(row["FILE_DATE"]) or (_file_date_from_data(d) is not pd.NaT and not pd.isna(_file_date_from_data(d))):
                    if not _dates_equal(row["FILE_DATE"], _file_date_from_data(d)):
                        violations += 1
        issued = _permit_date_from_tasks(d.get("tasks") or [])
        if issued is not pd.NaT and not pd.isna(issued):
            if pd.isna(row["PERMIT_DATE"]) or not _dates_equal(row["PERMIT_DATE"], issued):
                violations += 1
        if row["STATUS_NORMALIZED"] == "Final":
            final_src = _final_date_from_data(d)
            if final_src is not pd.NaT and not pd.isna(final_src):
                if pd.isna(row["FINAL_DATE"]) or not _dates_equal(row["FINAL_DATE"], final_src):
                    violations += 1
        else:
            if pd.notna(row["FINAL_DATE"]):
                violations += 1
    print(f"\nConsistency violations: {violations}")

    if agent_data_path:
        out_path = os.path.join(agent_data_path, "plantation_repaired_sample.parquet")
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote repaired sample → {out_path}")

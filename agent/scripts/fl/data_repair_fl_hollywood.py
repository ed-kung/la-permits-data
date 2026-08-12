"""Data repair for Hollywood (FL) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Hollywood DATA has two main sub-schemas in this sample:

  - project: legacy city portal with project.Permit Detail,
             inspections / reviews / approvals (/ subpermits)
  - accela:  newer Accela-style payload with status, tasks,
             inspections, search_data, date, …
  - search_only: search_data shell only (no usable status/dates)

Canonical mappings (project):
  - Permit Detail Status:          → STATUS_NORMALIZED
  - Application Date:              → FILE_DATE
  - Permit Date:                   → PERMIT_DATE
  - CO/CC Date: (else latest PASS
    inspection whose Description
    contains FINAL)                → FINAL_DATE

Canonical mappings (accela):
  - status                         → STATUS_NORMALIZED
  - top-level date / search Date   → FILE_DATE
  - Permit Issuance task "Issued"  → PERMIT_DATE
  - Inspection task
    "Final Inspection Complete"
    (else Passed Final inspection) → FINAL_DATE

Known issues repaired:
  - 1 Accela "Closed - Complete" row mislabeled Active → Final.
  - ~700 Final project rows had FINAL_DATE set to a plan-approval /
    Notice of Commencement date (often before PERMIT_DATE) → FIXED
    to CO/CC Date or latest PASS FINAL inspection.
  - ~729 Final project rows missing FINAL_DATE filled from
    inspections / CO/CC Date.
  - 1 Accela Final with an early "Final Inspection Complete" stamp
    updated to the latest completion event.
  - 1 Closed - Complete Active row also gains FINAL_DATE from a
    Passed Roofing Final Inspection.

Not repairable from DATA:
  - project CREATED/CANCELLED shells with blank Application Date
    → FILE_DATE stays missing.
  - Accela "Closed - Approved" (amendment / admin close) rows with
    no Permit Issuance or Final Inspection events → PERMIT_DATE /
    FINAL_DATE stay missing.
  - search_only shell with empty Status → STATUS_NORMALIZED null.
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


def _slug(text: Optional[str]) -> str:
    if text is None:
        return "none"
    s = re.sub(r"[^a-z0-9]+", "_", str(text).strip().lower()).strip("_")
    return s or "none"


def _apply_status(repairs: dict, current, expected: Optional[str]) -> Optional[str]:
    """Apply expected STATUS_NORMALIZED; return effective status."""
    if expected is None:
        if pd.isna(current):
            return None
        return current

    if pd.isna(current):
        repairs["STATUS_NORMALIZED"] = expected
        repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"
    elif current != expected:
        repairs["STATUS_NORMALIZED"] = expected
        repairs["STATUS_NORMALIZED_FLAG"] = "FIXED"

    return repairs.get("STATUS_NORMALIZED", current)


def _apply_date(repairs: dict, row, field: str, candidate) -> None:
    """Fill or fix *field* from *candidate* datetime (pd.NaT = no candidate)."""
    cand = _safe_to_datetime(candidate)
    if cand is pd.NaT or pd.isna(cand):
        return

    current = row[field]
    if pd.isna(current):
        repairs[field] = cand
        repairs[f"{field}_FLAG"] = "FILLED"
    elif not _dates_equal(current, cand):
        repairs[field] = cand
        repairs[f"{field}_FLAG"] = "FIXED"


def _clear_date(repairs: dict, row, field: str) -> None:
    """Clear a spurious date value."""
    current = repairs.get(field, row[field])
    if pd.isna(current):
        return
    repairs[field] = pd.NaT
    repairs[f"{field}_FLAG"] = "FIXED"


# ── Schema classification ────────────────────────────────────────────────────

def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    if not isinstance(data_dict, dict):
        return "unknown"
    if not data_dict:
        return "empty"

    keys = set(data_dict.keys())

    if "project" in keys:
        detail = (data_dict.get("project") or {}).get("Permit Detail") or {}
        if not isinstance(detail, dict):
            detail = {}
        return f"project_{_slug(detail.get('Status:'))}"

    if "status" in keys or "tasks" in keys:
        return f"accela_{_slug(data_dict.get('status'))}"

    if "search_data" in keys:
        sd = data_dict.get("search_data") or {}
        st = sd.get("Status") if isinstance(sd, dict) else None
        return f"search_only_{_slug(st)}"

    return "unknown"


# ── Status maps ──────────────────────────────────────────────────────────────

_PROJECT_STATUS_MAP = {
    "CLOSED": "Final",
    "ISSUED": "Active",
    "CREATED": "In Review",
    "APPLIED": "In Review",
    "READY": "In Review",
    "CANCELLED": "Inactive",
    "NULL AND VOID": "Inactive",
    "EXPIRED": "Inactive",
}

_ACCELA_STATUS_MAP = {
    "Closed - Complete": "Final",
    "Closed - Approved": "Final",
    "Inspection Phase": "Active",
    "Closed - Withdrawn": "Inactive",
    "Revisions Required": "In Review",
    "In Review": "In Review",
    "Pending": "In Review",
    "Ready to Issue": "In Review",
    "Plans Received": "In Review",
}


def _map_project_status(raw: Optional[str]) -> Optional[str]:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    return _PROJECT_STATUS_MAP.get(text) or _PROJECT_STATUS_MAP.get(text.upper())


def _map_accela_status(raw: Optional[str]) -> Optional[str]:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    return _ACCELA_STATUS_MAP.get(text)


# ── Date extractors ──────────────────────────────────────────────────────────

def _permit_detail(d: dict) -> dict:
    project = d.get("project") or {}
    if not isinstance(project, dict):
        return {}
    detail = project.get("Permit Detail") or {}
    return detail if isinstance(detail, dict) else {}


def _final_date_from_project_inspections(d: dict):
    """Latest PASS inspection whose Description contains FINAL."""
    final_dates = []
    for insp in d.get("inspections") or []:
        if not isinstance(insp, dict):
            continue
        result = str(insp.get("Results") or "").upper()
        if "PASS" not in result:
            continue
        desc = str(insp.get("Description") or "").upper()
        if "FINAL" not in desc:
            continue
        dt = _safe_to_datetime(insp.get("Insp. Date"))
        if dt is not pd.NaT and not pd.isna(dt):
            final_dates.append(dt)
    return max(final_dates) if final_dates else pd.NaT


def _project_final_candidate(d: dict):
    detail = _permit_detail(d)
    cocc = _safe_to_datetime(detail.get("CO/CC Date:"))
    if cocc is not pd.NaT and not pd.isna(cocc):
        return cocc
    return _final_date_from_project_inspections(d)


def _task_event_dates(d: dict, task_name: str, marked_as: str):
    dates = []
    for task in d.get("tasks") or []:
        if not isinstance(task, dict):
            continue
        if task.get("name") != task_name:
            continue
        for ev in task.get("events") or []:
            if not isinstance(ev, dict):
                continue
            if str(ev.get("Marked as") or "") != marked_as:
                continue
            dt = _safe_to_datetime(ev.get("on"))
            if dt is not pd.NaT and not pd.isna(dt):
                dates.append(dt)
    return dates


def _accela_permit_candidate(d: dict):
    """Earliest Permit Issuance / Issued event."""
    dates = _task_event_dates(d, "Permit Issuance", "Issued")
    return min(dates) if dates else pd.NaT


def _accela_final_candidate(d: dict):
    """Latest Final Inspection Complete task event; else Passed Final insp."""
    dates = _task_event_dates(d, "Inspection", "Final Inspection Complete")
    if dates:
        return max(dates)

    insp_dates = []
    for insp in d.get("inspections") or []:
        if not isinstance(insp, dict):
            continue
        title = str(insp.get("Title") or "").upper()
        status = str(insp.get("Status") or "").strip().upper()
        if "FINAL" not in title or status != "PASSED":
            continue
        dt = _safe_to_datetime(insp.get("Status Date"))
        if dt is not pd.NaT and not pd.isna(dt):
            insp_dates.append(dt)
    return max(insp_dates) if insp_dates else pd.NaT


def _accela_file_candidate(d: dict):
    dt = _safe_to_datetime(d.get("date"))
    if dt is not pd.NaT and not pd.isna(dt):
        return dt
    sd = d.get("search_data") or {}
    if isinstance(sd, dict):
        return _safe_to_datetime(sd.get("Date"))
    return pd.NaT


# ── Per-schema repair ────────────────────────────────────────────────────────

def _repair_project(row, d: dict, repairs: dict) -> None:
    detail = _permit_detail(d)
    expected = _map_project_status(detail.get("Status:"))
    effective_status = _apply_status(repairs, row["STATUS_NORMALIZED"], expected)

    _apply_date(repairs, row, "FILE_DATE", detail.get("Application Date:"))

    issue = _safe_to_datetime(detail.get("Permit Date:"))
    if issue is not pd.NaT and not pd.isna(issue):
        if effective_status in ("Active", "Final", "Inactive"):
            _apply_date(repairs, row, "PERMIT_DATE", issue)
        elif effective_status == "In Review":
            _clear_date(repairs, row, "PERMIT_DATE")
    elif effective_status == "In Review":
        _clear_date(repairs, row, "PERMIT_DATE")

    final_src = _project_final_candidate(d)
    current_final = row["FINAL_DATE"]
    if effective_status == "Final":
        if final_src is not pd.NaT and not pd.isna(final_src):
            if pd.isna(current_final):
                repairs["FINAL_DATE"] = final_src
                repairs["FINAL_DATE_FLAG"] = "FILLED"
            elif not _dates_equal(current_final, final_src):
                repairs["FINAL_DATE"] = final_src
                repairs["FINAL_DATE_FLAG"] = "FIXED"
        elif not pd.isna(current_final):
            # Existing FINAL_DATE is unsupported (e.g. NOC approval date
            # with blank inspection results) — clear it.
            _clear_date(repairs, row, "FINAL_DATE")
    elif not pd.isna(current_final):
        _clear_date(repairs, row, "FINAL_DATE")


def _repair_accela(row, d: dict, repairs: dict) -> None:
    expected = _map_accela_status(d.get("status"))
    if expected is None:
        sd = d.get("search_data") or {}
        if isinstance(sd, dict):
            expected = _map_accela_status(sd.get("Status"))
    effective_status = _apply_status(repairs, row["STATUS_NORMALIZED"], expected)

    _apply_date(repairs, row, "FILE_DATE", _accela_file_candidate(d))

    issued = _accela_permit_candidate(d)
    if issued is not pd.NaT and not pd.isna(issued):
        if effective_status in ("Active", "Final", "Inactive"):
            _apply_date(repairs, row, "PERMIT_DATE", issued)
        elif effective_status == "In Review":
            _clear_date(repairs, row, "PERMIT_DATE")
    elif effective_status == "In Review":
        _clear_date(repairs, row, "PERMIT_DATE")

    final_src = _accela_final_candidate(d)
    current_final = row["FINAL_DATE"]
    if effective_status == "Final":
        if final_src is not pd.NaT and not pd.isna(final_src):
            if pd.isna(current_final):
                repairs["FINAL_DATE"] = final_src
                repairs["FINAL_DATE_FLAG"] = "FILLED"
            elif not _dates_equal(current_final, final_src):
                repairs["FINAL_DATE"] = final_src
                repairs["FINAL_DATE_FLAG"] = "FIXED"
    elif not pd.isna(current_final):
        _clear_date(repairs, row, "FINAL_DATE")


def _repair_search_only(row, d: dict, repairs: dict) -> None:
    sd = d.get("search_data") or {}
    if not isinstance(sd, dict):
        sd = {}
    expected = _map_accela_status(sd.get("Status"))
    _apply_status(repairs, row["STATUS_NORMALIZED"], expected)
    _apply_date(repairs, row, "FILE_DATE", sd.get("Date"))


# ── Main entry point ─────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Hollywood permit records using information from the raw DATA JSON.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Hollywood".  Must
        contain columns STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE,
        FINAL_DATE, and DATA.

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

    for col in ("FILE_DATE", "PERMIT_DATE", "FINAL_DATE"):
        out[col] = pd.to_datetime(out[col], errors="coerce")

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
        if d is None or schema in {"missing", "unknown", "empty"}:
            continue

        repairs: dict = {}
        if schema.startswith("project_"):
            _repair_project(row, d, repairs)
        elif schema.startswith("accela_"):
            _repair_accela(row, d, repairs)
        elif schema.startswith("search_only"):
            _repair_search_only(row, d, repairs)

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
        (df["JURISDICTION"] == "Hollywood") & (df["STATE"] == "FL")
    ].copy()

    print(f"Hollywood records: {len(city):,}\n")
    repaired = data_repair(city)

    print("INFERRED_SCHEMA (top):")
    print(repaired["INFERRED_SCHEMA"].value_counts(dropna=False).head(25).to_string())
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

    print("\nSTATUS_NORMALIZED transitions (before → after):")
    transitions = (
        pd.DataFrame({
            "before": city["STATUS_NORMALIZED"].astype("object"),
            "after": repaired["STATUS_NORMALIZED"].astype("object"),
        })
        .groupby(["before", "after"], dropna=False)
        .size()
        .reset_index(name="n")
    )
    changed = transitions[
        transitions["before"].astype(str) != transitions["after"].astype(str)
    ]
    print(changed.sort_values("n", ascending=False).to_string(index=False))

    print("\nFILE_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FILE_DATE"].notna().sum()
        print(
            f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} "
            f"({(n_has / len(sub) if len(sub) else 0):.1%})"
        )

    print("\nPERMIT_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["PERMIT_DATE"].notna().sum()
        print(
            f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} "
            f"({(n_has / len(sub) if len(sub) else 0):.1%})"
        )

    print("\nFINAL_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FINAL_DATE"].notna().sum()
        print(
            f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} "
            f"({(n_has / len(sub) if len(sub) else 0):.1%})"
        )

    both = repaired[repaired["PERMIT_DATE"].notna() & repaired["FINAL_DATE"].notna()]
    n_inv = (
        both["PERMIT_DATE"].dt.normalize() > both["FINAL_DATE"].dt.normalize()
    ).sum()
    print(f"\nPERMIT_DATE > FINAL_DATE inversions after repair: {n_inv}")

    still_null = repaired[repaired["STATUS_NORMALIZED"].isna()]
    print(f"\nRemaining null STATUS_NORMALIZED: {len(still_null):,}")
    if len(still_null):
        print(still_null["INFERRED_SCHEMA"].value_counts().to_string())

    if agent_data_path:
        out_path = os.path.join(
            agent_data_path, "hollywood_repaired_sample.parquet"
        )
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote repaired sample → {out_path}")

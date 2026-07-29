"""Data repair for Monterey County (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Monterey County DATA is an Accela Citizen Access scrape. Task event
keys often have leading/trailing spaces ('Marked as ', ' on '). Nearly
all sample rows share the full Accela key set; a handful of sparse rows
omit contacts / inspections / fees. Content variants (INFERRED_SCHEMA):

  - accela_full_issued_finaled: dated Issue* + Inspection Finaled /
                                File Completed events
  - accela_full_issued:         dated Issue* events, no final marks
  - accela_full_finaled_only:   final marks, no Issue*
  - accela_full_other_events:   other dated workflow events
  - accela_full_empty_tasks:    tasks present but no dated events
  - accela_partial_*:           same content tags on sparse key sets

Canonical mappings:
  - DATA.status                                              → STATUS_NORMALIZED
  - DATA.date / search_data['Created Date']                  → FILE_DATE
  - Issue|Issued / Issued Online / Issued-Revised;
    Permit Issuance|Permit Issued                            → PERMIT_DATE
  - Inspection|Finaled / Inspection|File Completed
    (fallback: passed Final* inspection Status Date;
    Event Complete marks; planning Cleared / Staff Action)   → FINAL_DATE

Known issues repaired:
  - Unmapped STATUS_ORIGINAL (condition compliance, cleared, planner
    assigned, request, given out, comment) → FILLED from DATA.status.
  - Final missing FINAL_DATE despite passed Final* inspection or
    Event Complete / Cleared planning marks → FILLED.
  - Spurious FINAL_DATE on Expired Permit (Inactive) copied from
    Inspection|File Completed → FIXED (cleared).

Not repairable / left as-is:
  - FILE_DATE already matches DATA.date for every sample row.
  - Closed Building Permit Application shells (APP*) and Library /
    planning Active rows have no Issue* event → PERMIT_DATE stays
    missing.
  - Most Closed / Complete / Finished Final rows lack Final*
    inspections and Finaled / File Completed marks → FINAL_DATE stays
    missing.
  - Inspection|Closed is a mass 2016-03-30 batch stamp, not a true
    final date → ignored.
"""

from __future__ import annotations

import json
import math
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
    """Parse a date value, returning pd.NaT on failure / TBD / bad year."""
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return pd.NaT
    if isinstance(val, str) and not str(val).strip():
        return pd.NaT
    if isinstance(val, str) and str(val).strip().upper() == "TBD":
        return pd.NaT
    try:
        dt = pd.to_datetime(val)
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
    if da is pd.NaT or db is pd.NaT or pd.isna(da) or pd.isna(db):
        return False
    return da.normalize() == db.normalize()


def _event_field(event: dict, *names: str):
    """Read an event field, tolerating leading/trailing spaces in keys."""
    targets = {n.strip() for n in names}
    for k, v in event.items():
        if isinstance(k, str) and k.strip() in targets:
            return v
    return None


def _iter_tasks(tasks: list):
    """Yield top-level tasks and nested subtasks."""
    for t in tasks or []:
        if not isinstance(t, dict):
            continue
        yield t
        for st in t.get("subtasks") or []:
            if isinstance(st, dict):
                yield st


def _has_dated_events(tasks: list) -> bool:
    for t in _iter_tasks(tasks):
        for e in t.get("events") or []:
            if not isinstance(e, dict):
                continue
            if _safe_to_datetime(_event_field(e, "on")) is not pd.NaT:
                return True
    return False


def _schema_base(data_dict: dict) -> str:
    keys = set(data_dict.keys())
    if "tasks" not in keys or "status" not in keys:
        return "unknown"
    full = {"inspections", "fees_details", "contacts", "conditions"}
    if full.issubset(keys):
        return "accela_full"
    return "accela_partial"


def _has_issue_event(tasks: list) -> bool:
    for t in _iter_tasks(tasks):
        name = (t.get("name") or "").strip().lower()
        for e in t.get("events") or []:
            if not isinstance(e, dict):
                continue
            marked = _event_field(e, "Marked as")
            if marked is None:
                continue
            ml = str(marked).strip().lower()
            if ml not in {
                "issued",
                "issued online",
                "issued-revised",
                "permit issued",
            }:
                continue
            # Prefer Issue / Permit Issuance tasks; allow Permit Issued anywhere.
            if name not in {"issue", "permit issuance"} and ml != "permit issued":
                continue
            if _safe_to_datetime(_event_field(e, "on")) is not pd.NaT:
                return True
    return False


def _has_final_mark(tasks: list) -> bool:
    for t in _iter_tasks(tasks):
        name = (t.get("name") or "").strip().lower()
        for e in t.get("events") or []:
            if not isinstance(e, dict):
                continue
            marked = _event_field(e, "Marked as")
            if marked is None:
                continue
            ml = str(marked).strip().lower()
            dt = _safe_to_datetime(_event_field(e, "on"))
            if dt is pd.NaT:
                continue
            if name == "inspection" and ml in {"finaled", "file completed"}:
                return True
            if ml == "event complete":
                return True
            if ml == "cleared":
                return True
            if name == "staff action" and ml.startswith("no appeal approve"):
                return True
    return False


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    base = _schema_base(data_dict)
    if base == "unknown":
        return "unknown"

    tasks = data_dict.get("tasks") or []
    if not _has_dated_events(tasks):
        return f"{base}_empty_tasks"

    has_issue = _has_issue_event(tasks)
    has_final = _has_final_mark(tasks)
    if has_issue and has_final:
        return f"{base}_issued_finaled"
    if has_issue:
        return f"{base}_issued"
    if has_final:
        return f"{base}_finaled_only"
    return f"{base}_other_events"


# ── Status mapping ──────────────────────────────────────────────────────────

# DATA.status → STATUS_NORMALIZED (case-insensitive)
_STATUS_MAP = {
    # Final
    "finaled": "Final",
    "closed": "Final",
    "complete": "Final",
    "completed": "Final",
    "event complete": "Final",
    "finished": "Final",
    "conditional final": "Final",
    "superseded": "Final",
    "cleared": "Final",
    # Active
    "issued": "Active",
    "issued-revised": "Active",
    "issued revised": "Active",
    "active": "Active",
    "extended permit": "Active",
    "reinstated permit": "Active",
    "condition compliance": "Active",
    # Inactive
    "expired": "Inactive",
    "expired permit": "Inactive",
    "expired application": "Inactive",
    "void": "Inactive",
    "withdrawn": "Inactive",
    "withdrawn application": "Inactive",
    "withdrawn permit": "Inactive",
    # In Review
    "applied": "In Review",
    "incomplete": "In Review",
    "submitted via aca": "In Review",
    "ready to issue": "In Review",
    "under review": "In Review",
    "revision submitted": "In Review",
    "open": "In Review",
    "extended application": "In Review",
    "planner assigned": "In Review",
    "request": "In Review",
    "given out": "In Review",
    "comment": "In Review",
}


def _expected_status(data_status) -> Optional[str]:
    if data_status is None:
        return None
    if isinstance(data_status, float) and math.isnan(data_status):
        return None
    key = str(data_status).strip().lower()
    if not key:
        return None
    return _STATUS_MAP.get(key)


# ── Date extractors ─────────────────────────────────────────────────────────

def _issued_date(tasks: list):
    """Earliest true issuance date from Monterey Accela workflow events.

    Priority:
      1. Permit Issued on Permit Issuance
      2. Issued / Issued Online / Issued-Revised on Issue
      3. Issued / Issued Online / Issued-Revised / Permit Issued elsewhere
    """
    permit_issuance = []
    issued_on_issue = []
    issued_any = []

    for t in _iter_tasks(tasks):
        name = (t.get("name") or "").strip().lower()
        for e in t.get("events") or []:
            if not isinstance(e, dict):
                continue
            marked = _event_field(e, "Marked as")
            if marked is None:
                continue
            ml = str(marked).strip().lower()
            dt = _safe_to_datetime(_event_field(e, "on"))
            if dt is pd.NaT:
                continue
            if ml == "permit issued" and name == "permit issuance":
                permit_issuance.append(dt)
            elif ml in {"issued", "issued online", "issued-revised"} and name == "issue":
                issued_on_issue.append(dt)
            elif ml in {"issued", "issued online", "issued-revised", "permit issued"}:
                issued_any.append(dt)

    for group in (permit_issuance, issued_on_issue, issued_any):
        if group:
            return min(group)
    return pd.NaT


def _final_date_from_tasks(tasks: list):
    """Best completion date from workflow marks (excludes mass Inspection|Closed)."""
    finaled = []
    file_completed = []
    event_complete = []
    cleared = []
    staff_approve = []

    for t in _iter_tasks(tasks):
        name = (t.get("name") or "").strip().lower()
        for e in t.get("events") or []:
            if not isinstance(e, dict):
                continue
            marked = _event_field(e, "Marked as")
            if marked is None:
                continue
            ml = str(marked).strip().lower()
            dt = _safe_to_datetime(_event_field(e, "on"))
            if dt is pd.NaT:
                continue
            if name == "inspection" and ml == "finaled":
                finaled.append(dt)
            elif name == "inspection" and ml == "file completed":
                file_completed.append(dt)
            elif ml == "event complete":
                event_complete.append(dt)
            elif ml == "cleared":
                cleared.append(dt)
            elif name == "staff action" and ml.startswith("no appeal approve"):
                staff_approve.append(dt)

    for group in (finaled, file_completed, event_complete, cleared, staff_approve):
        if group:
            return max(group)
    return pd.NaT


def _final_date_from_inspections(inspections: list):
    """Fallback: Status Date of a Final*-titled Approval / Pass inspection."""
    dates = []
    for insp in inspections or []:
        if not isinstance(insp, dict):
            continue
        title = str(insp.get("Title") or "")
        status = str(insp.get("Status") or "").strip().lower()
        if "final" not in title.lower():
            continue
        if status not in {
            "pass",
            "passed",
            "approved",
            "approval",
            "complete",
            "conditional",
        }:
            continue
        dt = _safe_to_datetime(insp.get("Status Date"))
        if dt is not pd.NaT:
            dates.append(dt)
    return max(dates) if dates else pd.NaT


def _file_date_from_data(d: dict):
    """Best FILE_DATE: top-level date, else search_data Created Date."""
    file_date = _safe_to_datetime(d.get("date"))
    if file_date is not pd.NaT:
        return file_date

    sd = d.get("search_data") or {}
    if isinstance(sd, dict):
        for key in ("Created Date", "Date", "File Date"):
            file_date = _safe_to_datetime(sd.get(key))
            if file_date is not pd.NaT:
                return file_date
    return pd.NaT


# ── Repair logic ────────────────────────────────────────────────────────────

def _repair_record(row, d: dict, repairs: dict):
    """Repair one Monterey County Accela record."""
    tasks = d.get("tasks") or []
    data_status = d.get("status")
    if isinstance(data_status, str) and not data_status.strip():
        data_status = None
    if data_status is None:
        sd = d.get("search_data") or {}
        if isinstance(sd, dict):
            sstatus = sd.get("Status")
            if isinstance(sstatus, str) and sstatus.strip():
                data_status = sstatus.strip()

    # -- STATUS_NORMALIZED --
    current_status = row["STATUS_NORMALIZED"]
    expected = _expected_status(data_status)

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
    current_fd = _safe_to_datetime(row["FILE_DATE"])

    if file_src is not pd.NaT:
        if current_fd is pd.NaT or pd.isna(current_fd):
            repairs["FILE_DATE"] = file_src
            repairs["FILE_DATE_FLAG"] = "FILLED"
        elif not _dates_equal(current_fd, file_src):
            repairs["FILE_DATE"] = file_src
            repairs["FILE_DATE_FLAG"] = "FIXED"

    # -- PERMIT_DATE --
    issued = _issued_date(tasks)
    current_pd = row["PERMIT_DATE"]

    if issued is not pd.NaT:
        if pd.isna(current_pd):
            if effective_status in ("Active", "Final"):
                repairs["PERMIT_DATE"] = issued
                repairs["PERMIT_DATE_FLAG"] = "FILLED"
        elif not _dates_equal(current_pd, issued):
            repairs["PERMIT_DATE"] = issued
            repairs["PERMIT_DATE_FLAG"] = "FIXED"

    # -- FINAL_DATE --
    final_date = _final_date_from_tasks(tasks)
    if final_date is pd.NaT:
        final_date = _final_date_from_inspections(d.get("inspections") or [])

    current_final = row["FINAL_DATE"]

    if effective_status == "Final":
        if final_date is not pd.NaT:
            if pd.isna(current_final):
                repairs["FINAL_DATE"] = final_date
                repairs["FINAL_DATE_FLAG"] = "FILLED"
            elif not _dates_equal(current_final, final_date):
                repairs["FINAL_DATE"] = final_date
                repairs["FINAL_DATE_FLAG"] = "FIXED"
    elif not pd.isna(current_final):
        repairs["FINAL_DATE"] = pd.NaT
        repairs["FINAL_DATE_FLAG"] = "FIXED"


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Monterey County permit records using the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Monterey County".  Must
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
        if schema != "unknown" and schema != "missing":
            _repair_record(row, d, repairs)

        for key, value in repairs.items():
            out.at[idx, key] = value

    for col in ("FILE_DATE", "PERMIT_DATE", "FINAL_DATE"):
        if col in out.columns:
            out[col] = pd.to_datetime(out[col], errors="coerce")

    return out


# ── CLI: run standalone to preview repair stats ─────────────────────────────

if __name__ == "__main__":
    import os
    from pathlib import Path
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[3] / ".env")
    MY_DATA_PATH = os.getenv("MY_DATA_PATH")
    AGENT_DATA_PATH = os.getenv("AGENT_DATA_PATH")
    filepath = os.path.join(MY_DATA_PATH, "processed_data", "permits_ca_sample.parquet")
    df = pd.read_parquet(filepath)
    city = df[(df["JURISDICTION"] == "Monterey County") & (df["STATE"] == "CA")].copy()

    print(f"Monterey County records: {len(city):,}\n")

    repaired = data_repair(city)

    if AGENT_DATA_PATH:
        out_dir = Path(AGENT_DATA_PATH) / "repaired"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "permits_ca_monterey_county_repaired.parquet"
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

    print("\nSTATUS_NORMALIZED_FLAG breakdown:")
    print(repaired["STATUS_NORMALIZED_FLAG"].value_counts(dropna=False).to_string())

    print("\nSTATUS transitions (where flagged):")
    flagged = repaired[repaired["STATUS_NORMALIZED_FLAG"].notna()].copy()
    if len(flagged):
        flagged["before"] = city.loc[flagged.index, "STATUS_NORMALIZED"]
        print(
            flagged.groupby(
                [flagged["before"].fillna("(null)"), "STATUS_NORMALIZED", "STATUS_NORMALIZED_FLAG"]
            )
            .size()
            .rename("n")
            .reset_index()
            .to_string(index=False)
        )

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

    print("\nChronology checks (after repair):")
    f = pd.to_datetime(repaired["FILE_DATE"], errors="coerce")
    p = pd.to_datetime(repaired["PERMIT_DATE"], errors="coerce")
    fin = pd.to_datetime(repaired["FINAL_DATE"], errors="coerce")
    inv_fp = f.notna() & p.notna() & (p.dt.normalize() < f.dt.normalize())
    inv_pf = p.notna() & fin.notna() & (fin.dt.normalize() < p.dt.normalize())
    print(f"  PERMIT < FILE: {inv_fp.sum()}")
    print(f"  FINAL < PERMIT: {inv_pf.sum()}")

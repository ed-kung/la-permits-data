"""Data repair for San Antonio (TX) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

San Antonio DATA comes from the city's Accela Civic Access portal scrape.
Two top-level key-set variants appear in the sample:

  - accela_full:  full payload (inspections, conditions, fees, …)
  - accela_lean:  stub without inspections / conditions / fees_details

Canonical mappings:
  - DATA.status (portal status)                 → STATUS_NORMALIZED
  - DATA.date (fallback: search_data.Date)      → FILE_DATE
  - Earliest Permit Issued Marked as Issued /
    Approved; else Issuance Marked as Active;
    else Closure Marked as Issued               → PERMIT_DATE
  - Latest Permit Closure / Closure / LOC /
    Case Inspection completion markers;
    else Permit Issued→Permit Closure;
    else Inspection Results Completed /
    final-titled inspections (Final only)       → FINAL_DATE

Known issues repaired:
  - STATUS_NORMALIZED often lags live DATA.status (STATUS_ORIGINAL /
    search-list snapshot). Common: Closed/LOC/COO still Active;
    About to Expire labeled Inactive; unmapped investigation /
    renewal statuses left null → FIXED / FILLED from DATA.status.
  - FILE_DATE missing despite DATA.date present → FILLED.
  - Large PERMIT_DATE gap on Issued / Active / Final / Inactive rows
    filled from Permit Issued or Issuance workflow; mismatches vs
    Accela issuance events FIXED.
  - Large Final FINAL_DATE gap filled from Closure / Permit Closure /
    LOC / Case Resolved markers; spurious FINAL_DATE on non-Final
    rows (often Inspection Results on still-Issued permits) cleared.

Not repairable / left as-is:
  - 42 Contact Information / similar stubs with empty DATA.status.
  - Active/Final rows with no Issued / Issuance-Active event (esp.
    Approved pre-issuance and many Issued stubs with only TBD) →
    PERMIT_DATE stays missing.
  - Final Closed rows with no Closure / Permit Closure / LOC event
    (esp. some MEP Trade / Tree permits) → FINAL_DATE stays missing.
"""

from __future__ import annotations

import json
import math
from typing import Optional

import numpy as np
import pandas as pd


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
    """Parse a date value, returning pd.NaT on failure / blanks / sentinels."""
    if val is None:
        return pd.NaT
    if isinstance(val, float) and math.isnan(val):
        return pd.NaT
    if not isinstance(val, str) and pd.isna(val):
        return pd.NaT
    if isinstance(val, dict):
        return pd.NaT
    text = str(val).strip()
    if not text or text.upper() in {
        "TBD", "NONE", "N/A", "NA", "NULL", "NAN",
        "00/00/0000", "0/0/0000",
    }:
        return pd.NaT
    try:
        dt = pd.to_datetime(val, errors="coerce")
    except (ValueError, TypeError, OverflowError):
        return pd.NaT
    if pd.isna(dt):
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


def _event_marked(event: dict) -> tuple[str, object]:
    """Return (Marked as, on-date) from an Accela task event."""
    marked = (event.get("Marked as ") or event.get("Marked as") or "").strip()
    on = event.get(" on ")
    if on is None:
        on = event.get(" on")
    return marked, on


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())
    if not ({"status", "date", "tasks", "search_data"} <= keys):
        return "unknown"
    if "inspections" in keys and "conditions" in keys:
        return "accela_full"
    return "accela_lean"


def _apply_status(repairs: dict, current, expected: Optional[str]) -> Optional[str]:
    """Apply expected STATUS_NORMALIZED; return effective status."""
    if expected is None:
        return None if pd.isna(current) else current

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


def _task_event_dates(d: dict, task_name: str, markers: set[str]):
    """Return datetimes for task events whose Marked-as is in *markers*."""
    dates = []
    for task in d.get("tasks") or []:
        if not isinstance(task, dict) or task.get("name") != task_name:
            continue
        for event in task.get("events") or []:
            if not isinstance(event, dict):
                continue
            marked, on = _event_marked(event)
            if marked not in markers:
                continue
            dt = _safe_to_datetime(on)
            if dt is not pd.NaT and not pd.isna(dt):
                dates.append(dt)
    return dates


def _task_event_dates_name_contains(d: dict, needle: str, markers: set[str]):
    """Dates for tasks whose name contains *needle* and Marked-as in markers."""
    dates = []
    needle_l = needle.lower()
    for task in d.get("tasks") or []:
        if not isinstance(task, dict):
            continue
        name = str(task.get("name") or "")
        if needle_l not in name.lower():
            continue
        for event in task.get("events") or []:
            if not isinstance(event, dict):
                continue
            marked, on = _event_marked(event)
            if marked not in markers:
                continue
            dt = _safe_to_datetime(on)
            if dt is not pd.NaT and not pd.isna(dt):
                dates.append(dt)
    return dates


# ── Status mapping ───────────────────────────────────────────────────────────

_STATUS_MAP = {
    # Final / completed / certificate issued
    "Closed": "Final",
    "Completed": "Final",
    "COO Issued": "Final",
    "LOC Issued": "Final",
    "Case Resolved": "Final",
    "Recorded": "Final",
    "No Violation": "Final",
    # Active / issued / approved / still in force
    "Issued": "Active",
    "Active": "Active",
    "Approved": "Active",
    "About to Expire": "Active",
    "Awaiting Renewal": "Active",
    "Renewal In Process": "Active",
    "Released": "Active",
    "Pass No Red/Yellow Violation": "Active",
    # In review / pre-issuance / awaiting applicant or investigation
    "Received": "In Review",
    "Under Review": "In Review",
    "Fees Due": "In Review",
    "Additional Info Required": "In Review",
    "Pending Inspection": "In Review",
    "Pending Resolution": "In Review",
    "Pending Issuance": "In Review",
    "Pending Yellow Investigation": "In Review",
    "Pending Red Investigation": "In Review",
    # Inactive / terminal without completion
    "Inactive": "Inactive",
    "Expired": "Inactive",
    "Withdrawn": "Inactive",
    "Denied": "Inactive",
    "Revoked": "Inactive",
}


def _map_status(d: dict) -> Optional[str]:
    """Map DATA.status to STATUS_NORMALIZED."""
    raw = d.get("status")
    if raw is None or (isinstance(raw, float) and math.isnan(raw)):
        return None
    text = str(raw).strip()
    if not text:
        return None
    if text in _STATUS_MAP:
        return _STATUS_MAP[text]
    lower = {k.lower(): v for k, v in _STATUS_MAP.items()}
    return lower.get(text.lower())


def _issuance_date(d: dict):
    """Earliest Accela issuance / activation date."""
    dates = _task_event_dates(d, "Permit Issued", {"Issued", "Approved"})
    if dates:
        return min(dates)

    dates = _task_event_dates(d, "Issuance", {"Active"})
    if dates:
        return min(dates)

    dates = _task_event_dates(d, "Closure", {"Issued"})
    if dates:
        return min(dates)

    return pd.NaT


def _final_date_candidate(d: dict):
    """Best available completion / finalization date from DATA."""
    cands = []
    cands += _task_event_dates(
        d, "Permit Closure", {"Closed", "LOC Issued", "COO Issued", "Closure"}
    )
    cands += _task_event_dates(d, "Closure", {"Closed", "Closure"})
    cands += _task_event_dates(d, "LOC Issuance", {"LOC Issued"})
    cands += _task_event_dates_name_contains(
        d, "Letter of Certification", {"LOC Issued"}
    )
    cands += _task_event_dates(
        d, "Case Inspection", {"Case Resolved", "No Violation"}
    )
    # Transition into closure recorded on the Permit Issued task
    cands += _task_event_dates(d, "Permit Issued", {"Permit Closure"})

    if cands:
        return max(cands)

    # Weaker fallbacks
    insp_results = _task_event_dates(d, "Inspection Results", {"Completed"})
    if insp_results:
        return max(insp_results)

    insp_dates = []
    for insp in d.get("inspections") or []:
        if not isinstance(insp, dict):
            continue
        status = str(insp.get("Status") or "").strip().lower()
        if status not in ("approved", "passed", "complete", "completed", "finaled"):
            continue
        title = str(insp.get("Title") or "")
        if "final" not in title.lower():
            continue
        dt = _safe_to_datetime(insp.get("Status Date"))
        if dt is pd.NaT or pd.isna(dt):
            dt = _safe_to_datetime(insp.get("Last Update Date"))
        if dt is not pd.NaT and not pd.isna(dt):
            insp_dates.append(dt)
    if insp_dates:
        return max(insp_dates)

    return pd.NaT


def _file_date_candidate(d: dict):
    """Accela record / application date."""
    dt = _safe_to_datetime(d.get("date"))
    if dt is not pd.NaT and not pd.isna(dt):
        return dt
    search = d.get("search_data")
    if isinstance(search, dict):
        return _safe_to_datetime(search.get("Date"))
    return pd.NaT


# ── Per-row repair ───────────────────────────────────────────────────────────

def _repair_row(row, d: dict, repairs: dict) -> None:
    """Repair one San Antonio Accela record."""
    expected = _map_status(d)
    effective_status = _apply_status(repairs, row["STATUS_NORMALIZED"], expected)

    # -- FILE_DATE ← DATA.date / search_data.Date --
    _apply_date(repairs, row, "FILE_DATE", _file_date_candidate(d))

    # -- PERMIT_DATE ← Permit Issued Issued* / Issuance Active --
    issue = _issuance_date(d)
    if issue is not pd.NaT and not pd.isna(issue):
        if effective_status in ("Active", "Final", "Inactive", "In Review"):
            _apply_date(repairs, row, "PERMIT_DATE", issue)

    # -- FINAL_DATE ← Closure / Permit Closure / LOC / Case Resolved --
    final_src = _final_date_candidate(d)
    if effective_status == "Final":
        if final_src is not pd.NaT and not pd.isna(final_src):
            _apply_date(repairs, row, "FINAL_DATE", final_src)
    else:
        _clear_date(repairs, row, "FINAL_DATE")


# ── Main entry point ─────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    San Antonio permit records using the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "San Antonio".  Must contain
        columns STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, FINAL_DATE,
        and DATA.

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
        if d is None:
            continue

        repairs: dict = {}
        if schema.startswith("accela_"):
            _repair_row(row, d, repairs)

        for key, value in repairs.items():
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
    filepath = os.path.join(MY_DATA_PATH, "processed_data", "permits_tx_sample.parquet")
    df = pd.read_parquet(filepath)
    city = df[(df["JURISDICTION"] == "San Antonio") & (df["STATE"] == "TX")].copy()

    print(f"San Antonio records: {len(city):,}\n")

    repaired = data_repair(city)

    print("INFERRED_SCHEMA distribution:")
    for s, c in repaired["INFERRED_SCHEMA"].value_counts(dropna=False).items():
        print(f"  {str(s):35s}: {c:>4,}")
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

    print("\nFILE_DATE overall (after): "
          f"{repaired['FILE_DATE'].notna().sum()}/{len(repaired)}")

    print("\nPERMIT_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        if len(sub) == 0:
            continue
        n_has = sub["PERMIT_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({n_has / len(sub):.1%})")

    print("\nFINAL_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        if len(sub) == 0:
            continue
        n_has = sub["FINAL_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({n_has / len(sub):.1%})")

    if AGENT_DATA_PATH:
        out_dir = os.path.join(AGENT_DATA_PATH, "repaired")
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, "permits_tx_san_antonio_repaired.parquet")
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote {out_path}")

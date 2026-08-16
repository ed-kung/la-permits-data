"""Data repair for Dallas (TX) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Dallas DATA has two families of payloads:

  - legacy_*:  City of Dallas permit-portal scrape with top-level
               ``Status``, ``Created Date``, ``Issued Date``,
               ``Completed Date``. Key-set variants:
                 legacy_related — includes related_information (+ owner)
                 legacy_owner   — owner present, no related_information
                 legacy_parcel  — Parcel list present
  - accela:    Accela Civic Platform record with ``status``, ``date``,
               ``tasks``, ``search_data``, etc.

Canonical mappings (legacy):
  - Status            → STATUS_NORMALIZED
  - Created Date      → FILE_DATE
  - Issued Date       → PERMIT_DATE
  - Completed Date    → FINAL_DATE (Final status only)

Canonical mappings (accela):
  - status            → STATUS_NORMALIZED
  - date              → FILE_DATE
  - Permit Issuance task marked Issued → PERMIT_DATE
  - Inspection Final Inspection Complete /
    Certificate of Occupancy Final CO Issued /
    Modification Review Modification Request Approved → FINAL_DATE
    (Final status only)

Known issues repaired:
  - STATUS_NORMALIZED null for New Web Application, CO Complete, and
    several Accela statuses (Document Received, Application/Permit
    About to Expire) → FILLED from Status/status.
  - STATUS_NORMALIZED disagrees with DATA Status (e.g. Work Completed /
    CO Issued stored as Active because STATUS_ORIGINAL lagged) → FIXED.
  - Missing PERMIT_DATE when Issued Date / Permit Issuance Issued exists
    → FILLED.
  - Missing FINAL_DATE on Final rows when Completed Date or Accela
    completion task marks exist → FILLED.
  - Spurious FINAL_DATE on non-Final rows (agency stamps Completed Date
    on cancelled / expired / revoked / null-status cases; Accela may
    stamp Final Inspection Complete while still Inspection Phase)
    → cleared (FIXED).

Not repairable / left as-is:
  - ~200 legacy rows with null Status and no STATUS_ORIGINAL → status
    stays missing; dates cleared when non-Final.
  - FILE_DATE missing only when Created Date / date also absent.
  - Accela Closed - Complete / Closed - Approved rows without a
    completion task mark → FINAL_DATE stays missing.
  - Accela Active/Final rows without Permit Issuance Issued →
    PERMIT_DATE stays missing.
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


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())
    if "tasks" in keys and "status" in keys:
        return "accela"
    if "Status" in keys and "Created Date" in keys:
        if "related_information" in keys:
            return "legacy_related"
        if "Parcel" in keys:
            return "legacy_parcel"
        if "owner" in keys:
            return "legacy_owner"
        return "legacy_basic"
    return "unknown"


# ── Status mapping ───────────────────────────────────────────────────────────

_LEGACY_STATUS_MAP = {
    # Final
    "Work Completed": "Final",
    "CO Issued": "Final",
    "CO Complete": "Final",
    # Active
    "Permit Issued": "Active",
    "CO Pending": "Active",
    "Permit Application Approved": "Active",
    # In Review
    "New Application": "In Review",
    "New Web Application": "In Review",
    "Permit Pending": "In Review",
    # Inactive
    "Application Cancelled": "Inactive",
    "Application Denied": "Inactive",
    "Application Expired": "Inactive",
    "Permit Expired": "Inactive",
    "Permit Revoked": "Inactive",
}

_ACCELA_STATUS_MAP = {
    # Final
    "Closed - Complete": "Final",
    "Closed - Approved": "Final",
    "TCO Issued": "Final",
    # Active
    "Inspection Phase": "Active",
    "Active": "Active",
    "Permit About to Expire": "Active",
    # In Review
    "Additional Info Required": "In Review",
    "In Review": "In Review",
    "Pending": "In Review",
    "Plan Review": "In Review",
    "New": "In Review",
    "Ready to Issue": "In Review",
    "Document Received": "In Review",
    "Application About to Expire": "In Review",
    # Inactive
    "Closed - Denied": "Inactive",
    "Closed - Withdrawn": "Inactive",
    "Expired": "Inactive",
    "Permit Expired": "Inactive",
}


def _apply_status(repairs: dict, current, expected: Optional[str]):
    """Apply expected STATUS_NORMALIZED; return effective status."""
    if expected is None:
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


def _task_dates(d: dict, task_name: str, marked_values: set) -> list:
    """Collect event dates for a named Accela task with given marks."""
    dates = []
    for task in d.get("tasks") or []:
        if not isinstance(task, dict) or task.get("name") != task_name:
            continue
        for event in task.get("events") or []:
            if not isinstance(event, dict):
                continue
            if event.get("Marked as ") in marked_values:
                dt = _safe_to_datetime(event.get(" on "))
                if dt is not pd.NaT and not pd.isna(dt):
                    dates.append(dt)
    return dates


def _earliest_task_date(d: dict, task_name: str, marked_values: set):
    dates = _task_dates(d, task_name, marked_values)
    return min(dates) if dates else pd.NaT


def _latest_task_date(d: dict, task_name: str, marked_values: set):
    dates = _task_dates(d, task_name, marked_values)
    return max(dates) if dates else pd.NaT


def _accela_final_date(d: dict):
    """Best Accela completion / sign-off date from task marks."""
    candidates = []
    for task_name, marks in (
        ("Inspection", {"Final Inspection Complete"}),
        ("Certificate of Occupancy", {"Final CO Issued"}),
        ("Modification Review", {"Modification Request Approved"}),
    ):
        dt = _latest_task_date(d, task_name, marks)
        if dt is not pd.NaT and not pd.isna(dt):
            candidates.append(dt)
    return max(candidates) if candidates else pd.NaT


# ── Per-schema repair ────────────────────────────────────────────────────────

def _repair_legacy(row, d: dict, repairs: dict) -> None:
    raw = d.get("Status")
    expected = None
    if raw is not None and not (isinstance(raw, float) and math.isnan(raw)):
        expected = _LEGACY_STATUS_MAP.get(str(raw).strip())

    effective_status = _apply_status(repairs, row["STATUS_NORMALIZED"], expected)

    _apply_date(repairs, row, "FILE_DATE", d.get("Created Date"))
    _apply_date(repairs, row, "PERMIT_DATE", d.get("Issued Date"))

    if effective_status == "Final":
        _apply_date(repairs, row, "FINAL_DATE", d.get("Completed Date"))
    else:
        _clear_date(repairs, row, "FINAL_DATE")


def _repair_accela(row, d: dict, repairs: dict) -> None:
    raw = d.get("status")
    expected = None
    if raw is not None and not (isinstance(raw, float) and math.isnan(raw)):
        expected = _ACCELA_STATUS_MAP.get(str(raw).strip())

    effective_status = _apply_status(repairs, row["STATUS_NORMALIZED"], expected)

    _apply_date(repairs, row, "FILE_DATE", d.get("date"))

    issue_dt = _earliest_task_date(d, "Permit Issuance", {"Issued"})
    _apply_date(repairs, row, "PERMIT_DATE", issue_dt)

    if effective_status == "Final":
        _apply_date(repairs, row, "FINAL_DATE", _accela_final_date(d))
    else:
        _clear_date(repairs, row, "FINAL_DATE")


# ── Main entry point ─────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Dallas permit records using the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Dallas".  Must contain
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
        if schema.startswith("legacy_"):
            _repair_legacy(row, d, repairs)
        elif schema == "accela":
            _repair_accela(row, d, repairs)

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
    filepath = os.path.join(MY_DATA_PATH, "processed_data", "permits_tx_sample.parquet")
    df = pd.read_parquet(filepath)
    city = df[(df["JURISDICTION"] == "Dallas") & (df["STATE"] == "TX")].copy()

    print(f"Dallas records: {len(city):,}\n")

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
        out_path = os.path.join(out_dir, "permits_tx_dallas_repaired.parquet")
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote {out_path}")

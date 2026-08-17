"""Data repair for McAllen (TX) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

McAllen DATA is Accela Civic Platform. Two top-level key-set variants
appear in the sample (same status/date fields used for repair):

  - accela_full:  address, address_lines, conditions, contacts, date,
                  details, fees_details, inspections, job_value,
                  more_details, record_type, related_records,
                  search_data, status, tasks, total_fees, valuation
  - accela_lean:  subset without contacts / inspections / fees_details /
                  conditions / address_lines / related_records

Canonical mappings:
  - status                              → STATUS_NORMALIZED
  - date                                → FILE_DATE
  - Issue Permit marked Issued /
    Online Permit                       → PERMIT_DATE
  - Inspection / Inspect / Final
    marked Finaled; Certificate of
    Occupancy Issued CofO; Certificate
    of Completion Issued Cof C;
    Temp Occ* Finaled; Final* Passed
    inspection row                      → FINAL_DATE (Final only)

Known issues repaired:
  - STATUS_NORMALIZED null for Conditions Acknowledged / Working
    Clearance / Released / Acknowledge Conditions and a few rows where
    STATUS_ORIGINAL lagged DATA.status → FILLED.
  - STATUS_NORMALIZED disagrees with DATA.status (e.g. Certificate of
    Occupancy / Closed stored as Active; Issued stored as In Review /
    Final; Finaled stored as Inactive; Temporary Occupancy as Final;
    CO_Issued as Active) → FIXED.
  - Missing PERMIT_DATE when Issue Permit is marked Online Permit
    (upstream only captured Issued) → FILLED.
  - Missing FINAL_DATE on Final rows when Finaled / CofO / Final*
    Passed inspection signals exist → FILLED.
  - FINAL_DATE incorrectly set to Inspection Never Finaled date →
    FIXED (replaced with true Finaled / CofO date, or cleared).
  - Spurious FINAL_DATE on non-Final rows → cleared (FIXED).

Not repairable / left as-is:
  - 2 rows with null DATA.status and empty tasks.
  - Completed / Complete historical shells with empty task events and
    no usable Final* Passed inspection → PERMIT_DATE / FINAL_DATE stay
    missing.
  - Active / Final rows with no Issue Permit Issued or Online Permit
    event → PERMIT_DATE stays missing (common on Completed).
  - Approved (ready-to-issue but not yet issued) → PERMIT_DATE stays
    missing.
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
    if not ({"status", "date", "tasks"} <= keys):
        return "unknown"
    if "inspections" in keys and "contacts" in keys:
        return "accela_full"
    return "accela_lean"


# ── Status mapping ───────────────────────────────────────────────────────────

_STATUS_MAP = {
    # Final
    "Closed": "Final",
    "Finaled": "Final",
    "Completed": "Final",
    "Complete": "Final",
    "Certificate of Occupancy": "Final",
    "Certificate of Completion": "Final",
    "CO_Issued": "Final",
    # Active (issued / in construction / temporary use)
    "Issued": "Active",
    "Approved": "Active",
    "Working Clearance": "Active",
    "Released": "Active",
    "Temporary Occupancy": "Active",
    # In Review
    "Under Review": "In Review",
    "Scheduled": "In Review",
    "Applied": "In Review",
    "New": "In Review",
    "Accepted": "In Review",
    "Conditions Acknowledged": "In Review",
    "Acknowledge Conditions": "In Review",
    # Inactive
    "Expired": "Inactive",
    "Rejected": "Inactive",
    "Failed": "Inactive",
    "Void": "Inactive",
    "Never Finaled": "Inactive",
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


def _event_marked(event: dict) -> Optional[str]:
    marked = event.get("Marked as ")
    if marked is None:
        marked = event.get("Marked as")
    if marked is None or (isinstance(marked, float) and math.isnan(marked)):
        return None
    text = str(marked).strip()
    return text or None


def _task_dates(d: dict, task_names: set, marked_values: set) -> list:
    """Collect event dates for named Accela tasks with given marks."""
    dates = []
    for task in d.get("tasks") or []:
        if not isinstance(task, dict) or task.get("name") not in task_names:
            continue
        for event in task.get("events") or []:
            if not isinstance(event, dict):
                continue
            if _event_marked(event) in marked_values:
                dt = _safe_to_datetime(event.get(" on "))
                if dt is pd.NaT or pd.isna(dt):
                    dt = _safe_to_datetime(event.get("on"))
                if dt is not pd.NaT and not pd.isna(dt):
                    dates.append(dt)
    return dates


def _earliest_task_date(d: dict, task_names: set, marked_values: set):
    dates = _task_dates(d, task_names, marked_values)
    return min(dates) if dates else pd.NaT


def _latest_task_date(d: dict, task_names: set, marked_values: set):
    dates = _task_dates(d, task_names, marked_values)
    return max(dates) if dates else pd.NaT


def _expected_status(d: dict) -> Optional[str]:
    raw = d.get("status")
    if raw is not None and not (isinstance(raw, float) and math.isnan(raw)):
        text = str(raw).strip()
        if text:
            mapped = _STATUS_MAP.get(text)
            if mapped is not None:
                return mapped

    # Null / blank agency status: infer only from strong workflow signals
    if _latest_task_date(d, {"Inspection", "Inspect", "Final"}, {"Finaled"}) is not pd.NaT:
        return "Final"
    if _earliest_task_date(
        d, {"Issue Permit"}, {"Issued", "Online Permit"}
    ) is not pd.NaT:
        return "Active"
    return None


def _permit_date(d: dict):
    """Earliest permit issuance from Issue Permit Issued / Online Permit."""
    return _earliest_task_date(
        d, {"Issue Permit"}, {"Issued", "Online Permit"}
    )


def _final_inspection_passed_date(d: dict):
    """Latest Status Date on Final* inspections marked Passed/Pass."""
    dates = []
    for insp in d.get("inspections") or []:
        if not isinstance(insp, dict):
            continue
        title = str(insp.get("Title") or "").strip().lower()
        status = str(insp.get("Status") or "").strip().lower()
        if not title.startswith("final"):
            continue
        if "pass" not in status:
            continue
        dt = _safe_to_datetime(insp.get("Status Date"))
        if dt is not pd.NaT and not pd.isna(dt):
            dates.append(dt)
    return max(dates) if dates else pd.NaT


def _final_date(d: dict):
    """Best completion / sign-off date for Final records."""
    candidates = []

    finaled = _latest_task_date(
        d, {"Inspection", "Inspect", "Final"}, {"Finaled"}
    )
    if finaled is not pd.NaT and not pd.isna(finaled):
        candidates.append(finaled)

    cofo = _latest_task_date(
        d,
        {"Certificate of Occupancy"},
        {"Issued CofO", "Issued C of O"},
    )
    if cofo is not pd.NaT and not pd.isna(cofo):
        candidates.append(cofo)

    cofc = _latest_task_date(
        d, {"Certificate of Completion"}, {"Issued Cof C"}
    )
    if cofc is not pd.NaT and not pd.isna(cofc):
        candidates.append(cofc)

    if candidates:
        return max(candidates)

    # Weaker completion signals when no Finaled / CO stamp exists
    temp_finaled = _latest_task_date(
        d,
        {
            "Temp Occ/Working Clearance",
            "Temp Occ or Working Clearance",
            "Working Clearance",
        },
        {"Finaled"},
    )
    if temp_finaled is not pd.NaT and not pd.isna(temp_finaled):
        return temp_finaled

    return _final_inspection_passed_date(d)


# ── Per-row repair ───────────────────────────────────────────────────────────

def _repair_row(row, d: dict, repairs: dict) -> None:
    """Repair one McAllen Accela record."""
    expected = _expected_status(d)
    effective_status = _apply_status(repairs, row["STATUS_NORMALIZED"], expected)

    # -- FILE_DATE ← top-level date (application / record date) --
    _apply_date(repairs, row, "FILE_DATE", d.get("date"))

    # -- PERMIT_DATE ← Issue Permit Issued / Online Permit --
    _apply_date(repairs, row, "PERMIT_DATE", _permit_date(d))

    # -- FINAL_DATE ← Finaled / CofO / inspection Final* Passed (Final only) --
    if effective_status == "Final":
        _apply_date(repairs, row, "FINAL_DATE", _final_date(d))
    else:
        _clear_date(repairs, row, "FINAL_DATE")


# ── Main entry point ─────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    McAllen permit records using the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "McAllen".  Must contain
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
        if schema in {"accela_full", "accela_lean"}:
            _repair_row(row, d, repairs)

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
    city = df[(df["JURISDICTION"] == "McAllen") & (df["STATE"] == "TX")].copy()

    print(f"McAllen records: {len(city):,}\n")

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
        out_path = os.path.join(out_dir, "permits_tx_mcallen_repaired.parquet")
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote {out_path}")

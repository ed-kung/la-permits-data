"""Data repair for El Paso (TX) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

El Paso DATA is Accela Civic Platform. Two top-level key-set variants
appear in the sample (same status/date fields used for repair):

  - accela_full:  address, address_lines, conditions, contacts, date,
                  details, fees_details, inspections, job_value,
                  more_details, record_type, related_records,
                  search_data, status, tasks, total_fees, valuation
  - accela_lean:  subset without contacts / inspections / fees_details /
                  conditions / address_lines / related_records

Canonical mappings:
  - status                         → STATUS_NORMALIZED
  - date                           → FILE_DATE
  - Issue task marked Issued       → PERMIT_DATE
    (fallback: Issue Certificate Issued when Issue Issued is absent)
  - Close task marked Closed/Close → FINAL_DATE (Final status only)
    (fallbacks: Issue Certificate Issued; Inspection marked Closed;
     Inspection Issued TCO / Approved TCO)

Known issues repaired:
  - STATUS_NORMALIZED missing for unmapped agency statuses and for a
    few null-status rows with a Close task → FILLED.
  - PERMIT_DATE set to Issue Certificate date when an earlier Issue
    Issued date exists → FIXED to Issue Issued.
  - Missing PERMIT_DATE where Issue Issued exists → FILLED.
  - Missing FINAL_DATE on Final rows where Close / certificate / TCO /
    Inspection Closed signals exist → FILLED.

Not repairable / left as-is:
  - 21 rows with null DATA.status and no usable task marks.
  - FRZ / NFZ left mapped as In Review (flood-zone style labels with no
    further workflow signal in DATA).
  - Active / Final rows with no Issue or Issue Certificate Issued event
    → PERMIT_DATE stays missing.
  - Final rows with no Close / certificate / TCO / Inspection Closed
    signal → FINAL_DATE stays missing (common on older Closed records).
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
    "Final": "Final",
    "Issue Certificate": "Final",
    "TCO Issued": "Final",
    "Audit Review Complied": "Final",
    # Active
    "Inspection": "Active",
    "Issued": "Active",
    # In Review
    "In Review": "In Review",
    "Hold for Corrections": "In Review",
    "Out for Corrections": "In Review",
    "Pending Review": "In Review",
    "Pending Issuance": "In Review",
    "Ready to Issue": "In Review",
    "Non-Compliant Resubmit": "In Review",
    "Approved - Pending Contractor": "In Review",
    # Flood-zone style labels with no further workflow signal in sample
    "FRZ": "In Review",
    "NFZ": "In Review",
    # Inactive
    "Expired": "Inactive",
    "Cancelled": "Inactive",
    "Void": "Inactive",
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


def _task_dates(d: dict, task_name: str, marked_values: set) -> list:
    """Collect event dates for a named Accela task with given marks."""
    dates = []
    for task in d.get("tasks") or []:
        if not isinstance(task, dict) or task.get("name") != task_name:
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


def _earliest_task_date(d: dict, task_name: str, marked_values: set):
    dates = _task_dates(d, task_name, marked_values)
    return min(dates) if dates else pd.NaT


def _latest_task_date(d: dict, task_name: str, marked_values: set):
    dates = _task_dates(d, task_name, marked_values)
    return max(dates) if dates else pd.NaT


def _expected_status(d: dict) -> Optional[str]:
    raw = d.get("status")
    if raw is not None and not (isinstance(raw, float) and math.isnan(raw)):
        text = str(raw).strip()
        if text:
            mapped = _STATUS_MAP.get(text)
            if mapped is not None:
                return mapped

    # Null / blank agency status: infer only from strong terminal signals
    if _latest_task_date(d, "Close", {"Closed", "Close"}) is not pd.NaT:
        return "Final"
    if _earliest_task_date(d, "Issue", {"Issued"}) is not pd.NaT:
        return "Active"
    return None


def _permit_date(d: dict):
    """Earliest permit issuance date from Issue, else Issue Certificate."""
    issue = _earliest_task_date(d, "Issue", {"Issued"})
    if issue is not pd.NaT and not pd.isna(issue):
        return issue
    return _earliest_task_date(d, "Issue Certificate", {"Issued"})


def _final_date(d: dict):
    """Best completion / sign-off date for Final records."""
    candidates = []
    close = _latest_task_date(d, "Close", {"Closed", "Close"})
    if close is not pd.NaT and not pd.isna(close):
        candidates.append(close)

    cert = _latest_task_date(d, "Issue Certificate", {"Issued"})
    if cert is not pd.NaT and not pd.isna(cert):
        candidates.append(cert)

    insp_closed = _latest_task_date(d, "Inspection", {"Closed"})
    if insp_closed is not pd.NaT and not pd.isna(insp_closed):
        candidates.append(insp_closed)

    tco = _latest_task_date(d, "Inspection", {"Issued TCO", "Approved TCO"})
    if tco is not pd.NaT and not pd.isna(tco):
        candidates.append(tco)

    return max(candidates) if candidates else pd.NaT


# ── Per-row repair ───────────────────────────────────────────────────────────

def _repair_row(row, d: dict, repairs: dict) -> None:
    """Repair one El Paso Accela record."""
    expected = _expected_status(d)
    effective_status = _apply_status(repairs, row["STATUS_NORMALIZED"], expected)

    # -- FILE_DATE ← top-level date (application / record date) --
    _apply_date(repairs, row, "FILE_DATE", d.get("date"))

    # -- PERMIT_DATE ← Issue Issued (fallback Issue Certificate Issued) --
    _apply_date(repairs, row, "PERMIT_DATE", _permit_date(d))

    # -- FINAL_DATE ← Close / certificate / inspection close / TCO (Final only) --
    if effective_status == "Final":
        _apply_date(repairs, row, "FINAL_DATE", _final_date(d))
    else:
        _clear_date(repairs, row, "FINAL_DATE")


# ── Main entry point ─────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    El Paso permit records using the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "El Paso".  Must contain
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
    city = df[(df["JURISDICTION"] == "El Paso") & (df["STATE"] == "TX")].copy()

    print(f"El Paso records: {len(city):,}\n")

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
        out_path = os.path.join(out_dir, "permits_tx_el_paso_repaired.parquet")
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote {out_path}")

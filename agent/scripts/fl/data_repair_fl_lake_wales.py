"""Data repair for Lake Wales (FL) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Lake Wales DATA is the same nested city permit-portal family as Oldsmar
(Parcel / Permit / Contacts, optional Notes / InspectionsCompleted /
InspectionsScheduled / InspectionsRequested). Canonical dates and status
live under Permit.Main (colon-suffixed keys).

INFERRED_SCHEMA suffixes (key-set variants):
  - nested_insp_notes:       InspectionsCompleted + Notes
  - nested_insp_sched_notes: InspectionsCompleted + InspectionsScheduled
                             + Notes
  - nested_insp_sched:       InspectionsCompleted + InspectionsScheduled
  - nested_insp_req:         InspectionsCompleted + InspectionsRequested
  - nested_insp:             InspectionsCompleted only
  - nested_sched_notes:      InspectionsScheduled + Notes
  - nested_notes:            Notes only
  - nested_next_action:      Permit.Main has Next Action: (often omits
                             Issued Date:)
  - nested_minimal:          Parcel + Permit + Contacts only
  - nested_empty_main:       Permit.Main missing / empty (scrape shells)

Canonical mappings:
  - Permit.Main["Permit Status:"]     → STATUS_NORMALIZED
  - Permit.Main["Receipt Date:"];
      else ["Issued Date:"]           → FILE_DATE
  - Permit.Main["Issued Date:"]       → PERMIT_DATE
  - Permit.Main["Closed Date:"];
      else (Final only) latest COMPLETE
      InspectionsCompleted timestamp  → FINAL_DATE

Known issues repaired:
  - Null STATUS_NORMALIZED on INACTV / SM-ACT portal codes (not in the
    upstream map) → FILLED to Inactive / Active.
  - FINAL_DATE missing on COMPLT rows where Closed Date is blank / N/A
    but InspectionsCompleted has COMPLETE timestamps → FILLED from the
    latest completed inspection (calendar day).

Not repairable from DATA:
  - Hollow scrape shells (empty Permit.Main or empty Permit No / Receipt
    / Issued / Closed) → dates stay missing; status stays null when
    Permit Status is blank.
  - ACTIVE / COMPLT / VOID rows that omit Issued Date: → PERMIT_DATE
    stays missing (no issuance stamp in DATA).
  - COMPLT rows with blank Closed Date and no completed inspections →
    FINAL_DATE stays missing.
"""

from __future__ import annotations

import json
import math
import re
from typing import Optional

import numpy as np
import pandas as pd


_DATE_RE = re.compile(r"^\d{1,2}/\d{1,2}/\d{2,4}$")
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")


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
    """Parse a date value, returning pd.NaT on failure / sentinel."""
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return pd.NaT
    if isinstance(val, (dict, list)):
        return pd.NaT
    if not isinstance(val, str) and pd.isna(val):
        return pd.NaT

    text = str(val).strip().replace("\xa0", " ")
    if not text or text.upper() in {
        "TBD", "NULL", "NONE", "N/A", "NA", "NAN",
        "00/00/0000", "0/0/0000",
    }:
        return pd.NaT
    if text.startswith("01/01/1900") or text.startswith("1900-01-01"):
        return pd.NaT

    # Prefer calendar-shaped portal dates (with optional time suffix).
    date_part = text.split()[0] if " " in text else text
    if _DATE_RE.match(date_part) or _ISO_DATE_RE.match(date_part):
        try:
            dt = pd.to_datetime(text, errors="raise")
        except (ValueError, TypeError, OverflowError):
            return pd.NaT
        if pd.isna(dt):
            return pd.NaT
        return dt

    if len(text) > 40:
        return pd.NaT
    try:
        dt = pd.to_datetime(text, errors="raise")
    except (ValueError, TypeError, OverflowError):
        return pd.NaT
    if pd.isna(dt):
        return pd.NaT
    return dt


def _dates_equal(a, b) -> bool:
    """Compare two datelike values at calendar-day resolution."""
    da = _safe_to_datetime(a)
    db = _safe_to_datetime(b)
    if da is pd.NaT or db is pd.NaT:
        return False
    return da.normalize() == db.normalize()


def _lookup_status(raw_status: Optional[str], status_map: dict) -> Optional[str]:
    if raw_status is None:
        return None
    expected = status_map.get(raw_status)
    if expected is not None:
        return expected
    raw_norm = str(raw_status).strip()
    if not raw_norm:
        return None
    expected = status_map.get(raw_norm)
    if expected is not None:
        return expected
    expected = status_map.get(raw_norm.upper())
    if expected is not None:
        return expected
    for k, v in status_map.items():
        if k.lower() == raw_norm.lower():
            return v
    return None


def _apply_status(repairs: dict, current, raw_status: Optional[str], status_map: dict):
    """Map raw status → STATUS_NORMALIZED; return effective status."""
    expected = _lookup_status(raw_status, status_map)
    if expected is None:
        return current if not (isinstance(current, float) and pd.isna(current)) else None

    if pd.isna(current):
        repairs["STATUS_NORMALIZED"] = expected
        repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"
    elif current != expected:
        repairs["STATUS_NORMALIZED"] = expected
        repairs["STATUS_NORMALIZED_FLAG"] = "FIXED"

    return repairs.get("STATUS_NORMALIZED", current)


def _apply_date(repairs: dict, row, field: str, candidate, *, allow_fill: bool = True) -> None:
    """Fill or fix *field* from *candidate* datetime (pd.NaT = no candidate)."""
    cand = _safe_to_datetime(candidate)
    if cand is pd.NaT:
        return
    # Store calendar-day timestamps to match existing column style.
    cand = cand.normalize()

    current = row[field]
    if pd.isna(current):
        if allow_fill:
            repairs[field] = cand
            repairs[f"{field}_FLAG"] = "FILLED"
    elif not _dates_equal(current, cand):
        repairs[field] = cand
        repairs[f"{field}_FLAG"] = "FIXED"


def _permit_main(d: dict) -> dict:
    permit = d.get("Permit")
    if not isinstance(permit, dict):
        return {}
    main = permit.get("Main")
    return main if isinstance(main, dict) else {}


def _latest_completed_inspection(d: dict):
    """Return the latest COMPLETE InspectionsCompleted timestamp, or NaT."""
    inspections = d.get("InspectionsCompleted")
    if not isinstance(inspections, list):
        return pd.NaT
    latest = pd.NaT
    for insp in inspections:
        if not isinstance(insp, dict):
            continue
        status = str(insp.get("InspectionStatus") or "").strip().upper()
        if status != "COMPLETE":
            continue
        dt = _safe_to_datetime(insp.get("Date/TimeCompleted"))
        if dt is pd.NaT:
            dt = _safe_to_datetime(insp.get("Date/TimeRequested"))
        if dt is pd.NaT:
            continue
        if latest is pd.NaT or dt > latest:
            latest = dt
    return latest


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())
    if "Permit" not in keys:
        return "unknown"

    main = _permit_main(data_dict)
    if not main:
        return "nested_empty_main"

    has_insp = "InspectionsCompleted" in keys
    has_sched = "InspectionsScheduled" in keys
    has_req = "InspectionsRequested" in keys
    has_notes = "Notes" in keys
    has_next = "Next Action:" in main

    if has_next:
        return "nested_next_action"
    if has_insp and has_sched and has_notes:
        return "nested_insp_sched_notes"
    if has_insp and has_sched:
        return "nested_insp_sched"
    if has_insp and has_req:
        return "nested_insp_req"
    if has_insp and has_notes:
        return "nested_insp_notes"
    if has_insp:
        return "nested_insp"
    if has_sched and has_notes:
        return "nested_sched_notes"
    if has_notes:
        return "nested_notes"
    return "nested_minimal"


# ── Status maps ──────────────────────────────────────────────────────────────

# Permit.Main["Permit Status:"] (portal codes) → STATUS_NORMALIZED
_STATUS_MAP = {
    "ACTIVE": "Active",
    "COMPLT": "Final",
    "EXPIRED": "Inactive",
    "VOID": "Inactive",
    "INACTV": "Inactive",
    "SM-ACT": "Active",  # semi-active / still-open issued permit
}


# ── Per-schema repair logic ─────────────────────────────────────────────────

def _repair_record(row, d: dict, repairs: dict) -> None:
    """Repair a Lake Wales nested-portal record."""
    main = _permit_main(d)
    raw_status = main.get("Permit Status:")
    if isinstance(raw_status, str):
        raw_status = raw_status.strip() or None

    effective_status = _apply_status(
        repairs, row["STATUS_NORMALIZED"], raw_status, _STATUS_MAP
    )

    # FILE_DATE ← Receipt Date (application / fee receipt), else Issued.
    receipt = _safe_to_datetime(main.get("Receipt Date:"))
    issued = _safe_to_datetime(main.get("Issued Date:"))
    file_cand = receipt if receipt is not pd.NaT else issued
    _apply_date(repairs, row, "FILE_DATE", file_cand)

    # PERMIT_DATE ← Issued Date
    _apply_date(repairs, row, "PERMIT_DATE", issued)

    # FINAL_DATE ← Closed Date; for Final rows, fall back to latest
    # completed inspection when Closed is blank/N/A.
    closed = _safe_to_datetime(main.get("Closed Date:"))
    final_cand = closed
    if final_cand is pd.NaT and effective_status == "Final":
        final_cand = _latest_completed_inspection(d)
    _apply_date(repairs, row, "FINAL_DATE", final_cand)


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Lake Wales permit records using information from the raw DATA JSON.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Lake Wales".  Must contain
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
        if schema not in {"missing", "unknown"}:
            _repair_record(row, d, repairs)

        for key, value in repairs.items():
            out.at[idx, key] = value

    for col in ("FILE_DATE", "PERMIT_DATE", "FINAL_DATE"):
        out[col] = pd.to_datetime(out[col], errors="coerce")

    return out


# ── CLI: run standalone to preview repair stats ─────────────────────────────

if __name__ == "__main__":
    import os
    from dotenv import load_dotenv, find_dotenv

    load_dotenv(find_dotenv())
    MY_DATA_PATH = os.getenv("MY_DATA_PATH")
    AGENT_DATA_PATH = os.getenv("AGENT_DATA_PATH")
    filepath = os.path.join(MY_DATA_PATH, "processed_data", "permits_fl_sample.parquet")
    df = pd.read_parquet(filepath)
    city = df[df["JURISDICTION"] == "Lake Wales"].copy()

    print(f"Lake Wales records: {len(city):,}\n")

    repaired = data_repair(city)

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

    print("\nFILE_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        part = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = part["FILE_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(part):>4,} ({n_has/len(part) if len(part) else 0:.1%})")

    print("\nPERMIT_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        part = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = part["PERMIT_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(part):>4,} ({n_has/len(part) if len(part) else 0:.1%})")

    print("\nFINAL_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        part = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = part["FINAL_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(part):>4,} ({n_has/len(part) if len(part) else 0:.1%})")

    still_null = repaired[repaired["STATUS_NORMALIZED"].isna()]
    print(f"\nRemaining null STATUS_NORMALIZED: {len(still_null)}")

    if AGENT_DATA_PATH:
        out_path = os.path.join(AGENT_DATA_PATH, "lake_wales_repaired_sample.parquet")
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote {out_path}")

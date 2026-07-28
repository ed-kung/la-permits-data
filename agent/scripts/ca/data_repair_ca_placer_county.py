"""Data repair for Placer County (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Placer County DATA is an Accela Citizen Access scrape. Task event keys
often have leading/trailing spaces ('Marked as ', ' on '). Structural /
content variants (used as INFERRED_SCHEMA):

  - accela_with_date:   top-level ``date`` + fees/inspections (older scrape)
  - accela_no_date:     no top-level ``date``; FILE_DATE from search_data
  - accela_partial:     has status/tasks but missing fees or contacts
  - search_data_only:   only ``search_data`` (TMP shells, blank Status)
  - empty_tasks:        Accela shell whose tasks have no dated events
                        (legacy DONE / sparse Construction Complete)

Canonical mappings:
  - DATA.status                                      → STATUS_NORMALIZED
  - DATA.date / search_data['Date']                  → FILE_DATE
      (reject sentinel year 1900; optional earliest fee Date fallback)
  - Process for Issuance|Ready to Issue|Issue Status
      / Issued (fallback: Plan Check|Plan Review / Issued) → PERMIT_DATE
  - Inspections|Inspection / Construction Complete
      (fallback: Final*-titled Final Pass inspection) → FINAL_DATE

Known issues repaired:
  - Stale STATUS_ORIGINAL vs live DATA.status (Construction Complete
    labeled Active; Expired labeled Active; Issued labeled In Review)
    → FIXED.
  - DONE legacy shells incorrectly labeled In Review → FIXED to Final.
  - 2 search_data-only TMP shells with blank Status → FILLED In Review.
  - Sentinel FILE_DATE 1900-01-01 (matches Accela placeholder) → cleared;
    fill from earliest fees_details Date when available.
  - PERMIT_DATE set to Process for Issuance / Ready to Issue when a later
    Issued event exists → FIXED.
  - Active/Final missing PERMIT_DATE despite Issued task marks → FILLED.
  - Final missing FINAL_DATE despite Construction Complete or Final Pass
    inspection → FILLED; earlier Construction Complete stamps updated to
    the latest event.
  - Spurious FINAL_DATE on non-Final rows → cleared.

Not repairable / left as-is:
  - ~300 DONE / sparse shells with only the 1900 placeholder and no fee
    dates → FILE_DATE stays missing after clearing the sentinel.
  - Legacy Construction Complete rows with only an Inspections /
    Construction Complete event (no Issued mark) → PERMIT_DATE stays
    missing.
  - Final Processing rows still awaiting Process for Issuance (TBD) and
    Issued shells with no dated Issued event → PERMIT_DATE stays missing.
  - Most Final rows missing FINAL_DATE have Inspections marked TBD and no
    Final Pass inspection → FINAL_DATE stays missing.
  - DONE empty-task shells remapped to Final have no issuance / finaling
    timestamps in DATA.
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
    year = int(dt.year)
    if year < _MIN_YEAR or year > _MAX_YEAR:
        return pd.NaT
    return dt


def _dates_equal(a, b) -> bool:
    da = _safe_to_datetime(a)
    db = _safe_to_datetime(b)
    if da is pd.NaT or db is pd.NaT:
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


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())
    if keys <= {"search_data"}:
        return "search_data_only"
    if "tasks" not in keys or "status" not in keys:
        return "unknown"

    tasks = data_dict.get("tasks") or []
    if not _has_dated_events(tasks):
        # Legacy DONE shells and sparse Construction Complete rows.
        if "fees_details" not in keys or "contacts" not in keys:
            return "accela_partial"
        return "empty_tasks"

    has_date = "date" in keys
    has_fees = "fees_details" in keys
    has_contacts = "contacts" in keys
    if not has_fees or not has_contacts:
        return "accela_partial"
    if has_date:
        return "accela_with_date"
    return "accela_no_date"


# ── Status mapping ──────────────────────────────────────────────────────────

# DATA.status → STATUS_NORMALIZED (case-insensitive lookup)
_STATUS_MAP = {
    # Final
    "construction complete": "Final",
    "done": "Final",  # legacy Accela closed / finished
    # Active
    "issued": "Active",
    "final processing": "Active",
    # Inactive
    "expired": "Inactive",
    "expi": "Inactive",
    "canc": "Inactive",
    "canceled": "Inactive",
    "cancelled": "Inactive",
    # In Review
    "received": "In Review",
    "open": "In Review",
    "in review": "In Review",
    "corrections required": "In Review",
    "inspection request received": "In Review",
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

_ISSUANCE_TASKS = {
    "process for issuance",
    "ready to issue",
    "issue status",
}
_PLAN_ISSUED_TASKS = {
    "plan check",
    "plan review",
}


def _issued_date(tasks: list):
    """Earliest true issuance date from Placer Accela workflow events."""
    primary = []
    secondary = []
    tertiary = []

    for t in _iter_tasks(tasks):
        name = (t.get("name") or "").strip()
        nl = name.lower()
        for e in t.get("events") or []:
            if not isinstance(e, dict):
                continue
            marked = _event_field(e, "Marked as")
            if marked is None:
                continue
            ml = str(marked).strip().lower()
            if ml != "issued":
                continue
            dt = _safe_to_datetime(_event_field(e, "on"))
            if dt is pd.NaT:
                continue
            if nl in _ISSUANCE_TASKS or any(x in nl for x in _ISSUANCE_TASKS):
                primary.append(dt)
            elif nl in _PLAN_ISSUED_TASKS or any(x in nl for x in _PLAN_ISSUED_TASKS):
                secondary.append(dt)
            else:
                tertiary.append(dt)

    for group in (primary, secondary, tertiary):
        if group:
            return min(group)
    return pd.NaT


def _final_date_from_tasks(tasks: list):
    """Latest Construction Complete mark on Inspections / Inspection."""
    dates = []
    for t in _iter_tasks(tasks):
        name = (t.get("name") or "").strip().lower()
        if name not in {"inspections", "inspection"}:
            continue
        for e in t.get("events") or []:
            if not isinstance(e, dict):
                continue
            marked = _event_field(e, "Marked as")
            if marked is None:
                continue
            if str(marked).strip().lower() != "construction complete":
                continue
            dt = _safe_to_datetime(_event_field(e, "on"))
            if dt is not pd.NaT:
                dates.append(dt)
    return max(dates) if dates else pd.NaT


def _final_date_from_inspections(inspections: list):
    """Fallback: Status Date of a Final*-titled Final Pass / Pass inspection."""
    dates = []
    for insp in inspections or []:
        if not isinstance(insp, dict):
            continue
        title = str(insp.get("Title") or "")
        status = str(insp.get("Status") or "").strip().lower()
        if "final" not in title.lower() and status != "final pass":
            continue
        if status not in {"final pass", "pass", "complete", "approved"}:
            continue
        dt = _safe_to_datetime(insp.get("Status Date"))
        if dt is not pd.NaT:
            dates.append(dt)
    return max(dates) if dates else pd.NaT


def _file_date_from_data(d: dict):
    """Best FILE_DATE: top-level date, else search_data Date, else fee Date."""
    file_date = _safe_to_datetime(d.get("date"))
    if file_date is not pd.NaT:
        return file_date

    sd = d.get("search_data") or {}
    if isinstance(sd, dict):
        file_date = _safe_to_datetime(sd.get("Date"))
        if file_date is not pd.NaT:
            return file_date

    fee_dates = []
    for fee in d.get("fees_details") or []:
        if isinstance(fee, dict):
            dt = _safe_to_datetime(fee.get("Date"))
            if dt is not pd.NaT:
                fee_dates.append(dt)
    if fee_dates:
        return min(fee_dates)
    return pd.NaT


def _raw_file_date_is_sentinel(d: dict, row_file_date) -> bool:
    """True when FILE_DATE / DATA carry the Accela 1900-01-01 placeholder."""
    current = pd.to_datetime(row_file_date, errors="coerce")
    if pd.notna(current) and int(current.year) == 1900:
        return True
    raw = d.get("date")
    if raw is not None and str(raw).startswith("1900"):
        return True
    sd = d.get("search_data") or {}
    if isinstance(sd, dict):
        sdate = sd.get("Date")
        if sdate is not None and ("1900" in str(sdate)):
            return True
    return False


# ── Repair logic ────────────────────────────────────────────────────────────

def _repair_record(row, d: dict, repairs: dict):
    """Repair one Placer County Accela record."""
    tasks = d.get("tasks") or []
    data_status = d.get("status")
    if isinstance(data_status, str) and not data_status.strip():
        data_status = None
    # search_data_only shells may only expose Status under search_data
    if data_status is None:
        sd = d.get("search_data") or {}
        if isinstance(sd, dict):
            sstatus = sd.get("Status")
            if isinstance(sstatus, str) and sstatus.strip():
                data_status = sstatus.strip()

    # -- STATUS_NORMALIZED --
    current_status = row["STATUS_NORMALIZED"]
    expected = _expected_status(data_status)
    # Blank Accela / TMP shells with no Status → In Review (application stage).
    if expected is None and data_status is None and pd.isna(current_status):
        expected = "In Review"

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
    is_sentinel = _raw_file_date_is_sentinel(d, row["FILE_DATE"])

    if file_src is not pd.NaT:
        if current_fd is pd.NaT:
            repairs["FILE_DATE"] = file_src
            # 1900 placeholder was incorrect → FIXED; true null → FILLED
            repairs["FILE_DATE_FLAG"] = "FIXED" if is_sentinel else "FILLED"
        elif not _dates_equal(current_fd, file_src):
            repairs["FILE_DATE"] = file_src
            repairs["FILE_DATE_FLAG"] = "FIXED"
    elif is_sentinel:
        # No usable replacement — clear the placeholder.
        repairs["FILE_DATE"] = pd.NaT
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
    Placer County permit records using the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Placer County".  Must contain
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
    from dotenv import load_dotenv

    load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".env"))
    if not os.getenv("MY_DATA_PATH"):
        load_dotenv(".env")

    MY_DATA_PATH = os.getenv("MY_DATA_PATH")
    AGENT_DATA_PATH = os.getenv("AGENT_DATA_PATH")
    filepath = os.path.join(MY_DATA_PATH, "processed_data", "permits_ca_sample.parquet")
    df = pd.read_parquet(filepath)
    placer = df[df["JURISDICTION"] == "Placer County"].copy()

    print(f"Placer County records: {len(placer):,}\n")

    repaired = data_repair(placer)

    print("INFERRED_SCHEMA:")
    for s, c in repaired["INFERRED_SCHEMA"].value_counts(dropna=False).items():
        print(f"  {str(s):20s}: {c:>4,}")
    print()

    for field in ["STATUS_NORMALIZED", "FILE_DATE", "PERMIT_DATE", "FINAL_DATE"]:
        flag_col = f"{field}_FLAG"
        n_filled = (repaired[flag_col] == "FILLED").sum()
        n_fixed = (repaired[flag_col] == "FIXED").sum()
        print(f"{field}:")
        print(f"  FILLED: {n_filled:>4,}   FIXED: {n_fixed:>4,}")

        before_missing = placer[field].isna().sum()
        after_missing = repaired[field].isna().sum()
        print(f"  Missing before: {before_missing:>4,}   Missing after: {after_missing:>4,}")
        print()

    print("STATUS_NORMALIZED distribution:")
    print("  Before:")
    for s, c in placer["STATUS_NORMALIZED"].value_counts(dropna=False).items():
        print(f"    {str(s):15s}: {c:>4,}")
    print("  After:")
    for s, c in repaired["STATUS_NORMALIZED"].value_counts(dropna=False).items():
        print(f"    {str(s):15s}: {c:>4,}")

    print("\nFINAL_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        if len(sub) == 0:
            continue
        n_has = sub["FINAL_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({n_has / len(sub):.1%})")

    print("\nPERMIT_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        if len(sub) == 0:
            continue
        n_has = sub["PERMIT_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({n_has / len(sub):.1%})")

    print("\nFILE_DATE coverage:",
          f"{repaired['FILE_DATE'].notna().sum()} / {len(repaired)}")

    if AGENT_DATA_PATH:
        out_dir = os.path.join(AGENT_DATA_PATH, "processed_data")
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, "permits_ca_placer_county_repaired.parquet")
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote {out_path}")

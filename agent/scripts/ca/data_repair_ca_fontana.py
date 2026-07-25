"""Data repair for Fontana (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Fontana DATA has two sub-schemas:

  - permit_info_search_data (GIS / open-data feed): top-level keys
    contacts, fees, inspections, permit_info, search_data, site_info.
    Canonical fields:
      - permit_info.PermitStatus       → STATUS_NORMALIZED
      - permit_info.PermitAppliedDate  → FILE_DATE
      - permit_info.PermitIssuedDate   → PERMIT_DATE
          (fallback: PermitApprovedDate)
      - permit_info.PermitFinaledDate  → FINAL_DATE
          (fallback for Final rows: latest passed permit/building-final
           inspection Completed date)

  - legacy_portal (Accela Citizen Access): top-level keys include date,
    status, tasks, inspections, search_data, fees_details, etc.
    Canonical fields:
      - DATA.status                              → STATUS_NORMALIZED
      - DATA.date / search_data.Date             → FILE_DATE
      - Permit Issuance / Issued                 → PERMIT_DATE
      - Inspection / Final Inspection Complete   → FINAL_DATE
          (fallback: Certificate of Occupancy / Final CO Issued;
           then latest passed Permit Final / Building Final inspection)

Known issues repaired:
  - 1 permit_info row with empty PermitStatus but PermitIssuedDate →
    STATUS filled as Active.
  - 2 legacy Closed - Complete rows labeled Active (STATUS_ORIGINAL
    still "issued") → FIXED to Final; FINAL_DATE filled from Final
    Inspection Complete / Permit Final inspection.
  - 3 legacy rows where PERMIT_DATE equals FILE_DATE but a later
    Permit Issuance / Issued event exists → FIXED to Issued date.
  - Active/Final permit_info rows missing PERMIT_DATE with empty
    Issued but populated Approved → FILLED from PermitApprovedDate.
  - Final rows missing FINAL_DATE with a usable finaling inspection
    (or legacy Final Inspection Complete / Final CO) → FILLED.

Not repairable from DATA:
  - 3 FILE_DATE gaps (empty PermitAppliedDate and no alternate).
  - Most Closed / Closed - Complete historical rows lack Issued and
    Finaled dates in DATA (~128 Active/Final still missing PERMIT;
    ~~300 Final still missing FINAL after repair).
  - VOID rows may carry PermitFinaledDate; status stays Inactive and
    FINAL_DATE on those non-Final rows is cleared (FIXED).
"""

import json
import math
import re
from datetime import date, datetime
from typing import Optional

import pandas as pd
import numpy as np


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
    """Parse a date value, returning pd.NaT on failure or implausible year."""
    if val is None or (isinstance(val, str) and not str(val).strip()):
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


def _as_date(val) -> Optional[date]:
    """Normalize a datelike value to datetime.date."""
    if _is_missing(val):
        return None
    if isinstance(val, date) and not isinstance(val, datetime):
        return val
    if isinstance(val, pd.Timestamp):
        if pd.isna(val):
            return None
        return val.date()
    dt = _safe_to_datetime(val)
    if dt is pd.NaT or pd.isna(dt):
        return None
    return dt.date()


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())
    if {"permit_info", "search_data"}.issubset(keys):
        return "permit_info_search_data"
    if "status" in keys and ("tasks" in keys or "date" in keys):
        return "legacy_portal"
    return "unknown"


def _event_field(event: dict, *names: str):
    """Read an event field, tolerating leading/trailing spaces in keys."""
    targets = {n.strip() for n in names}
    for k, v in event.items():
        if isinstance(k, str) and k.strip() in targets:
            return v
    return None


def _event_dates(tasks: list, task_name: str, marked_pred) -> list:
    """Return datetimes for task_name events matching marked_pred(marked)."""
    dates = []
    for t in tasks or []:
        if not isinstance(t, dict) or t.get("name") != task_name:
            continue
        for e in t.get("events") or []:
            if not isinstance(e, dict):
                continue
            marked = _event_field(e, "Marked as")
            marked = (marked or "").strip() if isinstance(marked, str) else marked
            if not marked_pred(marked):
                continue
            on_val = _event_field(e, "on")
            dt = _safe_to_datetime(on_val)
            if dt is not pd.NaT:
                dates.append(dt)
    return dates


# ── Status maps ─────────────────────────────────────────────────────────────

# permit_info.PermitStatus (uppercased) → STATUS_NORMALIZED
_PI_STATUS_MAP = {
    "FINALED": "Final",
    "CLOSED": "Final",
    "ISSUED": "Active",
    "ACT": "Active",
    "APPROVED": "Active",
    "MISC BILLING": "Active",
    "RECEIVED": "In Review",
    "PAID": "In Review",
    "PND": "In Review",
    "READY FOR PAYMENT": "In Review",
    "INVOICED": "In Review",
    "EXPIRED": "Inactive",
    "VOID": "Inactive",
    "CANCELLED": "Inactive",
    "INA": "Inactive",
}

# legacy_portal DATA.status → STATUS_NORMALIZED
_LEGACY_STATUS_MAP = {
    "Closed - Complete": "Final",
    "Closed": "Final",
    "Issued": "Active",
    "Approved": "Active",
    "Permit Expired": "Inactive",
    "Closed - Withdrawn": "Inactive",
    "Closed - Void": "Inactive",
    "Pending": "In Review",
    "Ready to Issue": "In Review",
    "Additional Info Required": "In Review",
    "In Review": "In Review",
    "New": "In Review",
    "In Progress": "In Review",
}


_FINAL_INSP_OK = {
    "",
    "PASS",
    "PASSED",
    "APPROVED",
    "AP",
}


_FINAL_TITLE_RE = re.compile(
    r"(?i)(permit\s*final|building\s*final|final\s*building|final\s*bldg)"
)


# ── permit_info schema ──────────────────────────────────────────────────────

def _permit_info(d: dict) -> dict:
    pi = d.get("permit_info")
    return pi if isinstance(pi, dict) else {}


def _derive_pi_status(pi: dict) -> Optional[str]:
    """Map PermitStatus; infer from dates when status is blank.

    VOID / CANCELLED / EXPIRED stay Inactive even if PermitFinaledDate is
    populated (that date is a close/void timestamp, not a true finaling).
    """
    raw = (pi.get("PermitStatus") or "").strip().upper()
    if raw in _PI_STATUS_MAP:
        return _PI_STATUS_MAP[raw]

    if raw:
        if "FINAL" in raw:
            return "Final"
        if "EXPIRE" in raw or "VOID" in raw or "CANCEL" in raw:
            return "Inactive"
        return None

    if _as_date(pi.get("PermitFinaledDate")) is not None:
        return "Final"
    if _as_date(pi.get("PermitIssuedDate")) is not None:
        return "Active"
    if _as_date(pi.get("PermitApprovedDate")) is not None:
        return "Active"
    if _as_date(pi.get("PermitAppliedDate")) is not None:
        return "In Review"
    return None


def _preferred_pi_file_date(pi: dict) -> Optional[date]:
    return _as_date(pi.get("PermitAppliedDate"))


def _preferred_pi_permit_date(pi: dict) -> Optional[date]:
    issued = _as_date(pi.get("PermitIssuedDate"))
    if issued is not None:
        return issued
    return _as_date(pi.get("PermitApprovedDate"))


def _final_from_inspections(d: dict) -> Optional[date]:
    """Latest completion date from a passed permit/building-final inspection.

    Handles both open-data inspection dicts (Type / Result / Completed) and
    Accela-style dicts (Title / Status / Status Date).
    """
    inspections = d.get("inspections")
    if not isinstance(inspections, list):
        return None
    dates = []
    for item in inspections:
        if not isinstance(item, dict):
            continue
        text = " ".join(
            str(item.get(k) or "") for k in ("Type", "Title")
        )
        if not _FINAL_TITLE_RE.search(text):
            continue
        result = str(item.get("Result") or "").strip().upper()
        status = str(item.get("Status") or "").strip().upper()
        if result:
            if result not in _FINAL_INSP_OK:
                continue
        elif status and status != "PASSED":
            continue
        completed = _as_date(item.get("Completed") or item.get("Status Date"))
        if completed is not None:
            dates.append(completed)
    return max(dates) if dates else None


def _preferred_pi_final_date(pi: dict, d: dict) -> Optional[date]:
    finaled = _as_date(pi.get("PermitFinaledDate"))
    if finaled is not None:
        return finaled
    return _final_from_inspections(d)


def _repair_permit_info(row, d: dict, repairs: dict):
    pi = _permit_info(d)

    # -- STATUS_NORMALIZED --
    current_status = row["STATUS_NORMALIZED"]
    expected = _derive_pi_status(pi)
    if expected is not None:
        if pd.isna(current_status):
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"
        elif current_status != expected:
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FIXED"

    effective_status = repairs.get("STATUS_NORMALIZED", current_status)

    # -- FILE_DATE --
    preferred_fd = _preferred_pi_file_date(pi)
    current_fd = _as_date(row["FILE_DATE"])
    if preferred_fd is not None:
        if current_fd is None:
            repairs["FILE_DATE"] = pd.Timestamp(preferred_fd)
            repairs["FILE_DATE_FLAG"] = "FILLED"
        elif current_fd != preferred_fd:
            repairs["FILE_DATE"] = pd.Timestamp(preferred_fd)
            repairs["FILE_DATE_FLAG"] = "FIXED"

    # -- PERMIT_DATE --
    preferred_pd = _preferred_pi_permit_date(pi)
    current_pd = _as_date(row["PERMIT_DATE"])
    if preferred_pd is not None:
        if current_pd is None:
            if effective_status in ("Active", "Final"):
                repairs["PERMIT_DATE"] = pd.Timestamp(preferred_pd)
                repairs["PERMIT_DATE_FLAG"] = "FILLED"
        elif current_pd != preferred_pd:
            repairs["PERMIT_DATE"] = pd.Timestamp(preferred_pd)
            repairs["PERMIT_DATE_FLAG"] = "FIXED"

    # -- FINAL_DATE --
    preferred_final = _preferred_pi_final_date(pi, d)
    current_final = _as_date(row["FINAL_DATE"])
    if effective_status != "Final":
        # VOID/EXPIRED may carry PermitFinaledDate; that is a close timestamp,
        # not a completion finaling for STATUS_NORMALIZED purposes.
        if current_final is not None:
            repairs["FINAL_DATE"] = pd.NaT
            repairs["FINAL_DATE_FLAG"] = "FIXED"
    elif preferred_final is not None:
        if current_final is None:
            repairs["FINAL_DATE"] = pd.Timestamp(preferred_final)
            repairs["FINAL_DATE_FLAG"] = "FILLED"
        elif current_final != preferred_final:
            repairs["FINAL_DATE"] = pd.Timestamp(preferred_final)
            repairs["FINAL_DATE_FLAG"] = "FIXED"


# ── legacy_portal schema ────────────────────────────────────────────────────

def _legacy_file_date(d: dict):
    file_src = _safe_to_datetime(d.get("date"))
    if file_src is not pd.NaT:
        return file_src
    sd = d.get("search_data") if isinstance(d.get("search_data"), dict) else {}
    return _safe_to_datetime(sd.get("Date"))


def _legacy_permit_date(tasks: list):
    dates = _event_dates(tasks, "Permit Issuance", lambda m: m == "Issued")
    return min(dates) if dates else pd.NaT


def _legacy_final_date(tasks: list, d: dict):
    finals = _event_dates(
        tasks, "Inspection", lambda m: m == "Final Inspection Complete"
    )
    if finals:
        return max(finals)
    cos = _event_dates(
        tasks, "Certificate of Occupancy", lambda m: m == "Final CO Issued"
    )
    if cos:
        return max(cos)
    insp = _final_from_inspections(d)
    return pd.Timestamp(insp) if insp is not None else pd.NaT


def _repair_legacy_portal(row, d: dict, repairs: dict):
    tasks = d.get("tasks") or []
    if not isinstance(tasks, list):
        tasks = []

    data_status = d.get("status")
    if isinstance(data_status, str):
        data_status = data_status.strip() or None
    else:
        data_status = None

    # -- STATUS_NORMALIZED --
    current_status = row["STATUS_NORMALIZED"]
    expected = _LEGACY_STATUS_MAP.get(data_status) if data_status else None
    if expected is not None:
        if pd.isna(current_status):
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"
        elif current_status != expected:
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FIXED"

    effective_status = repairs.get("STATUS_NORMALIZED", current_status)

    # -- FILE_DATE --
    preferred_fd = _legacy_file_date(d)
    current_fd = _as_date(row["FILE_DATE"])
    preferred_fd_date = _as_date(preferred_fd)
    if preferred_fd_date is not None:
        if current_fd is None:
            repairs["FILE_DATE"] = preferred_fd
            repairs["FILE_DATE_FLAG"] = "FILLED"
        elif current_fd != preferred_fd_date:
            repairs["FILE_DATE"] = preferred_fd
            repairs["FILE_DATE_FLAG"] = "FIXED"

    # -- PERMIT_DATE --
    preferred_pd = _legacy_permit_date(tasks)
    preferred_pd_date = _as_date(preferred_pd)
    current_pd = _as_date(row["PERMIT_DATE"])
    if preferred_pd_date is not None:
        if current_pd is None:
            if effective_status in ("Active", "Final"):
                repairs["PERMIT_DATE"] = preferred_pd
                repairs["PERMIT_DATE_FLAG"] = "FILLED"
        elif current_pd != preferred_pd_date:
            repairs["PERMIT_DATE"] = preferred_pd
            repairs["PERMIT_DATE_FLAG"] = "FIXED"

    # -- FINAL_DATE --
    preferred_final = _legacy_final_date(tasks, d)
    preferred_final_date = _as_date(preferred_final)
    current_final = _as_date(row["FINAL_DATE"])
    if effective_status != "Final":
        if current_final is not None:
            repairs["FINAL_DATE"] = pd.NaT
            repairs["FINAL_DATE_FLAG"] = "FIXED"
    elif preferred_final_date is not None:
        if current_final is None:
            repairs["FINAL_DATE"] = preferred_final
            repairs["FINAL_DATE_FLAG"] = "FILLED"
        elif current_final != preferred_final_date:
            repairs["FINAL_DATE"] = preferred_final
            repairs["FINAL_DATE_FLAG"] = "FIXED"


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Fontana permit records using information from the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Fontana".  Must contain
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
        if schema == "permit_info_search_data":
            _repair_permit_info(row, d, repairs)
        elif schema == "legacy_portal":
            _repair_legacy_portal(row, d, repairs)

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
    filepath = os.path.join(MY_DATA_PATH, "processed_data", "permits_ca_sample.parquet")
    df = pd.read_parquet(filepath)
    city = df[(df["JURISDICTION"] == "Fontana") & (df["STATE"] == "CA")].copy()

    print(f"Fontana records: {len(city):,}\n")

    repaired = data_repair(city)

    if AGENT_DATA_PATH:
        out_path = os.path.join(AGENT_DATA_PATH, "fontana_repaired_sample.parquet")
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

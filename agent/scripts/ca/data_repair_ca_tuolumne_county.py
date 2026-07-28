"""Data repair for Tuolumne County (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Tuolumne County DATA has two top-level schemas:

  1. permit_info (GIS / open-data scrape): top-level keys ``contacts``,
     ``fees``, ``inspections``, ``permit_info``, ``search_data``,
     ``site_info``. Content variants (INFERRED_SCHEMA):

       - permit_info_with_inspections
       - permit_info_dates_only
       - permit_info_applied_only
       - permit_info_empty

     Canonical fields:
       - PermitStatus (+ PermitFinaledDate override) → STATUS_NORMALIZED
       - PermitAppliedDate                           → FILE_DATE
       - PermitIssuedDate (else PermitApprovedDate)  → PERMIT_DATE
       - PermitFinaledDate (else approved FINAL
         inspection Completed)                       → FINAL_DATE

  2. civic_main (CitizenServe / SmartGov): top-level keys ``main``,
     ``extra``, ``location``. ``extra`` uses numeric form-field IDs that
     differ by record type. Content variants (INFERRED_SCHEMA):

       - historic_building      (~36354 status; 36291/36294/36317/36310)
       - utility_encroachment   (~37586; 37527/37552/37530)
       - encroachment_app       (~37776; 37720/37723/37743)
       - land_use               (~34418; 34377/34421)
       - grading                (~34187; 34147/34150) — 34190 is a
                                  bulk 2023-09-18 migration stamp, ignored
       - misc_permit            (~36936 / 36934; 36918)
       - tentative_map          (~35744; 35697/35700/35747)
       - form_extra             modern Express/Standard building, EH, etc.
                                (no usable issue/final keys)
       - empty_extra

     Canonical fields:
       - extra status string (when present), else main.status (-1/0/1/2)
         → STATUS_NORMALIZED
       - main.dateSubmitted (else dateCreated) → FILE_DATE
       - schema-specific issue keys            → PERMIT_DATE
       - schema-specific final keys            → FINAL_DATE

Known issues repaired:
  - 3 permit_info rows with empty PermitStatus but Issued dates → FILLED
    Active.
  - Stale ISSUED / ACTIVE / HOLD / OPEN rows that carry PermitFinaledDate
    (and are not Inactive) → FIXED to Final.
  - Spurious FINAL_DATE on non-Final permit_info rows → cleared.
  - Final rows missing FINAL_DATE with an approved FINAL inspection →
    FILLED from that Completed date.
  - Active / Final rows missing PERMIT_DATE with Approved (no Issued) →
    FILLED from Approved.
  - civic_main FILE_DATE taken from dateCreated; when dateSubmitted falls
    on a later calendar day → FIXED to the submittal date.
  - civic_main EXPIRED / VOID / ACTIVE strings in extra overriding a
    stale main.status=2 (complete) → FIXED.
  - civic_main PERMIT_DATE / FINAL_DATE universally missing; fill from
    typed numeric keys where present.

Not repairable / left as-is:
  - ~30 Final COMPLETE shells with neither PermitFinaledDate nor a usable
    final inspection.
  - Modern form_extra / code-compliance civic rows lack issuance or
    finaling timestamps.
  - Grading 34190 bulk stamp is not a true final date.
  - 1 VOID permit_info shell with no dates at all.
"""

from __future__ import annotations

import json
import math
import re
from datetime import date, datetime
from typing import Optional

import numpy as np
import pandas as pd


_MIN_YEAR = 1900
_MAX_YEAR = 2035

# Bulk migration stamp on Historic Grading Permit field 34190.
_SENTINEL_DATES = {
    date(2023, 9, 18),
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
        return json.loads(data)
    return data


def _safe_to_datetime(val):
    """Parse a date value, returning pd.NaT on failure or implausible year."""
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return pd.NaT
    if isinstance(val, str) and not str(val).strip():
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


def _utc_date(val) -> Optional[date]:
    """Parse a timestamp and return its UTC calendar date."""
    if val is None or (isinstance(val, str) and not str(val).strip()):
        return None
    try:
        ts = pd.to_datetime(val, utc=True)
    except (ValueError, TypeError):
        return None
    if pd.isna(ts):
        return None
    return ts.date()


def _as_date(val) -> Optional[date]:
    """Normalize a date-like value to datetime.date."""
    if _is_missing(val):
        return None
    if isinstance(val, date) and not isinstance(val, datetime):
        return val
    dt = _safe_to_datetime(val)
    if dt is pd.NaT:
        return None
    return dt.date()


def _dates_equal(a, b) -> bool:
    da = _as_date(a)
    db = _as_date(b)
    if da is None or db is None:
        return False
    return da == db


def _permit_info(d: dict) -> dict:
    pi = d.get("permit_info")
    return pi if isinstance(pi, dict) else {}


def _main(d: dict) -> dict:
    main = d.get("main")
    return main if isinstance(main, dict) else {}


def _extra(d: dict) -> dict:
    extra = d.get("extra")
    return extra if isinstance(extra, dict) else {}


def _first_date(mapping: dict, keys) -> pd.Timestamp:
    for key in keys:
        dt = _safe_to_datetime(mapping.get(key))
        if dt is not pd.NaT:
            return dt
    return pd.NaT


def _plausible_final(dt, file_date) -> bool:
    if dt is pd.NaT:
        return False
    d = dt.date()
    if d in _SENTINEL_DATES:
        return False
    fd = _as_date(file_date)
    if fd is not None and d < fd:
        return False
    return True


# ── Schema classification ───────────────────────────────────────────────────

def _classify_permit_info(d: dict) -> str:
    inspections = d.get("inspections")
    has_insp = isinstance(inspections, list) and len(inspections) > 0
    pi = _permit_info(d)
    has_issued = _as_date(pi.get("PermitIssuedDate")) is not None
    has_approved = _as_date(pi.get("PermitApprovedDate")) is not None
    has_finaled = _as_date(pi.get("PermitFinaledDate")) is not None
    has_applied = _as_date(pi.get("PermitAppliedDate")) is not None
    if has_insp:
        return "permit_info_with_inspections"
    if has_issued or has_approved or has_finaled:
        return "permit_info_dates_only"
    if has_applied:
        return "permit_info_applied_only"
    return "permit_info_empty"


def _classify_civic(d: dict) -> str:
    extra = _extra(d)
    if not extra:
        return "empty_extra"
    # Prefer distinctive status / date field IDs over recordTypeName.
    if "36354" in extra or "36291" in extra:
        return "historic_building"
    if "37586" in extra or "37527" in extra:
        return "utility_encroachment"
    if "37776" in extra or "37720" in extra:
        return "encroachment_app"
    if "34418" in extra or "34377" in extra:
        return "land_use"
    if "34187" in extra or "34147" in extra:
        return "grading"
    if "36936" in extra or "36934" in extra or "36918" in extra:
        return "misc_permit"
    if "35744" in extra or "35697" in extra:
        return "tentative_map"
    return "form_extra"


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    if not isinstance(data_dict, dict):
        return "unknown"
    keys = set(data_dict.keys())
    if {"permit_info", "search_data"}.issubset(keys):
        return _classify_permit_info(data_dict)
    if "main" in keys:
        return _classify_civic(data_dict)
    return "unknown"


# ── permit_info status / dates ──────────────────────────────────────────────

_PI_STATUS_MAP = {
    "FINALED": "Final",
    "COMPLETE": "Final",
    "CLOSED": "Final",
    "ACTIVE": "Active",
    "ISSUED": "Active",
    "EXTENSION": "Active",
    "HOLD": "In Review",
    "IN PROGRESS": "In Review",
    "OPEN": "In Review",
    "INCOMPLETE": "In Review",
    "EXPIRED": "Inactive",
    "VOID": "Inactive",
    "VIOLATION": "Inactive",
}

_PI_INACTIVE_KEEP = {
    "EXPIRED",
    "VOID",
    "VIOLATION",
    "CANCELED",
    "CANCELLED",
    "WITHDRAWN",
    "DENIED",
}

_FINAL_INSP_OK = {
    "",
    "PASS",
    "PASSED",
    "APPROVED",
    "APPROVED INSPECTION",
    "AP",
    "PA",
    "COMPLETED",
    "COMPLETE",
}

_FINAL_TITLE_RE = re.compile(r"(?i)\bfinal\b")


def _normalize_status_key(raw) -> str:
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return ""
    return str(raw).strip().upper()


def _derive_status_permit_info(pi: dict) -> Optional[str]:
    """Map PermitStatus; prefer Final when a non-inactive row is finaled."""
    raw = _normalize_status_key(pi.get("PermitStatus"))
    status = _PI_STATUS_MAP.get(raw) if raw else None

    if raw in _PI_INACTIVE_KEEP:
        return status or "Inactive"

    if _as_date(pi.get("PermitFinaledDate")) is not None:
        return "Final"

    if status is not None:
        return status

    # Empty PermitStatus: infer from dates.
    if _as_date(pi.get("PermitIssuedDate")) is not None:
        return "Active"
    if _as_date(pi.get("PermitApprovedDate")) is not None:
        return "Active"
    if _as_date(pi.get("PermitAppliedDate")) is not None:
        return "In Review"
    return None


def _preferred_file_date_pi(pi: dict) -> Optional[date]:
    return _as_date(pi.get("PermitAppliedDate"))


def _preferred_permit_date_pi(pi: dict) -> Optional[date]:
    issued = _as_date(pi.get("PermitIssuedDate"))
    if issued is not None:
        return issued
    return _as_date(pi.get("PermitApprovedDate"))


def _final_from_inspections(d: dict) -> Optional[date]:
    inspections = d.get("inspections")
    if not isinstance(inspections, list):
        return None
    dates = []
    for item in inspections:
        if not isinstance(item, dict):
            continue
        text = str(item.get("Type") or item.get("Title") or "")
        if not _FINAL_TITLE_RE.search(text.strip()):
            continue
        result = str(item.get("Result") or "").strip().upper()
        if result not in _FINAL_INSP_OK:
            continue
        completed = _as_date(item.get("Completed") or item.get("Scheduled Date"))
        if completed is not None:
            dates.append(completed)
    return max(dates) if dates else None


def _preferred_final_date_pi(pi: dict, d: dict) -> Optional[date]:
    finaled = _as_date(pi.get("PermitFinaledDate"))
    if finaled is not None:
        return finaled
    return _final_from_inspections(d)


def _repair_permit_info(row, d: dict, repairs: dict):
    pi = _permit_info(d)

    current_status = row["STATUS_NORMALIZED"]
    expected = _derive_status_permit_info(pi)
    if expected is not None:
        if pd.isna(current_status):
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"
        elif current_status != expected:
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FIXED"

    effective_status = repairs.get("STATUS_NORMALIZED", current_status)

    preferred_fd = _preferred_file_date_pi(pi)
    current_fd = _as_date(row["FILE_DATE"])
    if preferred_fd is not None:
        if current_fd is None:
            repairs["FILE_DATE"] = pd.Timestamp(preferred_fd)
            repairs["FILE_DATE_FLAG"] = "FILLED"
        elif current_fd != preferred_fd:
            repairs["FILE_DATE"] = pd.Timestamp(preferred_fd)
            repairs["FILE_DATE_FLAG"] = "FIXED"

    preferred_pd = _preferred_permit_date_pi(pi)
    current_pd = _as_date(row["PERMIT_DATE"])
    if preferred_pd is not None:
        if current_pd is None:
            if effective_status in ("Active", "Final"):
                repairs["PERMIT_DATE"] = pd.Timestamp(preferred_pd)
                repairs["PERMIT_DATE_FLAG"] = "FILLED"
        elif current_pd != preferred_pd:
            repairs["PERMIT_DATE"] = pd.Timestamp(preferred_pd)
            repairs["PERMIT_DATE_FLAG"] = "FIXED"

    preferred_final = _preferred_final_date_pi(pi, d)
    current_final = _as_date(row["FINAL_DATE"])
    if effective_status != "Final":
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


# ── civic_main status / dates ───────────────────────────────────────────────

_STATUS_CODE_MAP = {
    0: "In Review",   # draft
    1: "Active",      # active
    2: "Final",       # complete
    -1: "Inactive",   # stopped
}

_EXTRA_STATUS_MAP = {
    "finaled": "Final",
    "complete": "Final",
    "closed": "Final",
    "approved": "Final",
    "recorded": "Final",
    "active": "Active",
    "issued": "Active",
    "in progress": "Active",
    "open": "Active",
    "hold": "In Review",
    "draft": "In Review",
    "incomplete": "In Review",
    "expired": "Inactive",
    "void": "Inactive",
    "stopped": "Inactive",
    "cancelled": "Inactive",
    "canceled": "Inactive",
    "withdrawn": "Inactive",
}

# Status string keys by civic sub-schema (first hit wins).
_CIVIC_STATUS_KEYS = {
    "historic_building": ("36354",),
    "utility_encroachment": ("37586",),
    "encroachment_app": ("37776",),
    "land_use": ("34418",),
    "grading": ("34187", "34170"),
    "misc_permit": ("36936", "36934"),
    "tentative_map": ("35744",),
    "form_extra": ("Application Status",),
}

_CIVIC_ISSUE_KEYS = {
    "historic_building": ("36317", "36294"),
    "utility_encroachment": ("37552", "37530"),
    "encroachment_app": ("37723", "37743"),
    "land_use": ("34421", "34384", "34380"),
    "grading": ("34150",),
    "misc_permit": (),
    "tentative_map": ("35700", "35727"),
    "form_extra": (),
    "empty_extra": (),
}

_CIVIC_FINAL_KEYS = {
    "historic_building": ("36310",),
    "utility_encroachment": ("37530", "37545"),
    "encroachment_app": ("37743", "37736"),
    "land_use": ("34421",),
    "grading": (),  # 34190 is a bulk migration stamp — ignore
    "misc_permit": (),
    "tentative_map": ("35747",),
    "form_extra": (),
    "empty_extra": (),
}


def _status_from_code(main: dict) -> Optional[str]:
    status = main.get("status")
    if status is None:
        return None
    try:
        code = int(status)
    except (TypeError, ValueError):
        return None
    return _STATUS_CODE_MAP.get(code)


def _map_extra_status(raw) -> Optional[str]:
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    return _EXTRA_STATUS_MAP.get(s.lower())


def _status_from_extra(extra: dict, schema: str) -> Optional[str]:
    for key in _CIVIC_STATUS_KEYS.get(schema, ()):
        mapped = _map_extra_status(extra.get(key))
        if mapped is not None:
            return mapped
    # Generic fallback: any known status-like string in extra.
    for key in (
        "36354", "37586", "37776", "34418", "34187", "36936", "36934",
        "35744", "Application Status",
    ):
        mapped = _map_extra_status(extra.get(key))
        if mapped is not None:
            return mapped
    return None


def _expected_status_civic(d: dict, schema: str) -> Optional[str]:
    """Prefer granular extra status strings over coarse main.status codes."""
    from_extra = _status_from_extra(_extra(d), schema)
    if from_extra is not None:
        return from_extra
    return _status_from_code(_main(d))


def _preferred_file_date_civic(d: dict) -> Optional[date]:
    main = _main(d)
    submitted = _utc_date(main.get("dateSubmitted"))
    if submitted is not None:
        return submitted
    return _utc_date(main.get("dateCreated"))


def _extract_permit_date_civic(d: dict, schema: str) -> pd.Timestamp:
    return _first_date(_extra(d), _CIVIC_ISSUE_KEYS.get(schema, ()))


def _extract_final_date_civic(d: dict, schema: str, file_date) -> pd.Timestamp:
    dt = _first_date(_extra(d), _CIVIC_FINAL_KEYS.get(schema, ()))
    if not _plausible_final(dt, file_date):
        return pd.NaT
    return dt


def _repair_civic(row, d: dict, schema: str, repairs: dict):
    current_status = row["STATUS_NORMALIZED"]
    expected = _expected_status_civic(d, schema)
    if expected is not None:
        if pd.isna(current_status):
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"
        elif current_status != expected:
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FIXED"

    effective_status = repairs.get("STATUS_NORMALIZED", current_status)

    preferred_fd = _preferred_file_date_civic(d)
    current_fd = _as_date(row["FILE_DATE"])
    if preferred_fd is not None:
        if current_fd is None:
            repairs["FILE_DATE"] = pd.Timestamp(preferred_fd)
            repairs["FILE_DATE_FLAG"] = "FILLED"
        elif current_fd != preferred_fd:
            repairs["FILE_DATE"] = pd.Timestamp(preferred_fd)
            repairs["FILE_DATE_FLAG"] = "FIXED"

    effective_file = repairs.get("FILE_DATE", row["FILE_DATE"])

    issue = _extract_permit_date_civic(d, schema)
    current_permit = row["PERMIT_DATE"]
    if effective_status in ("Active", "Final"):
        expected_permit = issue
    elif effective_status == "Inactive" and issue is not pd.NaT:
        expected_permit = issue
    else:
        expected_permit = pd.NaT

    if expected_permit is not pd.NaT:
        if pd.isna(current_permit):
            repairs["PERMIT_DATE"] = expected_permit
            repairs["PERMIT_DATE_FLAG"] = "FILLED"
        elif not _dates_equal(current_permit, expected_permit):
            repairs["PERMIT_DATE"] = expected_permit
            repairs["PERMIT_DATE_FLAG"] = "FIXED"

    final_src = _extract_final_date_civic(d, schema, effective_file)
    current_final = row["FINAL_DATE"]
    if effective_status == "Final":
        if pd.isna(current_final):
            if final_src is not pd.NaT:
                repairs["FINAL_DATE"] = final_src
                repairs["FINAL_DATE_FLAG"] = "FILLED"
        elif final_src is not pd.NaT and not _dates_equal(current_final, final_src):
            repairs["FINAL_DATE"] = final_src
            repairs["FINAL_DATE_FLAG"] = "FIXED"
    else:
        if not pd.isna(current_final):
            repairs["FINAL_DATE"] = pd.NaT
            repairs["FINAL_DATE_FLAG"] = "FIXED"


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Tuolumne County permit records using information from the raw DATA JSON.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Tuolumne County".  Must contain
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
        if schema.startswith("permit_info"):
            _repair_permit_info(row, d, repairs)
        elif schema not in ("missing", "unknown"):
            _repair_civic(row, d, schema, repairs)

        for key, value in repairs.items():
            out.at[idx, key] = value

    return out


# ── CLI: run standalone to preview repair stats ─────────────────────────────

if __name__ == "__main__":
    import os
    from dotenv import load_dotenv

    load_dotenv("/Users/ekung/projects/la-permits-data/.env")
    MY_DATA_PATH = os.getenv("MY_DATA_PATH")
    filepath = os.path.join(MY_DATA_PATH, "processed_data", "permits_ca_sample.parquet")
    df = pd.read_parquet(filepath)
    city = df[(df["JURISDICTION"] == "Tuolumne County") & (df["STATE"] == "CA")].copy()

    print(f"Tuolumne County records: {len(city):,}\n")

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

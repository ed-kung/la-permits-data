"""Data repair for Arroyo Grande (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Arroyo Grande DATA is a flat CityView-style portal scrape with top-level
keys ``Status``, ``Address ``, ``Permit #``, ``Sub Type``, ``Issue Date``,
``Permit Type``, and optionally ``Work Description``. Content variants
(used as INFERRED_SCHEMA):

  - cityview_standard:     canonical Status; Issue Date is a date or absent
  - cityview_desc_in_issue: canonical Status; Issue Date holds work-desc text
  - cityview_shifted:      real status landed in Sub Type (fields rotated);
                           Status may be a date or work description
  - cityview_garbled:      Status is non-canonical text/date and Sub Type
                           is not a recoverable status
  - cityview_no_status:    Status key missing / empty
  - missing / unknown

Canonical mappings:
  - DATA.Status (else Sub Type when shifted; else VOID in Status text)
                                         → STATUS_NORMALIZED
  - DATA['Issue Date'] when parseable as a date; else Status when Status
    is an MM/DD/YYYY date on shifted rows → PERMIT_DATE
  - FILE_DATE / FINAL_DATE: no source fields in DATA (left unchanged)

Known issues repaired:
  - STATUS_NORMALIZED null for numbered workflow statuses (1. Under Review,
    2. Plan Approved, 4. Being Constructed, 7. Project Complete),
    Pending - See Notes, and shifted rows whose status is in Sub Type
    → FILLED (~352).
  - Test mis-normalized as In Review → Inactive (FIXED).
  - PERMIT_DATE missing on shifted Active rows whose issue date was stored
    in Status → FILLED (~6).

Not repairable from DATA:
  - FILE_DATE is null for all sample rows; DATA has no application /
    submittal date field.
  - FINAL_DATE is null for all sample rows; DATA has no final / closed /
    completion date field (only Status text such as Finaled / Closed /
    7. Project Complete).
  - Active/Final rows whose Issue Date is missing or holds free-text
    work description keep a null PERMIT_DATE (~91 Active / ~38 Final
    after status repair).
  - ~21 garbled / no-status rows have no recoverable Status value.
"""

from __future__ import annotations

import json
import math
import re
from typing import Optional

import numpy as np
import pandas as pd


# ── Helpers ──────────────────────────────────────────────────────────────────

_DATE_RE = re.compile(r"^\d{1,2}/\d{1,2}/\d{4}$")


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
    """Parse a date value, returning pd.NaT on failure."""
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
    return dt


def _dates_equal(a, b) -> bool:
    """Compare two datelike values at calendar-day resolution."""
    da = _safe_to_datetime(a)
    db = _safe_to_datetime(b)
    if da is pd.NaT or db is pd.NaT:
        return False
    return da.normalize() == db.normalize()


def _get(d: dict, *names: str):
    """Read a field, tolerating trailing spaces in keys (e.g. 'Address ')."""
    for name in names:
        if name in d:
            return d.get(name)
    for k, v in d.items():
        if isinstance(k, str) and k.strip() in {n.strip() for n in names}:
            return v
    return None


# ── Status mapping ──────────────────────────────────────────────────────────

_STATUS_MAP = {
    # Final
    "Finaled": "Final",
    "Closed": "Final",
    "7. Project Complete": "Final",
    # Active — issued / approved / plan approved / under construction
    "Issued": "Active",
    "3. Permit Issued": "Active",
    "Approved": "Active",
    "2. Plan Approved": "Active",
    "4. Being Constructed": "Active",
    # In Review
    "1. Under Review": "In Review",
    "Under Review": "In Review",
    "Online Application Received": "In Review",
    "Out for Corrections": "In Review",
    "Pending - See Notes": "In Review",
    # Inactive
    "Expired": "Inactive",
    "Withdrawn": "Inactive",
    "Void": "Inactive",
    "Test": "Inactive",
}

_CANONICAL_STATUSES = set(_STATUS_MAP.keys())


def _raw_status(d: dict) -> Optional[str]:
    """Return the best status string from a CityView payload.

    Prefer ``Status`` when it is a known status. On shifted scrapes the
    real status lands in ``Sub Type``. Fall back to detecting VOID in the
    Status text (e.g. ``New Single Family Residence (VOID)``).
    """
    status = _get(d, "Status")
    if isinstance(status, str):
        status = status.strip()
    else:
        status = None

    if status in _CANONICAL_STATUSES:
        return status

    sub = _get(d, "Sub Type")
    if isinstance(sub, str):
        sub = sub.strip()
        if sub in _CANONICAL_STATUSES:
            return sub

    if status and "VOID" in status.upper():
        return "Void"

    return status or None


def _is_shifted(d: dict) -> bool:
    """True when Sub Type holds a canonical status (fields rotated)."""
    status = _get(d, "Status")
    if isinstance(status, str) and status.strip() in _CANONICAL_STATUSES:
        return False
    sub = _get(d, "Sub Type")
    return isinstance(sub, str) and sub.strip() in _CANONICAL_STATUSES


def _issue_date(d: dict):
    """Best available issuance date from Issue Date or shifted Status."""
    issue = _safe_to_datetime(_get(d, "Issue Date"))
    if issue is not pd.NaT:
        return issue
    # Shifted rows: Status often holds MM/DD/YYYY that was the Issue Date.
    if _is_shifted(d):
        status = _get(d, "Status")
        if isinstance(status, str) and _DATE_RE.match(status.strip()):
            return _safe_to_datetime(status.strip())
    return pd.NaT


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = {k.strip() if isinstance(k, str) else k for k in data_dict.keys()}
    if "Permit #" not in keys and "Status" not in keys:
        return "unknown"

    if _is_shifted(data_dict):
        return "cityview_shifted"

    status = _get(data_dict, "Status")
    if status is None or (isinstance(status, str) and not status.strip()):
        return "cityview_no_status"

    status_s = str(status).strip()
    if status_s not in _CANONICAL_STATUSES and "VOID" not in status_s.upper():
        return "cityview_garbled"

    issue_raw = _get(data_dict, "Issue Date")
    if issue_raw is not None and str(issue_raw).strip():
        if _safe_to_datetime(issue_raw) is pd.NaT:
            return "cityview_desc_in_issue"
    return "cityview_standard"


# ── Per-record repair logic ─────────────────────────────────────────────────

def _repair_record(row, d: dict, repairs: dict):
    """Populate *repairs* with corrected values for one Arroyo Grande record."""
    current_status = row["STATUS_NORMALIZED"]
    raw = _raw_status(d)
    expected = _STATUS_MAP.get(raw) if raw else None

    # -- STATUS_NORMALIZED --
    if expected is not None:
        if pd.isna(current_status):
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"
        elif current_status != expected:
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FIXED"

    effective_status = repairs.get("STATUS_NORMALIZED", current_status)

    # -- FILE_DATE --
    # No application / file date exists in the CityView payload.

    # -- PERMIT_DATE --
    issue = _issue_date(d)
    if not pd.isna(row["PERMIT_DATE"]):
        if issue is not pd.NaT and not _dates_equal(row["PERMIT_DATE"], issue):
            repairs["PERMIT_DATE"] = issue
            repairs["PERMIT_DATE_FLAG"] = "FIXED"
    elif effective_status in ("Active", "Final") and issue is not pd.NaT:
        repairs["PERMIT_DATE"] = issue
        repairs["PERMIT_DATE_FLAG"] = "FILLED"

    # -- FINAL_DATE --
    # No final / completion date exists in the CityView payload.


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Arroyo Grande permit records using information from the raw DATA JSON.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Arroyo Grande". Must contain
        columns STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, FINAL_DATE,
        and DATA.

    Returns
    -------
    pd.DataFrame
        Copy of *df* with corrected field values, an INFERRED_SCHEMA column
        naming the DATA JSON schema identified for each record, and new
        flag columns: STATUS_NORMALIZED_FLAG, FILE_DATE_FLAG,
        PERMIT_DATE_FLAG, FINAL_DATE_FLAG. Flag values are "FILLED"
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
        _repair_record(row, d, repairs)

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
    city = df[(df["JURISDICTION"] == "Arroyo Grande") & (df["STATE"] == "CA")].copy()

    print(f"Arroyo Grande records: {len(city):,}\n")

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

    print("\nFILE_DATE missing:", repaired["FILE_DATE"].isna().sum(), "/", len(repaired))

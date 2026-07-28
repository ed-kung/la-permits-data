"""Data repair for Riverside (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Riverside DATA is a flat agency portal scrape. All rows share the same
core top-level keys (``Status``, ``Created Date``, ``Issued Date``,
``Completed Date``, ``Other Information``, …). Optional keys
(``Parcel``, ``Contractors``, ``related_information``) define the
INFERRED_SCHEMA variants:

  - riverside_core
  - riverside_parcel
  - riverside_related
  - riverside_contractors
  - riverside_parcel_related
  - riverside_parcel_contractors
  - riverside_contractors_related
  - riverside_parcel_contractors_related
  - unknown / missing

Canonical mappings:
  - DATA.Status                         → STATUS_NORMALIZED
  - DATA['Created Date']                → FILE_DATE
  - DATA['Issued Date']                 → PERMIT_DATE
  - DATA['Completed Date'] (Final only) → FINAL_DATE

Known issues repaired:
  - 39 null STATUS_NORMALIZED rows for unmapped / inconsistently mapped
    revision and amendment statuses (Applicant Revisions, Plans
    Resubmitted, Amendment*, Planning Clearance Incomplete) → FILLED.
  - Spurious FINAL_DATE on non-Final rows (Issued, Stop Work, Cancelled,
    Expired, Withdrawn) where Completed Date is a close/cancel stamp,
    not a finalization → cleared (FIXED).

Not repairable / left as-is:
  - FILE_DATE already matches Created Date for all sample rows.
  - PERMIT_DATE already matches Issued Date when present; Active/Final
    rows are fully populated.
  - Construction Completed Date is always empty in the sample.
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
        return json.loads(data)
    return data


def _safe_to_datetime(val):
    """Parse a date value, returning pd.NaT on failure."""
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return pd.NaT
    if isinstance(val, str) and not str(val).strip():
        return pd.NaT
    if isinstance(val, str) and val.strip().upper() == "TBD":
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


def _nonempty(val) -> bool:
    if val is None:
        return False
    if isinstance(val, float) and math.isnan(val):
        return False
    if isinstance(val, str) and not val.strip():
        return False
    if isinstance(val, (dict, list)) and len(val) == 0:
        return False
    return True


_CORE_KEYS = {
    "Status",
    "Created Date",
    "Issued Date",
    "Completed Date",
    "Other Information",
    "Permit Number",
    "Record Number",
}


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())
    if not _CORE_KEYS <= keys:
        return "unknown"

    parts = ["riverside"]
    if "Parcel" in keys:
        parts.append("parcel")
    if "Contractors" in keys:
        parts.append("contractors")
    if "related_information" in keys:
        parts.append("related")

    if len(parts) == 1:
        return "riverside_core"
    return "_".join(parts)


# ── Status mapping ──────────────────────────────────────────────────────────

_STATUS_MAP = {
    # Final
    "Completed": "Final",
    # Active — issued / post-issuance amendments
    "Issued": "Active",
    "Amendment Applicant Revisions": "Active",
    "Amendment Review": "Active",
    "Amendment Requested": "Active",
    # In Review — application / plan check / pre-issuance / stop work
    "Draft": "In Review",
    "In Review": "In Review",
    "Application Incomplete": "In Review",
    "Applicant Revisions": "In Review",
    "Ready For Issue": "In Review",
    "Submitted": "In Review",
    "Stop Work": "In Review",
    "Plans Resubmitted": "In Review",
    "Planning Clearance Incomplete": "In Review",
    # Inactive
    "Expired": "Inactive",
    "Cancelled": "Inactive",
    "Withdrawn": "Inactive",
}


def _expected_status(d: dict) -> Optional[str]:
    raw = d.get("Status")
    if isinstance(raw, str) and raw.strip():
        mapped = _STATUS_MAP.get(raw.strip())
        if mapped is not None:
            return mapped
        # Post-issuance amendment-like statuses without an explicit map:
        # treat as Active when an Issued Date exists, else In Review.
        issued = _issued_date(d)
        if "amendment" in raw.strip().lower() and issued is not pd.NaT:
            return "Active"
        return "In Review"
    return None


def _issued_date(d: dict):
    dt = _safe_to_datetime(d.get("Issued Date"))
    if dt is not pd.NaT:
        return dt
    oi = d.get("Other Information")
    if isinstance(oi, dict):
        return _safe_to_datetime(oi.get("IssueDate"))
    return pd.NaT


def _file_date_from_data(d: dict):
    dt = _safe_to_datetime(d.get("Created Date"))
    if dt is not pd.NaT:
        return dt
    oi = d.get("Other Information")
    if isinstance(oi, dict):
        return _safe_to_datetime(oi.get("CreatedDate"))
    return pd.NaT


def _final_date_from_data(d: dict):
    """Completion / finalization date (only meaningful for Completed)."""
    dt = _safe_to_datetime(d.get("Completed Date"))
    if dt is not pd.NaT:
        return dt
    oi = d.get("Other Information")
    if isinstance(oi, dict):
        dt = _safe_to_datetime(oi.get("CompletedDate"))
        if dt is not pd.NaT:
            return dt
    return _safe_to_datetime(d.get("Construction Completed Date"))


# ── Repair logic ────────────────────────────────────────────────────────────

def _repair_record(row, d: dict, repairs: dict):
    # -- STATUS_NORMALIZED --
    current_status = row["STATUS_NORMALIZED"]
    expected = _expected_status(d)
    if expected is not None:
        if pd.isna(current_status):
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"
        elif current_status != expected:
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FIXED"

    effective_status = repairs.get("STATUS_NORMALIZED", current_status)

    # -- FILE_DATE --
    file_date = _file_date_from_data(d)
    if file_date is not pd.NaT:
        if pd.isna(row["FILE_DATE"]):
            repairs["FILE_DATE"] = file_date
            repairs["FILE_DATE_FLAG"] = "FILLED"
        elif not _dates_equal(row["FILE_DATE"], file_date):
            repairs["FILE_DATE"] = file_date
            repairs["FILE_DATE_FLAG"] = "FIXED"

    # -- PERMIT_DATE --
    issued = _issued_date(d)
    if issued is not pd.NaT:
        if pd.isna(row["PERMIT_DATE"]):
            if effective_status in ("Active", "Final"):
                repairs["PERMIT_DATE"] = issued
                repairs["PERMIT_DATE_FLAG"] = "FILLED"
        elif not _dates_equal(row["PERMIT_DATE"], issued):
            repairs["PERMIT_DATE"] = issued
            repairs["PERMIT_DATE_FLAG"] = "FIXED"

    # -- FINAL_DATE --
    if effective_status == "Final":
        final_date = _final_date_from_data(d)
        if final_date is not pd.NaT:
            if pd.isna(row["FINAL_DATE"]):
                repairs["FINAL_DATE"] = final_date
                repairs["FINAL_DATE_FLAG"] = "FILLED"
            elif not _dates_equal(row["FINAL_DATE"], final_date):
                repairs["FINAL_DATE"] = final_date
                repairs["FINAL_DATE_FLAG"] = "FIXED"
    else:
        # Completed Date on non-Final rows is a cancel/close/stop stamp,
        # not a finalization. Clear spurious FINAL_DATE.
        if not pd.isna(row["FINAL_DATE"]):
            repairs["FINAL_DATE"] = pd.NaT
            repairs["FINAL_DATE_FLAG"] = "FIXED"


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Riverside (CA) permit records using information from the raw DATA JSON.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Riverside". Must contain
        columns STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, FINAL_DATE,
        and DATA.

    Returns
    -------
    pd.DataFrame
        Copy of *df* with corrected field values, an INFERRED_SCHEMA column
        naming the DATA JSON sub-schema identified for each record, and new
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
    riv = df[(df["JURISDICTION"] == "Riverside") & (df["STATE"] == "CA")].copy()

    print(f"Riverside records: {len(riv):,}\n")

    repaired = data_repair(riv)

    print("INFERRED_SCHEMA:")
    for s, c in repaired["INFERRED_SCHEMA"].value_counts(dropna=False).items():
        print(f"  {str(s):45s}: {c:>4,}")
    print()

    for field in ["STATUS_NORMALIZED", "FILE_DATE", "PERMIT_DATE", "FINAL_DATE"]:
        flag_col = f"{field}_FLAG"
        n_filled = (repaired[flag_col] == "FILLED").sum()
        n_fixed = (repaired[flag_col] == "FIXED").sum()
        print(f"{field}:")
        print(f"  FILLED: {n_filled:>4,}   FIXED: {n_fixed:>4,}")

        before_missing = riv[field].isna().sum()
        after_missing = repaired[field].isna().sum()
        print(f"  Missing before: {before_missing:>4,}   Missing after: {after_missing:>4,}")
        print()

    print("STATUS_NORMALIZED distribution:")
    print("  Before:")
    for s, c in riv["STATUS_NORMALIZED"].value_counts(dropna=False).items():
        print(f"    {str(s):15s}: {c:>4,}")
    print("  After:")
    for s, c in repaired["STATUS_NORMALIZED"].value_counts(dropna=False).items():
        print(f"    {str(s):15s}: {c:>4,}")

    print("\nPERMIT_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["PERMIT_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({n_has / len(sub) if len(sub) else 0:.1%})")

    print("\nFINAL_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FINAL_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({n_has / len(sub) if len(sub) else 0:.1%})")

    print("\nFILE_DATE coverage after repair: "
          f"{repaired['FILE_DATE'].notna().sum()} / {len(repaired)}")

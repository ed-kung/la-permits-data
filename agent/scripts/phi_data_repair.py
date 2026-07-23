"""Data repair for Philadelphia permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

The Philadelphia DATA column has three sub-schemas:

  - nested:     Top-level keys 'Status', 'Created Date', 'Issued Date',
                'Completed Date', and nested 'Other Information' dict.
                (355 records)
  - flat_upper: Flat structure with uppercase keys like 'STATUS',
                'PERMITISSUEDATE', 'PERMITCOMPLETEDDATE'. No filing/creation
                date available. (1574 records)
  - flat_mixed: Flat structure with mixed-case keys like 'StatusDescription',
                'IssueDate', 'CompletedDate'. No created date field.
                (69 records)

Key issues repaired:
  - STATUS_NORMALIZED: 69 flat_mixed records have NaN status that can be parsed
    from StatusDescription. 9 nested records have STATUS_NORMALIZED=Active that
    conflicts with DATA.Status (Completed/Expired). 4 nested records have
    Status=Issued but non-empty Completed Date (should be Final). 2 records have
    unmapped amendment statuses.
  - FILE_DATE: No source data available for the 1643 missing records.
  - PERMIT_DATE: 62 flat_mixed records (Active/Final) can be filled from IssueDate.
  - FINAL_DATE: 6 nested records fixed to Final status can have FINAL_DATE filled
    from Completed Date.
"""

import json
import math
import re
from typing import Optional

import pandas as pd
import numpy as np


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
    if val is None or (isinstance(val, str) and not val.strip()):
        return pd.NaT
    try:
        return pd.to_datetime(val)
    except (ValueError, TypeError):
        return pd.NaT


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())
    if "Status" in keys and ("Created Date" in keys or "Issued Date" in keys):
        return "nested"
    if "STATUS" in keys or ("status" in keys and "applicanttype" in keys):
        return "flat_upper"
    if "StatusDescription" in keys and "Status" not in keys and "STATUS" not in keys:
        return "flat_mixed"
    return "unknown"


def _parse_status_description(sd: str) -> Optional[str]:
    """Extract the status word from a StatusDescription like 'Completed \\n  date'."""
    if not sd or not sd.strip():
        return None
    parts = re.split(r'\s*[\r\n]+\s*', sd.strip())
    return parts[0] if parts else None


# ── Status mapping tables ────────────────────────────────────────────────────

# nested schema: Status → STATUS_NORMALIZED
_NESTED_STATUS_MAP = {
    "Completed": "Final",
    "Issued": "Active",
    "Expired": "Inactive",
    "Ready For Issue": "In Review",
    "Stop Work": "In Review",
    "Withdrawn": "Inactive",
    "Amendment Applicant Revisions": "In Review",
}

# flat_upper schema: STATUS → STATUS_NORMALIZED
_FLAT_UPPER_STATUS_MAP = {
    "COMPLETED": "Final",
    "Completed": "Final",
    "Issued": "Active",
    "Expired": "Inactive",
    "EXPIRED": "Inactive",
    "CLOSED": "Final",
    "ABANDONED": "Inactive",
    "REVOKED": "Inactive",
    "Cancelled": "Inactive",
    "Denied": "Inactive",
    "Amendment Application Incomplete": "In Review",
}

# flat_mixed schema: parsed StatusDescription → STATUS_NORMALIZED
_FLAT_MIXED_STATUS_MAP = {
    "Completed": "Final",
    "Issued": "Active",
    "Expired": "Inactive",
    "Ready For Issue": "In Review",
    "Withdrawn": "Inactive",
}


# ── Per-schema repair logic ─────────────────────────────────────────────────

def _repair_nested(row, d: dict, repairs: dict):
    """Repair a nested-schema record."""
    raw_status = d.get("Status", "")
    completed_date_raw = d.get("Completed Date", "")
    has_completed_date = bool(
        completed_date_raw
        and isinstance(completed_date_raw, str)
        and completed_date_raw.strip()
    )

    # -- STATUS_NORMALIZED --
    current_status = row["STATUS_NORMALIZED"]
    expected = _NESTED_STATUS_MAP.get(raw_status)

    if raw_status == "Issued" and has_completed_date:
        expected = "Final"

    if expected is not None:
        if pd.isna(current_status):
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"
        elif current_status != expected:
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FIXED"

    effective_status = repairs.get("STATUS_NORMALIZED", current_status)

    # -- FILE_DATE --
    # Created Date is the filing date for nested schema
    if pd.isna(row["FILE_DATE"]):
        created = _safe_to_datetime(d.get("Created Date"))
        if created is not pd.NaT:
            repairs["FILE_DATE"] = created
            repairs["FILE_DATE_FLAG"] = "FILLED"

    # -- PERMIT_DATE --
    if pd.isna(row["PERMIT_DATE"]) and effective_status in ("Active", "Final"):
        issued = _safe_to_datetime(d.get("Issued Date"))
        if issued is not pd.NaT:
            repairs["PERMIT_DATE"] = issued
            repairs["PERMIT_DATE_FLAG"] = "FILLED"

    # -- FINAL_DATE --
    if pd.isna(row["FINAL_DATE"]) and effective_status == "Final":
        completed = _safe_to_datetime(completed_date_raw)
        if completed is not pd.NaT:
            repairs["FINAL_DATE"] = completed
            repairs["FINAL_DATE_FLAG"] = "FILLED"


def _repair_flat_upper(row, d: dict, repairs: dict):
    """Repair a flat_upper-schema record."""
    raw_status = d.get("STATUS", d.get("status", ""))

    # -- STATUS_NORMALIZED --
    current_status = row["STATUS_NORMALIZED"]
    expected = _FLAT_UPPER_STATUS_MAP.get(raw_status)
    if expected is not None:
        if pd.isna(current_status):
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"
        elif current_status != expected:
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FIXED"

    # FILE_DATE: no source available in flat_upper schema
    # PERMIT_DATE: already populated from PERMITISSUEDATE during loading
    # FINAL_DATE: already populated from PERMITCOMPLETEDDATE during loading


def _repair_flat_mixed(row, d: dict, repairs: dict):
    """Repair a flat_mixed-schema record."""
    sd = d.get("StatusDescription", "")
    parsed_status = _parse_status_description(sd)

    # -- STATUS_NORMALIZED --
    current_status = row["STATUS_NORMALIZED"]
    expected = _FLAT_MIXED_STATUS_MAP.get(parsed_status) if parsed_status else None
    if expected is not None:
        if pd.isna(current_status):
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"
        elif current_status != expected:
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FIXED"

    effective_status = repairs.get("STATUS_NORMALIZED", current_status)

    # -- FILE_DATE --
    # No filing/created date field available in flat_mixed schema

    # -- PERMIT_DATE --
    if pd.isna(row["PERMIT_DATE"]) and effective_status in ("Active", "Final"):
        issued = _safe_to_datetime(d.get("IssueDate"))
        if issued is not pd.NaT:
            repairs["PERMIT_DATE"] = issued
            repairs["PERMIT_DATE_FLAG"] = "FILLED"

    # -- FINAL_DATE --
    if pd.isna(row["FINAL_DATE"]) and effective_status == "Final":
        completed = _safe_to_datetime(d.get("CompletedDate"))
        if completed is not pd.NaT:
            repairs["FINAL_DATE"] = completed
            repairs["FINAL_DATE_FLAG"] = "FILLED"


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Philadelphia permit records using information from the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Philadelphia".  Must contain
        columns STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, FINAL_DATE,
        and DATA.

    Returns
    -------
    pd.DataFrame
        Copy of *df* with corrected field values and new flag columns:
        STATUS_NORMALIZED_FLAG, FILE_DATE_FLAG, PERMIT_DATE_FLAG,
        FINAL_DATE_FLAG.  Flag values are "FILLED" (was missing, now
        populated) or "FIXED" (had an incorrect value, now corrected).
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

    for idx in out.index:
        row = out.loc[idx]
        d = _safe_parse(row["DATA"])
        if d is None:
            continue

        schema = _classify_schema(d)
        repairs: dict = {}

        if schema == "nested":
            _repair_nested(row, d, repairs)
        elif schema == "flat_upper":
            _repair_flat_upper(row, d, repairs)
        elif schema == "flat_mixed":
            _repair_flat_mixed(row, d, repairs)

        for key, value in repairs.items():
            out.at[idx, key] = value

    return out


# ── CLI: run standalone to preview repair stats ─────────────────────────────

if __name__ == "__main__":
    import os
    from dotenv import load_dotenv

    load_dotenv("/Users/ekung/projects/la-permits-data/.env")
    MY_DATA_PATH = os.getenv("MY_DATA_PATH")
    filepath = os.path.join(MY_DATA_PATH, "processed_data", "permits_top50_sample.parquet")
    df = pd.read_parquet(filepath)
    phi = df[df["JURISDICTION"] == "Philadelphia"].copy()

    print(f"Philadelphia records: {len(phi):,}\n")

    repaired = data_repair(phi)

    for field in ["STATUS_NORMALIZED", "FILE_DATE", "PERMIT_DATE", "FINAL_DATE"]:
        flag_col = f"{field}_FLAG"
        n_filled = (repaired[flag_col] == "FILLED").sum()
        n_fixed = (repaired[flag_col] == "FIXED").sum()
        print(f"{field}:")
        print(f"  FILLED: {n_filled:>4,}   FIXED: {n_fixed:>4,}")

        before_missing = phi[field].isna().sum()
        after_missing = repaired[field].isna().sum()
        print(f"  Missing before: {before_missing:>4,}   Missing after: {after_missing:>4,}")
        print()

    print("STATUS_NORMALIZED distribution:")
    print("  Before:")
    for s, c in phi["STATUS_NORMALIZED"].value_counts(dropna=False).items():
        print(f"    {str(s):15s}: {c:>4,}")
    print("  After:")
    for s, c in repaired["STATUS_NORMALIZED"].value_counts(dropna=False).items():
        print(f"    {str(s):15s}: {c:>4,}")

    print("\nFINAL_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        if len(sub) > 0:
            n_has = sub["FINAL_DATE"].notna().sum()
            print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({n_has/len(sub):.1%})")

    print("\nPERMIT_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        if len(sub) > 0:
            n_has = sub["PERMIT_DATE"].notna().sum()
            print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({n_has/len(sub):.1%})")

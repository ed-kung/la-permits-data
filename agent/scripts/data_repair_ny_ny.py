"""Data repair for New York permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

The New York DATA column has three sub-schemas:
  - DOB_issuances:    top-level keys 'filings' + 'issuances'
  - DOB_filing_single: top-level key 'filing' (single dict)
  - other:            flat structure with 'filing_status', 'job_status',
                       'completion_date', 'permit_issued_date', etc.
"""

import json
import math
from typing import Optional, Union

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
    if "issuances" in keys:
        return "DOB_issuances"
    if "filing" in keys:
        return "DOB_filing_single"
    if "filing_status" in keys or "job_status" in keys:
        return "other"
    return "unknown"


# ── Status mapping tables ────────────────────────────────────────────────────

# DOB_issuances: filings[0].job_status_descrp → STATUS_NORMALIZED
_ISS_JSD_MAP = {
    "SIGNED OFF": "Final",
    "COMPLETED": "Final",
    "PERMIT ISSUED - ENTIRE JOB/WORK": "Active",
    "PERMIT ISSUED - PARTIAL JOB": "Active",
    "PLAN EXAM - IN PROCESS": "Active",
    "APPLICATION PROCESSED - ENTIRE": "In Review",
    "APPLICATION PROCESSED - NO PLAN EXAM": "In Review",
    "PLAN EXAM - APPROVED": "In Review",
    "PRE-FILING": "In Review",
    "APPLICATION ASSIGNED TO PLAN EXAMINER": "In Review",
    "PLAN EXAM - DISAPPROVED": "Inactive",
}

# DOB_filing_single: filing.filing_status → STATUS_NORMALIZED
_FS_MAP = {
    "Approved": "Active",
    "PAA Approved": "Active",
    "Permit Entire": "Active",
    "Permit Issued": "Active",
    "LOC Issued": "Final",
    "TA Certificate of Operation Issued": "Final",
    "PA Certificate of Operation Issued": "Final",
    "Objections": "In Review",
    "Pending Plan Examiner Assignment": "In Review",
    "Pending Prof Cert QA Assignment": "In Review",
    "Plan Examiner Review": "In Review",
    "QA Failed": "In Review",
    "On Hold - Administrative Action": "In Review",
    "Filing Withdrawn": "Inactive",
    "LL 158-2017-Denied": "Inactive",
}

# "other" schema: filing_status → STATUS_NORMALIZED
_OTHER_FS_MAP = {
    "Complete": "Final",
    "Approved": "Active",
    "Permit Issued": "Active",
    "Cancel": "Inactive",
    "Pending Payment": "In Review",
}


# ── Per-schema repair logic ─────────────────────────────────────────────────

def _repair_dob_issuances(row, d: dict, repairs: dict):
    """Repair a DOB_issuances record."""
    filings = d.get("filings", [])
    f0 = filings[0] if (filings and isinstance(filings[0], dict)) else None
    issuances = d.get("issuances", [])
    initials = sorted(
        [i for i in issuances if isinstance(i, dict) and i.get("filing_status") == "INITIAL"],
        key=lambda x: _safe_to_datetime(x.get("filing_date", "9999")),
    )

    # -- STATUS_NORMALIZED --
    current_status = row["STATUS_NORMALIZED"]
    if f0 is not None:
        jsd = f0.get("job_status_descrp", "")
        expected = _ISS_JSD_MAP.get(jsd)
        if expected is not None:
            if pd.isna(current_status):
                repairs["STATUS_NORMALIZED"] = expected
                repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"
            elif current_status != expected:
                repairs["STATUS_NORMALIZED"] = expected
                repairs["STATUS_NORMALIZED_FLAG"] = "FIXED"
    else:
        if pd.isna(current_status):
            has_issuance = any(
                isinstance(i, dict) and _safe_to_datetime(i.get("issuance_date")) is not pd.NaT
                for i in issuances
            )
            if has_issuance:
                repairs["STATUS_NORMALIZED"] = "Active"
                repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"

    effective_status = repairs.get("STATUS_NORMALIZED", current_status)

    # -- FILE_DATE --
    if pd.isna(row["FILE_DATE"]):
        if f0 is not None:
            pfd = _safe_to_datetime(f0.get("pre__filing_date"))
            if pfd is not pd.NaT:
                repairs["FILE_DATE"] = pfd
                repairs["FILE_DATE_FLAG"] = "FILLED"
        if "FILE_DATE" not in repairs and initials:
            fd = _safe_to_datetime(initials[0].get("filing_date"))
            if fd is not pd.NaT:
                repairs["FILE_DATE"] = fd
                repairs["FILE_DATE_FLAG"] = "FILLED"

    # -- PERMIT_DATE --
    if pd.isna(row["PERMIT_DATE"]) and effective_status in ("Active", "Final"):
        if f0 is not None:
            fp = _safe_to_datetime(f0.get("fully_permitted"))
            if fp is not pd.NaT:
                repairs["PERMIT_DATE"] = fp
                repairs["PERMIT_DATE_FLAG"] = "FILLED"
        if "PERMIT_DATE" not in repairs and initials:
            isd = _safe_to_datetime(initials[0].get("issuance_date"))
            if isd is not pd.NaT:
                repairs["PERMIT_DATE"] = isd
                repairs["PERMIT_DATE_FLAG"] = "FILLED"
        if "PERMIT_DATE" not in repairs and initials:
            jsd = _safe_to_datetime(initials[0].get("job_start_date"))
            if jsd is not pd.NaT:
                file_date = repairs.get("FILE_DATE", row["FILE_DATE"])
                file_dt = _safe_to_datetime(file_date)
                if file_dt is pd.NaT or jsd >= file_dt:
                    repairs["PERMIT_DATE"] = jsd
                    repairs["PERMIT_DATE_FLAG"] = "FILLED"

    # -- FINAL_DATE --
    if pd.isna(row["FINAL_DATE"]) and effective_status == "Final":
        if f0 is not None:
            sd = _safe_to_datetime(f0.get("signoff_date"))
            if sd is not pd.NaT:
                repairs["FINAL_DATE"] = sd
                repairs["FINAL_DATE_FLAG"] = "FILLED"


def _repair_dob_filing_single(row, d: dict, repairs: dict):
    """Repair a DOB_filing_single record."""
    filing = d.get("filing", {})
    fs = filing.get("filing_status", "")

    # -- STATUS_NORMALIZED --
    current_status = row["STATUS_NORMALIZED"]
    expected = _FS_MAP.get(fs)
    if expected is not None:
        if pd.isna(current_status):
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"
        elif current_status != expected:
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FIXED"

    effective_status = repairs.get("STATUS_NORMALIZED", current_status)

    # -- FILE_DATE --
    if pd.isna(row["FILE_DATE"]):
        fd = _safe_to_datetime(filing.get("filing_date"))
        if fd is not pd.NaT:
            repairs["FILE_DATE"] = fd
            repairs["FILE_DATE_FLAG"] = "FILLED"

    # -- PERMIT_DATE --
    if pd.isna(row["PERMIT_DATE"]) and effective_status in ("Active", "Final"):
        pid = _safe_to_datetime(filing.get("permit_issue_date"))
        if pid is not pd.NaT:
            repairs["PERMIT_DATE"] = pid
            repairs["PERMIT_DATE_FLAG"] = "FILLED"
        else:
            fpd = _safe_to_datetime(filing.get("first_permit_date"))
            if fpd is not pd.NaT:
                repairs["PERMIT_DATE"] = fpd
                repairs["PERMIT_DATE_FLAG"] = "FILLED"
        if "PERMIT_DATE" not in repairs:
            file_date = repairs.get("FILE_DATE", row["FILE_DATE"])
            file_dt = _safe_to_datetime(file_date)
            if file_dt is not pd.NaT:
                repairs["PERMIT_DATE"] = file_dt
                repairs["PERMIT_DATE_FLAG"] = "FILLED"

    # -- FINAL_DATE --
    if pd.isna(row["FINAL_DATE"]) and effective_status == "Final":
        fstatus = str(fs).lower()
        if "sign" in fstatus or "complete" in fstatus or "loc issued" in fstatus \
                or "certificate" in fstatus:
            csd = _safe_to_datetime(filing.get("current_status_date"))
            if csd is not pd.NaT:
                repairs["FINAL_DATE"] = csd
                repairs["FINAL_DATE_FLAG"] = "FILLED"


def _repair_other(row, d: dict, repairs: dict):
    """Repair an 'other' (electrical permits) record."""
    fs = d.get("filing_status", "")

    # -- STATUS_NORMALIZED --
    current_status = row["STATUS_NORMALIZED"]
    expected = _OTHER_FS_MAP.get(fs)
    if expected is not None:
        if pd.isna(current_status):
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"
        elif current_status != expected:
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FIXED"

    effective_status = repairs.get("STATUS_NORMALIZED", current_status)

    # -- FILE_DATE --
    if pd.isna(row["FILE_DATE"]):
        fd = _safe_to_datetime(d.get("filing_date"))
        if fd is not pd.NaT:
            repairs["FILE_DATE"] = fd
            repairs["FILE_DATE_FLAG"] = "FILLED"

    # -- PERMIT_DATE --
    if pd.isna(row["PERMIT_DATE"]) and effective_status in ("Active", "Final"):
        pid = _safe_to_datetime(d.get("permit_issued_date"))
        if pid is not pd.NaT:
            repairs["PERMIT_DATE"] = pid
            repairs["PERMIT_DATE_FLAG"] = "FILLED"
        if "PERMIT_DATE" not in repairs:
            jsd = _safe_to_datetime(d.get("job_start_date"))
            if jsd is not pd.NaT:
                file_date = repairs.get("FILE_DATE", row["FILE_DATE"])
                file_dt = _safe_to_datetime(file_date)
                if file_dt is pd.NaT or jsd >= file_dt:
                    repairs["PERMIT_DATE"] = jsd
                    repairs["PERMIT_DATE_FLAG"] = "FILLED"
        if "PERMIT_DATE" not in repairs:
            file_date = repairs.get("FILE_DATE", row["FILE_DATE"])
            file_dt = _safe_to_datetime(file_date)
            if file_dt is not pd.NaT:
                repairs["PERMIT_DATE"] = file_dt
                repairs["PERMIT_DATE_FLAG"] = "FILLED"

    # -- FINAL_DATE --
    if pd.isna(row["FINAL_DATE"]) and effective_status == "Final":
        cd = _safe_to_datetime(d.get("completion_date"))
        if cd is not pd.NaT:
            repairs["FINAL_DATE"] = cd
            repairs["FINAL_DATE_FLAG"] = "FILLED"


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    New York permit records using information from the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "New York".  Must contain
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

        if schema == "DOB_issuances":
            _repair_dob_issuances(row, d, repairs)
        elif schema == "DOB_filing_single":
            _repair_dob_filing_single(row, d, repairs)
        elif schema == "other":
            _repair_other(row, d, repairs)

        for key, value in repairs.items():
            out.at[idx, key] = value

    return out


# ── CLI: run standalone to preview repair stats ─────────────────────────────

if __name__ == "__main__":
    import os
    from dotenv import load_dotenv, find_dotenv

    load_dotenv(find_dotenv())
    MY_DATA_PATH = os.getenv("MY_DATA_PATH")
    filepath = os.path.join(MY_DATA_PATH, "processed_data", "permits_top50_sample.parquet")
    df = pd.read_parquet(filepath)
    ny = df[df["JURISDICTION"] == "New York"].copy()

    print(f"New York records: {len(ny):,}\n")

    repaired = data_repair(ny)

    for field in ["STATUS_NORMALIZED", "FILE_DATE", "PERMIT_DATE", "FINAL_DATE"]:
        flag_col = f"{field}_FLAG"
        n_filled = (repaired[flag_col] == "FILLED").sum()
        n_fixed = (repaired[flag_col] == "FIXED").sum()
        print(f"{field}:")
        print(f"  FILLED: {n_filled:>4,}   FIXED: {n_fixed:>4,}")

        before_missing = ny[field].isna().sum()
        after_missing = repaired[field].isna().sum()
        print(f"  Missing before: {before_missing:>4,}   Missing after: {after_missing:>4,}")
        print()

    # Show status distribution before/after
    print("STATUS_NORMALIZED distribution:")
    print("  Before:")
    for s, c in ny["STATUS_NORMALIZED"].value_counts(dropna=False).items():
        print(f"    {str(s):15s}: {c:>4,}")
    print("  After:")
    for s, c in repaired["STATUS_NORMALIZED"].value_counts(dropna=False).items():
        print(f"    {str(s):15s}: {c:>4,}")

    # Show FINAL_DATE by status after repair
    print("\nFINAL_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FINAL_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({n_has/len(sub):.1%})")

    # Show PERMIT_DATE by status after repair
    print("\nPERMIT_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["PERMIT_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({n_has/len(sub):.1%})")

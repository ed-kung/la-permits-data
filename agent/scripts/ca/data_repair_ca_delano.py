"""Data repair for Delano (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Delano DATA is a SmartGov community portal payload with top-level keys
``Build Status``, ``My Project``, ``Permit Type``, ``Permit Inspections``,
etc.  Three key-set variants appear in the sample:

  - smartgov_full:       includes ``ProjectDescription`` and
                         ``Parcel Number``
  - smartgov_no_desc:    includes ``Parcel Number`` but no
                         ``ProjectDescription``
  - smartgov_minimal:    neither ``ProjectDescription`` nor
                         ``Parcel Number``
  - empty_my_project:    Build Status / shell present but ``My Project``
                         is empty (no date fields)

Canonical fields:
  - DATA["Build Status"]              → STATUS_NORMALIZED
    (fallback: My Project date presence when Build Status is null)
  - My Project.Submitted (fallback:
    Created)                          → FILE_DATE
  - My Project.Issued (fallback:
    Approved)                         → PERMIT_DATE
  - My Project.Closed (fallback:
    latest passed Final inspection)   → FINAL_DATE

Known issues repaired:
  - STATUS_NORMALIZED missing for Expired:* labels, unmapped review
    labels (Plans returned…, Review process has started), Closed /
    Certificate of Occupancy shells with null STATUS_ORIGINAL, and
    recent scrapes with null Build Status → FILLED.
  - Stale STATUS_NORMALIZED vs current Build Status (Closed/Finaled
    still Active, Issued still In Review, Expired still Active) → FIXED.
  - In Review Build Status labels that already carry Issued/Closed
    dates in My Project → FIXED to Active/Final.
  - FILE_DATE filled from Submitted when missing.
  - PERMIT_DATE filled from Issued (or Approved) for Active / Final
    rows after status repair.
  - FINAL_DATE filled from Closed, or from a passed Final inspection
    when Build Status is Finaled but Closed is blank; stale FINAL_DATE
    overwritten when Closed differs; spurious FINAL_DATE cleared on
    non-Final rows.

Not repairable / left as-is:
  - Rows with empty My Project and no usable dates (FILE_DATE /
    STATUS stay missing).
  - Most Finaled rows with blank Closed and no passed Final inspection
    → FINAL_DATE stays missing.
  - Technically Completed (no Issued/Closed) stays In Review; no
    completion date to promote to Final.
  - Historical Final rows with neither Issued nor Approved →
    PERMIT_DATE stays missing.
"""

from __future__ import annotations

import json
import math
import re
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


def _is_blank_date(val) -> bool:
    if val is None:
        return True
    if isinstance(val, float) and math.isnan(val):
        return True
    s = str(val).strip()
    if not s or s.lower() in ("none", "nan", "tbd"):
        return True
    # SmartGov placeholder: " - -", "- -", "-"
    if re.fullmatch(r"[\s\-]*", s):
        return True
    return False


def _safe_to_datetime(val):
    """Parse a date value, returning pd.NaT on failure."""
    if _is_blank_date(val):
        return pd.NaT
    try:
        return pd.to_datetime(val)
    except (ValueError, TypeError):
        return pd.NaT


def _safe_to_date(val):
    """Parse a date value, returning None on failure."""
    dt = _safe_to_datetime(val)
    if dt is pd.NaT or pd.isna(dt):
        return None
    return dt.date()


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())
    if "My Project" not in keys and "Build Status" not in keys:
        return "unknown"
    mp = data_dict.get("My Project")
    if not isinstance(mp, dict) or not mp:
        return "empty_my_project"
    has_desc = "ProjectDescription" in keys
    has_parcel = "Parcel Number" in keys
    if has_desc:
        return "smartgov_full"
    if has_parcel:
        return "smartgov_no_desc"
    return "smartgov_minimal"


# ── Status mapping ───────────────────────────────────────────────────────────

_BUILD_STATUS_MAP = {
    # Final
    "closed": "Final",
    "certificate of occupancy": "Final",
    "finaled": "Final",
    # Active
    "issued": "Active",
    "approved": "Active",
    # Inactive
    "cancelled": "Inactive",
    # In Review (pre-issuance / incomplete completion shells)
    "pending": "In Review",
    "incomplete": "In Review",
    "ready to issue": "In Review",
    "under review": "In Review",
    "review process has started": "In Review",
    "plans returned to applicant for revisions or corrections": "In Review",
    "technically completed": "In Review",
}


def _status_from_build_status(build_status) -> Optional[str]:
    """Map a Build Status string to STATUS_NORMALIZED."""
    if build_status is None or (isinstance(build_status, float) and math.isnan(build_status)):
        return None
    bs = str(build_status).strip()
    if not bs:
        return None
    if bs.lower().startswith("expired"):
        return "Inactive"
    return _BUILD_STATUS_MAP.get(bs.lower())


def _status_from_my_project(mp: dict) -> Optional[str]:
    """Infer STATUS_NORMALIZED from My Project date availability."""
    if _safe_to_date(mp.get("Closed")) is not None:
        return "Final"
    if _safe_to_date(mp.get("Issued")) is not None:
        return "Active"
    if (
        _safe_to_date(mp.get("Submitted")) is not None
        or _safe_to_date(mp.get("Created")) is not None
        or _safe_to_date(mp.get("Approved")) is not None
    ):
        return "In Review"
    return None


def _final_inspection_date(d: dict):
    """Latest passed/approved inspection whose name contains 'Final'."""
    inspections = d.get("Permit Inspections") or []
    dates = []
    for insp in inspections:
        if not isinstance(insp, dict):
            continue
        status = str(insp.get("Status") or "").strip().lower()
        name = str(insp.get("Inspection") or "")
        if status not in ("passed", "approved"):
            continue
        if not re.search(r"\bfinal\b", name, re.IGNORECASE):
            continue
        dt = _safe_to_date(insp.get("Date"))
        if dt is not None:
            dates.append(dt)
    if not dates:
        return None
    return max(dates)


# ── Per-record repair logic ─────────────────────────────────────────────────

def _repair_record(row, d: dict, repairs: dict):
    """Populate *repairs* dict with corrected values for a single record."""
    mp = d.get("My Project") or {}
    if not isinstance(mp, dict):
        mp = {}
    build_status = d.get("Build Status")

    # -- STATUS_NORMALIZED --
    expected_status = _status_from_build_status(build_status)
    if expected_status is None:
        # null / blank Build Status → infer from dates (recent scrapes).
        # Unmapped non-empty labels are left unchanged.
        bs_blank = (
            build_status is None
            or (isinstance(build_status, float) and math.isnan(build_status))
            or not str(build_status).strip()
        )
        if bs_blank:
            expected_status = _status_from_my_project(mp)

    # Portal sometimes leaves Ready To Issue / Pending / Under Review after
    # recording Issued (or Closed). Prefer the stronger date signal.
    if expected_status == "In Review":
        if _safe_to_date(mp.get("Closed")) is not None:
            expected_status = "Final"
        elif _safe_to_date(mp.get("Issued")) is not None:
            expected_status = "Active"

    current_status = row["STATUS_NORMALIZED"]

    if expected_status is not None:
        if pd.isna(current_status):
            repairs["STATUS_NORMALIZED"] = expected_status
            repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"
        elif current_status != expected_status:
            repairs["STATUS_NORMALIZED"] = expected_status
            repairs["STATUS_NORMALIZED_FLAG"] = "FIXED"

    effective_status = repairs.get("STATUS_NORMALIZED", current_status)

    # -- FILE_DATE --
    submitted_dt = _safe_to_date(mp.get("Submitted"))
    created_dt = _safe_to_date(mp.get("Created"))
    preferred_file = submitted_dt if submitted_dt is not None else created_dt

    if pd.isna(row["FILE_DATE"]):
        if preferred_file is not None:
            repairs["FILE_DATE"] = pd.Timestamp(preferred_file)
            repairs["FILE_DATE_FLAG"] = "FILLED"
    else:
        current_fd = _safe_to_date(row["FILE_DATE"])
        if (
            submitted_dt is not None
            and current_fd is not None
            and current_fd != submitted_dt
        ):
            repairs["FILE_DATE"] = pd.Timestamp(submitted_dt)
            repairs["FILE_DATE_FLAG"] = "FIXED"

    # -- PERMIT_DATE --
    issued_dt = _safe_to_date(mp.get("Issued"))
    approved_dt = _safe_to_date(mp.get("Approved"))
    preferred_permit = issued_dt if issued_dt is not None else approved_dt

    if effective_status in ("Active", "Final"):
        if pd.isna(row["PERMIT_DATE"]):
            if preferred_permit is not None:
                repairs["PERMIT_DATE"] = pd.Timestamp(preferred_permit)
                repairs["PERMIT_DATE_FLAG"] = "FILLED"
        else:
            current_pd = _safe_to_date(row["PERMIT_DATE"])
            if (
                issued_dt is not None
                and current_pd is not None
                and current_pd != issued_dt
            ):
                repairs["PERMIT_DATE"] = pd.Timestamp(issued_dt)
                repairs["PERMIT_DATE_FLAG"] = "FIXED"

    # -- FINAL_DATE --
    closed_dt = _safe_to_date(mp.get("Closed"))
    insp_final_dt = _final_inspection_date(d)
    preferred_final = closed_dt if closed_dt is not None else insp_final_dt

    if effective_status == "Final":
        if pd.isna(row["FINAL_DATE"]):
            if preferred_final is not None:
                repairs["FINAL_DATE"] = pd.Timestamp(preferred_final)
                repairs["FINAL_DATE_FLAG"] = "FILLED"
        else:
            current_final = _safe_to_date(row["FINAL_DATE"])
            if (
                closed_dt is not None
                and current_final is not None
                and current_final != closed_dt
            ):
                repairs["FINAL_DATE"] = pd.Timestamp(closed_dt)
                repairs["FINAL_DATE_FLAG"] = "FIXED"
    elif not pd.isna(row["FINAL_DATE"]):
        # Spurious FINAL_DATE on non-Final rows.
        repairs["FINAL_DATE"] = pd.NaT
        repairs["FINAL_DATE_FLAG"] = "FIXED"


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Delano permit records using information from the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Delano".  Must contain
        columns STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, FINAL_DATE,
        and DATA.

    Returns
    -------
    pd.DataFrame
        Copy of *df* with corrected field values, an INFERRED_SCHEMA column
        naming the DATA JSON schema identified for each record, and new
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
        _repair_record(row, d, repairs)

        for key, value in repairs.items():
            out.at[idx, key] = value

    return out


# ── CLI: run standalone to preview repair stats ─────────────────────────────

if __name__ == "__main__":
    import os
    from dotenv import load_dotenv, find_dotenv

    load_dotenv(find_dotenv())
    MY_DATA_PATH = os.getenv("MY_DATA_PATH")
    filepath = os.path.join(MY_DATA_PATH, "processed_data", "permits_ca_sample.parquet")
    df = pd.read_parquet(filepath)
    city = df[df["JURISDICTION"] == "Delano"].copy()

    print(f"Delano records: {len(city):,}\n")

    repaired = data_repair(city)

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

    print("\nINFERRED_SCHEMA:")
    print(repaired["INFERRED_SCHEMA"].value_counts(dropna=False).to_string())

    print("\nFINAL_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FINAL_DATE"].notna().sum()
        n_total = len(sub) if len(sub) > 0 else 1
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({n_has/n_total:.1%})")

    print("\nPERMIT_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["PERMIT_DATE"].notna().sum()
        n_total = len(sub) if len(sub) > 0 else 1
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({n_has/n_total:.1%})")

    print("\nFILE_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FILE_DATE"].notna().sum()
        n_total = len(sub) if len(sub) > 0 else 1
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({n_has/n_total:.1%})")

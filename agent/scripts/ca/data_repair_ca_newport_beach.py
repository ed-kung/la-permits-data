"""Data repair for Newport Beach (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Newport Beach DATA is a civic-portal payload with shared ``entity`` /
``details`` / ``contacts`` / ``processing_status`` keys and three
content variants:

  - portal_basic: entity + details + contacts + processing_status
  - portal_fees:  portal_basic + fees
  - portal_full:  portal_fees + holds + reviews + more_info + attachments

Canonical mappings (prefer ``entity``, fall back to ``details``):

  - CaseStatus / PermitStatus              → STATUS_NORMALIZED
  - ApplyDate                              → FILE_DATE
  - IssueDate                              → PERMIT_DATE
  - FinalDate / FinalizeDate               → FINAL_DATE
      (fallback for Final rows: latest Approved inspection whose
       description contains ``Final``)

Known issues repaired:
  - STATUS_NORMALIZED was derived from stale STATUS_ORIGINAL while
    CaseStatus is more current (14 rows): e.g. Final labeled Active
    (STATUS_ORIGINAL=issued), Issued labeled Final / In Review / missing,
    Expired labeled Active, In Review labeled Active → FIXED or FILLED.
  - Two Issued rows remapped to Active were missing PERMIT_DATE despite
    a populated IssueDate → FILLED.
  - One In Review row (STATUS_ORIGINAL=issued) carried a spurious
    PERMIT_DATE with blank IssueDate → cleared (FIXED).
  - Seven Final / remapped-to-Final rows missing FINAL_DATE despite
    FinalDate / FinalizeDate → FILLED.
  - Five Final rows with blank FinalDate but an Approved ``*Final*``
    inspection → FILLED from the latest such inspection date.
  - Spurious FINAL_DATE on non-Final rows (Active / Inactive, including
    two Issued rows whose STATUS_ORIGINAL=final left a FINAL_DATE with
    no FinalDate in DATA) → cleared (FIXED).

Not repairable / left as-is:
  - FILE_DATE already matches entity.ApplyDate for all 2,000 sample rows.
  - ~240 Final rows (mostly Closed Residential Building Reports and
    Encroachment / trade shells) have blank IssueDate → PERMIT_DATE
    left missing.
  - One Closed Residential Building Report has neither FinalDate nor
    usable finaling inspections → FINAL_DATE left missing.
"""

import json
import math
import re
from datetime import date, datetime
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
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return pd.NaT
    if isinstance(val, str) and not str(val).strip():
        return pd.NaT
    try:
        return pd.to_datetime(val)
    except (ValueError, TypeError):
        return pd.NaT


def _as_date(val) -> Optional[date]:
    """Normalize a datelike value to datetime.date (calendar day)."""
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


def _entity(d: dict) -> dict:
    ent = d.get("entity")
    return ent if isinstance(ent, dict) else {}


def _details(d: dict) -> dict:
    det = d.get("details")
    return det if isinstance(det, dict) else {}


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())
    if "entity" not in keys or "details" not in keys:
        return "unknown"
    if {"reviews", "holds", "more_info", "attachments"} & keys:
        return "portal_full"
    if "fees" in keys:
        return "portal_fees"
    return "portal_basic"


# ── Status mapping ──────────────────────────────────────────────────────────

# CaseStatus / PermitStatus → STATUS_NORMALIZED
_STATUS_MAP = {
    "Final": "Final",
    "Closed": "Final",
    "Approved": "Active",
    "Issued": "Active",
    "Reissued": "Active",
    "Applied": "In Review",
    "Pending": "In Review",
    "Plan Check Applied": "In Review",
    "Plan Check Approved": "In Review",
    "In Review": "In Review",
    "Declined": "Inactive",
    "Expired": "Inactive",
    "Cancelled": "Inactive",
    "Void": "Inactive",
}


def _expected_status(d: dict) -> Optional[str]:
    """Map CaseStatus (fallback PermitStatus) to STATUS_NORMALIZED."""
    ent = _entity(d)
    det = _details(d)
    raw = ent.get("CaseStatus") or det.get("PermitStatus")
    if not isinstance(raw, str) or not raw.strip():
        return None
    return _STATUS_MAP.get(raw.strip())


def _apply_date(d: dict) -> Optional[date]:
    """Prefer entity.ApplyDate (calendar day); fall back to details."""
    ent = _entity(d)
    det = _details(d)
    return _as_date(ent.get("ApplyDate")) or _as_date(det.get("ApplyDate"))


def _issue_date(d: dict) -> Optional[date]:
    ent = _entity(d)
    det = _details(d)
    return _as_date(ent.get("IssueDate")) or _as_date(det.get("IssueDate"))


def _final_date(d: dict) -> Optional[date]:
    """FinalDate / FinalizeDate, else latest Approved ``*Final*`` inspection."""
    ent = _entity(d)
    det = _details(d)
    return (
        _as_date(ent.get("FinalDate"))
        or _as_date(det.get("FinalizeDate"))
        or _final_from_inspections(d)
    )


def _final_from_inspections(d: dict) -> Optional[date]:
    """Latest Approved processing_status date whose description has Final."""
    ps = d.get("processing_status")
    if not isinstance(ps, list):
        return None
    dates = []
    for item in ps:
        if not isinstance(item, dict):
            continue
        status = str(item.get("status") or "").strip().lower()
        if status != "approved":
            continue
        desc = str(item.get("description") or "")
        if not re.search(r"\bfinal\b", desc, flags=re.IGNORECASE):
            continue
        for key in ("scheduled_date", "requested_date"):
            dt = _as_date(item.get(key))
            if dt is not None:
                dates.append(dt)
                break
    if not dates:
        return None
    return max(dates)


# ── Per-record repair ───────────────────────────────────────────────────────

def _repair_record(row, d: dict, repairs: dict):
    """Repair one Newport Beach permit record in-place via *repairs* dict."""

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

    # -- FILE_DATE (ApplyDate) --
    apply = _apply_date(d)
    current_file = _as_date(row["FILE_DATE"])
    if apply is not None:
        if current_file is None:
            repairs["FILE_DATE"] = apply
            repairs["FILE_DATE_FLAG"] = "FILLED"
        elif current_file != apply:
            repairs["FILE_DATE"] = apply
            repairs["FILE_DATE_FLAG"] = "FIXED"

    # -- PERMIT_DATE (IssueDate) --
    issue = _issue_date(d)
    current_permit = _as_date(row["PERMIT_DATE"])

    if effective_status in ("Active", "Final"):
        if issue is not None:
            if current_permit is None:
                repairs["PERMIT_DATE"] = issue
                repairs["PERMIT_DATE_FLAG"] = "FILLED"
            elif current_permit != issue:
                repairs["PERMIT_DATE"] = issue
                repairs["PERMIT_DATE_FLAG"] = "FIXED"
    elif current_permit is not None and issue is None:
        # Spurious PERMIT_DATE on non-issued In Review / Inactive rows.
        repairs["PERMIT_DATE"] = pd.NaT
        repairs["PERMIT_DATE_FLAG"] = "FIXED"
    elif issue is not None and current_permit is not None and current_permit != issue:
        repairs["PERMIT_DATE"] = issue
        repairs["PERMIT_DATE_FLAG"] = "FIXED"

    # -- FINAL_DATE (FinalDate / FinalizeDate / Final inspection) --
    final = _final_date(d)
    current_final = _as_date(row["FINAL_DATE"])

    if effective_status == "Final":
        if final is not None:
            if current_final is None:
                repairs["FINAL_DATE"] = final
                repairs["FINAL_DATE_FLAG"] = "FILLED"
            elif current_final != final:
                repairs["FINAL_DATE"] = final
                repairs["FINAL_DATE_FLAG"] = "FIXED"
    elif current_final is not None:
        # Spurious FINAL_DATE on non-Final rows.
        repairs["FINAL_DATE"] = pd.NaT
        repairs["FINAL_DATE_FLAG"] = "FIXED"


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Newport Beach permit records using information from the raw DATA JSON
    column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Newport Beach".  Must contain
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
    from dotenv import load_dotenv

    load_dotenv("/Users/ekung/projects/la-permits-data/.env")
    MY_DATA_PATH = os.getenv("MY_DATA_PATH")
    AGENT_DATA_PATH = os.getenv("AGENT_DATA_PATH")
    filepath = os.path.join(MY_DATA_PATH, "processed_data", "permits_ca_sample.parquet")
    df = pd.read_parquet(filepath)
    city = df[
        (df["JURISDICTION"] == "Newport Beach") & (df["STATE"] == "CA")
    ].copy()

    print(f"Newport Beach records: {len(city):,}\n")

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

    print("\nFILE_DATE coverage after repair:")
    n_has = repaired["FILE_DATE"].notna().sum()
    print(f"  {n_has:,} / {len(repaired):,} ({n_has / len(repaired):.1%})")

    print("\nPERMIT_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["PERMIT_DATE"].notna().sum()
        pct = n_has / len(sub) if len(sub) else 0.0
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({pct:.1%})")

    print("\nFINAL_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FINAL_DATE"].notna().sum()
        pct = n_has / len(sub) if len(sub) else 0.0
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({pct:.1%})")

    # Remaining Final gaps
    final_sub = repaired[repaired["STATUS_NORMALIZED"] == "Final"]
    print(f"\nFinal still missing PERMIT_DATE: {final_sub['PERMIT_DATE'].isna().sum()}")
    print(f"Final still missing FINAL_DATE:  {final_sub['FINAL_DATE'].isna().sum()}")

    if AGENT_DATA_PATH:
        out_path = os.path.join(AGENT_DATA_PATH, "newport_beach_repaired_sample.parquet")
        for col in ["FILE_DATE", "PERMIT_DATE", "FINAL_DATE"]:
            repaired[col] = pd.to_datetime(repaired[col], errors="coerce")
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote {out_path}")

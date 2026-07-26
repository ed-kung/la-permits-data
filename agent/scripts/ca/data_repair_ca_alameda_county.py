"""Data repair for Alameda County (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Alameda County DATA is a civic/project portal payload with two key-set
variants (same date/status fields in both):

  - project_full:    includes inspections / permitType / work / etc.
  - project_compact: includes apn; omits inspections block

Canonical mappings:
  - DATA.status                         → STATUS_NORMALIZED
      (override: ISS / EXP with Finaled evidence → Final)
  - DATA.created (fallback: issued)     → FILE_DATE
  - DATA.issued                         → PERMIT_DATE
  - DATA.closed (fallback: search[]
      Project entry dateVal when
      datePrefix is ``Finaled on``)     → FINAL_DATE

Known issues repaired:
  - 63 STATUS_NORMALIZED nulls for unmapped statuses (code-enforcement
    Closed / *, REC, New Case, EXH, CLR, etc.) → FILLED.
  - Complaint Received wrongly mapped to Inactive → FIXED to In Review.
  - 2 ISS - Issued and 4 EXP - Expired rows with closed / ``Finaled on``
    evidence but lagging status text → FIXED to Final.
  - 1 FILE_DATE null with blank created but populated issued → FILLED.
  - ~350+ Final rows (and newly mapped Closed / * rows) missing
    FINAL_DATE despite search ``Finaled on`` dateVal → FILLED.
  - Spurious FINAL_DATE on non-Final rows after status resolution →
    cleared (FIXED); none remain once ISS/EXP finaled rows are remapped.

Not repairable / left as-is:
  - 74 Active/Final rows with blank issued (APR - Approved never issued;
    legacy FIN/CLO shells with only created) → PERMIT_DATE stays missing.
  - ~190 Final rows (mostly CLO - Closed / FIN with Issued on or
    Created on prefixes and no closed) have no finaled date in DATA →
    FINAL_DATE stays missing.
"""

import json
import math
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
    # Handle timezone-aware timestamps
    if getattr(dt, "tzinfo", None) is not None:
        return dt.date()
    return dt.date()


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())
    if "status" not in keys or "created" not in keys:
        return "unknown"
    if "inspections" in keys or "permitType" in keys:
        return "project_full"
    if "apn" in keys:
        return "project_compact"
    return "project_other"


def _project_search(d: dict) -> dict:
    """Return the Project:* search entry, else the first search dict."""
    for s in d.get("search") or []:
        if isinstance(s, dict) and str(s.get("msValue", "")).startswith("Project:"):
            return s
    search = d.get("search") or []
    if search and isinstance(search[0], dict):
        return search[0]
    return {}


def _has_finaled_evidence(d: dict) -> bool:
    """True when closed is set or Project search is tagged Finaled on."""
    if _as_date(d.get("closed")) is not None:
        return True
    ps = _project_search(d)
    prefix = str(ps.get("datePrefix") or "").lower()
    if "final" in prefix and _as_date(ps.get("dateVal")) is not None:
        return True
    return False


# ── Status mapping ──────────────────────────────────────────────────────────

# DATA.status → STATUS_NORMALIZED (before Finaled-evidence override)
_STATUS_MAP = {
    # Final
    "FIN - Finaled": "Final",
    "CLO - Closed": "Final",
    "Closed": "Final",
    "Closed / No Violation": "Final",
    "Closed / In Compliance": "Final",
    "Closed / Referral": "Final",
    "Closed Per Admin Action": "Final",
    "Closed Approved": "Final",
    # Active
    "ISS - Issued": "Active",
    "APR - Approved": "Active",
    "EXH - Folder/Plans Hold 2+yrs": "Active",
    # Inactive
    "EXP - Expired": "Inactive",
    "WDN - Withdrawn": "Inactive",
    "EXR": "Inactive",
    # In Review
    "INC - Incomplete": "In Review",
    "In Process": "In Review",
    "FEE - Pending Fees": "In Review",
    "RVW - Under Review": "In Review",
    "ACL - Additional Correction List": "In Review",
    "REC - Received": "In Review",
    "APP - Applied": "In Review",
    "Under Review RVW": "In Review",
    "Hearing HRG": "In Review",
    "New Case": "In Review",
    "Initial Notice Sent": "In Review",
    "Verified Violation": "In Review",
    "Courtesy Notice Sent": "In Review",
    "Fines & Fees Sent": "In Review",
    "Complaint Received": "In Review",
    "Progress Made": "In Review",
    "APT": "In Review",
    "CLR": "In Review",
}


def _expected_status(d: dict) -> Optional[str]:
    raw = d.get("status")
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None
    mapped = _STATUS_MAP.get(str(raw).strip())
    # Lagging ISS / EXP text with Finaled evidence → Final
    if mapped in ("Active", "Inactive") and _has_finaled_evidence(d):
        return "Final"
    return mapped


def _file_date(d: dict) -> Optional[date]:
    created = _as_date(d.get("created"))
    if created is not None:
        return created
    # Last resort when created is blank (rare): use issued
    return _as_date(d.get("issued"))


def _permit_date(d: dict) -> Optional[date]:
    return _as_date(d.get("issued"))


def _final_date(d: dict) -> Optional[date]:
    closed = _as_date(d.get("closed"))
    if closed is not None:
        return closed
    ps = _project_search(d)
    prefix = str(ps.get("datePrefix") or "").lower()
    if "final" in prefix:
        return _as_date(ps.get("dateVal"))
    return None


# ── Per-record repair ───────────────────────────────────────────────────────

def _repair_record(row, d: dict, repairs: dict):
    """Repair one Alameda County permit record via *repairs* dict."""

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

    # -- FILE_DATE (created / application) --
    apply = _file_date(d)
    current_file = _as_date(row["FILE_DATE"])
    if apply is not None:
        if current_file is None:
            repairs["FILE_DATE"] = apply
            repairs["FILE_DATE_FLAG"] = "FILLED"
        elif current_file != apply:
            repairs["FILE_DATE"] = apply
            repairs["FILE_DATE_FLAG"] = "FIXED"

    # -- PERMIT_DATE (issued) --
    issue = _permit_date(d)
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
        repairs["PERMIT_DATE"] = pd.NaT
        repairs["PERMIT_DATE_FLAG"] = "FIXED"
    elif issue is not None and current_permit is not None and current_permit != issue:
        repairs["PERMIT_DATE"] = issue
        repairs["PERMIT_DATE_FLAG"] = "FIXED"

    # -- FINAL_DATE (closed / Finaled on) --
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
        repairs["FINAL_DATE"] = pd.NaT
        repairs["FINAL_DATE_FLAG"] = "FIXED"


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Alameda County permit records using information from the raw DATA JSON
    column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Alameda County".  Must contain
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
    filepath = os.path.join(MY_DATA_PATH, "processed_data", "permits_ca_sample.parquet")
    df = pd.read_parquet(filepath)
    county = df[(df["JURISDICTION"] == "Alameda County") & (df["STATE"] == "CA")].copy()

    print(f"Alameda County records: {len(county):,}\n")

    repaired = data_repair(county)

    print("INFERRED_SCHEMA:")
    print(repaired["INFERRED_SCHEMA"].value_counts(dropna=False).to_string())
    print()

    for field in ["STATUS_NORMALIZED", "FILE_DATE", "PERMIT_DATE", "FINAL_DATE"]:
        flag_col = f"{field}_FLAG"
        n_filled = (repaired[flag_col] == "FILLED").sum()
        n_fixed = (repaired[flag_col] == "FIXED").sum()
        print(f"{field}:")
        print(f"  FILLED: {n_filled:>4,}   FIXED: {n_fixed:>4,}")

        before_missing = county[field].isna().sum()
        after_missing = repaired[field].isna().sum()
        print(f"  Missing before: {before_missing:>4,}   Missing after: {after_missing:>4,}")
        print()

    print("STATUS_NORMALIZED distribution:")
    print("  Before:")
    for s, c in county["STATUS_NORMALIZED"].value_counts(dropna=False).items():
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

    print("\nFILE_DATE missing after:", repaired["FILE_DATE"].isna().sum())

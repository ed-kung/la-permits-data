"""Data repair for Gardena (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Gardena DATA is a single flat portal schema (all sample rows share the
same top-level keys: contacts, fees, inspections, permit_info,
search_data, site_info). Canonical fields:

  - permit_info.PermitStatus       → STATUS_NORMALIZED
      (asterisk decorations like **FINALED** / FINALED** stripped)
  - permit_info.PermitAppliedDate  → FILE_DATE
  - permit_info.PermitIssuedDate   → PERMIT_DATE
      (fallback: PermitApprovedDate / search_data.APPROVED)
  - permit_info.PermitFinaledDate  → FINAL_DATE
      (identical to search_data.FINALED when present;
       fallback for Final rows: latest inspection Completed date
       with Result containing FINALED, or Type containing FINAL
       plus a successful/neutral Result such as PASSED)

``PermitExpirationDate`` / search_data.EXPIRED are permit-validity
windows, not finaling / completion dates.

Known issues repaired:
  - STATUS_NORMALIZED is null for 199 sample rows (197 empty
    PermitStatus, plus PL CK ONLY / <NONE>) → infer from dates /
    map remaining labels.
  - 33 rows have PermitFinaledDate but STATUS_NORMALIZED is not Final
    (ISSUED, WAIVED, EXPIRED, and one **FINALED** mislabeled Active)
    → Final.
  - PERMIT_DATE missing on Active/Final when Issued is empty but
    Approved is present → fill from PermitApprovedDate.
  - FINAL_DATE missing on Final rows with empty PermitFinaledDate but
    a finaling inspection (Result or Type FINALED) → fill from
    inspection Completed.

Not repairable from DATA:
  - 5 rows have empty PermitAppliedDate (and no alternate application
    date) → FILE_DATE stays missing.
  - Many Final/Active rows lack both Issued and Approved dates
    (~155 Final / 4 Active after repair).
  - 7 FINALED-status rows lack both PermitFinaledDate and a usable
    finaling inspection (empty inspections, FAILED-only finals, or
    non-final inspection types).
"""

import json
import math
from datetime import date, datetime
from typing import Optional

import pandas as pd
import numpy as np


# Plausible calendar-year range for permit dates in this jurisdiction.
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
    return "unknown"


def _normalize_status_key(raw) -> str:
    """Uppercase PermitStatus and strip asterisk decorations."""
    if raw is None:
        return ""
    s = str(raw).strip().upper()
    return s.replace("*", "").strip()


# ── Status mapping ──────────────────────────────────────────────────────────

# Normalized PermitStatus (asterisks stripped, uppercased) → STATUS_NORMALIZED
_STATUS_MAP = {
    "FINALED": "Final",
    "MEP PL CK FINALED": "Final",
    "ISSUED": "Active",
    "APPROVED": "Active",
    "APPLIED": "In Review",
    "UNDER REVIEW": "In Review",
    "SUBMITTED": "In Review",
    "HOLD": "In Review",
    "CHANGE OF CONTR": "In Review",
    "WAIVED": "In Review",
    "PL CK ONLY": "In Review",
    "EXPIRED": "Inactive",
    "EXPIRED PERMIT": "Inactive",
    "EXPIRED PL CK": "Inactive",
    "PL CK EXPIRED": "Inactive",
    "WITHDRAWN": "Inactive",
    "CANCELLED": "Inactive",
    "VOIDED": "Inactive",
    "VOIDED ORD 1614": "Inactive",
    "DENIED": "Inactive",
    "<NONE>": None,
    "": None,
}


def _permit_info(d: dict) -> dict:
    pi = d.get("permit_info")
    return pi if isinstance(pi, dict) else {}


def _search_data(d: dict) -> dict:
    sd = d.get("search_data")
    return sd if isinstance(sd, dict) else {}


def _map_permit_status(raw) -> Optional[str]:
    key = _normalize_status_key(raw)
    if key in _STATUS_MAP:
        return _STATUS_MAP[key]
    if "FINALED" in key:
        return "Final"
    if "EXPIRED" in key or "VOIDED" in key:
        return "Inactive"
    return None


def _derive_status(pi: dict) -> Optional[str]:
    """Map PermitStatus to STATUS_NORMALIZED; prefer Final when finaled.

    Empty / unmapped portal statuses are inferred from available dates:
    Issued/Approved → Active, Applied-only → In Review.
    """
    status = _map_permit_status(pi.get("PermitStatus"))

    # A populated finaled date is stronger evidence of completion than a
    # stale ISSUED / WAIVED / EXPIRED / empty portal label.
    if _as_date(pi.get("PermitFinaledDate")) is not None:
        return "Final"

    if status is not None:
        return status

    if _as_date(pi.get("PermitIssuedDate")) is not None:
        return "Active"
    if _as_date(pi.get("PermitApprovedDate")) is not None:
        return "Active"
    if _as_date(pi.get("PermitAppliedDate")) is not None:
        return "In Review"
    return None


def _preferred_file_date(pi: dict) -> Optional[date]:
    return _as_date(pi.get("PermitAppliedDate"))


def _preferred_permit_date(pi: dict, sd: dict) -> Optional[date]:
    issued = _as_date(pi.get("PermitIssuedDate"))
    if issued is not None:
        return issued
    approved = _as_date(pi.get("PermitApprovedDate"))
    if approved is not None:
        return approved
    return _as_date(sd.get("APPROVED"))


# Inspection Result values treated as a successful / completed final when the
# Type itself is a final-* inspection (FINALED, FINAL ELECTRICAL, etc.).
_FINAL_INSP_OK_RESULTS = {
    "",
    "PASSED",
    "APPROVED",
    "AP",
    "FINALED",
    "PARTIAL - SEE NOTES",
    "PARTIAL",
}


def _finaled_from_inspections(d: dict) -> Optional[date]:
    """Latest Completed date from a finaling inspection.

    Accepts either:
      - Result containing FINALED, or
      - Type containing FINAL (FINALED / FINAL ELECTRICAL / …) with a
        successful / neutral Result (PASSED, APPROVED, empty, etc.).
        Failed / canceled / not-ready finals are ignored.
    """
    inspections = d.get("inspections")
    if not isinstance(inspections, list):
        return None
    dates = []
    for item in inspections:
        if not isinstance(item, dict):
            continue
        result = _normalize_status_key(item.get("Result"))
        typ = _normalize_status_key(item.get("Type"))
        result_is_finaled = "FINALED" in result
        type_is_final = "FINAL" in typ
        if result_is_finaled:
            ok = True
        elif type_is_final and result in _FINAL_INSP_OK_RESULTS:
            ok = True
        else:
            ok = False
        if not ok:
            continue
        completed = _as_date(item.get("Completed"))
        if completed is not None:
            dates.append(completed)
    return max(dates) if dates else None


def _preferred_final_date(pi: dict, sd: dict, d: dict) -> Optional[date]:
    finaled = _as_date(pi.get("PermitFinaledDate"))
    if finaled is not None:
        return finaled
    sd_finaled = _as_date(sd.get("FINALED"))
    if sd_finaled is not None:
        return sd_finaled
    return _finaled_from_inspections(d)


# ── Per-record repair logic ─────────────────────────────────────────────────

def _repair_record(row, d: dict, repairs: dict):
    """Populate *repairs* with corrected values for a single Gardena record."""
    pi = _permit_info(d)
    sd = _search_data(d)

    # -- STATUS_NORMALIZED --
    current_status = row["STATUS_NORMALIZED"]
    expected = _derive_status(pi)
    if expected is not None:
        if pd.isna(current_status):
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"
        elif current_status != expected:
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FIXED"

    effective_status = repairs.get("STATUS_NORMALIZED", current_status)

    # -- FILE_DATE --
    preferred_fd = _preferred_file_date(pi)
    current_fd = _as_date(row["FILE_DATE"])
    if preferred_fd is not None:
        if current_fd is None:
            repairs["FILE_DATE"] = pd.Timestamp(preferred_fd)
            repairs["FILE_DATE_FLAG"] = "FILLED"
        elif current_fd != preferred_fd:
            repairs["FILE_DATE"] = pd.Timestamp(preferred_fd)
            repairs["FILE_DATE_FLAG"] = "FIXED"

    # -- PERMIT_DATE --
    preferred_pd = _preferred_permit_date(pi, sd)
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
    preferred_final = _preferred_final_date(pi, sd, d)
    current_final = _as_date(row["FINAL_DATE"])
    if preferred_final is not None:
        if current_final is None:
            if effective_status == "Final":
                repairs["FINAL_DATE"] = pd.Timestamp(preferred_final)
                repairs["FINAL_DATE_FLAG"] = "FILLED"
        elif current_final != preferred_final:
            repairs["FINAL_DATE"] = pd.Timestamp(preferred_final)
            repairs["FINAL_DATE_FLAG"] = "FIXED"
    elif current_final is not None and effective_status != "Final":
        # Clear final dates on non-Final rows when DATA has no finaled signal.
        repairs["FINAL_DATE"] = pd.NaT
        repairs["FINAL_DATE_FLAG"] = "FIXED"


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Gardena permit records using information from the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Gardena".  Must contain
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
    filepath = os.path.join(MY_DATA_PATH, "processed_data", "permits_la_sample.parquet")
    df = pd.read_parquet(filepath)
    city = df[(df["JURISDICTION"] == "Gardena") & (df["STATE"] == "CA")].copy()

    print(f"Gardena records: {len(city):,}\n")

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

    print("\nFILE_DATE coverage (after repair):")
    n_has = repaired["FILE_DATE"].notna().sum()
    print(f"  {n_has:>4,} / {len(repaired):>4,} ({n_has/len(repaired):.1%})")

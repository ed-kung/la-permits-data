"""Data repair for San Rafael (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

San Rafael DATA is a single PAT / civic-portal schema. All sample rows
share top-level keys ``contacts``, ``fees``, ``inspections``,
``permit_info``, ``search_data``, and ``site_info``. Content variants
(used as INFERRED_SCHEMA) differ by which ``permit_info`` dates are
populated and whether inspections exist:

  - permit_info_complete[_insp]:     Applied + Issued/Approved + Finaled
  - permit_info_issued[_insp]:       Applied + Issued/Approved (no Finaled)
  - permit_info_application[_insp]:  Applied only
  - permit_info_partial[_insp]:      other incomplete date combinations
  - permit_info_empty:               no usable permit_info dates
  - unknown / missing

Canonical fields (from ``permit_info``):

  - PermitStatus                         → STATUS_NORMALIZED
    (upgrade to Final when PermitFinaledDate is set, unless inactive)
  - PermitAppliedDate (fallback: search
    Issue Date / earliest fee Paid Date /
    Issued / Approved)                   → FILE_DATE
  - PermitIssuedDate (fallback:
    PermitApprovedDate)                  → PERMIT_DATE
  - PermitFinaledDate (fallback: latest
    approved final inspection; for
    COMPLETED* resales, latest completed
    inspection)                          → FINAL_DATE

Known issues repaired:
  - Stale labels (FINALED/COMPLETED→Active or In Review, EXPIRED→Active,
    NO FINAL→Final without a finaled date) → FIXED from PermitStatus.
  - Null STATUS_NORMALIZED on blank / INDEFINITE statuses → FILLED from
    status text and date evidence.
  - Active / Final rows missing PERMIT_DATE when Issued is empty but
    Approved is present → FILLED from PermitApprovedDate.
  - Final rows missing FINAL_DATE with PermitFinaledDate or a usable
    final / resale completion inspection → FILLED.
  - Spurious FINAL_DATE on non-Final rows (EXPIRED / CANCELED /
    PENDING close timestamps) → cleared (FIXED).
  - Rare FILE_DATE gaps filled from search Issue Date / fees / Issued.

Not repairable from DATA:
  - Most FILE_DATE gaps are empty VOID / UNDER REVIEW shells with no
    applied, issue, or fee dates.
  - Some Active rows lack both Issued and Approved dates.
  - Some FINALED / COMPLETED* rows lack PermitFinaledDate and have no
    usable inspection completion date.
"""

from __future__ import annotations

import json
import math
import re
from datetime import date, datetime
from typing import Optional

import numpy as np
import pandas as pd


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


def _permit_info(d: dict) -> dict:
    pi = d.get("permit_info")
    return pi if isinstance(pi, dict) else {}


def _search_data(d: dict) -> dict:
    sd = d.get("search_data")
    return sd if isinstance(sd, dict) else {}


def _has_inspections(d: dict) -> bool:
    insp = d.get("inspections")
    return isinstance(insp, list) and len(insp) > 0


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())
    if not {"permit_info", "search_data"}.issubset(keys):
        return "unknown"

    pi = _permit_info(data_dict)
    has_applied = _as_date(pi.get("PermitAppliedDate")) is not None
    has_issued = _as_date(pi.get("PermitIssuedDate")) is not None
    has_approved = _as_date(pi.get("PermitApprovedDate")) is not None
    has_finaled = _as_date(pi.get("PermitFinaledDate")) is not None
    has_any_other = has_issued or has_approved or has_finaled
    has_issuance = has_issued or has_approved

    if has_applied and has_issuance and has_finaled:
        base = "permit_info_complete"
    elif has_applied and has_issuance:
        base = "permit_info_issued"
    elif has_applied and not has_any_other:
        base = "permit_info_application"
    elif has_any_other:
        base = "permit_info_partial"
    else:
        base = "permit_info_empty"

    if _has_inspections(data_dict):
        return f"{base}_insp"
    return base


# ── Status mapping ──────────────────────────────────────────────────────────

# permit_info.PermitStatus (uppercased) → STATUS_NORMALIZED
_STATUS_MAP = {
    "FINALED": "Final",
    "COMPLETED": "Final",
    "COMPLETED B": "Final",
    "COMPLETED C": "Final",
    "COMPLETED B OLD": "Final",
    "COMPLETED C OLD": "Final",
    "COMPLETED RES. 14870": "Final",
    "ACTIVE": "Active",
    "APPROVED": "Active",
    "NO FINAL": "Active",
    "READY 2 ISSUE": "In Review",
    "UNDER REVIEW": "In Review",
    "PW UNDER REVIEW": "In Review",
    "PROCESSING": "In Review",
    "APPLIED": "In Review",
    "APPLIED ONLINE": "In Review",
    "PENDING": "In Review",
    "PLANS APPROVED": "In Review",
    "ON HOLD-SEE CHRONO": "In Review",
    "REGISTERED": "In Review",
    "EXPIRED": "Inactive",
    "EXPIRED IN P/C": "Inactive",
    "EXPIRED W/O FINAL": "Inactive",
    "EXPIRED BAL DUE": "Inactive",
    "CANCELED": "Inactive",
    "CANCELLED": "Inactive",
    "VOID": "Inactive",
    "WITHDRAWN": "Inactive",
    "BUSINESS CLOSED": "Inactive",
}

# Terminal inactive labels: PermitFinaledDate on these is a close/void
# timestamp, not evidence the permit should be treated as Final.
_INACTIVE_KEEP = {
    "EXPIRED",
    "EXPIRED IN P/C",
    "EXPIRED W/O FINAL",
    "EXPIRED BAL DUE",
    "CANCELED",
    "CANCELLED",
    "VOID",
    "WITHDRAWN",
    "BUSINESS CLOSED",
}

_RESALE_COMPLETED = {
    "COMPLETED",
    "COMPLETED B",
    "COMPLETED C",
    "COMPLETED B OLD",
    "COMPLETED C OLD",
    "COMPLETED RES. 14870",
}

_FINAL_INSP_OK = {
    "",
    "APPROVED",
    "APPROVED W/CMTS",
    "PASS",
    "PASSED",
    "COMPLETED",
    "COMPLETE",
    "SEE ATTACHMENT",
}

_FINAL_TITLE_RE = re.compile(
    r"(?i)\bfinal\b|c\s*of\s*o|cofo|certificate\s*of\s*occupancy"
)
_RESALE_DONE_RE = re.compile(
    r"(?i)resale\s+inspection|resale\s+report|rbr\s+compliance|buyer\s+cert"
)


def _normalize_status_key(raw) -> str:
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return ""
    return str(raw).strip().upper()


def _derive_status(pi: dict) -> Optional[str]:
    """Map PermitStatus; prefer Final when a non-inactive row is finaled."""
    raw = _normalize_status_key(pi.get("PermitStatus"))
    status = _STATUS_MAP.get(raw) if raw else None

    if raw in _INACTIVE_KEEP:
        return status or "Inactive"

    if _as_date(pi.get("PermitFinaledDate")) is not None:
        return "Final"

    if status is not None:
        return status

    if raw == "INDEFINITE":
        if (
            _as_date(pi.get("PermitIssuedDate")) is not None
            or _as_date(pi.get("PermitApprovedDate")) is not None
        ):
            return "Active"
        return "In Review"

    if not raw:
        desc = str(pi.get("PermitDesc") or "").strip().upper()
        if "VOID" in desc:
            return "Inactive"
        if (
            _as_date(pi.get("PermitIssuedDate")) is not None
            or _as_date(pi.get("PermitApprovedDate")) is not None
        ):
            return "Active"
        return "In Review"

    if "FINAL" in raw or "COMPLETE" in raw:
        return "Final"
    if (
        "EXPIRE" in raw
        or "VOID" in raw
        or "CANCEL" in raw
        or "WITHDRAW" in raw
        or "DENY" in raw
    ):
        return "Inactive"
    if "ISSUE" in raw or "APPROV" in raw or raw == "ACTIVE":
        return "Active"
    if "REVIEW" in raw or "HOLD" in raw or "PENDING" in raw or "APPLIED" in raw:
        return "In Review"
    return None


def _earliest_fee_paid(d: dict) -> Optional[date]:
    fees = d.get("fees")
    if not isinstance(fees, dict):
        return None
    items = fees.get("fees")
    if not isinstance(items, list):
        return None
    dates = []
    for item in items:
        if not isinstance(item, dict):
            continue
        paid = _as_date(item.get("Paid Date"))
        if paid is not None:
            dates.append(paid)
    return min(dates) if dates else None


def _preferred_file_date(pi: dict, d: dict) -> Optional[date]:
    applied = _as_date(pi.get("PermitAppliedDate"))
    if applied is not None:
        return applied

    sd = _search_data(d)
    issue = _as_date(sd.get("Issue Date"))
    if issue is not None:
        return issue

    fee = _earliest_fee_paid(d)
    if fee is not None:
        return fee

    issued = _as_date(pi.get("PermitIssuedDate"))
    if issued is not None:
        return issued
    return _as_date(pi.get("PermitApprovedDate"))


def _preferred_permit_date(pi: dict) -> Optional[date]:
    issued = _as_date(pi.get("PermitIssuedDate"))
    if issued is not None:
        return issued
    return _as_date(pi.get("PermitApprovedDate"))


def _final_from_inspections(d: dict, allow_resale: bool = False) -> Optional[date]:
    """Latest completion date from an approved final (or resale) inspection."""
    inspections = d.get("inspections")
    if not isinstance(inspections, list):
        return None
    dates = []
    for item in inspections:
        if not isinstance(item, dict):
            continue
        text = str(item.get("Type") or item.get("Title") or "").strip()
        is_final = bool(_FINAL_TITLE_RE.search(text))
        is_resale = allow_resale and bool(_RESALE_DONE_RE.search(text))
        if not (is_final or is_resale):
            continue
        result = str(item.get("Result") or "").strip().upper()
        if result not in _FINAL_INSP_OK:
            continue
        completed = _as_date(item.get("Completed") or item.get("Scheduled Date"))
        if completed is not None:
            dates.append(completed)
    return max(dates) if dates else None


def _preferred_final_date(pi: dict, d: dict) -> Optional[date]:
    finaled = _as_date(pi.get("PermitFinaledDate"))
    if finaled is not None:
        return finaled
    raw = _normalize_status_key(pi.get("PermitStatus"))
    allow_resale = raw in _RESALE_COMPLETED or "RESALE" in str(
        pi.get("PermitType") or ""
    ).upper()
    return _final_from_inspections(d, allow_resale=allow_resale)


# ── Per-record repair logic ─────────────────────────────────────────────────

def _repair_record(row, d: dict, repairs: dict):
    """Populate *repairs* with corrected values for a single San Rafael record."""
    pi = _permit_info(d)

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
    preferred_fd = _preferred_file_date(pi, d)
    current_fd = _as_date(row["FILE_DATE"])
    if preferred_fd is not None:
        if current_fd is None:
            repairs["FILE_DATE"] = pd.Timestamp(preferred_fd)
            repairs["FILE_DATE_FLAG"] = "FILLED"
        elif current_fd != preferred_fd:
            repairs["FILE_DATE"] = pd.Timestamp(preferred_fd)
            repairs["FILE_DATE_FLAG"] = "FIXED"

    # -- PERMIT_DATE --
    preferred_pd = _preferred_permit_date(pi)
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
    preferred_final = _preferred_final_date(pi, d)
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


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    San Rafael permit records using information from the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "San Rafael".  Must contain
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
    city = df[(df["JURISDICTION"] == "San Rafael") & (df["STATE"] == "CA")].copy()

    print(f"San Rafael records: {len(city):,}\n")

    repaired = data_repair(city)

    if AGENT_DATA_PATH:
        out_path = os.path.join(AGENT_DATA_PATH, "san_rafael_repaired_sample.parquet")
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

    print("\nSTATUS_NORMALIZED_FLAG breakdown:")
    print(repaired["STATUS_NORMALIZED_FLAG"].value_counts(dropna=False).to_string())

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

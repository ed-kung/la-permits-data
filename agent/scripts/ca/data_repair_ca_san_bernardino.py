"""Data repair for San Bernardino (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

San Bernardino DATA is a city permit-portal scrape. All sample rows share
the same top-level keys (``permit_status``, ``File Date``, ``Status``,
``Payments``, ``Completed Inspections``, ``Scheduled Inspections``, …).
Content variants (used as INFERRED_SCHEMA) differ by which date sources
are populated:

  - portal_status_and_inspections: dated ``Status`` events + completed
                                   inspections
  - portal_inspections:            completed inspections, no Status events
  - portal_status_events:          dated ``Status`` events, no inspections
  - portal_payments_only:          payments present; no Status / inspections
  - portal_shell:                  File Date only (no payments / Status /
                                   inspections)
  - unknown / missing

Canonical mappings:
  - DATA.permit_status                         → STATUS_NORMALIZED
  - DATA['File Date']                          → FILE_DATE
  - Status ISSUED/JOB CARD comment date;
    else AP:Approved Status Date;
    else earliest Completed Inspection;
    else earliest non-void Payment Date;
    else File Date (Active/Final last resort)  → PERMIT_DATE
  - Latest approved BUILDING FINAL / FINAL*
    inspection (incl. legacy null-status
    BUILDING FINAL); Approved: Finaled;
    STAT CLOSE COMPLAINT; Fire Inspection with
    FINAL comment                              → FINAL_DATE

Known issues repaired:
  - 132 null STATUS_NORMALIZED (mostly CODE / LIEN / ZV statuses such as
    VOLUNTRY, SUBMITTD, PICKEDUP, REQ INSP, …) → FILLED from permit_status.
  - 14 rows where STATUS_ORIGINAL disagreed with permit_status
    (e.g. issued→Active while permit_status is FINAL) → FIXED to the
    permit_status mapping.
  - PERMIT_DATE missing on every row → FILLED for Active/Final from the
    hierarchy above (no dedicated issued-date field in DATA).
  - FINAL_DATE missing on every Final row with a usable final / close
    inspection → FILLED.

Not repairable / left as-is:
  - FILE_DATE already matches DATA['File Date'] for all sample rows.
  - ~85 Final rows (mostly CODE VOLUNTRY/ADCLOSED shells without a close
    inspection, plus a few FINAL/COMPLETE/RECORDED without finals) stay
    missing FINAL_DATE.
  - PERMIT_DATE for Active/Final with only File Date / same-day payment
    uses that as a weak OTC proxy; there is no stronger agency issue date.
"""

from __future__ import annotations

import json
import math
import re
from typing import Optional

import numpy as np
import pandas as pd


_MIN_YEAR = 1980
_MAX_YEAR = 2035

_FINAL_DESC_RE = re.compile(
    r"BUILDING\s+FINAL|\bFINAL\b|STAT\s+CLOSE|CLOSE\s+COMPLAINT",
    re.IGNORECASE,
)


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


def _dates_equal(a, b) -> bool:
    """Compare two datelike values at calendar-day resolution."""
    da = _safe_to_datetime(a)
    db = _safe_to_datetime(b)
    if da is pd.NaT or db is pd.NaT:
        return False
    return da.normalize() == db.normalize()


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())
    if "permit_status" not in keys or "File Date" not in keys:
        return "unknown"

    has_status = bool(data_dict.get("Status"))
    has_insp = bool(data_dict.get("Completed Inspections"))
    has_pay = bool(data_dict.get("Payments"))

    if has_status and has_insp:
        return "portal_status_and_inspections"
    if has_insp:
        return "portal_inspections"
    if has_status:
        return "portal_status_events"
    if has_pay:
        return "portal_payments_only"
    return "portal_shell"


# ── Status mapping ───────────────────────────────────────────────────────────

_STATUS_MAP = {
    # Final — completed / closed / recorded
    "FINAL": "Final",
    "COMPLETE": "Final",
    "CLOSED": "Final",
    "RECORDED": "Final",
    "ADCLOSED": "Final",
    "RESOLUTN": "Final",
    "VOLUNTRY": "Final",   # code case closed via voluntary compliance
    "CORRECTD": "Final",   # code case corrected / closed
    # Active — issued / open enforcement
    "ISSUED": "Active",
    "APPROVED": "Active",
    "PICKEDUP": "Active",
    "REQ INSP": "Active",
    "EXTENSIO": "Active",
    "ORDER": "Active",
    "CITATION": "Active",
    "24 HOUR": "Active",
    "72 HOUR": "Active",
    "NOTICE1": "Active",
    # In Review — application / plan check / hearing
    "APPLIED": "In Review",
    "PAID": "In Review",
    "PLAN CK": "In Review",
    "PLANCK": "In Review",
    "SUBMITTD": "In Review",
    "RECEIVED": "In Review",
    "COURTESY": "In Review",
    "PC": "In Review",
    "Pend-MCC": "In Review",
    "HEARING": "In Review",
    "REFERRED": "In Review",
    "SUSPEND": "In Review",
    # Inactive
    "EXPIRED": "Inactive",
    "VOID": "Inactive",
    "CANCEL": "Inactive",
    "WITHDRWN": "Inactive",
    "DENIED": "Inactive",
    "INVALID": "Inactive",
    "ABANDOND": "Inactive",
    "DUPLCATE": "Inactive",
    "UNFOUND": "Inactive",
}


def _expected_status(d: dict) -> Optional[str]:
    raw = d.get("permit_status")
    if not isinstance(raw, str) or not raw.strip():
        return None
    return _STATUS_MAP.get(raw.strip())


# ── Date extractors ──────────────────────────────────────────────────────────

def _status_issued_date(d: dict):
    """Earliest Status Date whose comment mentions ISSUED / JOB CARD."""
    dates = []
    for s in d.get("Status") or []:
        if not isinstance(s, dict):
            continue
        comment = str(s.get("Comment") or "").upper()
        if "ISSUED" not in comment and "JOB CARD" not in comment:
            continue
        dt = _safe_to_datetime(s.get("Status Date"))
        if dt is not pd.NaT:
            dates.append(dt)
    return min(dates) if dates else pd.NaT


def _status_approved_date(d: dict):
    """Earliest AP:Approved / AP :Approved Status Date."""
    dates = []
    for s in d.get("Status") or []:
        if not isinstance(s, dict):
            continue
        st = str(s.get("Status") or "")
        if not (st.startswith("AP:") or st.startswith("AP :")):
            continue
        dt = _safe_to_datetime(s.get("Status Date"))
        if dt is not pd.NaT:
            dates.append(dt)
    return min(dates) if dates else pd.NaT


def _first_payment_date(d: dict):
    dates = []
    for p in d.get("Payments") or []:
        if not isinstance(p, dict):
            continue
        if p.get("Payment Type") == "Void":
            continue
        dt = _safe_to_datetime(p.get("Payment Date"))
        if dt is not pd.NaT:
            dates.append(dt)
    return min(dates) if dates else pd.NaT


def _first_inspection_date(d: dict):
    dates = []
    for insp in d.get("Completed Inspections") or []:
        if not isinstance(insp, dict):
            continue
        dt = _safe_to_datetime(insp.get("Date"))
        if dt is not pd.NaT:
            dates.append(dt)
    return min(dates) if dates else pd.NaT


def _file_date_from_data(d: dict):
    return _safe_to_datetime(d.get("File Date"))


def _permit_date_from_data(d: dict):
    """Best available issuance / approval proxy.

    San Bernardino DATA has no dedicated issued-date field. Prefer explicit
    issuance notes in the Status workflow, then approval marks, then the
    earliest completed inspection (work implies issuance), then payment,
    then File Date as a last-resort OTC proxy.
    """
    for getter in (
        _status_issued_date,
        _status_approved_date,
        _first_inspection_date,
        _first_payment_date,
        _file_date_from_data,
    ):
        dt = getter(d)
        if dt is not pd.NaT:
            return dt
    return pd.NaT


def _inspection_is_final(insp: dict) -> bool:
    """Whether a Completed Inspections item counts as a finaling / close."""
    desc = str(insp.get("Inspection Description") or "")
    st = str(insp.get("Status") or "")
    comment = str(insp.get("Inspector's Comment") or "")

    # Explicit finaled result
    if st == "Approved: Finaled":
        return True

    approved = st.startswith("Approved")
    desc_u = desc.upper()
    comment_u = comment.upper()

    # Legacy BUILDING FINAL rows often have null Status — still usable.
    if "BUILDING FINAL" in desc_u and (approved or not st.strip()):
        return True

    if approved and _FINAL_DESC_RE.search(desc):
        return True

    # Fire finals sometimes put FINAL only in the inspector comment.
    if approved and "FIRE" in desc_u and "FINAL" in comment_u:
        return True

    # Code-compliance close-out (Status often null).
    if re.search(r"STAT\s+CLOSE|CLOSE\s+COMPLAINT", desc, re.IGNORECASE):
        return True

    return False


def _final_date_from_data(d: dict):
    """Latest usable finaling / close-out inspection date."""
    dates = []
    for insp in d.get("Completed Inspections") or []:
        if not isinstance(insp, dict):
            continue
        if not _inspection_is_final(insp):
            continue
        dt = _safe_to_datetime(insp.get("Date"))
        if dt is not pd.NaT:
            dates.append(dt)
    return max(dates) if dates else pd.NaT


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
    issued = _permit_date_from_data(d)
    if effective_status in ("Active", "Final") and issued is not pd.NaT:
        if pd.isna(row["PERMIT_DATE"]):
            repairs["PERMIT_DATE"] = issued
            repairs["PERMIT_DATE_FLAG"] = "FILLED"
        elif not _dates_equal(row["PERMIT_DATE"], issued):
            # Prefer Status ISSUED/JOB CARD or AP:Approved when present.
            canonical = _status_issued_date(d)
            if canonical is pd.NaT:
                canonical = _status_approved_date(d)
            if canonical is not pd.NaT and not _dates_equal(
                row["PERMIT_DATE"], canonical
            ):
                repairs["PERMIT_DATE"] = canonical
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
    elif not pd.isna(row["FINAL_DATE"]):
        repairs["FINAL_DATE"] = pd.NaT
        repairs["FINAL_DATE_FLAG"] = "FIXED"


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    San Bernardino permit records using information from the raw DATA JSON.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "San Bernardino".  Must contain
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
    from dotenv import load_dotenv, find_dotenv

    load_dotenv(find_dotenv())
    MY_DATA_PATH = os.getenv("MY_DATA_PATH")
    filepath = os.path.join(
        MY_DATA_PATH, "processed_data", "permits_ca_sample.parquet"
    )
    df = pd.read_parquet(filepath)
    city = df[df["JURISDICTION"] == "San Bernardino"].copy()

    print(f"San Bernardino records: {len(city):,}\n")

    repaired = data_repair(city)

    print("INFERRED_SCHEMA:")
    for s, c in repaired["INFERRED_SCHEMA"].value_counts(dropna=False).items():
        print(f"  {str(s):35s}: {c:>4,}")
    print()

    for field in ["STATUS_NORMALIZED", "FILE_DATE", "PERMIT_DATE", "FINAL_DATE"]:
        flag_col = f"{field}_FLAG"
        n_filled = (repaired[flag_col] == "FILLED").sum()
        n_fixed = (repaired[flag_col] == "FIXED").sum()
        print(f"{field}:")
        print(f"  FILLED: {n_filled:>4,}   FIXED: {n_fixed:>4,}")

        before_missing = city[field].isna().sum()
        after_missing = repaired[field].isna().sum()
        print(
            f"  Missing before: {before_missing:>4,}   "
            f"Missing after: {after_missing:>4,}"
        )
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
        pct = n_has / len(sub) if len(sub) else 0.0
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({pct:.1%})")

    print("\nFINAL_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FINAL_DATE"].notna().sum()
        pct = n_has / len(sub) if len(sub) else 0.0
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({pct:.1%})")

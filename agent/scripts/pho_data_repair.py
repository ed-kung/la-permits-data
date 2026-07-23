"""Phoenix-specific date and status extraction from the DATA column.

This module provides functions to extract PERMIT_DATE, FINAL_DATE, and
STATUS_NORMALIZED from the JSON stored in the DATA column for Phoenix, AZ
building-permit records.

Phoenix records use a "custom" schema (not Accela or Energov) with a flat
structure containing permit information from the City of Phoenix permitting
system.  All 1,992 records in the sample share the same schema family, but
~1,530 have an additional nested "permit" sub-object with richer fields.

Data structure overview:

  All records have these date-relevant top-level keys:
      issued      — DD-MMM-YYYY string (e.g. "20-AUG-2008"); the permit
                    issuance date.  Present in ~1,770/1,992 records.
      expires     — DD-MMM-YYYY string; permit expiration date.
      status      — Short code: DONE, OPEN, EXPR, VOID, CNCL, SHAP.

  ~1,530 records also have a "permit" sub-object with keys:
      IssuedDate     — Microsoft JSON date format "/Date(ms)/"
      Status         — Same short code as top-level status
      DatePosted     — Always null in sample
      DataSubmitted  — Always null in sample

  ~1,461 records have an "inspections" list of objects with:
      CompletedDate   — Microsoft JSON date format "/Date(ms)/"
      ScheduledDate   — Microsoft JSON date format "/Date(ms)/"
      InspectionType  — String like "999 FINAL FIRE INSPECTION"
      Result          — PASS, FAIL, PROGRESS, DUP REQ, etc.

Mapping logic (validated against records where values are already populated):

  FILE_DATE (application/submitted date):
    No application or submission date field exists in the Phoenix DATA
    structure.  FILE_DATE cannot be recovered from available data.

  PERMIT_DATE (approval/issued date):
    1. Top-level "issued" field (DD-MMM-YYYY)
       — Matches 100% of known PERMIT_DATE values (1,768/1,768 overlaps).
    2. permit.IssuedDate (/Date(ms)/ format)
       — Matches 100% of known PERMIT_DATE values where both present (1,332).
       — Provides additional coverage for 111 records missing "issued".

  FINAL_DATE (finalized/completion/signed-off date):
    Strategy: latest CompletedDate among inspections with Result == "PASS".
    — Matches 88.4% of known FINAL_DATE values (1,185/1,341 with PASS).
    — Fallback: latest CompletedDate from any inspection (83.2% accuracy).
    — Only meaningful for DONE-status records (non-DONE records shouldn't
      have a FINAL_DATE as they haven't been completed).

  STATUS_NORMALIZED:
    Mapping from DATA.status:
      DONE → "In Review"  (matches existing 1,268/1,269 = 99.9%)
      OPEN → "In Review"  (matches existing 209/209 = 100%)
      EXPR → "Inactive"   (matches existing 372/373 = 99.7%)
      VOID → "Inactive"   (matches existing 64/65 = 98.5%)
      CNCL → "Inactive"   (matches existing 1/1 = 100%)
      SHAP → "Active"     (tentative; all 75 SHAP records have missing
              STATUS_NORMALIZED; 47/75 have FINAL_DATE which suggests
              completed work, but no ground truth exists for validation)

Overall fill potential on the 1,992-record Phoenix sample:
    FILE_DATE       — 0% fillable (no source data)
    PERMIT_DATE     — 113/214 missing values fillable (52.8%)
    FINAL_DATE      — 18/90 DONE-status missing values fillable (20.0%)
                      (remaining 542 missing are non-DONE status = expected)
    STATUS_NORMALIZED — 75/75 missing values fillable (100%, tentative SHAP mapping)
"""

import json
import math
import re
from typing import Optional, Union

import pandas as pd


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_missing(data) -> bool:
    """Return True for None / NaN."""
    if data is None:
        return True
    if isinstance(data, float) and math.isnan(data):
        return True
    return False


def _safe_parse(data: Union[dict, str, None]) -> Optional[dict]:
    """Parse DATA to dict, returning None if missing or unparseable."""
    if _is_missing(data):
        return None
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except (json.JSONDecodeError, ValueError):
            return None
    if not isinstance(data, dict):
        return None
    return data


def _try_parse_date(value) -> Optional[pd.Timestamp]:
    """Attempt to parse a scalar value as a date; return None on failure."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return pd.to_datetime(value).normalize()
    except (ValueError, TypeError):
        return None


_MS_DATE_RE = re.compile(r"/Date\((-?\d+)\)/")


def _parse_ms_date(value) -> Optional[pd.Timestamp]:
    """Parse Microsoft JSON date format '/Date(milliseconds)/' to Timestamp."""
    if not isinstance(value, str):
        return None
    m = _MS_DATE_RE.match(value)
    if m:
        ms = int(m.group(1))
        return pd.Timestamp(ms, unit="ms").normalize()
    return None


def _parse_dmy(value) -> Optional[pd.Timestamp]:
    """Parse DD-MMM-YYYY format (e.g. '20-AUG-2008') to Timestamp."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return pd.to_datetime(value, format="%d-%b-%Y").normalize()
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Phoenix status mapping
# ---------------------------------------------------------------------------

# Mapping from DATA.status codes to STATUS_NORMALIZED values.
# Validated against existing STATUS_NORMALIZED values in the sample:
#   DONE -> In Review (99.9%), OPEN -> In Review (100%),
#   EXPR -> Inactive (99.7%), VOID -> Inactive (98.5%),
#   CNCL -> Inactive (100%), SHAP -> Active (tentative, no ground truth).
_PHO_STATUS_MAP = {
    "DONE": "In Review",
    "OPEN": "In Review",
    "EXPR": "Inactive",
    "VOID": "Inactive",
    "CNCL": "Inactive",
    "SHAP": "Active",
}


# ---------------------------------------------------------------------------
# Public API — Phoenix date/status extraction
# ---------------------------------------------------------------------------

def extract_pho_permit_date(data: Union[dict, str, None]) -> Optional[str]:
    """Extract the approval/issued date (PERMIT_DATE) for a Phoenix record.

    Searches the DATA column JSON using Phoenix-specific field mappings:
      1. Top-level "issued" field (DD-MMM-YYYY format)
      2. permit.IssuedDate (/Date(ms)/ format, fallback)

    Returns the raw date string if found, or None.
    """
    d = _safe_parse(data)
    if d is None:
        return None

    # Primary: top-level "issued" field (DD-MMM-YYYY)
    issued_val = d.get("issued")
    if issued_val and isinstance(issued_val, str):
        parsed = _parse_dmy(issued_val)
        if parsed is not None:
            return issued_val

    # Fallback: permit.IssuedDate (/Date(ms)/)
    permit_obj = d.get("permit")
    if isinstance(permit_obj, dict):
        issued_date = permit_obj.get("IssuedDate")
        if isinstance(issued_date, str):
            parsed = _parse_ms_date(issued_date)
            if parsed is not None:
                return issued_date

    return None


def extract_pho_final_date(data: Union[dict, str, None]) -> Optional[str]:
    """Extract the finalized/completion date (FINAL_DATE) for a Phoenix record.

    Uses the latest CompletedDate among inspections with Result == "PASS".
    Falls back to the latest CompletedDate from any inspection if no PASS
    results exist.

    Only intended for records with DATA.status == "DONE"; non-DONE records
    are not expected to have a FINAL_DATE.

    Strategy validation (on records with known FINAL_DATE):
      - Latest PASS CompletedDate matches 88.4% of known values.
      - Latest any CompletedDate matches 83.2% of known values.

    Returns the raw /Date(ms)/ string if found, or None.
    """
    d = _safe_parse(data)
    if d is None:
        return None

    # Only attempt for DONE-status records
    status = d.get("status")
    if status != "DONE":
        return None

    inspections = d.get("inspections")
    if not isinstance(inspections, list) or not inspections:
        return None

    latest_pass = None
    latest_pass_raw = None
    latest_any = None
    latest_any_raw = None

    for insp in inspections:
        if not isinstance(insp, dict):
            continue
        completed_raw = insp.get("CompletedDate")
        completed = _parse_ms_date(completed_raw)
        if completed is None:
            continue

        # Track latest overall
        if latest_any is None or completed > latest_any:
            latest_any = completed
            latest_any_raw = completed_raw

        # Track latest PASS
        if insp.get("Result") == "PASS":
            if latest_pass is None or completed > latest_pass:
                latest_pass = completed
                latest_pass_raw = completed_raw

    # Prefer latest PASS; fall back to latest any
    if latest_pass_raw is not None:
        return latest_pass_raw
    if latest_any_raw is not None:
        return latest_any_raw

    return None


def extract_pho_status(data: Union[dict, str, None]) -> Optional[str]:
    """Extract STATUS_NORMALIZED for a Phoenix record from DATA.status.

    Maps the short status codes in the DATA column to the four standard
    STATUS_NORMALIZED categories:
      DONE → "In Review"
      OPEN → "In Review"
      EXPR → "Inactive"
      VOID → "Inactive"
      CNCL → "Inactive"
      SHAP → "Active"  (tentative — no ground truth for validation)

    Returns the mapped status string, or None if no mapping exists.
    """
    d = _safe_parse(data)
    if d is None:
        return None

    status_code = d.get("status")
    if not isinstance(status_code, str):
        return None

    return _PHO_STATUS_MAP.get(status_code.upper())


# ---------------------------------------------------------------------------
# Batch fill function
# ---------------------------------------------------------------------------

def fill_pho_dates(df: pd.DataFrame) -> pd.DataFrame:
    """Fill missing PERMIT_DATE, FINAL_DATE, and STATUS_NORMALIZED for Phoenix.

    Operates on a DataFrame filtered to JURISDICTION == "Phoenix".
    Only fills values where the existing column is NaN/NaT/None.

    Note: FILE_DATE cannot be filled — no application/submission date exists
    in the Phoenix DATA structure.

    Parameters
    ----------
    df : pd.DataFrame
        Must contain columns DATA, PERMIT_DATE, FINAL_DATE, STATUS_NORMALIZED.

    Returns
    -------
    pd.DataFrame
        Copy of *df* with missing values filled where possible.  Additional
        boolean columns track which values were imputed:
        PERMIT_DATE_FILLED, FINAL_DATE_FILLED, STATUS_NORMALIZED_FILLED.
    """
    out = df.copy()

    # Fill PERMIT_DATE
    permit_missing = out["PERMIT_DATE"].isna()
    if permit_missing.any():
        extracted = out.loc[permit_missing, "DATA"].apply(extract_pho_permit_date)
        parsed = extracted.apply(
            lambda v: (
                _parse_dmy(v)
                if isinstance(v, str) and not v.startswith("/")
                else _parse_ms_date(v) if isinstance(v, str) else None
            )
        )
        out.loc[permit_missing, "PERMIT_DATE"] = parsed
        out["PERMIT_DATE_FILLED"] = False
        out.loc[permit_missing & parsed.notna(), "PERMIT_DATE_FILLED"] = True
    else:
        out["PERMIT_DATE_FILLED"] = False

    # Fill FINAL_DATE
    final_missing = out["FINAL_DATE"].isna()
    if final_missing.any():
        extracted = out.loc[final_missing, "DATA"].apply(extract_pho_final_date)
        parsed = extracted.apply(
            lambda v: _parse_ms_date(v) if isinstance(v, str) else None
        )
        out.loc[final_missing, "FINAL_DATE"] = parsed
        out["FINAL_DATE_FILLED"] = False
        out.loc[final_missing & parsed.notna(), "FINAL_DATE_FILLED"] = True
    else:
        out["FINAL_DATE_FILLED"] = False

    # Fill STATUS_NORMALIZED
    status_missing = out["STATUS_NORMALIZED"].isna()
    if status_missing.any():
        extracted = out.loc[status_missing, "DATA"].apply(extract_pho_status)
        out.loc[status_missing, "STATUS_NORMALIZED"] = extracted
        out["STATUS_NORMALIZED_FILLED"] = False
        out.loc[status_missing & extracted.notna(), "STATUS_NORMALIZED_FILLED"] = True
    else:
        out["STATUS_NORMALIZED_FILLED"] = False

    return out

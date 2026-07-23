"""Philadelphia-specific date and status extraction from the DATA column.

This module provides functions to extract FILE_DATE, PERMIT_DATE, FINAL_DATE,
and STATUS_NORMALIZED from the JSON stored in the DATA column for Philadelphia
building-permit records.

Philadelphia records come from two underlying systems and appear in three
DATA sub-schemas:

  Sub-schema A ("POSSE / HANSEN" — flat, upper- or lower-case keys):
      Key identifiers: PERMITISSUEDATE / permitissuedate
      ~79% of Philly records (1,574 / 1,998 in sample).
      Contains PERMITISSUEDATE, PERMITCOMPLETEDDATE,
      CERTIFICATEOFOCCUPANCYDATE, STATUS.
      SYSTEMOFRECORD is "HANSEN" or "ECLIPSE".

  Sub-schema B ("Eclipse — detailed", with Title Case keys):
      Key identifiers: top-level "Status", "Created Date", "Issued Date"
      ~18% of Philly records (355 / 1,998 in sample).
      Contains Created Date, Issued Date, Completed Date,
      Construction Completed Date, Status, plus an "Other Information"
      sub-dict that mirrors the top-level dates.

  Sub-schema C ("Eclipse — flat detail", no top-level "Status"):
      Key identifiers: IssueDate or StatusDescription, but no "Status" key.
      ~3% of Philly records (69 / 1,998 in sample).
      Contains IssueDate, CompletedDate, ExpirationDate,
      StatusDescription (format: "Status \\n date"), Inspection list.

Mapping logic (validated against records where values are already populated):

  FILE_DATE (application/submitted date):
    A → No application/submission date field exists.
    B → "Created Date"  (validated: 354/354 = 100% match)
    C → No application/submission date field exists.
    Overall: FILE_DATE cannot be recovered for 82.3% of records (POSSE +
    flat_detail schemas lack an application date). Only Eclipse records have
    "Created Date", but the 1 Eclipse record with missing FILE_DATE also has
    an empty "Created Date".
    ⇒ 0 / 1,644 missing FILE_DATEs fillable (0%).

  PERMIT_DATE (approval/issued date):
    A → PERMITISSUEDATE / permitissuedate
        (validated: 1,573/1,573 = 100% match)
    B → "Issued Date"
        (validated: 347/347 = 100% match)
    C → IssueDate
        (no overlap for validation — all 69 records have missing PERMIT_DATE.
         IssueDate is present in 67/69 records.)
    ⇒ 67 / 78 missing PERMIT_DATEs fillable (85.9%).

  FINAL_DATE (finalized/completion/signed-off date):
    A → PERMITCOMPLETEDDATE / permitcompleteddate
        (validated: 1,348/1,348 = 100% match)
        226 POSSE records have missing FINAL_DATE; all have empty
        PERMITCOMPLETEDDATE → 0 fillable.
    B → "Completed Date"
        (validated: 255/255 = 100% match)
        100 Eclipse records have missing FINAL_DATE; 9 have a non-empty
        Completed Date → 9 fillable.
    C → CompletedDate
        (validated: 34/34 = 100% match for records with existing FINAL_DATE)
        35 flat_detail records have missing FINAL_DATE; all have empty
        CompletedDate → 0 fillable.
    ⇒ 9 / 361 missing FINAL_DATEs fillable (2.5%).

  STATUS_NORMALIZED:
    A → DATA.STATUS / DATA.status, mapped via _PHI_POSSE_STATUS_MAP.
        (validated: 1,573/1,573 = 100% match after correcting CLOSED → Final)
        1 missing → 1 fillable.
    B → DATA."Status", mapped via _PHI_ECLIPSE_STATUS_MAP.
        (validated: 344/354 = 97.2% match; 10 mismatches are stale statuses
         where the existing STATUS_NORMALIZED was "Active" but DATA.Status
         had since changed to "Completed" or "Expired")
        1 missing → 1 fillable.
    C → First word of DATA.StatusDescription, mapped via
        _PHI_FLAT_STATUS_MAP.
        (no overlap for validation — all 69 records missing STATUS_NORMALIZED)
        69 missing → 69 fillable.
    ⇒ 71 / 71 missing STATUS_NORMALIZEDs fillable (100%).
"""

import json
import math
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
    """Attempt to parse a scalar value as a date; return None on failure.

    Normalizes to midnight and strips timezone info so that values with
    baked-in UTC offsets (e.g. "2022/03/15 00:00:00+00") compare equal
    to tz-naive date-only strings.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        ts = pd.to_datetime(value)
        if ts.tz is not None:
            ts = ts.tz_localize(None)
        return ts.normalize()
    except (ValueError, TypeError):
        return None


def _classify_phi_schema(d: dict) -> str:
    """Classify a parsed Philadelphia DATA dict into its sub-schema.

    Returns one of: 'posse', 'eclipse', 'flat_detail', or 'unknown'.
    """
    keys = set(d.keys())
    keys_lower = {k.lower() for k in keys}

    if "permitissuedate" in keys_lower:
        return "posse"
    if "Status" in keys and ("Created Date" in keys or "Issued Date" in keys):
        return "eclipse"
    if "IssueDate" in keys or "StatusDescription" in keys:
        return "flat_detail"
    return "unknown"


# ---------------------------------------------------------------------------
# Philadelphia status mappings
# ---------------------------------------------------------------------------

# POSSE / HANSEN schema — STATUS field (upper or mixed case).
# Validated against existing STATUS_NORMALIZED values:
#   COMPLETED/Completed → Final (100%), Issued → Active (100%),
#   EXPIRED/Expired → Inactive (100%), CLOSED → Final (100%),
#   ABANDONED → Inactive, REVOKED → Inactive, Cancelled → Inactive,
#   Denied → Inactive.
#   "Amendment Application Incomplete" → In Review (tentative; no ground
#   truth in sample — 1 record with missing STATUS_NORMALIZED).
_PHI_POSSE_STATUS_MAP = {
    "COMPLETED": "Final",
    "Completed": "Final",
    "completed": "Final",
    "Issued": "Active",
    "issued": "Active",
    "EXPIRED": "Inactive",
    "Expired": "Inactive",
    "expired": "Inactive",
    "CLOSED": "Final",
    "closed": "Final",
    "ABANDONED": "Inactive",
    "abandoned": "Inactive",
    "REVOKED": "Inactive",
    "revoked": "Inactive",
    "Cancelled": "Inactive",
    "cancelled": "Inactive",
    "CANCELLED": "Inactive",
    "Denied": "Inactive",
    "denied": "Inactive",
    "DENIED": "Inactive",
    "Amendment Application Incomplete": "In Review",
    "amendment application incomplete": "In Review",
}

# Eclipse detailed schema — "Status" field.
# Validated: Completed → Final (97.2%), Issued → Active (100%),
# Expired → Inactive (93.8%), Ready For Issue → In Review (100%),
# Stop Work → In Review (100%), Withdrawn → Inactive (100%).
# "Amendment Applicant Revisions" → In Review (tentative; 1 record,
# no ground truth).
_PHI_ECLIPSE_STATUS_MAP = {
    "Completed": "Final",
    "Issued": "Active",
    "Expired": "Inactive",
    "Ready For Issue": "In Review",
    "Stop Work": "In Review",
    "Withdrawn": "Inactive",
    "Amendment Applicant Revisions": "In Review",
}

# Flat detail schema — first word of StatusDescription.
# No ground truth for validation (all 69 records have missing
# STATUS_NORMALIZED). Mapping inferred from the Eclipse status map
# which uses the same status vocabulary.
_PHI_FLAT_STATUS_MAP = {
    "Completed": "Final",
    "Issued": "Active",
    "Expired": "Inactive",
    "Ready": "In Review",       # "Ready For Issue ..."
    "Withdrawn": "Inactive",
    "Stop": "In Review",        # "Stop Work ..."
}


# ---------------------------------------------------------------------------
# Public API — Philadelphia date/status extraction
# ---------------------------------------------------------------------------

def extract_phi_file_date(data: Union[dict, str, None]) -> Optional[str]:
    """Extract the application/submitted date (FILE_DATE) for a Philadelphia record.

    Only the Eclipse detailed schema (sub-schema B) contains an application
    date ("Created Date").  POSSE and flat_detail schemas lack this field.

    Returns the raw date string if found, or None.
    """
    d = _safe_parse(data)
    if d is None:
        return None

    schema = _classify_phi_schema(d)

    if schema == "eclipse":
        val = d.get("Created Date")
        if _try_parse_date(val) is not None:
            return val

    return None


def extract_phi_permit_date(data: Union[dict, str, None]) -> Optional[str]:
    """Extract the approval/issued date (PERMIT_DATE) for a Philadelphia record.

    Searches the DATA column JSON using Philadelphia-specific field mappings:
      POSSE:       PERMITISSUEDATE / permitissuedate
      Eclipse:     "Issued Date"
      Flat detail: IssueDate

    Returns the raw date string if found, or None.
    """
    d = _safe_parse(data)
    if d is None:
        return None

    schema = _classify_phi_schema(d)

    if schema == "posse":
        val = d.get("PERMITISSUEDATE") or d.get("permitissuedate")
        if _try_parse_date(val) is not None:
            return val

    elif schema == "eclipse":
        val = d.get("Issued Date")
        if _try_parse_date(val) is not None:
            return val

    elif schema == "flat_detail":
        val = d.get("IssueDate")
        if _try_parse_date(val) is not None:
            return val

    return None


def extract_phi_final_date(data: Union[dict, str, None]) -> Optional[str]:
    """Extract the finalized/completion date (FINAL_DATE) for a Philadelphia record.

    Searches the DATA column JSON using Philadelphia-specific field mappings:
      POSSE:       PERMITCOMPLETEDDATE / permitcompleteddate
      Eclipse:     "Completed Date"
      Flat detail: CompletedDate

    Returns the raw date string if found, or None.
    """
    d = _safe_parse(data)
    if d is None:
        return None

    schema = _classify_phi_schema(d)

    if schema == "posse":
        val = d.get("PERMITCOMPLETEDDATE") or d.get("permitcompleteddate")
        if _try_parse_date(val) is not None:
            return val

    elif schema == "eclipse":
        val = d.get("Completed Date")
        if _try_parse_date(val) is not None:
            return val

    elif schema == "flat_detail":
        val = d.get("CompletedDate")
        if _try_parse_date(val) is not None:
            return val

    return None


def extract_phi_status(data: Union[dict, str, None]) -> Optional[str]:
    """Extract STATUS_NORMALIZED for a Philadelphia record from the DATA column.

    Uses schema-specific status fields and mappings:
      POSSE:       DATA.STATUS / DATA.status → _PHI_POSSE_STATUS_MAP
      Eclipse:     DATA."Status"             → _PHI_ECLIPSE_STATUS_MAP
      Flat detail: first word of DATA.StatusDescription → _PHI_FLAT_STATUS_MAP

    Returns the mapped status string ('Active', 'Final', 'In Review',
    'Inactive'), or None if no mapping exists.
    """
    d = _safe_parse(data)
    if d is None:
        return None

    schema = _classify_phi_schema(d)

    if schema == "posse":
        status_code = d.get("STATUS") or d.get("status")
        if isinstance(status_code, str):
            return _PHI_POSSE_STATUS_MAP.get(status_code)

    elif schema == "eclipse":
        status_code = d.get("Status")
        if isinstance(status_code, str):
            return _PHI_ECLIPSE_STATUS_MAP.get(status_code)

    elif schema == "flat_detail":
        status_desc = d.get("StatusDescription", "")
        if isinstance(status_desc, str):
            first_word = status_desc.strip().split()[0] if status_desc.strip() else None
            if first_word:
                return _PHI_FLAT_STATUS_MAP.get(first_word)

    return None


# ---------------------------------------------------------------------------
# Batch fill function
# ---------------------------------------------------------------------------

def fill_phi_dates(df: pd.DataFrame) -> pd.DataFrame:
    """Fill missing FILE_DATE, PERMIT_DATE, FINAL_DATE, STATUS_NORMALIZED for Philadelphia.

    Operates on a DataFrame filtered to JURISDICTION == "Philadelphia".
    Only fills values where the existing column is NaN/NaT/None.

    Parameters
    ----------
    df : pd.DataFrame
        Must contain columns DATA, FILE_DATE, PERMIT_DATE, FINAL_DATE,
        STATUS_NORMALIZED.

    Returns
    -------
    pd.DataFrame
        Copy of *df* with missing values filled where possible.  Additional
        boolean columns track which values were imputed:
        FILE_DATE_FILLED, PERMIT_DATE_FILLED, FINAL_DATE_FILLED,
        STATUS_NORMALIZED_FILLED.
    """
    out = df.copy()

    # Fill date columns
    for col, extractor in [
        ("FILE_DATE", extract_phi_file_date),
        ("PERMIT_DATE", extract_phi_permit_date),
        ("FINAL_DATE", extract_phi_final_date),
    ]:
        was_missing = out[col].isna()
        if not was_missing.any():
            out[f"{col}_FILLED"] = False
            continue
        extracted = out.loc[was_missing, "DATA"].apply(extractor)
        extracted_parsed = extracted.apply(
            lambda v: _try_parse_date(v) if v is not None else None
        )
        extracted_parsed = pd.to_datetime(extracted_parsed, errors="coerce")
        out.loc[was_missing, col] = extracted_parsed
        out[f"{col}_FILLED"] = False
        out.loc[was_missing & extracted_parsed.notna(), f"{col}_FILLED"] = True

    # Fill STATUS_NORMALIZED
    status_missing = out["STATUS_NORMALIZED"].isna()
    if status_missing.any():
        extracted = out.loc[status_missing, "DATA"].apply(extract_phi_status)
        out.loc[status_missing, "STATUS_NORMALIZED"] = extracted
        out["STATUS_NORMALIZED_FILLED"] = False
        out.loc[status_missing & extracted.notna(), "STATUS_NORMALIZED_FILLED"] = True
    else:
        out["STATUS_NORMALIZED_FILLED"] = False

    return out

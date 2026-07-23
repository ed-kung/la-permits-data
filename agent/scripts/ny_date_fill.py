"""New York–specific date extraction from the DATA column.

This module provides functions to extract FILE_DATE, PERMIT_DATE, and
FINAL_DATE from the JSON stored in the DATA column for New York City
building-permit records.

New York records use a "custom" schema (not Accela or Energov) and contain
three distinct DATA sub-schemas from different NYC DOB data sources:

  Sub-schema A ("DOB NOW / BIS filings+issuances"):
      Top-level keys: {filings, issuances}
      ~63% of NY records (1,263 / 2,000 in sample).

  Sub-schema B ("DOB NOW / BIS filing+permits"):
      Top-level keys: {filing, permits}
      ~22% of NY records (446 / 2,000 in sample).

  Sub-schema C ("Electrical permits / flat"):
      Top-level keys include filing_date, permit_issued_date,
      completion_date, job_start_date, and many flat fields.
      ~15% of NY records (291 / 2,000 in sample).

Mapping logic (validated against records where dates are already populated):

  FILE_DATE (application/submitted date):
    A → filings[0].pre__filing_date    (matches 57.8% of known FILE_DATEs)
    B → filing.filing_date             (matches 24.4%)
    C → filing_date                    (matches 16.7%)
    Fallback → issuances[INITIAL earliest].filing_date  (catches 4.5%)

  PERMIT_DATE (approval/issued date):
    A → filings[0].fully_permitted     (matches 59.0% of known PERMIT_DATEs)
    A/B fallback → issuances[INITIAL earliest].issuance_date (33.1%)
    C → permit_issued_date             (matches 19.7%)
    B → filing.permit_issue_date       (3.7%)
    B → permits[0].issued_date         (0.7%)

  FINAL_DATE (finalized/completion/signed-off date):
    A → filings[0].signoff_date        (29.8% of all records; 82.9% of Final)
    B → filing.current_status_date     (when filing_status indicates completion,
        e.g. "LOC Issued", "Certificate of Operation Issued")
    C → completion_date                (14.5% of all records)

Overall coverage validated on the 2,000-record NY sample:
    FILE_DATE  – 98.9% of known values matched by candidates.
    PERMIT_DATE – 83.1% of known values matched by candidates.
    FINAL_DATE – no existing values to validate (100% missing in sample),
                 but candidates available for 44.4% of records.
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

    Normalizes to midnight so that values with baked-in UTC offsets
    (e.g. "2022-10-03T04:00:00.000") compare equal to date-only strings.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return pd.to_datetime(value).normalize()
    except (ValueError, TypeError):
        return None


def _earliest_initial_issuance(issuances: list, field: str) -> Optional[str]:
    """Return *field* from the earliest INITIAL issuance entry, or None."""
    initials = [
        entry for entry in issuances
        if isinstance(entry, dict) and entry.get("filing_status") == "INITIAL"
    ]
    if not initials:
        return None

    best_date = None
    best_value = None
    for entry in initials:
        val = entry.get(field)
        parsed = _try_parse_date(val)
        if parsed is not None:
            if best_date is None or parsed < best_date:
                best_date = parsed
                best_value = val
    return best_value


# ---------------------------------------------------------------------------
# Public API — New York date extraction
# ---------------------------------------------------------------------------

def extract_ny_file_date(data: Union[dict, str, None]) -> Optional[str]:
    """Extract the application/submitted date (FILE_DATE) for a New York record.

    Searches the DATA column JSON using New York–specific field mappings:
      1. filings[0].pre__filing_date  (DOB filings+issuances schema)
      2. filing.filing_date           (DOB filing+permits schema)
      3. Top-level filing_date        (Electrical permits schema)
      4. issuances[INITIAL earliest].filing_date  (fallback)

    Returns the raw date string if found, or None.
    """
    d = _safe_parse(data)
    if d is None:
        return None

    # Sub-schema A: filings[].pre__filing_date
    if "filings" in d and isinstance(d["filings"], list):
        for filing in d["filings"]:
            if isinstance(filing, dict) and filing.get("pre__filing_date"):
                if _try_parse_date(filing["pre__filing_date"]) is not None:
                    return filing["pre__filing_date"]
                break

    # Sub-schema B: filing.filing_date
    if "filing" in d and isinstance(d["filing"], dict):
        val = d["filing"].get("filing_date")
        if _try_parse_date(val) is not None:
            return val

    # Sub-schema C: top-level filing_date
    if "filing_date" in d and not isinstance(d["filing_date"], (dict, list)):
        if _try_parse_date(d["filing_date"]) is not None:
            return d["filing_date"]

    # Fallback: earliest INITIAL issuance filing_date
    if "issuances" in d and isinstance(d["issuances"], list):
        val = _earliest_initial_issuance(d["issuances"], "filing_date")
        if val is not None:
            return val

    return None


def extract_ny_permit_date(data: Union[dict, str, None]) -> Optional[str]:
    """Extract the approval/issued date (PERMIT_DATE) for a New York record.

    Searches the DATA column JSON using New York–specific field mappings:
      1. filings[0].fully_permitted                 (DOB filings+issuances schema)
      1b. filings[0].approved                       (fallback when fully_permitted absent)
      2. permits[Initial Permit].approved_date      (DOB filing+permits schema)
      3. permit_issued_date                         (Electrical permits schema)
      4. filing.permit_issue_date                   (DOB filing+permits fallback)
      5. issuances[INITIAL earliest].issuance_date  (fallback)

    Returns the raw date string if found, or None.
    """
    d = _safe_parse(data)
    if d is None:
        return None

    # Sub-schema A: filings[].fully_permitted, falling back to approved
    # fully_permitted is the full permit-issuance date; approved is the
    # plan-exam approval date (an earlier step).  When fully_permitted is
    # absent the permit was approved but not yet fully issued, so approved
    # is the best available proxy for PERMIT_DATE.
    if "filings" in d and isinstance(d["filings"], list):
        for filing in d["filings"]:
            if not isinstance(filing, dict):
                continue
            if filing.get("fully_permitted"):
                if _try_parse_date(filing["fully_permitted"]) is not None:
                    return filing["fully_permitted"]
            if filing.get("approved"):
                if _try_parse_date(filing["approved"]) is not None:
                    return filing["approved"]
            break

    # Sub-schema B: permits[Initial Permit].approved_date takes priority
    # In the filing+permits schema, PERMIT_DATE maps to approved_date (not
    # issued_date) on the entry with filing_reason == "Initial Permit".
    if "permits" in d and isinstance(d["permits"], list):
        for permit in d["permits"]:
            if isinstance(permit, dict) and permit.get("filing_reason") == "Initial Permit":
                val = permit.get("approved_date")
                if _try_parse_date(val) is not None:
                    return val

    # Sub-schema C: top-level permit_issued_date
    if "permit_issued_date" in d and not isinstance(d["permit_issued_date"], (dict, list)):
        if _try_parse_date(d["permit_issued_date"]) is not None:
            return d["permit_issued_date"]

    # Sub-schema B fallback: filing.permit_issue_date
    if "filing" in d and isinstance(d["filing"], dict):
        val = d["filing"].get("permit_issue_date")
        if _try_parse_date(val) is not None:
            return val

    # Sub-schema B fallback: permits[].issued_date (any entry)
    if "permits" in d and isinstance(d["permits"], list):
        for permit in d["permits"]:
            if isinstance(permit, dict) and permit.get("issued_date"):
                if _try_parse_date(permit["issued_date"]) is not None:
                    return permit["issued_date"]
                break

    # Fallback: earliest INITIAL issuance issuance_date
    if "issuances" in d and isinstance(d["issuances"], list):
        val = _earliest_initial_issuance(d["issuances"], "issuance_date")
        if val is not None:
            return val

    return None


# Filing statuses in the filing+permits sub-schema (B) that indicate the
# permit has reached a final/completed state.  "LOC" = Letter of Completion.
_NY_COMPLETION_STATUSES = frozenset({
    "LOC Issued",
    "TA Certificate of Operation Issued",
    "PA Certificate of Operation Issued",
})


def extract_ny_final_date(data: Union[dict, str, None]) -> Optional[str]:
    """Extract the finalized/signed-off date (FINAL_DATE) for a New York record.

    Searches the DATA column JSON using New York–specific field mappings:
      1. filings[0].signoff_date               (DOB filings+issuances schema)
      2. filing.current_status_date             (DOB filing+permits schema,
         only when filing.filing_status indicates completion — e.g.
         "LOC Issued" = Letter of Completion)
      3. completion_date                        (Electrical permits schema)

    Returns the raw date string if found, or None.

    Note: signoff_date appears almost exclusively on records whose
    job_status_descrp is "SIGNED OFF" or "COMPLETED". It is present
    for ~83% of records with STATUS_NORMALIZED == "Final" and rarely
    for non-final records (where it may represent a partial sign-off).
    """
    d = _safe_parse(data)
    if d is None:
        return None

    # Sub-schema A: filings[].signoff_date
    if "filings" in d and isinstance(d["filings"], list):
        for filing in d["filings"]:
            if isinstance(filing, dict) and filing.get("signoff_date"):
                if _try_parse_date(filing["signoff_date"]) is not None:
                    return filing["signoff_date"]
                break

    # Sub-schema B: filing.current_status_date when status indicates completion
    if "filing" in d and isinstance(d["filing"], dict):
        filing_status = d["filing"].get("filing_status", "")
        if filing_status in _NY_COMPLETION_STATUSES:
            val = d["filing"].get("current_status_date")
            if _try_parse_date(val) is not None:
                return val

    # Sub-schema C: top-level completion_date
    if "completion_date" in d and not isinstance(d["completion_date"], (dict, list)):
        if _try_parse_date(d["completion_date"]) is not None:
            return d["completion_date"]

    return None


def fill_ny_dates(df: pd.DataFrame) -> pd.DataFrame:
    """Fill missing FILE_DATE, PERMIT_DATE, FINAL_DATE for New York records.

    Operates on a DataFrame filtered to JURISDICTION == "New York".
    Only fills values where the existing column is NaN/NaT.

    Parameters
    ----------
    df : pd.DataFrame
        Must contain columns DATA, FILE_DATE, PERMIT_DATE, FINAL_DATE.

    Returns
    -------
    pd.DataFrame
        Copy of *df* with missing dates filled where possible. Three
        additional boolean columns are added to track which values were
        imputed: FILE_DATE_FILLED, PERMIT_DATE_FILLED, FINAL_DATE_FILLED.
    """
    out = df.copy()

    for col, extractor in [
        ("FILE_DATE", extract_ny_file_date),
        ("PERMIT_DATE", extract_ny_permit_date),
        ("FINAL_DATE", extract_ny_final_date),
    ]:
        was_missing = out[col].isna()
        extracted = out.loc[was_missing, "DATA"].apply(extractor)
        extracted_parsed = pd.to_datetime(extracted, errors="coerce", format="mixed")
        out.loc[was_missing, col] = extracted_parsed
        out[f"{col}_FILLED"] = False
        out.loc[was_missing & extracted_parsed.notna(), f"{col}_FILLED"] = True

    return out

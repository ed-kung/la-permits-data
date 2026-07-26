"""Data repair for Eureka (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Eureka DATA is an OpenGov / SmartGov-style payload with top-level keys
``main``, ``extra``, and ``location``.  ``extra`` uses several
sub-schemas depending on record type:

  - named_extra:           string keys STATUS, APPLIED, ISSUED, FINALED, …
  - building_legacy:       numeric keys ~23692–23888 (Legacy Building Permit)
  - encroachment_legacy:   numeric keys ~23475–23507
  - code_enforcement_legacy
  - utility_legacy
  - design_review_legacy
  - variance_legacy
  - home_occupation_legacy
  - business_license_legacy
  - public_works_legacy
  - form_extra:            modern form fields without legacy date IDs
  - empty_extra

Canonical mappings:
  - main.status (-1/0/1/2) → STATUS_NORMALIZED; when null, fall back to
    OpenGov / legacy STATUS strings in extra
  - main.dateSubmitted (else dateCreated / APPLIED) → FILE_DATE
  - ISSUED / schema-specific issue keys → PERMIT_DATE
  - FINALED / schema-specific final keys → FINAL_DATE

Known issues repaired:
  - 53 rows with null main.status / STATUS_NORMALIZED → FILLED from extra
    status strings (Stopped/EXPIRED/CANCELLED/Closed/…).
  - FILE_DATE was taken from dateCreated; when dateSubmitted falls on a
    later calendar day (~24 rows) → FIXED to the submittal date.
  - PERMIT_DATE and FINAL_DATE are universally missing in the sample;
    fill from ISSUED/FINALED (and legacy numeric equivalents) where
    present.  Reject sentinel final dates (1950-01-01, bulk
    2022-02-22 / 2022-09-01 migration stamps, implausible years).

Not repairable / left as-is:
  - Modern form_extra / empty_extra Active & Final rows often lack any
    issuance or finaling timestamp → PERMIT_DATE / FINAL_DATE stay
    missing.
  - Encroachment Final rows usually lack a distinct final date beyond
    the issue/complete field used as a proxy when clearly post-file.
"""

from __future__ import annotations

import json
import math
from datetime import date, datetime
from typing import Optional

import numpy as np
import pandas as pd


_MIN_YEAR = 1980
_MAX_YEAR = 2035

# Bulk migration / placeholder stamps observed in FINALED / 23703.
_SENTINEL_DATES = {
    date(1950, 1, 1),
    date(2022, 2, 22),
    date(2022, 9, 1),
}


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
    # Normalize tz-aware values to naive UTC midnight for comparisons.
    if getattr(dt, "tzinfo", None) is not None:
        dt = dt.tz_convert("UTC").tz_localize(None)
    year = int(dt.year)
    if year < _MIN_YEAR or year > _MAX_YEAR:
        return pd.NaT
    return dt


def _utc_date(val) -> Optional[date]:
    """Parse a timestamp and return its UTC calendar date."""
    if val is None or (isinstance(val, str) and not str(val).strip()):
        return None
    try:
        ts = pd.to_datetime(val, utc=True)
    except (ValueError, TypeError):
        return None
    if pd.isna(ts):
        return None
    return ts.date()


def _as_date(val) -> Optional[date]:
    """Normalize a FILE_DATE-like value to datetime.date."""
    if _is_missing(val):
        return None
    if isinstance(val, date) and not isinstance(val, datetime):
        return val
    dt = _safe_to_datetime(val)
    if dt is pd.NaT:
        return None
    return dt.date()


def _dates_equal(a, b) -> bool:
    da = _as_date(a)
    db = _as_date(b)
    if da is None or db is None:
        return False
    return da == db


def _extra(d: dict) -> dict:
    extra = d.get("extra")
    return extra if isinstance(extra, dict) else {}


def _main(d: dict) -> dict:
    main = d.get("main")
    return main if isinstance(main, dict) else {}


def _first_date(extra: dict, keys) -> pd.Timestamp:
    for key in keys:
        dt = _safe_to_datetime(extra.get(key))
        if dt is not pd.NaT:
            return dt
    return pd.NaT


def _plausible_final(dt, file_date) -> bool:
    """Reject sentinel stamps and finals that precede FILE_DATE."""
    if dt is pd.NaT:
        return False
    d = dt.date()
    if d in _SENTINEL_DATES:
        return False
    fd = _as_date(file_date)
    if fd is not None and d < fd:
        return False
    return True


# ── Schema classification ───────────────────────────────────────────────────

def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    if not isinstance(data_dict, dict) or "main" not in data_dict:
        return "unknown"

    extra = _extra(data_dict)
    if not extra:
        return "empty_extra"
    if "STATUS" in extra or "APPLIED" in extra or "ISSUED" in extra:
        return "named_extra"
    if "23723" in extra or "23888" in extra:
        return "building_legacy"
    if "23507" in extra or "23492" in extra:
        return "encroachment_legacy"
    if "25107" in extra or "25094" in extra:
        return "code_enforcement_legacy"
    if "24254" in extra or "24239" in extra:
        return "utility_legacy"
    if "25745" in extra or "25728" in extra:
        return "design_review_legacy"
    if "34788" in extra or "34772" in extra:
        return "variance_legacy"
    if "29573" in extra or "29558" in extra:
        return "home_occupation_legacy"
    if "26328" in extra or "26314" in extra:
        return "business_license_legacy"
    if "36898" in extra:
        return "public_works_legacy"
    return "form_extra"


# ── Status mapping ──────────────────────────────────────────────────────────

_STATUS_CODE_MAP = {
    0: "In Review",   # draft
    1: "Active",      # active
    2: "Final",       # complete
    -1: "Inactive",   # stopped
}

# OpenGov Status / numeric OpenGov counterparts
_OPENGOV_MAP = {
    "complete": "Final",
    "active": "Active",
    "stop": "Inactive",
    "stopped": "Inactive",
    "draft": "In Review",
}

# Legacy STATUS / permit-status strings
_LEGACY_STATUS_MAP = {
    "finaled": "Final",
    "closed": "Final",
    "case closed": "Final",
    "approved": "Final",
    "approved w/cond": "Final",
    "issued": "Active",
    "active": "Active",
    "under review": "In Review",
    "expired": "Inactive",
    "void": "Inactive",
    "cancelled": "Inactive",
    "canceled": "Inactive",
    "dead file": "Inactive",
    "withdrawn": "Inactive",
    "refunded": "Inactive",
    "inactive": "Inactive",
    "denied": "Inactive",
    "<none>": "Inactive",
}

# Keys that may hold a legacy / OpenGov status string in extra.
_STATUS_VALUE_KEYS = (
    "OpenGov Status",
    "STATUS",
    "23888",
    "23492",
    "25094",
    "25728",
    "26314",
    "29558",
    "34772",
    "24239",
    "36898",
    "23723",
    "23507",
    "25107",
    "25745",
    "26328",
    "29573",
    "34788",
    "24254",
    # Misc legacy planning / contact status fields seen on null-main rows
    "29481",
    "29492",
    "31803",
    "26572",
    "26589",
    "34494",
    "34508",
    "29741",
    "29754",
)


def _status_from_code(main: dict) -> Optional[str]:
    status = main.get("status")
    if status is None:
        return None
    try:
        code = int(status)
    except (TypeError, ValueError):
        return None
    return _STATUS_CODE_MAP.get(code)


def _map_status_string(raw) -> Optional[str]:
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    # "Building" under 23888 is a corrupted PermitType bleed, not a status.
    if s.lower() == "building":
        return None
    low = s.lower()
    if low in _OPENGOV_MAP:
        return _OPENGOV_MAP[low]
    if low in _LEGACY_STATUS_MAP:
        return _LEGACY_STATUS_MAP[low]
    return None


def _status_from_extra(extra: dict) -> Optional[str]:
    """Derive STATUS_NORMALIZED from extra when main.status is absent.

    Prefer OpenGov lifecycle strings, then legacy STATUS codes.  "Closed"
    without supporting final evidence is treated as Inactive (abandoned
    shell) rather than Final.
    """
    # Pass 1: OpenGov-style keys
    for key in (
        "OpenGov Status",
        "23888",
        "23492",
        "25094",
        "25728",
        "26314",
        "29558",
        "34772",
        "24239",
        "36898",
        "29481",
        "31803",
        "26572",
        "34494",
        "29741",
    ):
        mapped = _map_status_string(extra.get(key))
        if mapped is not None:
            # Stopped/Complete/Active from OpenGov are authoritative.
            return mapped

    # Pass 2: legacy STATUS codes
    closed_seen = False
    for key in (
        "STATUS",
        "23723",
        "23507",
        "25107",
        "25745",
        "26328",
        "29573",
        "34788",
        "24254",
        "29492",
        "26589",
        "34508",
        "29754",
    ):
        raw = extra.get(key)
        if raw is None:
            continue
        low = str(raw).strip().lower()
        if low == "closed":
            closed_seen = True
            continue
        mapped = _map_status_string(raw)
        if mapped is not None:
            return mapped

    if closed_seen:
        # Closed shells with a plausible FINALED → Final; else Inactive.
        final_dt = _first_date(extra, ("FINALED", "23703", "23486", "25090", "24233", "25723"))
        if _plausible_final(final_dt, _first_date(extra, ("APPLIED", "23692", "23475", "25105"))):
            return "Final"
        return "Inactive"

    return None


def _expected_status(d: dict) -> Optional[str]:
    main = _main(d)
    from_code = _status_from_code(main)
    if from_code is not None:
        return from_code
    return _status_from_extra(_extra(d))


# ── Date extraction ─────────────────────────────────────────────────────────

_APPLIED_KEYS = {
    "named_extra": ("APPLIED",),
    "building_legacy": ("23692",),
    "encroachment_legacy": ("23475",),
    "code_enforcement_legacy": ("25105",),
    "utility_legacy": ("24222",),
    "design_review_legacy": ("25718",),
    "variance_legacy": ("34762",),
    "home_occupation_legacy": ("29548",),
    "business_license_legacy": ("26304",),
    "public_works_legacy": ("36882",),
}

_ISSUE_KEYS = {
    "named_extra": ("ISSUED",),
    "building_legacy": ("23706",),
    # Encroachment: 23488 ≈ issue; 23477 ≈ approve; 23486 often final/complete
    "encroachment_legacy": ("23488", "23477", "23486"),
    "code_enforcement_legacy": ("25092",),
    "utility_legacy": ("24224", "24235"),
    "design_review_legacy": ("25720",),
    "variance_legacy": ("34764",),
    "home_occupation_legacy": ("29550",),
    "business_license_legacy": ("26306", "26309"),
    "public_works_legacy": ("36881",),
    "form_extra": (
        "ISSUED",
        "Approval Date:",
        "Certificate Issue Date",
        "Date License Issued ",
    ),
}

_FINAL_KEYS = {
    "named_extra": ("FINALED",),
    "building_legacy": ("23703",),
    "encroachment_legacy": ("23486",),
    "code_enforcement_legacy": ("25090",),
    "utility_legacy": ("24233",),
    "design_review_legacy": ("25723",),
    "variance_legacy": ("34767",),
    "home_occupation_legacy": ("29553",),
    "business_license_legacy": ("26309",),
    "public_works_legacy": ("36881",),
    "form_extra": ("FINALED", "Certificate Issue Date", "Date Completed"),
}


def _preferred_file_date(d: dict, schema: str) -> Optional[date]:
    """Prefer dateSubmitted, then dateCreated, then schema APPLIED field."""
    main = _main(d)
    submitted = _utc_date(main.get("dateSubmitted"))
    if submitted is not None:
        return submitted
    created = _utc_date(main.get("dateCreated"))
    if created is not None:
        return created
    keys = _APPLIED_KEYS.get(schema, ())
    dt = _first_date(_extra(d), keys)
    if dt is pd.NaT:
        return None
    return dt.date()


def _extract_permit_date(d: dict, schema: str):
    return _first_date(_extra(d), _ISSUE_KEYS.get(schema, ()))


def _extract_final_date(d: dict, schema: str, file_date):
    dt = _first_date(_extra(d), _FINAL_KEYS.get(schema, ()))
    if not _plausible_final(dt, file_date):
        return pd.NaT
    return dt


# ── Per-record repair logic ─────────────────────────────────────────────────

def _repair_record(row, d: dict, schema: str, repairs: dict):
    """Populate *repairs* with corrected values for a single Eureka record."""
    current_status = row["STATUS_NORMALIZED"]
    expected = _expected_status(d)

    # -- STATUS_NORMALIZED --
    if expected is not None:
        if pd.isna(current_status):
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"
        elif current_status != expected:
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FIXED"

    effective_status = repairs.get("STATUS_NORMALIZED", current_status)

    # -- FILE_DATE --
    preferred = _preferred_file_date(d, schema)
    current_fd = _as_date(row["FILE_DATE"])
    if preferred is not None:
        if current_fd is None:
            repairs["FILE_DATE"] = pd.Timestamp(preferred)
            repairs["FILE_DATE_FLAG"] = "FILLED"
        elif current_fd != preferred:
            repairs["FILE_DATE"] = pd.Timestamp(preferred)
            repairs["FILE_DATE_FLAG"] = "FIXED"

    effective_file = repairs.get("FILE_DATE", row["FILE_DATE"])

    # -- PERMIT_DATE --
    issue = _extract_permit_date(d, schema)
    current_permit = row["PERMIT_DATE"]

    if effective_status in ("Active", "Final"):
        expected_permit = issue
    elif effective_status == "Inactive" and issue is not pd.NaT:
        # Issued then stopped/expired/revoked — keep issuance date.
        expected_permit = issue
    else:
        expected_permit = pd.NaT

    if expected_permit is not pd.NaT:
        if pd.isna(current_permit):
            repairs["PERMIT_DATE"] = expected_permit
            repairs["PERMIT_DATE_FLAG"] = "FILLED"
        elif not _dates_equal(current_permit, expected_permit):
            repairs["PERMIT_DATE"] = expected_permit
            repairs["PERMIT_DATE_FLAG"] = "FIXED"
    else:
        if not pd.isna(current_permit) and effective_status in ("In Review",):
            repairs["PERMIT_DATE"] = pd.NaT
            repairs["PERMIT_DATE_FLAG"] = "FIXED"

    # -- FINAL_DATE --
    final_src = _extract_final_date(d, schema, effective_file)
    current_final = row["FINAL_DATE"]

    if effective_status == "Final":
        if pd.isna(current_final):
            if final_src is not pd.NaT:
                repairs["FINAL_DATE"] = final_src
                repairs["FINAL_DATE_FLAG"] = "FILLED"
        elif final_src is not pd.NaT and not _dates_equal(current_final, final_src):
            repairs["FINAL_DATE"] = final_src
            repairs["FINAL_DATE_FLAG"] = "FIXED"
        elif final_src is pd.NaT and not pd.isna(current_final):
            # Existing value is a known-bad sentinel / pre-file stamp.
            if not _plausible_final(_safe_to_datetime(current_final), effective_file):
                repairs["FINAL_DATE"] = pd.NaT
                repairs["FINAL_DATE_FLAG"] = "FIXED"
    else:
        if not pd.isna(current_final):
            repairs["FINAL_DATE"] = pd.NaT
            repairs["FINAL_DATE_FLAG"] = "FIXED"


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Eureka permit records using information from the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Eureka".  Must contain
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
        _repair_record(row, d, schema, repairs)

        for key, value in repairs.items():
            out.at[idx, key] = value

    return out


# ── CLI: run standalone to preview repair stats ─────────────────────────────

if __name__ == "__main__":
    import os
    from pathlib import Path
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[3] / ".env")
    MY_DATA_PATH = os.getenv("MY_DATA_PATH")
    AGENT_DATA_PATH = os.getenv("AGENT_DATA_PATH")
    filepath = os.path.join(MY_DATA_PATH, "processed_data", "permits_ca_sample.parquet")
    df = pd.read_parquet(filepath)
    city = df[(df["JURISDICTION"] == "Eureka") & (df["STATE"] == "CA")].copy()

    print(f"Eureka records: {len(city):,}\n")

    repaired = data_repair(city)

    print("INFERRED_SCHEMA:")
    for s, c in repaired["INFERRED_SCHEMA"].value_counts(dropna=False).items():
        print(f"  {s}: {c:,}")
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

    print("\nFILE_DATE missing by status (after):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_miss = sub["FILE_DATE"].isna().sum()
        print(f"  {status:15s}: missing {n_miss:>4,} / {len(sub):>4,}")

    if AGENT_DATA_PATH:
        out_path = os.path.join(AGENT_DATA_PATH, "eureka_repaired_sample.parquet")
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote {out_path}")

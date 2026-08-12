"""Data repair for Biscayne Park (FL) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED"
or "FIXED" annotations for every value that was changed.

Biscayne Park DATA is a CitizenServe / SmartGov-style payload with
top-level keys ``main``, ``extra``, and ``location``. Content variants
(INFERRED_SCHEMA):

  - citizenserve_draft:            unsubmitted drafts (main.status == 0)
  - citizenserve_legacy_building:  Legacy Building Permit (HIST-*)
  - citizenserve_legacy_code:      Legacy Code Enforcement (HIST-*)
  - citizenserve_building:         modern building / trade permits
  - citizenserve_code:             modern Code Enforcement
  - citizenserve_other:            landlord, planning, garage sale, etc.
  - unknown / missing

Canonical mappings:
  - main.status (0/1/2/-1)                         → STATUS_NORMALIZED
  - Legacy Building ASI 16197 else
    Legacy CE ASI 16028 (when on/before created) else
    main.dateSubmitted else main.dateCreated       → FILE_DATE
  - extra['DATE ISSUED'] / extra['Date Issued']
    (Active/Final only)                            → PERMIT_DATE
  - extra['Final Date'] else
    extra['Violation Resolution Date'] (Final) else
    Legacy CE ASI 16034 when after created (Final) → FINAL_DATE

Known issues repaired:
  - FILE_DATE was derived from main.dateCreated. Prefer
    dateSubmitted when it falls on a later calendar day, and fill
    the single row that has dateSubmitted but null dateCreated.
  - Legacy HIST rows use CitizenServe import timestamps as
    dateCreated/dateSubmitted; earlier unlabeled ASI dates
    (16197 building apply, 16028 CE notice) are the real file dates.
  - PERMIT_DATE / FINAL_DATE are universally missing upstream;
    a subset can be filled from named CE / building form fields
    and from Legacy CE close timestamps.

Not repairable from DATA:
  - STATUS_NORMALIZED already matches main.status 1:1.
  - Modern building Active/Final rows have no issuance timestamp
    (lastUpdatedDate / expirationDate are not safe proxies).
  - Legacy Building ASI 16203/16206 are ambiguous or migration-
    clustered, so PERMIT_DATE / FINAL_DATE stay missing there.
  - Modern CE Compliance / Correction dates behave like deadlines
    on Active rows and are not used as FINAL_DATE.
"""

from __future__ import annotations

import json
import math
from datetime import date, datetime
from typing import Optional

import numpy as np
import pandas as pd


_MIN_YEAR = 1900
_MAX_YEAR = 2035

# Legacy Building Permit ASI keys (unlabeled numeric extra fields)
_LEGACY_BLDG_APPLY = "16197"

# Legacy Code Enforcement ASI keys
_LEGACY_CE_NOTICE = "16028"
_LEGACY_CE_CLOSED = "16034"


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
        try:
            parsed = json.loads(data)
        except (json.JSONDecodeError, TypeError):
            return None
        return parsed if isinstance(parsed, dict) else None
    return data if isinstance(data, dict) else None


def _safe_to_datetime(val):
    """Parse a date value, returning pd.NaT on failure or implausible year."""
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return pd.NaT
    if isinstance(val, dict):
        return pd.NaT
    if isinstance(val, str):
        s = val.strip()
        if not s or s.upper() in {"TBD", "NULL", "NONE", "N/A", "NA"}:
            return pd.NaT
    try:
        dt = pd.to_datetime(val, errors="coerce")
    except (ValueError, TypeError):
        return pd.NaT
    if pd.isna(dt):
        return pd.NaT
    year = int(dt.year)
    if year < _MIN_YEAR or year > _MAX_YEAR:
        return pd.NaT
    if getattr(dt, "tzinfo", None) is not None:
        dt = dt.tz_convert("UTC").tz_localize(None)
    return dt


def _utc_date(val) -> Optional[date]:
    """Parse a timestamp and return its UTC calendar date."""
    if val is None or (isinstance(val, str) and not val.strip()):
        return None
    try:
        ts = pd.to_datetime(val, utc=True, errors="coerce")
    except (ValueError, TypeError):
        return None
    if pd.isna(ts):
        return None
    year = int(ts.year)
    if year < _MIN_YEAR or year > _MAX_YEAR:
        return None
    return ts.date()


def _as_date(val) -> Optional[date]:
    """Normalize a FILE_DATE-like value to datetime.date."""
    if _is_missing(val):
        return None
    if isinstance(val, date) and not isinstance(val, datetime):
        return val
    dt = _safe_to_datetime(val)
    if dt is pd.NaT or pd.isna(dt):
        return None
    if getattr(dt, "tzinfo", None) is not None:
        dt = dt.tz_convert("UTC") if hasattr(dt, "tz_convert") else dt
        return dt.date()
    return dt.date()


def _main(d: dict) -> dict:
    main = d.get("main")
    return main if isinstance(main, dict) else {}


def _extra(d: dict) -> dict:
    extra = d.get("extra")
    return extra if isinstance(extra, dict) else {}


# ── Schema classification ───────────────────────────────────────────────────

_BUILDING_TOKENS = (
    "building",
    "roof",
    "solar",
    "pool",
    "fence",
    "mechanical",
    "electrical",
    "plumbing",
    "demolition",
    "sign",
    "window",
    "shed",
    "fire",
    "irrigation",
    "driveway",
    "paint",
    "dumpster",
    "septic",
    "revision",
    "right-of-way",
)


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys()) if isinstance(data_dict, dict) else set()
    if not {"main", "extra", "location"}.issubset(keys):
        if "main" in keys:
            return "main_only"
        return "unknown"

    main = _main(data_dict)
    rtype = (main.get("recordTypeName") or "").strip()
    rtype_l = rtype.lower()

    try:
        status_code = int(main.get("status"))
    except (TypeError, ValueError):
        status_code = None
    if status_code == 0:
        return "citizenserve_draft"

    if rtype == "Legacy Building Permit":
        return "citizenserve_legacy_building"
    if rtype == "Legacy Code Enforcement":
        return "citizenserve_legacy_code"
    if rtype == "Code Enforcement" or "code enforcement" in rtype_l:
        return "citizenserve_code"
    if any(token in rtype_l for token in _BUILDING_TOKENS):
        return "citizenserve_building"

    return "citizenserve_other"


# ── Status mapping ──────────────────────────────────────────────────────────

# main.status (int) → STATUS_NORMALIZED
_STATUS_CODE_MAP = {
    0: "In Review",  # draft
    1: "Active",     # active
    2: "Final",      # complete
    -1: "Inactive",  # stopped
}


def _derive_status(main: dict) -> Optional[str]:
    status = main.get("status")
    if status is None:
        return None
    try:
        code = int(status)
    except (TypeError, ValueError):
        return None
    return _STATUS_CODE_MAP.get(code)


def _preferred_file_date(main: dict, extra: dict, schema: str) -> Optional[date]:
    """Best application / submittal / notice date available in DATA."""
    created = _utc_date(main.get("dateCreated"))
    submitted = _utc_date(main.get("dateSubmitted"))

    if schema == "citizenserve_legacy_building":
        apply = _as_date(_safe_to_datetime(extra.get(_LEGACY_BLDG_APPLY)))
        if apply is not None:
            return apply

    if schema == "citizenserve_legacy_code":
        notice = _as_date(_safe_to_datetime(extra.get(_LEGACY_CE_NOTICE)))
        # Only trust the ASI notice date when it is not after the import day.
        if notice is not None and (created is None or notice <= created):
            return notice

    if submitted is not None:
        return submitted
    if created is not None:
        return created

    # Fallbacks when main timestamps are absent
    if schema == "citizenserve_legacy_code":
        notice = _as_date(_safe_to_datetime(extra.get(_LEGACY_CE_NOTICE)))
        if notice is not None:
            return notice
    return None


def _permit_date_from_extra(extra: dict) -> Optional[pd.Timestamp]:
    for key in ("DATE ISSUED", "Date Issued"):
        dt = _safe_to_datetime(extra.get(key))
        if dt is not pd.NaT and pd.notna(dt):
            return dt
    return None


def _final_date_from_data(
    main: dict, extra: dict, schema: str, effective_status
) -> Optional[pd.Timestamp]:
    """Completion / resolution / signoff date when status is Final."""
    if effective_status != "Final":
        return None

    named = _safe_to_datetime(extra.get("Final Date"))
    if named is not pd.NaT and pd.notna(named):
        return named

    resolution = _safe_to_datetime(extra.get("Violation Resolution Date"))
    if resolution is not pd.NaT and pd.notna(resolution):
        return resolution

    if schema == "citizenserve_legacy_code":
        closed = _safe_to_datetime(extra.get(_LEGACY_CE_CLOSED))
        created = _utc_date(main.get("dateCreated"))
        closed_day = _as_date(closed)
        # Skip values that collapse to the CitizenServe import day.
        if (
            closed is not pd.NaT
            and pd.notna(closed)
            and closed_day is not None
            and (created is None or closed_day > created)
        ):
            return closed

    return None


def _set_date_repair(repairs: dict, field: str, current, new_dt: pd.Timestamp):
    """Write FILLED/FIXED for a date field when *new_dt* improves *current*."""
    if new_dt is pd.NaT or pd.isna(new_dt):
        return
    new_day = _as_date(new_dt)
    if new_day is None:
        return
    cur_day = _as_date(current)
    if cur_day is None:
        repairs[field] = pd.Timestamp(new_day)
        repairs[f"{field}_FLAG"] = "FILLED"
    elif cur_day != new_day:
        repairs[field] = pd.Timestamp(new_day)
        repairs[f"{field}_FLAG"] = "FIXED"


# ── Per-record repair logic ─────────────────────────────────────────────────

def _repair_record(row, d: dict, schema: str, repairs: dict):
    """Populate *repairs* with corrected values for a single record."""
    main = _main(d)
    extra = _extra(d)

    # -- STATUS_NORMALIZED --
    current_status = row["STATUS_NORMALIZED"]
    expected = _derive_status(main)
    if expected is not None:
        if pd.isna(current_status):
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"
        elif current_status != expected:
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FIXED"

    effective_status = repairs.get("STATUS_NORMALIZED", current_status)

    # -- FILE_DATE --
    preferred = _preferred_file_date(main, extra, schema)
    current_fd = _as_date(row["FILE_DATE"])
    if preferred is not None:
        if current_fd is None:
            repairs["FILE_DATE"] = pd.Timestamp(preferred)
            repairs["FILE_DATE_FLAG"] = "FILLED"
        elif current_fd != preferred:
            repairs["FILE_DATE"] = pd.Timestamp(preferred)
            repairs["FILE_DATE_FLAG"] = "FIXED"

    # -- PERMIT_DATE --
    if effective_status in ("Active", "Final"):
        issued = _permit_date_from_extra(extra)
        if issued is not None:
            _set_date_repair(repairs, "PERMIT_DATE", row["PERMIT_DATE"], issued)

    # -- FINAL_DATE --
    final_dt = _final_date_from_data(main, extra, schema, effective_status)
    if final_dt is not None:
        _set_date_repair(repairs, "FINAL_DATE", row["FINAL_DATE"], final_dt)
    elif (
        effective_status != "Final"
        and not pd.isna(row["FINAL_DATE"])
    ):
        repairs["FINAL_DATE"] = pd.NaT
        repairs["FINAL_DATE_FLAG"] = "FIXED"


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Biscayne Park permit records using information from the raw DATA JSON.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Biscayne Park".  Must contain
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

    for col in ("FILE_DATE", "PERMIT_DATE", "FINAL_DATE"):
        out[col] = pd.to_datetime(out[col], errors="coerce")

    return out


# ── CLI: run standalone to preview repair stats ─────────────────────────────

if __name__ == "__main__":
    import os
    from pathlib import Path

    from dotenv import load_dotenv

    repo_root = Path(__file__).resolve().parents[3]
    load_dotenv(repo_root / ".env")
    my_data_path = os.getenv("MY_DATA_PATH")
    agent_data_path = os.getenv("AGENT_DATA_PATH")
    filepath = os.path.join(my_data_path, "processed_data", "permits_fl_sample.parquet")
    df = pd.read_parquet(filepath)
    city = df[(df["JURISDICTION"] == "Biscayne Park") & (df["STATE"] == "FL")].copy()

    print(f"Biscayne Park records: {len(city):,}\n")

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

    print("\nCoverage by STATUS_NORMALIZED (after):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        if len(sub) == 0:
            continue
        for field in ["FILE_DATE", "PERMIT_DATE", "FINAL_DATE"]:
            n_has = sub[field].notna().sum()
            print(
                f"  {status:12s} {field:12s}: "
                f"{n_has:>4,} / {len(sub):>4,} ({n_has / len(sub):.1%})"
            )

    print("\nFILE_DATE_FLAG by INFERRED_SCHEMA:")
    ct = pd.crosstab(
        repaired["INFERRED_SCHEMA"],
        repaired["FILE_DATE_FLAG"].fillna("(none)"),
    )
    print(ct.to_string())

    if agent_data_path:
        out_path = os.path.join(agent_data_path, "biscayne_park_repaired_sample.parquet")
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote repaired sample → {out_path}")

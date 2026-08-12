"""Data repair for Apopka (FL) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Apopka DATA is a CitizenServe / SmartGov-style payload with top-level
keys ``main``, ``extra``, and ``location``. Content variants
(INFERRED_SCHEMA):

  - citizenserve_historical:      HIST- / HPerm migrated legacy rows
  - citizenserve_btr:             Business Tax Receipt applications
  - citizenserve_contractor_reg:  Building-Contractor Registration
  - citizenserve_planning:        planning / arbor / annex / plat forms
  - citizenserve_draft:           unsubmitted drafts (main.status == 0)
  - citizenserve_building:        building / trade / roof / solar / etc.
  - citizenserve_other:           residual form types
  - unknown / missing

Canonical mappings:
  - main.status (0/1/2/-1)                         → STATUS_NORMALIZED
  - main.dateSubmitted (else dateCreated;
    else extra['Application Date'])               → FILE_DATE
  - (none reliable)                                → PERMIT_DATE
  - (none reliable)                                → FINAL_DATE

Known issues repaired:
  - FILE_DATE was derived from main.dateCreated. When dateSubmitted
    falls on a later calendar day (71 sample rows), overwrite with
    the submittal date.

Not repairable from DATA:
  - STATUS_NORMALIZED already matches main.status 1:1
    (draft/active/complete/stopped ↔ In Review/Active/Final/Inactive).
    extra.Status quirks (e.g. Inactive BTRs labeled "Completed") do
    not override the portal lifecycle code.
  - PERMIT_DATE is universally missing. Issue Date keys exist but are
    blank; BTR Effective Date is a license-period start (often Oct 1),
    not an issuance timestamp; lastUpdatedDate / expirationDate are
    not safe approval proxies.
  - FINAL_DATE is universally missing. No completion / finaled /
    signoff field exists in main or extra.
  - Five Inactive BTR shells have null dateCreated / dateSubmitted /
    Application Date → FILE_DATE stays missing.
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

def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys()) if isinstance(data_dict, dict) else set()
    if not {"main", "extra", "location"}.issubset(keys):
        if "main" in keys:
            return "main_only"
        return "unknown"

    main = _main(data_dict)
    prefix = (main.get("prefix") or "").strip()
    historical_id = str(main.get("historicalID") or "")
    rtype = (main.get("recordTypeName") or "").strip().lower()

    if prefix.startswith("HIST") or historical_id.startswith("HPerm"):
        return "citizenserve_historical"
    if "business tax" in rtype or prefix.startswith("BTR"):
        return "citizenserve_btr"
    if "contractor registration" in rtype or prefix.startswith("CR"):
        return "citizenserve_contractor_reg"
    if any(
        token in rtype
        for token in (
            "plat",
            "mdp",
            "csp",
            "zoning",
            "annex",
            "variance",
            "rezon",
            "land use",
            "arbor",
            "tree",
            "planning",
            "appeal",
            "vacat",
            "planned development",
            "master plan",
            "addressing",
        )
    ):
        return "citizenserve_planning"
    try:
        status_code = int(main.get("status"))
    except (TypeError, ValueError):
        status_code = None
    if status_code == 0:
        return "citizenserve_draft"
    if any(
        token in rtype
        for token in (
            "building",
            "roof",
            "solar",
            "pool",
            "fence",
            "mechanical",
            "electrical",
            "plumbing",
            "townhome",
            "townhouse",
            "apartment",
            "sign",
            "sub-contractor",
            "stocking",
            "single family",
            "commercial building",
            "window",
            "demolition",
            "shed",
            "fire",
            "irrigation",
            "oil and grease",
        )
    ):
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


def _preferred_file_date(main: dict, extra: dict) -> Optional[date]:
    """Application/submittal date: dateSubmitted → dateCreated → Application Date."""
    submitted = _utc_date(main.get("dateSubmitted"))
    if submitted is not None:
        return submitted
    created = _utc_date(main.get("dateCreated"))
    if created is not None:
        return created
    app = _safe_to_datetime(extra.get("Application Date"))
    if app is not pd.NaT and pd.notna(app):
        return app.date()
    return None


# ── Per-record repair logic ─────────────────────────────────────────────────

def _repair_record(row, d: dict, repairs: dict):
    """Populate *repairs* with corrected values for a single Apopka record."""
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

    # -- FILE_DATE --
    preferred = _preferred_file_date(main, extra)
    current_fd = _as_date(row["FILE_DATE"])
    if preferred is not None:
        if current_fd is None:
            repairs["FILE_DATE"] = pd.Timestamp(preferred)
            repairs["FILE_DATE_FLAG"] = "FILLED"
        elif current_fd != preferred:
            repairs["FILE_DATE"] = pd.Timestamp(preferred)
            repairs["FILE_DATE_FLAG"] = "FIXED"

    # -- PERMIT_DATE --
    # No reliable issuance/approval date in DATA; leave as-is.

    # -- FINAL_DATE --
    # No reliable finaling/completion/signoff date in DATA; leave as-is.


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Apopka permit records using information from the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Apopka".  Must contain
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
    filepath = os.path.join(MY_DATA_PATH, "processed_data", "permits_fl_sample.parquet")
    df = pd.read_parquet(filepath)
    apopka = df[(df["JURISDICTION"] == "Apopka") & (df["STATE"] == "FL")].copy()

    print(f"Apopka records: {len(apopka):,}\n")

    repaired = data_repair(apopka)

    print("INFERRED_SCHEMA:")
    print(repaired["INFERRED_SCHEMA"].value_counts(dropna=False).to_string())
    print()

    for field in ["STATUS_NORMALIZED", "FILE_DATE", "PERMIT_DATE", "FINAL_DATE"]:
        flag_col = f"{field}_FLAG"
        n_filled = (repaired[flag_col] == "FILLED").sum()
        n_fixed = (repaired[flag_col] == "FIXED").sum()
        print(f"{field}:")
        print(f"  FILLED: {n_filled:>4,}   FIXED: {n_fixed:>4,}")

        before_missing = apopka[field].isna().sum()
        after_missing = repaired[field].isna().sum()
        print(f"  Missing before: {before_missing:>4,}   Missing after: {after_missing:>4,}")
        print()

    print("STATUS_NORMALIZED distribution:")
    print("  Before:")
    for s, c in apopka["STATUS_NORMALIZED"].value_counts(dropna=False).items():
        print(f"    {str(s):15s}: {c:>4,}")
    print("  After:")
    for s, c in repaired["STATUS_NORMALIZED"].value_counts(dropna=False).items():
        print(f"    {str(s):15s}: {c:>4,}")

    print("\nFILE_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FILE_DATE"].notna().sum()
        n = len(sub)
        pct = n_has / n if n else 0.0
        print(f"  {status:15s}: {n_has:>4,} / {n:>4,} ({pct:.1%})")

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

    if AGENT_DATA_PATH:
        out_path = os.path.join(AGENT_DATA_PATH, "apopka_repaired_sample.parquet")
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote repaired sample → {out_path}")

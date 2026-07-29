"""Data repair for Scotts Valley (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Scotts Valley DATA is a CitizenServe / OpenGov-style payload with
top-level keys ``main``, ``extra``, and ``location``. Content variants
(INFERRED_SCHEMA) are classified by record-type family:

  - citizenserve_residential_building
  - citizenserve_commercial_building
  - citizenserve_electrical
  - citizenserve_mechanical
  - citizenserve_plumbing
  - citizenserve_solar
  - citizenserve_encroachment
  - citizenserve_practice
  - citizenserve_address
  - citizenserve_form_other / empty_extra / unknown / missing

Canonical mappings:
  - main.status (0/1/2/-1) → STATUS_NORMALIZED
  - main.dateSubmitted (when present) → FILE_DATE; else keep existing
    FILE_DATE, filling from dateCreated only when FILE_DATE is missing
  - (none reliable) → PERMIT_DATE
  - (none reliable) → FINAL_DATE

Known issues repaired:
  - STATUS_NORMALIZED was derived from STATUS_ORIGINAL (active / draft /
    complete / stopped), which can lag the live numeric main.status.
    Sample mismatches (status=2 still Active, status=1 still Final,
    status=-1 still Active, status=0 still Active / Final) → FIXED to
    the code map.
  - FILE_DATE was taken from main.dateCreated for many rows. When
    dateSubmitted falls on a later calendar day → FIXED to the
    submittal date. One Final shell with null FILE_DATE but a
    dateSubmitted → FILLED.
  - Pre-portal migration shells keep an earlier FILE_DATE that does not
    match dateCreated and have no dateSubmitted; those historical
    application dates are left as-is (not overwritten with the portal
    import stamp).

Not repairable from DATA:
  - No Permit Issued / Issue / Approval Date, no Permit Finaled /
    Inspection Final / Completion Date, and no Issued ASI companion
    pairs. extra['Primary Status'] is a contractor bond/insurance flag
    (CLEAR / Susp), not lifecycle. Department "Final Sign Off"
    checkboxes are application attestations, not completion stamps.
    expirationDate and lastUpdatedDate are not safe proxies for
    PERMIT_DATE / FINAL_DATE. Consequently PERMIT_DATE and FINAL_DATE
    remain missing on all sample rows.
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
        if not data.strip():
            return None
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
    if val is None or (isinstance(val, str) and not str(val).strip()):
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
    if not isinstance(data_dict, dict) or "main" not in data_dict:
        return "unknown"

    main = _main(data_dict)
    extra = _extra(data_dict)
    rt = (main.get("recordTypeName") or "").strip().lower()

    if "encroach" in rt:
        return "citizenserve_encroachment"
    if "solar" in rt or "pv" in rt:
        return "citizenserve_solar"
    if "electrical" in rt:
        return "citizenserve_electrical"
    if "mechanical" in rt:
        return "citizenserve_mechanical"
    if "plumbing" in rt:
        return "citizenserve_plumbing"
    if "commercial" in rt and "building" in rt:
        return "citizenserve_commercial_building"
    if "residential" in rt and "building" in rt:
        return "citizenserve_residential_building"
    if "practice" in rt:
        return "citizenserve_practice"
    if "address" in rt:
        return "citizenserve_address"

    if not extra:
        return "empty_extra"
    return "citizenserve_form_other"


# ── Status / date derivation ────────────────────────────────────────────────

# main.status (int) → STATUS_NORMALIZED
_STATUS_CODE_MAP = {
    0: "In Review",  # draft
    1: "Active",     # active
    2: "Final",      # complete
    -1: "Inactive",  # stopped
}


def _derive_status(main: dict) -> Optional[str]:
    """Map CitizenServe portal lifecycle code to STATUS_NORMALIZED.

    Prefer live ``main.status`` over lagged STATUS_ORIGINAL. Scotts Valley
    has no form-level Issued / Finaled stamps to refine against.
    """
    status = main.get("status")
    if status is None:
        return None
    try:
        code = int(status)
    except (TypeError, ValueError):
        return None
    return _STATUS_CODE_MAP.get(code)


def _repair_file_date(row, main: dict, repairs: dict) -> None:
    """Prefer dateSubmitted; only fall back to dateCreated when FILE_DATE
    is missing.

    When dateSubmitted is absent and FILE_DATE already holds a date that
    differs from dateCreated (pre-portal migration shells), keep the
    existing application date rather than overwriting with the portal
    import stamp.
    """
    submitted = _utc_date(main.get("dateSubmitted"))
    created = _utc_date(main.get("dateCreated"))
    current_fd = _as_date(row["FILE_DATE"])

    if submitted is not None:
        if current_fd is None:
            repairs["FILE_DATE"] = pd.Timestamp(submitted)
            repairs["FILE_DATE_FLAG"] = "FILLED"
        elif current_fd != submitted:
            repairs["FILE_DATE"] = pd.Timestamp(submitted)
            repairs["FILE_DATE_FLAG"] = "FIXED"
        return

    if current_fd is None and created is not None:
        repairs["FILE_DATE"] = pd.Timestamp(created)
        repairs["FILE_DATE_FLAG"] = "FILLED"


# ── Per-record repair logic ─────────────────────────────────────────────────

def _repair_record(row, d: dict, repairs: dict):
    """Populate *repairs* with corrected values for a single record."""
    main = _main(d)

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
    _repair_file_date(row, main, repairs)

    # -- PERMIT_DATE --
    # No reliable issuance/approval timestamp in DATA; leave as-is.

    # -- FINAL_DATE --
    # No reliable finaling/completion timestamp in DATA; leave as-is.
    # FINAL_DATE is already null on every sample row.


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Scotts Valley permit records using information from the raw DATA JSON.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Scotts Valley".  Must
        contain columns STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE,
        FINAL_DATE, and DATA.

    Returns
    -------
    pd.DataFrame
        Copy of *df* with corrected field values, an INFERRED_SCHEMA
        column naming the DATA JSON sub-schema identified for each
        record, and new flag columns: STATUS_NORMALIZED_FLAG,
        FILE_DATE_FLAG, PERMIT_DATE_FLAG, FINAL_DATE_FLAG.  Flag values
        are "FILLED" (was missing, now populated) or "FIXED" (had an
        incorrect value, now corrected).
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

    for col in ("FILE_DATE", "PERMIT_DATE", "FINAL_DATE"):
        if col in out.columns:
            out[col] = pd.to_datetime(out[col], utc=True, errors="coerce")

    return out


# ── CLI: run standalone to preview repair stats ─────────────────────────────

if __name__ == "__main__":
    import os
    from pathlib import Path

    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[3] / ".env")
    MY_DATA_PATH = os.getenv("MY_DATA_PATH")
    AGENT_DATA_PATH = os.getenv("AGENT_DATA_PATH")
    filepath = os.path.join(
        MY_DATA_PATH, "processed_data", "permits_ca_sample.parquet"
    )
    df = pd.read_parquet(filepath)
    city = df[
        (df["JURISDICTION"] == "Scotts Valley") & (df["STATE"] == "CA")
    ].copy()

    print(f"Scotts Valley records: {len(city):,}\n")

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

    transitions = {}
    for idx in city.index:
        before = city.at[idx, "STATUS_NORMALIZED"]
        after = repaired.at[idx, "STATUS_NORMALIZED"]
        if before != after:
            key = (str(before), str(after))
            transitions[key] = transitions.get(key, 0) + 1
    if transitions:
        print("\nStatus transitions (FIXED):")
        for (b, a), n in sorted(transitions.items(), key=lambda x: -x[1]):
            print(f"  {b} → {a}: {n}")

    print("\nFILE_DATE coverage:")
    n_has = repaired["FILE_DATE"].notna().sum()
    print(f"  {n_has:,} / {len(repaired):,} ({n_has / len(repaired):.1%})")

    # FILE_DATE fix breakdown
    fd_fixed = repaired[repaired["FILE_DATE_FLAG"] == "FIXED"]
    if len(fd_fixed):
        deltas = []
        for idx in fd_fixed.index:
            before = _as_date(city.at[idx, "FILE_DATE"])
            after = _as_date(repaired.at[idx, "FILE_DATE"])
            if before is not None and after is not None:
                deltas.append((after - before).days)
        if deltas:
            print(
                f"  FILE_DATE FIXED day deltas: "
                f"min={min(deltas)} median={sorted(deltas)[len(deltas)//2]} "
                f"max={max(deltas)} (n={len(deltas)})"
            )

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
        out_dir = Path(AGENT_DATA_PATH) / "repaired"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "permits_ca_scotts_valley_repaired.parquet"
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote {out_path}")

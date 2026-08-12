"""Data repair for Lake County (FL) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Lake County DATA is a flat county portal extract with Status,
Application Date, Issued Date, Certificate Number, Certificate of
Occupancy, and Permit History (the last two are always null in this
sample). Three layout variants appear:

  - lake_portal:             base key set
  - lake_portal_desc:        adds Permit Description
  - lake_portal_underscore:  also carries Job_Value / Job_Description /
                             Permit_Description duplicates

Content suffixes further split by portal Status slug
(``_coed``, ``_issued``, ``_inspect``, ``_final``, ``_apply``,
``_ready``, ``_city``, ``_cancel``, ``_expired``, ``_void``,
``_closed_ni``).

Canonical mappings:
  - DATA.Status              → STATUS_NORMALIZED
  - Application Date         → FILE_DATE
  - Issued Date              → PERMIT_DATE
  - Certificate of Occupancy / Permit History → FINAL_DATE
    (both always null here; no recoverable final timestamp)

Status values observed:
  - COED / FINAL → Final
  - ISSUED / INSPECT → Active
  - APPLY / READY / CITY → In Review
  - CANCEL / EXPIRED / VOID / CLOSED_NI → Inactive
    (CLOSED_NI = closed without inspection / final)

Known issues repaired:
  - 3 rows with null STATUS_NORMALIZED (CLOSED_NI / closed_ni) →
    FILLED to Inactive.

Not repairable from DATA:
  - FILE_DATE already equals Application Date for every sample row.
  - PERMIT_DATE already equals Issued Date wherever Issued Date
    exists; remaining blanks are true nulls on APPLY / READY /
    never-issued CANCEL / EXPIRED / VOID / CITY.
  - FINAL_DATE cannot be recovered: Certificate of Occupancy and
    Permit History are null on every row; Certificate Number has no
    associated date. All 1,637 Final rows stay missing FINAL_DATE.
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
    """Parse a date value, returning pd.NaT on failure / blanks / OOR."""
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return pd.NaT
    if isinstance(val, dict):
        return pd.NaT
    if isinstance(val, str):
        s = val.strip()
        if not s or s.upper() in {
            "TBD", "NULL", "NONE", "N/A", "NA", "NAN",
            "00/00/0000", "0/0/0000",
        }:
            return pd.NaT
    try:
        dt = pd.to_datetime(val, errors="coerce")
    except (ValueError, TypeError, OverflowError):
        return pd.NaT
    if pd.isna(dt):
        return pd.NaT
    year = int(dt.year)
    if year < _MIN_YEAR or year > _MAX_YEAR:
        return pd.NaT
    return dt


def _dates_equal(a, b) -> bool:
    """Compare two datelike values at calendar-day resolution."""
    da = _safe_to_datetime(a)
    db = _safe_to_datetime(b)
    if da is pd.NaT or db is pd.NaT or pd.isna(da) or pd.isna(db):
        return False
    return pd.Timestamp(da).normalize() == pd.Timestamp(db).normalize()


# ── Status mapping ───────────────────────────────────────────────────────────

_STATUS_MAP = {
    "COED": "Final",
    "FINAL": "Final",
    "ISSUED": "Active",
    "INSPECT": "Active",
    "APPLY": "In Review",
    "READY": "In Review",
    "CITY": "In Review",
    "CANCEL": "Inactive",
    "EXPIRED": "Inactive",
    "VOID": "Inactive",
    # Closed without inspection / final sign-off.
    "CLOSED_NI": "Inactive",
}

_SCHEMA_SUFFIX = {
    "COED": "coed",
    "FINAL": "final",
    "ISSUED": "issued",
    "INSPECT": "inspect",
    "APPLY": "apply",
    "READY": "ready",
    "CITY": "city",
    "CANCEL": "cancel",
    "EXPIRED": "expired",
    "VOID": "void",
    "CLOSED_NI": "closed_ni",
}


def _map_status(raw: Optional[str]) -> Optional[str]:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    expected = _STATUS_MAP.get(text)
    if expected is not None:
        return expected
    return _STATUS_MAP.get(text.upper())


def _raw_status(d: dict) -> str:
    return str(d.get("Status") or "").strip()


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())
    required = {
        "Status",
        "Application Date",
        "Issued Date",
        "Certificate of Occupancy",
        "Permit History",
        "Permit Number",
    }
    if not required <= keys:
        return "unknown"

    if {"Job_Value", "Job_Description", "Permit_Description"} & keys:
        prefix = "lake_portal_underscore"
    elif "Permit Description" in keys:
        prefix = "lake_portal_desc"
    else:
        prefix = "lake_portal"

    ps = _raw_status(data_dict).upper()
    suffix = _SCHEMA_SUFFIX.get(ps)
    if suffix is None:
        slug = re.sub(r"[^a-z0-9]+", "_", ps.lower()).strip("_") or "other"
        return f"{prefix}_{slug}"
    return f"{prefix}_{suffix}"


def _apply_status(repairs: dict, current, expected: Optional[str]) -> Optional[str]:
    """Apply expected STATUS_NORMALIZED; return effective status."""
    if expected is None:
        if pd.isna(current):
            return None
        return current

    if pd.isna(current):
        repairs["STATUS_NORMALIZED"] = expected
        repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"
    elif current != expected:
        repairs["STATUS_NORMALIZED"] = expected
        repairs["STATUS_NORMALIZED_FLAG"] = "FIXED"

    return repairs.get("STATUS_NORMALIZED", current)


def _apply_date(repairs: dict, row, field: str, candidate) -> None:
    """Fill or fix *field* from *candidate* datetime (pd.NaT = no candidate)."""
    cand = _safe_to_datetime(candidate)
    if cand is pd.NaT or pd.isna(cand):
        return

    current = row[field]
    if pd.isna(current):
        repairs[field] = cand
        repairs[f"{field}_FLAG"] = "FILLED"
    elif not _dates_equal(current, cand):
        repairs[field] = cand
        repairs[f"{field}_FLAG"] = "FIXED"


def _final_date_candidate(d: dict):
    """Best completion / CO date from DATA (usually unavailable)."""
    for key in ("Certificate of Occupancy", "Permit History"):
        val = d.get(key)
        if val is None:
            continue
        if isinstance(val, list):
            dates = []
            for item in val:
                if isinstance(item, dict):
                    for dk in (
                        "Date", "date", "Issue Date", "Issued Date",
                        "CO Date", "Final Date", "Status Date",
                    ):
                        dt = _safe_to_datetime(item.get(dk))
                        if dt is not pd.NaT and not pd.isna(dt):
                            dates.append(dt)
                else:
                    dt = _safe_to_datetime(item)
                    if dt is not pd.NaT and not pd.isna(dt):
                        dates.append(dt)
            if dates:
                return max(dates)
        else:
            dt = _safe_to_datetime(val)
            if dt is not pd.NaT and not pd.isna(dt):
                return dt
    return pd.NaT


# ── Per-schema repair logic ─────────────────────────────────────────────────

def _repair_lake_portal(row, d: dict, repairs: dict) -> None:
    """Repair a Lake County flat-portal record."""
    expected = _map_status(d.get("Status"))
    effective_status = _apply_status(repairs, row["STATUS_NORMALIZED"], expected)

    # FILE_DATE ← Application Date (already correct for all sample rows).
    _apply_date(repairs, row, "FILE_DATE", d.get("Application Date"))

    # PERMIT_DATE ← Issued Date when present.
    issued = _safe_to_datetime(d.get("Issued Date"))
    if issued is not pd.NaT and not pd.isna(issued):
        if effective_status in ("Active", "Final", "Inactive", "In Review"):
            _apply_date(repairs, row, "PERMIT_DATE", issued)

    # FINAL_DATE for Final only when a true CO / history date exists.
    if effective_status == "Final":
        _apply_date(repairs, row, "FINAL_DATE", _final_date_candidate(d))


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Lake County permit records using information from the raw DATA JSON.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Lake County".  Must
        contain columns STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE,
        FINAL_DATE, and DATA.

    Returns
    -------
    pd.DataFrame
        Copy of *df* with corrected field values, an INFERRED_SCHEMA
        column naming the DATA JSON sub-schema identified for each
        record, and flag columns: STATUS_NORMALIZED_FLAG, FILE_DATE_FLAG,
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

        if schema.startswith("lake_portal"):
            _repair_lake_portal(row, d, repairs)

        for key, value in repairs.items():
            out.at[idx, key] = value

    for col in ("FILE_DATE", "PERMIT_DATE", "FINAL_DATE"):
        out[col] = pd.to_datetime(out[col], errors="coerce")

    return out


# ── CLI: run standalone to preview repair stats ─────────────────────────────

if __name__ == "__main__":
    import os
    from dotenv import load_dotenv, find_dotenv

    load_dotenv(find_dotenv())
    MY_DATA_PATH = os.getenv("MY_DATA_PATH")
    AGENT_DATA_PATH = os.getenv("AGENT_DATA_PATH")
    filepath = os.path.join(MY_DATA_PATH, "processed_data", "permits_fl_sample.parquet")
    df = pd.read_parquet(filepath)
    lc = df[df["JURISDICTION"] == "Lake County"].copy()

    print(f"Lake County records: {len(lc):,}\n")

    repaired = data_repair(lc)

    print("INFERRED_SCHEMA:")
    print(repaired["INFERRED_SCHEMA"].value_counts(dropna=False).to_string())
    print()

    for field in ["STATUS_NORMALIZED", "FILE_DATE", "PERMIT_DATE", "FINAL_DATE"]:
        flag_col = f"{field}_FLAG"
        n_filled = (repaired[flag_col] == "FILLED").sum()
        n_fixed = (repaired[flag_col] == "FIXED").sum()
        print(f"{field}:")
        print(f"  FILLED: {n_filled:>4,}   FIXED: {n_fixed:>4,}")

        before_missing = lc[field].isna().sum()
        after_missing = repaired[field].isna().sum()
        print(f"  Missing before: {before_missing:>4,}   Missing after: {after_missing:>4,}")
        print()

    print("STATUS_NORMALIZED distribution:")
    print("  Before:")
    for s, c in lc["STATUS_NORMALIZED"].value_counts(dropna=False).items():
        print(f"    {str(s):15s}: {c:>4,}")
    print("  After:")
    for s, c in repaired["STATUS_NORMALIZED"].value_counts(dropna=False).items():
        print(f"    {str(s):15s}: {c:>4,}")

    print("\nFILE_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FILE_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({n_has/len(sub) if len(sub) else 0:.1%})")

    print("\nPERMIT_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["PERMIT_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({n_has/len(sub) if len(sub) else 0:.1%})")

    print("\nFINAL_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FINAL_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({n_has/len(sub) if len(sub) else 0:.1%})")

    n_unmapped = 0
    n_file_mismatch = 0
    n_permit_mismatch = 0
    for idx in repaired.index:
        d = _safe_parse(repaired.at[idx, "DATA"]) or {}
        if _map_status(d.get("Status")) is None:
            n_unmapped += 1
        app = _safe_to_datetime(d.get("Application Date"))
        if app is not pd.NaT and not pd.isna(app):
            if not _dates_equal(repaired.at[idx, "FILE_DATE"], app):
                n_file_mismatch += 1
        issued = _safe_to_datetime(d.get("Issued Date"))
        if (
            issued is not pd.NaT
            and not pd.isna(issued)
            and not _dates_equal(repaired.at[idx, "PERMIT_DATE"], issued)
        ):
            n_permit_mismatch += 1

    print(f"\nUnmapped Status values: {n_unmapped}")
    print(f"FILE_DATE != Application Date after repair: {n_file_mismatch}")
    print(f"PERMIT_DATE != Issued Date after repair: {n_permit_mismatch}")

    print("\nFlagged STATUS_NORMALIZED rows:")
    flagged = repaired[repaired["STATUS_NORMALIZED_FLAG"].notna()][
        ["PERMIT_NUMBER", "STATUS_ORIGINAL", "STATUS_NORMALIZED", "STATUS_NORMALIZED_FLAG"]
    ]
    print(flagged.to_string(index=False) if len(flagged) else "  (none)")

    if AGENT_DATA_PATH:
        out_path = os.path.join(AGENT_DATA_PATH, "lake_county_repaired_sample.parquet")
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote {out_path}")

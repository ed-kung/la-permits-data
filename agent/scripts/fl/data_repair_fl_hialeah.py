"""Data repair for Hialeah (FL) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Hialeah DATA is a flat city-portal project payload with a single key set
(``Status``, ``Project Number``, ``Reviews``, ``Inspections``, etc.).
Content variants are labeled by which date-bearing collections are
populated:

  - hialeah_rev_insp:     Reviews + Inspections with usable dates
  - hialeah_rev_only:     Reviews with dates, no usable Inspection dates
  - hialeah_insp_only:    Inspections with dates, no usable Review dates
  - hialeah_status_only:  neither collection yields a usable date
  - missing / unknown

Canonical mappings:
  - DATA.Status                         → STATUS_NORMALIZED
  - Earliest Reviews[].Date Created or
    Inspections[].Date Created          → FILE_DATE
  - Earliest Inspections[].Date Created → PERMIT_DATE
  - (no finaled / CO / sign-off
    timestamp in DATA)                  → FINAL_DATE unavailable

Status values observed:
  - Finaled / Closed / CO Issued / CC Issued / RO Issued → Final
  - Active / Renewed / RO Conditional → Active
  - On Review / Hold / Open / Ready / Plans Pick-Up / Lien → In Review
  - Expired / Void / Canceled / Abandoned / Denied / Duplicate → Inactive

Known issues / sample findings:
  - STATUS_NORMALIZED null for RO Issued / Plans Pick-Up / RO Conditional
    (and 2 rows where STATUS_ORIGINAL lagged live Status).
  - FILE_DATE entirely missing upstream; filled from earliest review /
    inspection Date Created when present.
  - PERMIT_DATE often taken from the first Inspections list item rather
    than the chronologically earliest Date Created → FIXED to min date.
  - No completion / finaled / CO date field exists → FINAL_DATE cannot
    be filled for Final rows.
"""

from __future__ import annotations

import json
import math
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
    """Parse a date value, returning pd.NaT on failure / blanks / OOR year."""
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
    if getattr(dt, "tzinfo", None) is not None:
        dt = dt.tz_convert("UTC").tz_localize(None)
    return dt


def _dates_equal(a, b) -> bool:
    """Compare two datelike values at calendar-day resolution."""
    da = _safe_to_datetime(a)
    db = _safe_to_datetime(b)
    if da is pd.NaT or db is pd.NaT or pd.isna(da) or pd.isna(db):
        return False
    return pd.Timestamp(da).normalize() == pd.Timestamp(db).normalize()


def _as_list(val) -> list:
    if val is None:
        return []
    if isinstance(val, list):
        return val
    if isinstance(val, dict):
        return [val]
    return []


def _collect_dates(items: list, field: str) -> list:
    out = []
    for item in items:
        if not isinstance(item, dict):
            continue
        dt = _safe_to_datetime(item.get(field))
        if dt is not pd.NaT and not pd.isna(dt):
            out.append(pd.Timestamp(dt).normalize())
    return out


def _min_date(dates: list):
    return min(dates) if dates else pd.NaT


def _classify_schema(data_dict: Optional[dict], has_rev: bool, has_insp: bool) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())
    if "Status" not in keys or "Project Number" not in keys:
        return "unknown"
    if has_rev and has_insp:
        return "hialeah_rev_insp"
    if has_rev:
        return "hialeah_rev_only"
    if has_insp:
        return "hialeah_insp_only"
    return "hialeah_status_only"


# ── Status mapping ───────────────────────────────────────────────────────────

# DATA.Status → STATUS_NORMALIZED
_STATUS_MAP = {
    # Final / completed / certificate issued
    "Finaled": "Final",
    "Closed": "Final",
    "CO Issued": "Final",
    "CC Issued": "Final",
    "RO Issued": "Final",  # Re-Occupancy issued (certificate-like)
    # Active / issued
    "Active": "Active",
    "Renewed": "Active",
    "RO Conditional": "Active",
    # In review / pre-issuance / hold
    "On Review": "In Review",
    "Hold": "In Review",
    "Open": "In Review",
    "Ready": "In Review",
    "Plans Pick-Up": "In Review",
    "Lien": "In Review",
    # Inactive
    "Expired": "Inactive",
    "Void": "Inactive",
    "Canceled": "Inactive",
    "Abandoned": "Inactive",
    "Denied": "Inactive",
    "Duplicate": "Inactive",
}


def _derive_status(d: dict) -> Optional[str]:
    raw = d.get("Status")
    if raw is None or (isinstance(raw, str) and not str(raw).strip()):
        return None
    text = str(raw).strip()
    if text in _STATUS_MAP:
        return _STATUS_MAP[text]

    lower_map = {k.lower(): v for k, v in _STATUS_MAP.items()}
    if text.lower() in lower_map:
        return lower_map[text.lower()]

    lower = text.lower()
    if "co issued" in lower or "cc issued" in lower or "finaled" in lower:
        return "Final"
    if "ro issued" in lower:
        return "Final"
    if "closed" in lower:
        return "Final"
    if "renew" in lower or lower == "active" or "conditional" in lower:
        return "Active"
    if (
        "expire" in lower
        or "void" in lower
        or "cancel" in lower
        or "abandon" in lower
        or "denied" in lower
        or "duplicate" in lower
    ):
        return "Inactive"
    if (
        "review" in lower
        or "hold" in lower
        or lower == "open"
        or lower == "ready"
        or "pick-up" in lower
        or "pickup" in lower
        or "lien" in lower
    ):
        return "In Review"
    return None


def _apply_status(repairs: dict, current, expected: Optional[str]) -> Optional[str]:
    if expected is None:
        return None if pd.isna(current) else current

    if pd.isna(current):
        repairs["STATUS_NORMALIZED"] = expected
        repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"
    elif current != expected:
        repairs["STATUS_NORMALIZED"] = expected
        repairs["STATUS_NORMALIZED_FLAG"] = "FIXED"

    return repairs.get("STATUS_NORMALIZED", current)


def _apply_date(repairs: dict, row, field: str, candidate) -> None:
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


# ── Per-record repair ────────────────────────────────────────────────────────

def _repair_hialeah(row, d: dict, repairs: dict) -> tuple[bool, bool]:
    reviews = _as_list(d.get("Reviews"))
    inspections = _as_list(d.get("Inspections"))
    rev_dates = _collect_dates(reviews, "Date Created")
    insp_dates = _collect_dates(inspections, "Date Created")
    has_rev = len(rev_dates) > 0
    has_insp = len(insp_dates) > 0

    expected = _derive_status(d)
    effective_status = _apply_status(repairs, row["STATUS_NORMALIZED"], expected)

    # -- FILE_DATE ← earliest review or inspection Date Created --
    file_cand = _min_date(rev_dates + insp_dates)
    _apply_date(repairs, row, "FILE_DATE", file_cand)

    # -- PERMIT_DATE ← earliest inspection Date Created --
    # Sub-permit / trade "Date Created" is the best issuance proxy in this
    # portal extract (no dedicated Issue Date field).
    permit_cand = _min_date(insp_dates)
    has_permit = permit_cand is not pd.NaT and not pd.isna(permit_cand)
    if has_permit:
        if pd.isna(row["PERMIT_DATE"]):
            if effective_status in ("Active", "Final", "Inactive"):
                repairs["PERMIT_DATE"] = permit_cand
                repairs["PERMIT_DATE_FLAG"] = "FILLED"
        elif not _dates_equal(row["PERMIT_DATE"], permit_cand):
            repairs["PERMIT_DATE"] = permit_cand
            repairs["PERMIT_DATE_FLAG"] = "FIXED"

    # -- FINAL_DATE --
    # Inspections only expose Date Created (creation/issuance of the trade
    # permit), not a finaled/sign-off timestamp. Reviews expose plan-review
    # dates only. No true FINAL_DATE source exists in DATA.
    # Clear only if a non-Final row somehow carries a FINAL_DATE.
    if effective_status != "Final" and not pd.isna(row["FINAL_DATE"]):
        repairs["FINAL_DATE"] = pd.NaT
        repairs["FINAL_DATE_FLAG"] = "FIXED"

    return has_rev, has_insp


# ── Main entry point ─────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Hialeah permit records using information from the raw DATA JSON.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Hialeah".  Must contain
        columns STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, FINAL_DATE,
        and DATA.

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
        if d is None:
            out.at[idx, "INFERRED_SCHEMA"] = "missing"
            continue

        repairs: dict = {}
        has_rev, has_insp = _repair_hialeah(row, d, repairs)
        schema = _classify_schema(d, has_rev, has_insp)
        out.at[idx, "INFERRED_SCHEMA"] = schema
        if schema == "unknown":
            continue

        for key, value in repairs.items():
            out.at[idx, key] = value

    for col in ("FILE_DATE", "PERMIT_DATE", "FINAL_DATE"):
        out[col] = pd.to_datetime(out[col], errors="coerce")

    return out


# ── CLI: run standalone to preview repair stats ──────────────────────────────

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
    city = df[
        (df["JURISDICTION"] == "Hialeah") & (df["STATE"] == "FL")
    ].copy()

    print(f"Hialeah records: {len(city):,}\n")
    repaired = data_repair(city)

    print("INFERRED_SCHEMA:")
    print(repaired["INFERRED_SCHEMA"].value_counts(dropna=False).to_string())
    print()

    for field in ["STATUS_NORMALIZED", "FILE_DATE", "PERMIT_DATE", "FINAL_DATE"]:
        flag_col = f"{field}_FLAG"
        n_filled = (repaired[flag_col] == "FILLED").sum()
        n_fixed = (repaired[flag_col] == "FIXED").sum()
        before_missing = city[field].isna().sum()
        after_missing = repaired[field].isna().sum()
        print(f"{field}:")
        print(f"  FILLED: {n_filled:>4,}   FIXED: {n_fixed:>4,}")
        print(f"  Missing before: {before_missing:>4,}   Missing after: {after_missing:>4,}")
        print()

    print("STATUS_NORMALIZED distribution:")
    print("  Before:")
    for s, c in city["STATUS_NORMALIZED"].value_counts(dropna=False).items():
        print(f"    {str(s):15s}: {c:>4,}")
    print("  After:")
    for s, c in repaired["STATUS_NORMALIZED"].value_counts(dropna=False).items():
        print(f"    {str(s):15s}: {c:>4,}")

    print("\nSTATUS changes:")
    ch = repaired[repaired["STATUS_NORMALIZED_FLAG"].notna()].copy()
    if len(ch):
        ch["BEFORE"] = city.loc[ch.index, "STATUS_NORMALIZED"]
        print(
            ch.groupby(["STATUS_ORIGINAL", "BEFORE", "STATUS_NORMALIZED"], dropna=False)
            .size()
            .to_string()
        )
    else:
        print("  (none)")

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

    if agent_data_path:
        out_path = os.path.join(agent_data_path, "hialeah_repaired_sample.parquet")
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote repaired sample → {out_path}")

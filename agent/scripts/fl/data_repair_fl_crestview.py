"""Data repair for Crestview (FL) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Crestview DATA is a flat MyGovernmentOnline (MGO) project payload
(``ProjectStatus``, ``DateCreated``, ``DateIssued``, applicant/site
fields, etc.). Two layout variants appear:

  - mgo_ppm:   includes ``PaymentProcessorModule`` (typically ``MGO``)
  - mgo_base:  same key set without ``PaymentProcessorModule``
  - missing / unknown

Canonical mappings:
  - ProjectStatus (whitespace-stripped) → STATUS_NORMALIZED
  - DateCreated                         → FILE_DATE
  - DateIssued (when not the .NET
    sentinel ``0001-01-01``)            → PERMIT_DATE
  - (no final/sign-off timestamp in
    DATA)                               → FINAL_DATE unavailable

Status values observed:
  - Project Closed/Complete → Final
  - Permit Issued → Active
  - Pending (Under Review) → In Review
  - Expired / Cancelled → Inactive

Known issues / sample findings:
  - STATUS_NORMALIZED already matches ProjectStatus for every sample
    row (0 fills / fixes needed).
  - FILE_DATE already equals DateCreated (calendar day) on all rows.
  - DateIssued is the sentinel ``0001-01-01T00:00:00`` on every sample
    row → PERMIT_DATE cannot be filled for Active/Final.
  - No finaled / completion / CO date field exists → FINAL_DATE cannot
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
    """Parse a date value, returning pd.NaT on failure / sentinel / OOR year."""
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
        # MGO / .NET sentinel for "no date"
        if s.startswith("0001-01-01"):
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


def _normalize_project_status(raw) -> str:
    if raw is None or (isinstance(raw, str) and not str(raw).strip()):
        return ""
    return str(raw).replace("\t", " ").strip()


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())
    if "ProjectStatus" not in keys or "DateCreated" not in keys:
        return "unknown"
    if "PaymentProcessorModule" in keys:
        return "mgo_ppm"
    return "mgo_base"


# ── Status mapping ───────────────────────────────────────────────────────────

# ProjectStatus (stripped) → STATUS_NORMALIZED
_STATUS_MAP = {
    # Final / completed
    "Project Closed/Complete": "Final",
    "Closed": "Final",
    # Active / issued
    "Permit Issued": "Active",
    "Issued": "Active",
    # In review / pre-issuance
    "Pending (Under Review)": "In Review",
    "Open": "In Review",
    "In Review": "In Review",
    # Inactive
    "Expired": "Inactive",
    "Cancelled": "Inactive",
}


def _derive_status(d: dict) -> Optional[str]:
    raw = _normalize_project_status(d.get("ProjectStatus"))
    if not raw:
        return None
    if raw in _STATUS_MAP:
        return _STATUS_MAP[raw]

    # Case-insensitive fallback for minor portal casing variants.
    lower_map = {k.lower(): v for k, v in _STATUS_MAP.items()}
    if raw.lower() in lower_map:
        return lower_map[raw.lower()]

    lower = raw.lower()
    if "administratively" in lower:
        return "Inactive"
    if "coc" in lower or "co issued" in lower or "final" in lower:
        return "Final"
    if "closed" in lower or "complete" in lower:
        return "Final"
    if "issued" in lower and "ready" not in lower:
        return "Active"
    if (
        "expire" in lower
        or "void" in lower
        or "terminat" in lower
        or "withdraw" in lower
        or "cancel" in lower
        or "denied" in lower
    ):
        return "Inactive"
    if "pending" in lower or "review" in lower or "hold" in lower or lower == "open":
        return "In Review"
    if "active" in lower:
        return "Active"
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

def _repair_mgo(row, d: dict, repairs: dict) -> None:
    expected = _derive_status(d)
    effective_status = _apply_status(repairs, row["STATUS_NORMALIZED"], expected)

    # -- FILE_DATE ← DateCreated --
    _apply_date(repairs, row, "FILE_DATE", d.get("DateCreated"))

    # -- PERMIT_DATE ← DateIssued when real (sample: always sentinel) --
    issued = _safe_to_datetime(d.get("DateIssued"))
    has_issued = issued is not pd.NaT and not pd.isna(issued)
    if has_issued:
        if pd.isna(row["PERMIT_DATE"]):
            if effective_status in ("Active", "Final"):
                repairs["PERMIT_DATE"] = issued
                repairs["PERMIT_DATE_FLAG"] = "FILLED"
        elif not _dates_equal(row["PERMIT_DATE"], issued):
            repairs["PERMIT_DATE"] = issued
            repairs["PERMIT_DATE_FLAG"] = "FIXED"

    # -- FINAL_DATE --
    # No finaled / completion / CO timestamp exists in the Crestview MGO
    # payload (DateUpdated is also the .NET sentinel on every sample row).
    # Clear only if a non-Final row somehow carries a FINAL_DATE.
    if effective_status != "Final" and not pd.isna(row["FINAL_DATE"]):
        repairs["FINAL_DATE"] = pd.NaT
        repairs["FINAL_DATE_FLAG"] = "FIXED"


# ── Main entry point ─────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Crestview permit records using information from the raw DATA JSON.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Crestview".  Must contain
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
        schema = _classify_schema(d)
        out.at[idx, "INFERRED_SCHEMA"] = schema
        if d is None or schema == "unknown":
            continue

        repairs: dict = {}
        _repair_mgo(row, d, repairs)
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
        (df["JURISDICTION"] == "Crestview") & (df["STATE"] == "FL")
    ].copy()

    print(f"Crestview records: {len(city):,}\n")
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
    ch = repaired[repaired["STATUS_NORMALIZED_FLAG"].notna()][
        ["STATUS_ORIGINAL", "STATUS_NORMALIZED"]
    ].copy()
    if len(ch):
        ch["BEFORE"] = city.loc[ch.index, "STATUS_NORMALIZED"]
        print(
            ch.groupby(["STATUS_ORIGINAL", "BEFORE", "STATUS_NORMALIZED"])
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
        out_path = os.path.join(agent_data_path, "crestview_repaired_sample.parquet")
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote repaired sample → {out_path}")

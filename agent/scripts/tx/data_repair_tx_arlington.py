"""Data repair for Arlington (TX) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Arlington DATA has two payload families plus null scrapes:

  - underscore_*:  legacy portal rows with ``STATUS``,
                   ``Application_Date``, ``Issue_Date`` (and people /
                   zoning / construction key variants)
  - spaced_*:      newer portal rows with ``Status``,
                   ``Application Date``, ``Issued``, ``Expiry Date``
                   (and zoning / sewer / event / minimal variants)
  - missing:       no usable DATA JSON

Canonical mappings:
  - STATUS / Status     → STATUS_NORMALIZED
  - Application_Date /
    Application Date    → FILE_DATE
  - Issue_Date / Issued → PERMIT_DATE
  - (no final-date field in DATA) → FINAL_DATE left as-is for Final;
    cleared on non-Final when present

Known issues repaired:
  - Spurious FINAL_DATE on Active / Inactive spaced rows copied from
    ``Expiry Date`` (permit expiration, not completion/signoff) → cleared.
  - Occasional PERMIT_DATE mismatch vs ``Issued`` → FIXED to Issued.

Not repairable from DATA:
  - 312 rows with missing DATA (FILE_DATE stays missing; Final rows that
    already carry FINAL_DATE are left unchanged).
  - Underscore ``Finaled`` rows (758) have no completion/signoff date
    field → FINAL_DATE stays missing.
  - Active row with blank ``Issued`` → PERMIT_DATE stays missing.
"""

from __future__ import annotations

import json
import math
from typing import Optional

import numpy as np
import pandas as pd


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
    """Parse a date value, returning pd.NaT on failure / blanks / sentinels."""
    if val is None:
        return pd.NaT
    if isinstance(val, float) and math.isnan(val):
        return pd.NaT
    if not isinstance(val, str) and pd.isna(val):
        return pd.NaT
    if isinstance(val, dict):
        return pd.NaT
    text = str(val).strip()
    if not text or text.upper() in {
        "TBD", "NONE", "N/A", "NA", "NULL", "NAN",
        "00/00/0000", "0/0/0000",
    }:
        return pd.NaT
    try:
        dt = pd.to_datetime(val, errors="coerce")
    except (ValueError, TypeError, OverflowError):
        return pd.NaT
    if pd.isna(dt):
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


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())

    # Underscore family: STATUS / Application_Date / Issue_Date
    if "STATUS" in keys or "Application_Date" in keys or "Issue_Date" in keys:
        if "FOLDERRSN" in keys:
            return "underscore_folderrsn"
        if "Building_SqFt" in keys:
            return "underscore_building"
        if "Construction_SqFt" in keys or "Construction_Valuation" in keys:
            return "underscore_construction"
        if "Zoning_District" in keys or "FDesc" in keys:
            return "underscore_zoning"
        if "WORK" in keys or "Sub" in keys or "SubDivision" in keys:
            return "underscore_work_sub"
        return "underscore_minimal"

    # Spaced family: Status / Application Date / Issued
    if "Status" in keys or "Application Date" in keys or "Issued" in keys:
        if "Address" not in keys:
            return "spaced_minimal"
        if "End Date of Event" in keys or "Start Date of Event" in keys:
            return "spaced_event"
        if "What type of Sewer Service at this property?" in keys:
            return "spaced_sewer"
        if "Zoning District" in keys:
            return "spaced_zoning"
        if "Construction Valuation-Declared" in keys or "Construction Square Footage" in keys:
            return "spaced_valuation"
        return "spaced_core"

    return "unknown"


# ── Status mapping ───────────────────────────────────────────────────────────

_UNDERSCORE_STATUS_MAP = {
    "Finaled": "Final",
    "Issued": "Active",
    "Void": "Inactive",
    "Expired": "Inactive",
}

_SPACED_STATUS_MAP = {
    "Active": "Active",
    "Issued": "Active",
    "Expired": "Inactive",
    "InActive": "Inactive",
    "Pending": "In Review",
}


def _expected_status(d: dict, schema: str) -> Optional[str]:
    if schema.startswith("underscore"):
        raw = d.get("STATUS")
        if raw is None or (isinstance(raw, float) and math.isnan(raw)):
            return None
        return _UNDERSCORE_STATUS_MAP.get(str(raw).strip())
    if schema.startswith("spaced"):
        raw = d.get("Status")
        if raw is None or (isinstance(raw, float) and math.isnan(raw)):
            return None
        return _SPACED_STATUS_MAP.get(str(raw).strip())
    return None


def _apply_status(repairs: dict, current, expected: Optional[str]):
    """Apply expected STATUS_NORMALIZED; return effective status."""
    if expected is None:
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


def _clear_date(repairs: dict, row, field: str) -> None:
    """Clear a spurious date value."""
    current = repairs.get(field, row[field])
    if pd.isna(current):
        return
    repairs[field] = pd.NaT
    repairs[f"{field}_FLAG"] = "FIXED"


def _file_date_candidate(d: dict, schema: str):
    if schema.startswith("underscore"):
        return d.get("Application_Date")
    if schema.startswith("spaced"):
        return d.get("Application Date")
    return None


def _permit_date_candidate(d: dict, schema: str):
    if schema.startswith("underscore"):
        return d.get("Issue_Date")
    if schema.startswith("spaced"):
        return d.get("Issued")
    return None


# ── Per-row repair ───────────────────────────────────────────────────────────

def _repair_row(row, d: dict, schema: str, repairs: dict) -> None:
    """Repair one Arlington underscore_* / spaced_* record."""
    expected = _expected_status(d, schema)
    effective_status = _apply_status(repairs, row["STATUS_NORMALIZED"], expected)

    # -- FILE_DATE ← Application_Date / Application Date --
    _apply_date(repairs, row, "FILE_DATE", _file_date_candidate(d, schema))

    # -- PERMIT_DATE ← Issue_Date / Issued (authoritative when present) --
    _apply_date(repairs, row, "PERMIT_DATE", _permit_date_candidate(d, schema))

    # -- FINAL_DATE: no completion field in DATA; clear spurious non-Final --
    if effective_status == "Final":
        # Nothing to fill from DATA (no Final/Completed/Close date key).
        pass
    else:
        _clear_date(repairs, row, "FINAL_DATE")


# ── Main entry point ─────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Arlington permit records using the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Arlington".  Must contain
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

    for col in ("FILE_DATE", "PERMIT_DATE", "FINAL_DATE"):
        out[col] = pd.to_datetime(out[col], errors="coerce")

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
        if schema.startswith("underscore") or schema.startswith("spaced"):
            _repair_row(row, d, schema, repairs)

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
    filepath = os.path.join(MY_DATA_PATH, "processed_data", "permits_tx_sample.parquet")
    df = pd.read_parquet(filepath)
    city = df[(df["JURISDICTION"] == "Arlington") & (df["STATE"] == "TX")].copy()

    print(f"Arlington records: {len(city):,}\n")

    repaired = data_repair(city)

    print("INFERRED_SCHEMA distribution:")
    for s, c in repaired["INFERRED_SCHEMA"].value_counts(dropna=False).items():
        print(f"  {str(s):35s}: {c:>4,}")
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

    print("\nFILE_DATE overall (after): "
          f"{repaired['FILE_DATE'].notna().sum()}/{len(repaired)}")

    print("\nPERMIT_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        if len(sub) == 0:
            continue
        n_has = sub["PERMIT_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({n_has / len(sub):.1%})")

    print("\nFINAL_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        if len(sub) == 0:
            continue
        n_has = sub["FINAL_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({n_has / len(sub):.1%})")

    if AGENT_DATA_PATH:
        out_dir = os.path.join(AGENT_DATA_PATH, "repaired")
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, "permits_tx_arlington_repaired.parquet")
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote {out_path}")

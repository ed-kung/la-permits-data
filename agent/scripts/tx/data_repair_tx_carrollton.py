"""Data repair for Carrollton (TX) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Carrollton DATA is an Accela / CitizenAccess-style case payload with a
shared ``Summary`` block and one of two permit containers:

  - permits:          Locations? + Permits (list) + Summary
  - permits_project:  same as permits + ``project_id``
  - permit_info:      Locations? + Permit Info (dict) + Summary
  - missing / unknown

Canonical mappings:
  - Summary.Application Status → STATUS_NORMALIZED
  - Summary.Application Date   → FILE_DATE
  - Summary.Issued Date        → PERMIT_DATE
  - Summary.Date Finaled       → FINAL_DATE (Final only;
    years outside 1900–2035 treated as sentinel / invalid)

Known issues repaired:
  - STATUS_NORMALIZED missing for uncommon Application Status /
    STATUS_ORIGINAL values (Returned for Correction; invalid license
    on a Closed case) → FILLED.
  - STATUS_NORMALIZED stale vs Application Status (STATUS_ORIGINAL
    lagged: Closed still ``permit(s) issued`` / ``ready for issuance``
    / ``pending`` / ``in plan check``; Expired still ``permit(s)
    issued``; Permit(s) Issued still ``pending`` / ``in plan check``)
    → FIXED.
  - Missing PERMIT_DATE when Issued Date is present → FILLED.
  - Missing FINAL_DATE on Final rows with a usable Date Finaled →
    FILLED.
  - Spurious FINAL_DATE on non-Final rows (Active / Inactive that
    still carry Date Finaled) → cleared (FIXED).

Not repairable / left as-is:
  - FILE_DATE already matches Application Date on all sample rows.
  - Active / Final rows with no Issued Date → PERMIT_DATE stays
    missing (rare Closed rows).
  - Most Final (Closed) rows omit Date Finaled even when Permit Status
    is Finaled; no alternate completion timestamp exists → FINAL_DATE
    stays missing.
  - Date Finaled values in 2090–2099 are portal sentinels and are not
    written into FINAL_DATE.
"""

from __future__ import annotations

import json
import math
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
        try:
            parsed = json.loads(data)
        except (json.JSONDecodeError, TypeError):
            return None
        return parsed if isinstance(parsed, dict) else None
    return data if isinstance(data, dict) else None


def _safe_to_datetime(val):
    """Parse a date value, returning pd.NaT on failure / blanks / OOR year."""
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


def _summary(d: dict) -> dict:
    s = d.get("Summary")
    return s if isinstance(s, dict) else {}


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())
    if "Summary" not in keys:
        return "unknown"
    if "Permits" in keys:
        if "project_id" in keys:
            return "permits_project"
        return "permits"
    if "Permit Info" in keys:
        return "permit_info"
    return "unknown"


# ── Status mapping ───────────────────────────────────────────────────────────

_STATUS_MAP = {
    # Final
    "Closed": "Final",
    # Active
    "Permit(s) Issued": "Active",
    # In Review
    "Ready for Issuance": "In Review",
    "In Plan Check": "In Review",
    "On Hold": "In Review",
    "Returned for Correction": "In Review",
    # Inactive
    "Expired": "Inactive",
    "Withdrawn": "Inactive",
    "Denied": "Inactive",
    "Canceled": "Inactive",
    "Closed - Incomplete Submittal": "Inactive",
}


def _expected_status(d: dict) -> Optional[str]:
    app = _summary(d).get("Application Status")
    if app is None or (isinstance(app, float) and math.isnan(app)):
        return None
    key = str(app).strip()
    if not key:
        return None
    if key in _STATUS_MAP:
        return _STATUS_MAP[key]
    lower_map = {k.lower(): v for k, v in _STATUS_MAP.items()}
    return lower_map.get(key.lower())


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


# ── Per-row repair ───────────────────────────────────────────────────────────

def _repair_row(row, d: dict, repairs: dict) -> None:
    """Repair one Carrollton Summary + Permits / Permit Info record."""
    summary = _summary(d)
    expected = _expected_status(d)
    effective_status = _apply_status(repairs, row["STATUS_NORMALIZED"], expected)

    # -- FILE_DATE ← Application Date --
    _apply_date(repairs, row, "FILE_DATE", summary.get("Application Date"))

    # -- PERMIT_DATE ← Issued Date --
    _apply_date(repairs, row, "PERMIT_DATE", summary.get("Issued Date"))

    # -- FINAL_DATE ← Date Finaled (Final only; reject 209x sentinels) --
    if effective_status == "Final":
        _apply_date(repairs, row, "FINAL_DATE", summary.get("Date Finaled"))
    else:
        _clear_date(repairs, row, "FINAL_DATE")


# ── Main entry point ─────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Carrollton permit records using the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Carrollton".  Must contain
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

    known = {"permits", "permits_project", "permit_info"}

    for idx in out.index:
        row = out.loc[idx]
        d = _safe_parse(row["DATA"])
        schema = _classify_schema(d)
        out.at[idx, "INFERRED_SCHEMA"] = schema
        if d is None:
            continue

        repairs: dict = {}
        if schema in known:
            _repair_row(row, d, repairs)

        for key, value in repairs.items():
            out.at[idx, key] = value

    return out


# ── CLI: run standalone to preview repair stats ─────────────────────────────

if __name__ == "__main__":
    import os
    from pathlib import Path

    from dotenv import load_dotenv

    repo_root = Path(__file__).resolve().parents[3]
    load_dotenv(repo_root / ".env")
    MY_DATA_PATH = os.getenv("MY_DATA_PATH")
    AGENT_DATA_PATH = os.getenv("AGENT_DATA_PATH")
    filepath = os.path.join(MY_DATA_PATH, "processed_data", "permits_tx_sample.parquet")
    df = pd.read_parquet(filepath)
    city = df[(df["JURISDICTION"] == "Carrollton") & (df["STATE"] == "TX")].copy()

    print(f"Carrollton records: {len(city):,}\n")

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

        if field.endswith("DATE"):
            before_missing = pd.to_datetime(city[field], errors="coerce").isna().sum()
        else:
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
        out_path = os.path.join(out_dir, "permits_tx_carrollton_repaired.parquet")
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote {out_path}")

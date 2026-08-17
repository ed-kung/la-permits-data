"""Data repair for Southlake (TX) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Southlake DATA is a CivicPlus / EnerGov-style case payload. Two top-level
key-set variants appear in the sample (both share the same ``entity`` /
``details`` date and status fields used for repair):

  - entity_core:  contacts, details, entity, fees, processing_status
  - entity_rich:  entity_core + attachments, holds, more_info, reviews

Canonical mappings:
  - entity.CaseStatus                         → STATUS_NORMALIZED
  - entity.ApplyDate (else details.ApplyDate) → FILE_DATE
  - entity.IssueDate (else details.IssueDate) → PERMIT_DATE
  - entity.FinalDate (else details.FinalizeDate)
                                              → FINAL_DATE (Final only)

Known issues repaired:
  - STATUS_NORMALIZED missing for ``1st Letter Issued`` (6) → FILLED
    as Inactive (notice-letter / non-permit workflow).
  - STATUS_NORMALIZED lagging STATUS_ORIGINAL while CaseStatus has
    already advanced (Closed / CO Issued still "Active"; Expired still
    "Active"; Issued still "In Review"/"Inactive"; Withdrawn still
    "In Review") → FIXED from CaseStatus.
  - Missing PERMIT_DATE on Issued / Closed rows that carry IssueDate
    → FILLED.
  - Missing FINAL_DATE on Closed / CO Issued rows that carry FinalDate
    / FinalizeDate while still labeled Active → FILLED after status fix.
  - Spurious FINAL_DATE on non-Final rows (Issued / Submitted / Expired
    / Withdrawn / etc. often carry FinalDate, frequently equal to
    ApplyDate as a portal stub) → cleared (FIXED).

Not repairable / left as-is:
  - FILE_DATE already equals ApplyDate (calendar day) on every sample
    row; no FILE_DATE changes expected.
  - Active/Final rows with null IssueDate (contractor registration /
    earth disturbance / irrigation shells, etc.) → PERMIT_DATE stays
    missing.
  - processing_status is null on nearly every sample row (no inspection
    fallback).
"""

from __future__ import annotations

import json
import math
from typing import Optional

import numpy as np
import pandas as pd


# ── Helpers ──────────────────────────────────────────────────────────────────

_MIN_YEAR = 1900
_MAX_YEAR = 2035


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


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())
    if not ({"entity", "details", "contacts", "processing_status"} <= keys):
        return "unknown"
    rich_extras = {"attachments", "holds", "more_info", "reviews"}
    if rich_extras <= keys:
        return "entity_rich"
    if "fees" in keys:
        return "entity_core"
    return "entity_minimal"


def _entity(d: dict) -> dict:
    ent = d.get("entity")
    return ent if isinstance(ent, dict) else {}


def _details(d: dict) -> dict:
    det = d.get("details")
    return det if isinstance(det, dict) else {}


def _first_date(*vals):
    """Return the first parseable datetime among *vals."""
    for val in vals:
        dt = _safe_to_datetime(val)
        if dt is not pd.NaT and not pd.isna(dt):
            return dt
    return pd.NaT


# ── Status mapping ───────────────────────────────────────────────────────────

_STATUS_MAP = {
    # Final
    "Closed": "Final",
    "CO Issued": "Final",
    # Active
    "Issued": "Active",
    "Renewed": "Active",
    # In Review
    "In Review": "In Review",
    "Incomplete": "In Review",
    "Submitted": "In Review",
    "Submitted - Online": "In Review",
    "Reviewed": "In Review",
    "On Hold": "In Review",
    "Stop Work Order": "In Review",
    # Inactive
    "Withdrawn": "Inactive",
    "Expired": "Inactive",
    # Notice-letter / non-permit workflow (Backflow 1st letter)
    "1st Letter Issued": "Inactive",
}


def _expected_status(d: dict) -> Optional[str]:
    cs = _entity(d).get("CaseStatus")
    if cs is None or (isinstance(cs, float) and math.isnan(cs)):
        return None
    key = str(cs).strip()
    return _STATUS_MAP.get(key)


def _apply_date_candidate(d: dict):
    """Prefer entity.ApplyDate; then details.ApplyDate."""
    ent = _entity(d)
    det = _details(d)
    return _first_date(ent.get("ApplyDate"), det.get("ApplyDate"))


def _issue_date_candidate(d: dict):
    """Prefer entity.IssueDate; then details.IssueDate."""
    ent = _entity(d)
    det = _details(d)
    return _first_date(ent.get("IssueDate"), det.get("IssueDate"))


def _final_date_candidate(d: dict):
    """Prefer entity.FinalDate; then details.FinalizeDate."""
    ent = _entity(d)
    det = _details(d)
    return _first_date(ent.get("FinalDate"), det.get("FinalizeDate"))


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


def _clear_invalid_permit_date(repairs: dict, row) -> None:
    """Clear PERMIT_DATE when it is a sentinel / out-of-range year."""
    current = repairs.get("PERMIT_DATE", row["PERMIT_DATE"])
    if pd.isna(current):
        return
    try:
        raw = pd.to_datetime(current, errors="coerce")
    except (ValueError, TypeError, OverflowError):
        return
    if pd.isna(raw):
        return
    if getattr(raw, "tzinfo", None) is not None:
        raw = raw.tz_convert("UTC").tz_localize(None)
    year = int(raw.year)
    if year < _MIN_YEAR or year > _MAX_YEAR:
        _clear_date(repairs, row, "PERMIT_DATE")


# ── Per-row repair ───────────────────────────────────────────────────────────

def _repair_row(row, d: dict, repairs: dict) -> None:
    """Repair one Southlake entity_* record."""
    expected = _expected_status(d)
    effective_status = _apply_status(repairs, row["STATUS_NORMALIZED"], expected)

    # -- FILE_DATE ← ApplyDate --
    _apply_date(repairs, row, "FILE_DATE", _apply_date_candidate(d))

    # -- PERMIT_DATE ← IssueDate --
    issue = _issue_date_candidate(d)
    if issue is not pd.NaT and not pd.isna(issue):
        _apply_date(repairs, row, "PERMIT_DATE", issue)
    else:
        _clear_invalid_permit_date(repairs, row)

    # -- FINAL_DATE ← FinalDate / FinalizeDate (Final only) --
    if effective_status == "Final":
        _apply_date(repairs, row, "FINAL_DATE", _final_date_candidate(d))
    else:
        _clear_date(repairs, row, "FINAL_DATE")


# ── Main entry point ─────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Southlake permit records using the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Southlake".  Must contain
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
        if schema in {"entity_core", "entity_rich", "entity_minimal"}:
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
    city = df[(df["JURISDICTION"] == "Southlake") & (df["STATE"] == "TX")].copy()

    print(f"Southlake records: {len(city):,}\n")

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

    print("\nSTATUS changes:")
    ch_mask = repaired["STATUS_NORMALIZED_FLAG"].notna()
    if ch_mask.any():
        ch = pd.DataFrame({
            "STATUS_ORIGINAL": city.loc[ch_mask, "STATUS_ORIGINAL"],
            "BEFORE": city.loc[ch_mask, "STATUS_NORMALIZED"],
            "AFTER": repaired.loc[ch_mask, "STATUS_NORMALIZED"],
            "FLAG": repaired.loc[ch_mask, "STATUS_NORMALIZED_FLAG"],
        })
        print(ch.groupby(["STATUS_ORIGINAL", "BEFORE", "AFTER", "FLAG"]).size().to_string())
    else:
        print("  (none)")

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

    # Date-order checks
    f = repaired["FILE_DATE"]
    p = repaired["PERMIT_DATE"]
    fin = repaired["FINAL_DATE"]
    fp = ((f.notna()) & (p.notna()) & (f.dt.normalize() > p.dt.normalize())).sum()
    pf = ((p.notna()) & (fin.notna()) & (p.dt.normalize() > fin.dt.normalize())).sum()
    ff = ((f.notna()) & (fin.notna()) & (f.dt.normalize() > fin.dt.normalize())).sum()
    print(f"\nDate-order violations: FILE>PERMIT={fp}, PERMIT>FINAL={pf}, FILE>FINAL={ff}")

    if AGENT_DATA_PATH:
        out_dir = os.path.join(AGENT_DATA_PATH, "repaired")
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, "permits_tx_southlake_repaired.parquet")
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote {out_path}")

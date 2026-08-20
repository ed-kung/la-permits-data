"""Data repair for Kyle (TX) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Kyle DATA is a CivicPlus / EnerGov-style case payload with two top-level
key sets:

  - entity_core:  contacts, details, entity, fees, processing_status
  - entity_rich:  entity_core + attachments, holds, more_info, reviews

Canonical mappings:
  - details.PermitStatus when Complete, else
    entity.CaseStatus                         → STATUS_NORMALIZED
  - entity.ApplyDate                          → FILE_DATE
  - entity.IssueDate (else details.IssueDate) → PERMIT_DATE
  - entity.FinalDate (else details.FinalizeDate)
                                              → FINAL_DATE (Final only)

Known issues repaired:
  - STATUS_NORMALIZED lagging portal status when CaseStatus / PermitStatus
    already say Complete while STATUS_ORIGINAL still says issued / expired
    → FIXED to Final; FINAL_DATE filled from FinalDate / FinalizeDate.
  - STATUS_NORMALIZED lagging when portal says Issued but STATUS_ORIGINAL
    still says in review (or CaseStatus still In Review while
    PermitStatus is already Issued) → FIXED to Active; PERMIT_DATE
    filled from IssueDate.
  - STATUS_NORMALIZED lagging when portal says Expired but STATUS_ORIGINAL
    still says issued → FIXED to Inactive; spurious FINAL_DATE cleared.
  - Spurious FINAL_DATE on non-Final rows (Issued / Plan Approval Expired)
    → cleared (FIXED).

Not repairable / left as-is:
  - FILE_DATE already equals entity.ApplyDate (calendar day) on every row.
  - Issued / Complete rows with Issued=False and null IssueDate →
    PERMIT_DATE stays missing.
  - One Complete row with null FinalDate and FinalizeDate → FINAL_DATE
    stays missing.
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


def _status_key(val) -> str:
    if val is None:
        return ""
    if isinstance(val, float) and math.isnan(val):
        return ""
    return str(val).strip()


# ── Status mapping ───────────────────────────────────────────────────────────

_STATUS_MAP = {
    # Final
    "Complete": "Final",
    "Closed": "Final",
    # Active
    "Issued": "Active",
    # In Review
    "Submitted": "In Review",
    "Submitted - Online": "In Review",
    "In Review": "In Review",
    "Plan Approved": "In Review",
    "On Hold": "In Review",
    "Requires Resubmittal": "In Review",
    "Review Approved": "In Review",
    # Inactive
    "Void": "Inactive",
    "Expired": "Inactive",
    "Plan Approval Expired": "Inactive",
    "Denied": "Inactive",
}

_FINAL_PORTAL_STATUSES = {
    "Complete",
}

_ACTIVE_PORTAL_STATUSES = {
    "Issued",
}


def _expected_status(d: dict) -> Optional[str]:
    """Derive STATUS_NORMALIZED from PermitStatus / CaseStatus.

    Prefer Final, then Active, portal statuses on either field
    (details.PermitStatus can advance ahead of entity.CaseStatus).
    Otherwise map entity.CaseStatus, falling back to PermitStatus.
    """
    ent = _entity(d)
    det = _details(d)
    cs_key = _status_key(ent.get("CaseStatus"))
    ps_key = _status_key(det.get("PermitStatus"))

    if ps_key in _FINAL_PORTAL_STATUSES or cs_key in _FINAL_PORTAL_STATUSES:
        return "Final"
    if ps_key in _ACTIVE_PORTAL_STATUSES or cs_key in _ACTIVE_PORTAL_STATUSES:
        return "Active"
    if cs_key:
        return _STATUS_MAP.get(cs_key)
    if ps_key:
        return _STATUS_MAP.get(ps_key)
    return None


def _issue_date_candidate(d: dict):
    """Prefer entity.IssueDate; then details.IssueDate."""
    ent = _entity(d)
    det = _details(d)
    issue = _safe_to_datetime(ent.get("IssueDate"))
    if issue is not pd.NaT and not pd.isna(issue):
        return issue
    return _safe_to_datetime(det.get("IssueDate"))


def _final_date_candidate(d: dict):
    """Prefer entity.FinalDate; then details.FinalizeDate."""
    ent = _entity(d)
    det = _details(d)
    final = _safe_to_datetime(ent.get("FinalDate"))
    if final is not pd.NaT and not pd.isna(final):
        return final
    return _safe_to_datetime(det.get("FinalizeDate"))


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
    """Repair one Kyle entity_* record."""
    ent = _entity(d)
    expected = _expected_status(d)
    effective_status = _apply_status(repairs, row["STATUS_NORMALIZED"], expected)

    # -- FILE_DATE ← ApplyDate (entity local time matches existing FILE_DATE) --
    _apply_date(repairs, row, "FILE_DATE", ent.get("ApplyDate"))

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
    Kyle permit records using the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Kyle".  Must contain
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

    # Cast to ns so sub-second portal timestamps (FinalizeDate) assign cleanly.
    for col in ("FILE_DATE", "PERMIT_DATE", "FINAL_DATE"):
        out[col] = pd.to_datetime(out[col], errors="coerce").astype("datetime64[ns]")

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
    city = df[(df["JURISDICTION"] == "Kyle") & (df["STATE"] == "TX")].copy()

    print(f"Kyle records: {len(city):,}\n")

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
    flagged = repaired[repaired["STATUS_NORMALIZED_FLAG"].notna()].copy()
    if len(flagged):
        flagged["BEFORE"] = city.loc[flagged.index, "STATUS_NORMALIZED"]
        flagged["STATUS_ORIGINAL"] = city.loc[flagged.index, "STATUS_ORIGINAL"]
        print(
            flagged.groupby(
                ["STATUS_ORIGINAL", "BEFORE", "STATUS_NORMALIZED", "STATUS_NORMALIZED_FLAG"]
            )
            .size()
            .to_string()
        )
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
        out_path = os.path.join(out_dir, "permits_tx_kyle_repaired.parquet")
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote {out_path}")

"""Data repair for Cedar Hill (TX) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Cedar Hill DATA is a CivicPlus / EnerGov-style case payload. Every sample
row shares the same top-level key set:

  - entity_rich:  attachments, contacts, details, entity, fees, holds,
                  more_info, processing_status, reviews
  - missing / unknown

Canonical mappings:
  - details.PermitStatus when Complete, else
    entity.CaseStatus                         → STATUS_NORMALIZED
  - entity.ApplyDate                          → FILE_DATE
  - entity.IssueDate                          → PERMIT_DATE
  - entity.FinalDate (else details.FinalizeDate)
                                              → FINAL_DATE (Final only;
    years outside 1900–2035 / ``2999-01-01`` treated as sentinel)

Known issues repaired:
  - STATUS_NORMALIZED lagged on STATUS_ORIGINAL ``issued`` while
    CaseStatus is Complete (3) or Void (1), or while PermitStatus is
    Complete with CaseStatus still Issued (20) → FIXED to Final /
    Inactive.
  - Missing FINAL_DATE on rows remapped to Final that carry FinalizeDate
    or FinalDate → FILLED.
  - Spurious FINAL_DATE on Active (Issued) rows that still carry a
    portal FinalDate (often equal to IssueDate) → cleared (FIXED).

Not repairable / left as-is:
  - FILE_DATE already matches ApplyDate on all sample rows.
  - Active / Final rows with IssueDate sentinel ``2999-01-01`` (27
    Active, 1 Final) → PERMIT_DATE stays missing.
  - Final (Complete) rows whose FinalDate / FinalizeDate are the
    ``2999-01-01`` sentinel (4) → FINAL_DATE stays missing.
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
    required = {"entity", "details", "contacts", "processing_status"}
    if not (required <= keys):
        return "unknown"
    rich_extras = {"attachments", "holds", "more_info", "reviews", "fees"}
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


# ── Status mapping ───────────────────────────────────────────────────────────

_STATUS_MAP = {
    # Final
    "Complete": "Final",
    "Finaled": "Final",
    # Active
    "Issued": "Active",
    # In Review
    "In Review": "In Review",
    "Submitted - Online": "In Review",
    "Submitted": "In Review",
    "On Hold": "In Review",
    "Stop Work Order": "In Review",
    # Inactive
    "Expired": "Inactive",
    "Void": "Inactive",
    "Denied": "Inactive",
    "Plan Approval Expired": "Inactive",
}


def _expected_status(d: dict) -> Optional[str]:
    """Derive STATUS_NORMALIZED from PermitStatus / CaseStatus.

    Prefer ``Complete`` on either field (details.PermitStatus can advance
    ahead of entity.CaseStatus). Otherwise map entity.CaseStatus.
    """
    ent = _entity(d)
    det = _details(d)
    cs = ent.get("CaseStatus")
    ps = det.get("PermitStatus")

    cs_key = str(cs).strip() if cs is not None and not (
        isinstance(cs, float) and math.isnan(cs)
    ) else ""
    ps_key = str(ps).strip() if ps is not None and not (
        isinstance(ps, float) and math.isnan(ps)
    ) else ""

    if ps_key == "Complete" or cs_key == "Complete":
        return "Final"
    if cs_key:
        return _STATUS_MAP.get(cs_key)
    if ps_key:
        return _STATUS_MAP.get(ps_key)
    return None


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
    """Repair one Cedar Hill entity_* record."""
    ent = _entity(d)
    expected = _expected_status(d)
    effective_status = _apply_status(repairs, row["STATUS_NORMALIZED"], expected)

    # -- FILE_DATE ← ApplyDate --
    _apply_date(repairs, row, "FILE_DATE", ent.get("ApplyDate"))

    # -- PERMIT_DATE ← IssueDate --
    issue = _safe_to_datetime(ent.get("IssueDate"))
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
    Cedar Hill permit records using the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Cedar Hill".  Must contain
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
    city = df[(df["JURISDICTION"] == "Cedar Hill") & (df["STATE"] == "TX")].copy()

    print(f"Cedar Hill records: {len(city):,}\n")

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
        out_path = os.path.join(out_dir, "permits_tx_cedar_hill_repaired.parquet")
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote {out_path}")

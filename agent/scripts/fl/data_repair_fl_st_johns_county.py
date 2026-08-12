"""Data repair for St. Johns County (FL) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

St. Johns County DATA is a Civic/Accela-style portal payload with a
canonical ``Permit Main`` block on every row, plus ``Charges``,
``Associated``, and ``Inspections``. Richer scrapes also include
``Project Data`` and ``Project Holds``.

Canonical fields:

  - Permit Main.status (+ IssueDt / ComplDt / BL FNL inspection fallbacks)
      → STATUS_NORMALIZED
  - (no application / submittal date in DATA) → FILE_DATE cannot be filled
  - Permit Main.IssueDt                       → PERMIT_DATE
  - Permit Main.ComplDt (fallback permit_date when it is not IssueDt)
                                              → FINAL_DATE

Key-set variants (INFERRED_SCHEMA prefixes):
  - portal_full:  Project Data + Project Holds present
  - portal_basic: Permit Main without Project Data / Project Holds

Content suffixes further split by which canonical dates are populated
(``_issued_finaled``, ``_issued``, ``_finaled``, ``_status_only``).

Known issues repaired:
  - STATUS_NORMALIZED almost entirely null: Cert Compl / Cert Occ never
    mapped to Final; Admin Close never mapped to Inactive; empty-status
    rows with ComplDt → Final, with IssueDt only → Active, with BL FNL
    but no dates → Final → FILLED.
  - FILE_DATE was incorrectly copied from IssueDt (issuance) → cleared
    (FIXED). No true application/submittal date exists in DATA.
  - PERMIT_DATE was incorrectly copied from permit_date / ComplDt
    (completion) → overwritten with IssueDt (FIXED / FILLED).
  - FINAL_DATE already matched ComplDt when present; fills remaining
    Final rows from permit_date when ComplDt is blank; clears FINAL_DATE
    on non-Final statuses (Inactive Admin Close / Expired / Voided).

Not repairable from DATA:
  - FILE_DATE: no application / filed / submitted field in the payload.
  - ~30 sparse portal_basic rows with empty status and no IssueDt /
    ComplDt / BL FNL → STATUS_NORMALIZED left null.
  - Final rows with neither ComplDt nor a distinct permit_date →
    FINAL_DATE stays missing.
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
    """Parse a date value, returning pd.NaT on failure / sentinel / OOR."""
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


def _permit_main(d: dict) -> dict:
    pm = d.get("Permit Main")
    return pm if isinstance(pm, dict) else {}


def _has_approved_building_final(d: dict) -> bool:
    insp = d.get("Inspections")
    if not isinstance(insp, list):
        return False
    for item in insp:
        if not isinstance(item, dict):
            continue
        desc = str(item.get("AprvDesc") or "").strip().upper()
        result = str(item.get("Result") or "").strip().lower()
        if desc == "BL FNL" and result.startswith("approv"):
            return True
    return False


def _extract_fields(d: dict):
    """Return (raw_status, issued, finaled).

    FILE / application date is intentionally omitted — St. Johns County
    DATA has no filed/submitted/applied stamp.
    """
    pm = _permit_main(d)
    raw = pm.get("status")
    if isinstance(raw, str):
        raw = raw.strip()
    else:
        raw = None

    issued = _safe_to_datetime(pm.get("IssueDt"))

    finaled = _safe_to_datetime(pm.get("ComplDt"))
    if finaled is pd.NaT or pd.isna(finaled):
        # permit_date mirrors ComplDt when both exist; when ComplDt is
        # blank on Cert Compl rows it still holds the completion stamp.
        # Never treat it as final if it equals IssueDt.
        pdate = _safe_to_datetime(pm.get("permit_date"))
        if pdate is not pd.NaT and not pd.isna(pdate) and not _dates_equal(pdate, issued):
            finaled = pdate

    # Project Holds.CODt is the same completion stamp when present.
    if finaled is pd.NaT or pd.isna(finaled):
        ph = d.get("Project Holds")
        if isinstance(ph, dict):
            codt = _safe_to_datetime(ph.get("CODt"))
            if codt is not pd.NaT and not pd.isna(codt) and not _dates_equal(codt, issued):
                finaled = codt

    return raw, issued, finaled


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())
    if "Permit Main" not in keys:
        return "unknown"

    if "Project Data" in keys or "Project Holds" in keys:
        base = "portal_full"
    else:
        base = "portal_basic"

    _, issued, finaled = _extract_fields(data_dict)
    has_issued = issued is not pd.NaT and not pd.isna(issued)
    has_final = finaled is not pd.NaT and not pd.isna(finaled)

    if has_issued and has_final:
        return f"{base}_issued_finaled"
    if has_issued:
        return f"{base}_issued"
    if has_final:
        return f"{base}_finaled"
    return f"{base}_status_only"


# ── Status mapping ───────────────────────────────────────────────────────────

_STATUS_MAP = {
    "Cert Compl": "Final",
    "Cert Occ": "Final",
    "Admin Close": "Inactive",
    "Expired": "Inactive",
    "Voided": "Inactive",
}


def _expected_status(raw_status: Optional[str], issued, finaled, d: dict) -> Optional[str]:
    raw = (raw_status or "").strip()
    if raw:
        if raw in _STATUS_MAP:
            return _STATUS_MAP[raw]
        for key, val in _STATUS_MAP.items():
            if key.lower() == raw.lower():
                return val
        return None

    # Empty Permit Main.status — infer from dates / final inspection.
    # ComplDt (or equivalent) is required for Final when status is blank;
    # an approved BL FNL inspection alone with IssueDt still present is
    # treated as Active (final inspection ≠ certificate/close).
    has_final = finaled is not pd.NaT and not pd.isna(finaled)
    has_issued = issued is not pd.NaT and not pd.isna(issued)
    if has_final:
        return "Final"
    if has_issued:
        return "Active"
    if _has_approved_building_final(d):
        return "Final"
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
        return
    if not _dates_equal(current, cand):
        repairs[field] = cand
        repairs[f"{field}_FLAG"] = "FIXED"


def _clear_date(repairs: dict, row, field: str) -> None:
    current = repairs.get(field, row[field])
    if pd.isna(current):
        return
    repairs[field] = pd.NaT
    repairs[f"{field}_FLAG"] = "FIXED"


# ── Per-record repair ────────────────────────────────────────────────────────

def _repair_record(row, d: dict, repairs: dict) -> None:
    raw_status, issued, finaled = _extract_fields(d)
    expected = _expected_status(raw_status, issued, finaled, d)
    effective_status = _apply_status(repairs, row["STATUS_NORMALIZED"], expected)

    # FILE_DATE: DATA has no application/submittal stamp. Existing values
    # were incorrectly copied from IssueDt — clear those.
    if not pd.isna(row["FILE_DATE"]) and _dates_equal(row["FILE_DATE"], issued):
        _clear_date(repairs, row, "FILE_DATE")

    # PERMIT_DATE ← IssueDt for issued / completed / inactive statuses.
    if issued is not pd.NaT and not pd.isna(issued):
        if effective_status in ("Active", "Final", "Inactive"):
            _apply_date(repairs, row, "PERMIT_DATE", issued)
        elif effective_status == "In Review":
            _clear_date(repairs, row, "PERMIT_DATE")
    elif effective_status == "In Review":
        _clear_date(repairs, row, "PERMIT_DATE")

    # FINAL_DATE ← ComplDt / permit_date for Final only; clear otherwise.
    if effective_status == "Final":
        if finaled is not pd.NaT and not pd.isna(finaled):
            _apply_date(repairs, row, "FINAL_DATE", finaled)
    else:
        _clear_date(repairs, row, "FINAL_DATE")


# ── Main entry point ─────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    St. Johns County permit records using the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "St. Johns County".  Must
        contain columns STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE,
        FINAL_DATE, and DATA.

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
        if d is None or schema == "unknown":
            continue

        repairs: dict = {}
        _repair_record(row, d, repairs)
        for key, value in repairs.items():
            out.at[idx, key] = value

    for col in ("FILE_DATE", "PERMIT_DATE", "FINAL_DATE"):
        out[col] = pd.to_datetime(out[col], errors="coerce")

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
    city = df[df["JURISDICTION"] == "St. Johns County"].copy()

    print(f"St. Johns County records: {len(city):,}\n")

    repaired = data_repair(city)

    print("INFERRED_SCHEMA:")
    for s, c in repaired["INFERRED_SCHEMA"].value_counts(dropna=False).items():
        print(f"  {str(s):40s}: {c:>4,}")
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

    print("\nFILE_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FILE_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({(n_has / len(sub) if len(sub) else 0):.1%})")

    print("\nPERMIT_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["PERMIT_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({(n_has / len(sub) if len(sub) else 0):.1%})")

    print("\nFINAL_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FINAL_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({(n_has / len(sub) if len(sub) else 0):.1%})")

    if AGENT_DATA_PATH:
        out_path = os.path.join(AGENT_DATA_PATH, "st_johns_county_repaired_sample.parquet")
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote repaired sample → {out_path}")

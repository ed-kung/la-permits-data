"""Data repair for La Porte (TX) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

La Porte DATA is a municipal building-permit portal payload with two
top-level key-set variants:

  - permit_full:       ``detail`` + ``permit_status`` /
                       ``permit_status_detail`` + ``insp_status`` /
                       ``insp_status_detail`` (+ fees)
  - application_only:  ``detail`` + fees only (no permit / inspection block)
  - missing / unknown

Canonical mappings:
  - permit_full: ``permit_status_detail['Status for Permit Number']``
                 → STATUS_NORMALIZED
  - application_only: ``detail['Application Status']``
                 → STATUS_NORMALIZED
  - ``detail['Application Date']``            → FILE_DATE
  - ``permit_status_detail['Issue Date']``
    (fallback: ``Permit Date``)              → PERMIT_DATE
  - last APPROVED row in ``insp_status_detail``
    (date column index 3, else 1)            → FINAL_DATE

Known issues / sample findings:
  - 109 rows missing STATUS_NORMALIZED (101 application_only + 8
    permit_full with null STATUS_ORIGINAL) → FILLED from status fields.
  - 5 permit_full rows where STATUS_NORMALIZED disagrees with
    ``Status for Permit Number`` (stale STATUS_ORIGINAL) → FIXED.
  - FILE_DATE already equals Application Date on all sample rows.
  - Upstream PERMIT_DATE usually copied ``Permit Date``, which is often a
    later status-update stamp *after* final inspection. Canonical issuance
    stamp is ``Issue Date`` → FIXED for most Final rows; fall back to
    ``Permit Date`` when Issue Date is blank.
  - FINAL_DATE for Final rows usually equals the last APPROVED
    inspection date; ~400+ CLOSED Final rows have empty inspection
    lists and no final timestamp in DATA → not fillable.
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
        "00/00/0000", "0/0/0000", "00/00/00", "0/0/00",
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


def _detail(d: dict) -> dict:
    det = d.get("detail")
    return det if isinstance(det, dict) else {}


def _permit_status_detail(d: dict) -> dict:
    psd = d.get("permit_status_detail")
    return psd if isinstance(psd, dict) else {}


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())
    if "detail" not in keys:
        return "unknown"
    if "permit_status" in keys or "permit_status_detail" in keys:
        return "permit_full"
    return "application_only"


# ── Status mapping ───────────────────────────────────────────────────────────

# permit_status_detail["Status for Permit Number"] (uppercased / stripped)
_PERMIT_STATUS_MAP = {
    "PERMIT PRINTED": "Active",
    "CLOSED": "Final",
    "FINAL INSPECTION COMPLETE": "Final",
    "C.O. ISSUED": "Final",
    "TEMPORARY C.O. ISSUED": "Final",
    "TO BE ISSUED": "In Review",
    "PLAN CHECK": "In Review",
    "PERMIT REVOKED": "Inactive",
}

# detail["Application Status"] — used when no permit block exists
_APP_STATUS_MAP = {
    "COMPLETE - NO CO NEEDED": "Final",
    "CERT. OF OCCUPANCY": "Final",
    "ADMIN. PERMIT CLOSED": "Final",
    "PERMIT ISSUED": "Active",
    "APPROVED - READY TO ISSUE": "In Review",
    "PLAN REVIEW PROCESS": "In Review",
    "APPL./INSP.  ON HOLD": "In Review",  # double space as in source
    "APPL./INSP. ON HOLD": "In Review",
    "APPL. IS VOIDED/DELETED": "Inactive",
    "APPL. IS REJECTED": "Inactive",
}


def _expected_status(d: dict, schema: str) -> Optional[str]:
    if schema == "permit_full":
        raw = _permit_status_detail(d).get("Status for Permit Number")
        key = str(raw).strip().upper() if raw not in (None, "") else ""
        if key:
            return _PERMIT_STATUS_MAP.get(key)
        # Rare: permit block present but status blank — fall back to app status
    raw_app = _detail(d).get("Application Status")
    app_key = str(raw_app).strip().upper() if raw_app not in (None, "") else ""
    return _APP_STATUS_MAP.get(app_key) if app_key else None


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


def _iter_insp_rows(isd) -> list:
    """Yield inspection rows ``[label, date_a, result, date_b]`` from DATA."""
    rows = []
    if not isinstance(isd, list):
        return rows
    for block in isd:
        if not isinstance(block, list) or not block:
            continue
        if isinstance(block[0], str):
            rows.append(block)
        else:
            for item in block:
                if isinstance(item, list) and item:
                    rows.append(item)
    return rows


def _last_approved_inspection_date(d: dict):
    """Latest APPROVED inspection date (prefer 4th column, else 2nd)."""
    best = pd.NaT
    for row in _iter_insp_rows(d.get("insp_status_detail")):
        if len(row) < 3:
            continue
        result = str(row[2]).upper()
        if "APPROV" not in result:
            continue
        d3 = _safe_to_datetime(row[3]) if len(row) > 3 else pd.NaT
        d1 = _safe_to_datetime(row[1]) if len(row) > 1 else pd.NaT
        cand = d3 if d3 is not pd.NaT and not pd.isna(d3) else d1
        if cand is pd.NaT or pd.isna(cand):
            continue
        if best is pd.NaT or pd.isna(best) or cand > best:
            best = cand
    return best


def _permit_date_candidate(d: dict):
    """Prefer Issue Date (issuance); fall back to Permit Date."""
    psd = _permit_status_detail(d)
    issue_dt = _safe_to_datetime(psd.get("Issue Date"))
    if issue_dt is not pd.NaT and not pd.isna(issue_dt):
        return issue_dt
    return _safe_to_datetime(psd.get("Permit Date"))


def _file_date_candidate(d: dict):
    det = _detail(d)
    app_dt = _safe_to_datetime(det.get("Application Date"))
    if app_dt is not pd.NaT and not pd.isna(app_dt):
        return app_dt
    return _safe_to_datetime(_permit_status_detail(d).get("Application Date"))


# ── Per-row repair ───────────────────────────────────────────────────────────

def _repair_row(row, d: dict, schema: str, repairs: dict) -> None:
    """Repair one La Porte permit record."""
    expected = _expected_status(d, schema)
    effective_status = _apply_status(repairs, row["STATUS_NORMALIZED"], expected)

    # -- FILE_DATE --
    _apply_date(repairs, row, "FILE_DATE", _file_date_candidate(d))

    # -- PERMIT_DATE --
    # Issue Date is the issuance stamp; Permit Date is often updated later
    # (frequently after final inspection) and is only a fallback.
    permit_cand = _permit_date_candidate(d)
    if effective_status in ("Active", "Final"):
        _apply_date(repairs, row, "PERMIT_DATE", permit_cand)

    # -- FINAL_DATE --
    if effective_status == "Final":
        _apply_date(repairs, row, "FINAL_DATE", _last_approved_inspection_date(d))
    else:
        _clear_date(repairs, row, "FINAL_DATE")


# ── Main entry point ─────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    La Porte permit records using the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "La Porte".  Must contain
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
        if d is None or schema in {"missing", "unknown"}:
            continue

        repairs: dict = {}
        _repair_row(row, d, schema, repairs)

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
    city = df[(df["JURISDICTION"] == "La Porte") & (df["STATE"] == "TX")].copy()

    print(f"La Porte records: {len(city):,}\n")

    repaired = data_repair(city)

    print("INFERRED_SCHEMA distribution:")
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
        out_path = os.path.join(out_dir, "permits_tx_la_porte_repaired.parquet")
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote {out_path}")

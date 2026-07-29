"""Data repair for Truckee (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Truckee DATA is a legacy Logos / citizen portal payload with top-level
keys ``Permit Summary``, ``Payment Summary``, ``Permit Details``,
``Inspections``, ``Location``, ``Notes``, ``Conditions``,
``CONTACT INFORMATION``, and ``GENERAL CONSTRUCTION``. Every sample row
uses the same key set (``INFERRED_SCHEMA = "portal"``); optional Lathrop-
style sections (Business Valuation, Certificate of Occupancy, etc.) do
not appear in this extract.

Canonical fields:
  - Permit Summary.StatusValue          → STATUS_NORMALIZED (+ embedded date)
  - StatusValue Created / Pending date  → FILE_DATE
  - StatusValue Issued date; else PaidValue → PERMIT_DATE (Active/Final)
  - StatusValue Completed date          → FINAL_DATE

Known issues repaired:
  - StatusValue/STATUS_NORMALIZED mismatches: Completed→Active (13) or
    In Review (2), Issued→In Review (7) → FIXED.
  - Created / Pending rows missing FILE_DATE → FILLED from StatusValue;
    two Created/Pending rows whose FILE_DATE disagreed with StatusValue
    → FIXED.
  - Issued rows missing PERMIT_DATE (after status fix from In Review) →
    FILLED from Issued StatusValue date.
  - Completed/Final rows missing PERMIT_DATE → FILLED from PaidValue when
    payment is on or before the completion date.
  - Completed mislabeled Active/In Review missing FINAL_DATE → FILLED
    from Completed StatusValue date.

Not repairable / left as-is:
  - Issued / Completed FILE_DATE: no application/submittal date in
    StatusValue (Issued/Completed dates are not filing dates). A few
    Issued/Completed rows already carry earlier FILE_DATE values and are
    retained.
  - Three undated ``Permit Created`` StatusValues → FILE_DATE stays
    missing.
  - Completed rows where PaidValue is after the completion date, or
    PaidValue is missing / "Not paid" → PERMIT_DATE stays missing
    (9 Final rows in sample).
  - Inspections shells in this extract are empty (no usable dates).
"""

from __future__ import annotations

import json
import math
import re
from typing import Optional

import numpy as np
import pandas as pd


_MIN_YEAR = 1990
_MAX_YEAR = 2035

_SV_DATE_RE = re.compile(
    r"(?P<label>Permit Completed|Permit Issued|Permit Created|"
    r"Application Created|Pending Payment|Pending Review|"
    r"Permit Expired)"
    r".*?\b(?P<date>\d{1,2}/\d{1,2}/\d{2,4})\b",
    re.IGNORECASE,
)


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
        return json.loads(data)
    return data


def _safe_to_datetime(val):
    """Parse a date value, returning pd.NaT on failure or implausible year."""
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return pd.NaT
    if isinstance(val, str):
        s = val.strip()
        if not s or s.upper() == "TBD" or s.lower() == "not paid":
            return pd.NaT
    try:
        dt = pd.to_datetime(val)
    except (ValueError, TypeError):
        return pd.NaT
    if dt is pd.NaT or pd.isna(dt):
        return pd.NaT
    if getattr(dt, "tzinfo", None) is not None:
        dt = dt.tz_convert("UTC").tz_localize(None)
    year = int(dt.year)
    if year < _MIN_YEAR or year > _MAX_YEAR:
        return pd.NaT
    return dt


def _dates_equal(a, b) -> bool:
    da = _safe_to_datetime(a)
    db = _safe_to_datetime(b)
    if da is pd.NaT or db is pd.NaT:
        return False
    return da.normalize() == db.normalize()


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())
    if "Permit Summary" not in keys:
        return "unknown"

    has_bv = "Business Valuation" in keys
    has_prod = "Permit Category" in keys or "Production Permits" in keys
    has_coo = "Certificate of Occupancy" in keys

    if has_bv and has_prod and has_coo:
        return "portal_bv_prod_coo"
    if has_bv and has_prod:
        return "portal_bv_prod"
    if has_prod:
        return "portal_prod"
    if has_bv and has_coo:
        return "portal_coo"
    if has_bv:
        return "portal_bv"
    if has_coo:
        return "portal_coo"
    return "portal"


def _set_status(repairs: dict, row, expected: str):
    current = row["STATUS_NORMALIZED"]
    if pd.isna(current):
        repairs["STATUS_NORMALIZED"] = expected
        repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"
    elif current != expected:
        repairs["STATUS_NORMALIZED"] = expected
        repairs["STATUS_NORMALIZED_FLAG"] = "FIXED"


def _fill_date(repairs: dict, row, field: str, value):
    if value is pd.NaT or pd.isna(value):
        return
    if pd.isna(row[field]):
        repairs[field] = value
        repairs[f"{field}_FLAG"] = "FILLED"


def _fix_date(repairs: dict, row, field: str, value):
    if value is pd.NaT or pd.isna(value):
        return
    current = row[field]
    if pd.isna(current):
        repairs[field] = value
        repairs[f"{field}_FLAG"] = "FILLED"
    elif not _dates_equal(current, value):
        repairs[field] = value
        repairs[f"{field}_FLAG"] = "FIXED"


def _clear_date(repairs: dict, row, field: str):
    if not pd.isna(row[field]):
        repairs[field] = pd.NaT
        repairs[f"{field}_FLAG"] = "FIXED"


# ── StatusValue parsing ──────────────────────────────────────────────────────

def _parse_status_value(sv: str):
    """Return (kind, embedded_date) from Permit Summary.StatusValue."""
    if not sv or not isinstance(sv, str):
        return None, pd.NaT
    text = sv.strip()
    low = text.lower()

    kind = None
    if "expired" in low:
        kind = "expired"
    elif "completed" in low:
        kind = "completed"
    elif "issued" in low:
        kind = "issued"
    elif "pending" in low:
        kind = "pending"
    elif "created" in low:
        kind = "created"

    m = _SV_DATE_RE.search(text)
    if m:
        return kind, _safe_to_datetime(m.group("date"))

    # Fallback: any MM/DD/YYYY in the string (covers "Permit Expired MM/DD/YYYY")
    m2 = re.search(r"(\d{1,2}/\d{1,2}/\d{2,4})", text)
    dt = _safe_to_datetime(m2.group(1)) if m2 else pd.NaT
    return kind, dt


def _expected_status(kind: Optional[str]) -> Optional[str]:
    return {
        "completed": "Final",
        "issued": "Active",
        "pending": "In Review",
        "created": "In Review",
        "expired": "Inactive",
    }.get(kind)


# ── Per-record repair ────────────────────────────────────────────────────────

def _repair_portal(row, d: dict, repairs: dict):
    summary = d.get("Permit Summary") or {}
    payment = d.get("Payment Summary") or {}
    sv = summary.get("StatusValue") or ""
    kind, sv_dt = _parse_status_value(sv)
    paid_dt = _safe_to_datetime(payment.get("PaidValue"))

    expected = _expected_status(kind)
    if expected is not None:
        _set_status(repairs, row, expected)

    effective = repairs.get("STATUS_NORMALIZED", row["STATUS_NORMALIZED"])

    # FILE_DATE: application / created / pending-as-of date only.
    # Issued / Completed / Expired StatusValue dates are not filing dates.
    if kind in ("created", "pending") and sv_dt is not pd.NaT:
        if pd.isna(row["FILE_DATE"]):
            _fill_date(repairs, row, "FILE_DATE", sv_dt)
        elif not _dates_equal(row["FILE_DATE"], sv_dt):
            _fix_date(repairs, row, "FILE_DATE", sv_dt)

    # PERMIT_DATE for Active / Final
    if effective in ("Active", "Final"):
        permit_src = pd.NaT
        if kind == "issued" and sv_dt is not pd.NaT:
            permit_src = sv_dt
        elif paid_dt is not pd.NaT:
            # PaidValue is the best issuance proxy when StatusValue is Completed.
            final_ref = sv_dt if kind == "completed" else _safe_to_datetime(
                row["FINAL_DATE"]
            )
            if final_ref is pd.NaT or paid_dt.normalize() <= final_ref.normalize():
                permit_src = paid_dt
        if permit_src is not pd.NaT:
            if pd.isna(row["PERMIT_DATE"]):
                _fill_date(repairs, row, "PERMIT_DATE", permit_src)
            elif kind == "issued" and not _dates_equal(row["PERMIT_DATE"], permit_src):
                _fix_date(repairs, row, "PERMIT_DATE", permit_src)

    # FINAL_DATE for Completed → Final
    if kind == "completed" and sv_dt is not pd.NaT:
        if repairs.get("STATUS_NORMALIZED", row["STATUS_NORMALIZED"]) == "Final":
            if pd.isna(row["FINAL_DATE"]):
                _fill_date(repairs, row, "FINAL_DATE", sv_dt)
            elif not _dates_equal(row["FINAL_DATE"], sv_dt):
                _fix_date(repairs, row, "FINAL_DATE", sv_dt)

    # Clear FINAL_DATE on non-Final portal rows
    eff = repairs.get("STATUS_NORMALIZED", row["STATUS_NORMALIZED"])
    if eff != "Final":
        _clear_date(repairs, row, "FINAL_DATE")


# ── Main entry point ─────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Truckee permit records using information from the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Truckee". Must contain
        columns STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, FINAL_DATE,
        and DATA.

    Returns
    -------
    pd.DataFrame
        Copy of *df* with corrected field values, an INFERRED_SCHEMA column
        naming the DATA JSON sub-schema identified for each record, and new
        flag columns: STATUS_NORMALIZED_FLAG, FILE_DATE_FLAG,
        PERMIT_DATE_FLAG, FINAL_DATE_FLAG. Flag values are "FILLED"
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

        if schema.startswith("portal"):
            _repair_portal(row, d, repairs)

        for key, value in repairs.items():
            out.at[idx, key] = value

    # Normalize repaired date columns to datetime64 (avoid mixed date/Timestamp).
    for col in ("FILE_DATE", "PERMIT_DATE", "FINAL_DATE"):
        out[col] = pd.to_datetime(out[col], errors="coerce")

    return out


# ── CLI: run standalone to preview repair stats ──────────────────────────────

if __name__ == "__main__":
    import os
    from dotenv import load_dotenv

    load_dotenv("/Users/ekung/projects/la-permits-data/.env")
    MY_DATA_PATH = os.getenv("MY_DATA_PATH")
    AGENT_DATA_PATH = os.getenv("AGENT_DATA_PATH")
    filepath = os.path.join(MY_DATA_PATH, "processed_data", "permits_ca_sample.parquet")
    df = pd.read_parquet(filepath)
    city = df[(df["JURISDICTION"] == "Truckee") & (df["STATE"] == "CA")].copy()

    print(f"Truckee records: {len(city):,}\n")

    repaired = data_repair(city)

    print("INFERRED_SCHEMA:")
    print(repaired["INFERRED_SCHEMA"].value_counts(dropna=False).to_string())
    print()

    summary_rows = []
    for field in ["STATUS_NORMALIZED", "FILE_DATE", "PERMIT_DATE", "FINAL_DATE"]:
        flag_col = f"{field}_FLAG"
        n_filled = int((repaired[flag_col] == "FILLED").sum())
        n_fixed = int((repaired[flag_col] == "FIXED").sum())
        before_missing = int(city[field].isna().sum())
        after_missing = int(repaired[field].isna().sum())
        print(f"{field}:")
        print(f"  FILLED: {n_filled:>4,}   FIXED: {n_fixed:>4,}")
        print(f"  Missing before: {before_missing:>4,}   Missing after: {after_missing:>4,}")
        print()
        summary_rows.append({
            "field": field,
            "filled": n_filled,
            "fixed": n_fixed,
            "missing_before": before_missing,
            "missing_after": after_missing,
        })

    print("STATUS_NORMALIZED distribution:")
    print("  Before:")
    for s, c in city["STATUS_NORMALIZED"].value_counts(dropna=False).items():
        print(f"    {str(s):15s}: {c:>4,}")
    print("  After:")
    for s, c in repaired["STATUS_NORMALIZED"].value_counts(dropna=False).items():
        print(f"    {str(s):15s}: {c:>4,}")

    print("\nFINAL_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FINAL_DATE"].notna().sum()
        n = len(sub)
        pct = n_has / n if n else 0.0
        print(f"  {status:15s}: {n_has:>4,} / {n:>4,} ({pct:.1%})")

    print("\nPERMIT_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["PERMIT_DATE"].notna().sum()
        n = len(sub)
        pct = n_has / n if n else 0.0
        print(f"  {status:15s}: {n_has:>4,} / {n:>4,} ({pct:.1%})")

    print("\nFILE_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FILE_DATE"].notna().sum()
        n = len(sub)
        pct = n_has / n if n else 0.0
        print(f"  {status:15s}: {n_has:>4,} / {n:>4,} ({pct:.1%})")

    if AGENT_DATA_PATH:
        out_csv = os.path.join(AGENT_DATA_PATH, "truckee_repair_summary.csv")
        pd.DataFrame(summary_rows).to_csv(out_csv, index=False)
        print(f"\nWrote summary: {out_csv}")

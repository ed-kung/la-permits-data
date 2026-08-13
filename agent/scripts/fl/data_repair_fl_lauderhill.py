"""Data repair for Lauderhill (FL) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Lauderhill DATA has a single schema in this sample:

  - permit_bundle: nested payload with permit_info, inspection_info,
                   plan_info, fee_info, owner_info, applicant_info,
                   general_contractor_info, miscellaneous_info,
                   property_on_permit_info

Canonical mappings (from permit_info / inspection_info):
  - Status (+ Issued Date for Open)     → STATUS_NORMALIZED
  - Application Date                    → FILE_DATE
  - Issued Date                         → PERMIT_DATE
  - C.O. Issued, else passed Final
    inspection, else last passed insp   → FINAL_DATE

Known issues repaired:
  - Open permits that already have Issued Date were mapped to
    In Review; they are FIXED to Active (issued / under inspection).
  - Final (Closed) rows almost all lack FINAL_DATE; upstream only
    copied C.O. Issued (~45 rows). FILLED from C.O. Issued when
    present, else a passed inspection whose TYPE contains "FINAL",
    else the latest passed inspection INSP DATE.
  - One Open row had a spurious FINAL_DATE from C.O. Issued → cleared.

Not repairable / left as-is:
  - 8 rows with blank permit_info.Status (and blank Issued Date /
    empty inspection RES codes) → STATUS_NORMALIZED stays null.
  - 2 rows with blank Application Date → FILE_DATE stays missing.
  - PERMIT_DATE already matches Issued Date when both present; rows
    without Issued Date (90 Closed, 184 Open, 27 Inactive, 8 blank)
    stay missing.
  - Closed / Final rows with neither C.O. Issued nor a dated passed
    inspection stay missing FINAL_DATE.
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
    """Parse a date value, returning pd.NaT on failure / blanks / OOR."""
    if val is None:
        return pd.NaT
    if isinstance(val, float) and math.isnan(val):
        return pd.NaT
    if isinstance(val, str):
        text = val.strip().replace("\xa0", " ")
        if not text:
            return pd.NaT
        if text.upper() in {
            "TBD", "NONE", "N/A", "NA", "NULL", "NAN",
            "00/00/0000", "0/0/0000",
        }:
            return pd.NaT
        if text.startswith("0001-01-01") or text.startswith("1900-01-01"):
            return pd.NaT
    elif not isinstance(val, str) and pd.isna(val):
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


def _present(dt) -> bool:
    return dt is not pd.NaT and not pd.isna(dt)


def _dates_equal(a, b) -> bool:
    """Compare two datelike values at calendar-day resolution."""
    da = _safe_to_datetime(a)
    db = _safe_to_datetime(b)
    if not _present(da) or not _present(db):
        return False
    return pd.Timestamp(da).normalize() == pd.Timestamp(db).normalize()


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())
    if "permit_info" in keys:
        return "permit_bundle"
    return "unknown"


def _permit_info(d: dict) -> dict:
    pi = d.get("permit_info")
    return pi if isinstance(pi, dict) else {}


# ── Status mapping ───────────────────────────────────────────────────────────

# Direct Status → STATUS_NORMALIZED (Open handled separately when issued).
_STATUS_MAP = {
    "Closed": "Final",
    "Open": "In Review",  # overridden to Active when Issued Date present
    "Hold": "In Review",
    "Expired": "Inactive",
    "Void": "Inactive",
    "Reject": "Inactive",
}


def _expected_status(raw_status: Optional[str], issued) -> Optional[str]:
    if raw_status is None:
        return None
    text = str(raw_status).strip()
    if not text:
        return None
    if text == "Open" and _present(_safe_to_datetime(issued)):
        return "Active"
    return _STATUS_MAP.get(text)


def _apply_status(repairs: dict, current, expected: Optional[str]) -> Optional[str]:
    """Apply expected STATUS_NORMALIZED; return effective status."""
    if expected is None:
        if pd.isna(current):
            return None
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
    if not _present(cand):
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


def _insp_date(insp: dict):
    """Prefer INSP DATE; fall back to SCHED DATE."""
    dt = _safe_to_datetime(insp.get("INSP DATE"))
    if _present(dt):
        return dt
    return _safe_to_datetime(insp.get("SCHED DATE"))


def _last_passed_final_inspection(d: dict):
    """Latest date among passed inspections whose TYPE has 'FINAL'."""
    dates = []
    for insp in d.get("inspection_info") or []:
        if not isinstance(insp, dict):
            continue
        typ = str(insp.get("TYPE") or "")
        res = str(insp.get("RES") or "").strip().upper()
        if res != "P":
            continue
        if "FINAL" not in typ.upper():
            continue
        dt = _insp_date(insp)
        if _present(dt):
            dates.append(dt)
    return max(dates) if dates else pd.NaT


def _last_passed_inspection(d: dict):
    """Latest date among any passed inspection (RES == 'P')."""
    dates = []
    for insp in d.get("inspection_info") or []:
        if not isinstance(insp, dict):
            continue
        res = str(insp.get("RES") or "").strip().upper()
        if res != "P":
            continue
        dt = _insp_date(insp)
        if _present(dt):
            dates.append(dt)
    return max(dates) if dates else pd.NaT


def _final_date_from_data(d: dict, pi: dict):
    """Prefer C.O. Issued; else passed Final inspection; else last pass."""
    co = _safe_to_datetime(pi.get("C.O. Issued"))
    if _present(co):
        return co
    final_insp = _last_passed_final_inspection(d)
    if _present(final_insp):
        return final_insp
    return _last_passed_inspection(d)


# ── Per-schema repair logic ─────────────────────────────────────────────────

def _repair_permit_bundle(row, d: dict, repairs: dict) -> None:
    """Repair a permit_bundle record."""
    pi = _permit_info(d)
    raw_status = pi.get("Status")
    issued = _safe_to_datetime(pi.get("Issued Date"))
    expected = _expected_status(raw_status, pi.get("Issued Date"))
    effective_status = _apply_status(repairs, row["STATUS_NORMALIZED"], expected)

    # -- FILE_DATE ← Application Date --
    _apply_date(repairs, row, "FILE_DATE", pi.get("Application Date"))

    # -- PERMIT_DATE ← Issued Date --
    if _present(issued):
        if pd.isna(row["PERMIT_DATE"]):
            if effective_status in ("Active", "Final"):
                repairs["PERMIT_DATE"] = issued
                repairs["PERMIT_DATE_FLAG"] = "FILLED"
        elif not _dates_equal(row["PERMIT_DATE"], issued):
            repairs["PERMIT_DATE"] = issued
            repairs["PERMIT_DATE_FLAG"] = "FIXED"

    # -- FINAL_DATE ← C.O. Issued / passed Final insp / last pass --
    final_src = _final_date_from_data(d, pi)
    if effective_status == "Final":
        if _present(final_src):
            _apply_date(repairs, row, "FINAL_DATE", final_src)
    else:
        _clear_date(repairs, row, "FINAL_DATE")


# ── Main entry point ─────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Lauderhill permit records using information from the raw DATA JSON.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Lauderhill".  Must contain
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
        if d is None or schema in ("missing", "unknown"):
            continue

        repairs: dict = {}
        if schema == "permit_bundle":
            _repair_permit_bundle(row, d, repairs)

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
    filepath = os.path.join(
        MY_DATA_PATH, "processed_data", "permits_fl_sample.parquet"
    )
    df = pd.read_parquet(filepath)
    city = df[df["JURISDICTION"] == "Lauderhill"].copy()

    print(f"Lauderhill records: {len(city):,}\n")

    repaired = data_repair(city)

    print("INFERRED_SCHEMA:")
    print(repaired["INFERRED_SCHEMA"].value_counts(dropna=False).to_string())
    print()

    for field in ["STATUS_NORMALIZED", "FILE_DATE", "PERMIT_DATE", "FINAL_DATE"]:
        flag_col = f"{field}_FLAG"
        n_filled = (repaired[flag_col] == "FILLED").sum()
        n_fixed = (repaired[flag_col] == "FIXED").sum()
        print(f"{field}:")
        print(f"  FILLED: {n_filled:>4,}   FIXED: {n_fixed:>4,}")

        before_missing = city[field].isna().sum()
        after_missing = repaired[field].isna().sum()
        print(
            f"  Missing before: {before_missing:>4,}   "
            f"Missing after: {after_missing:>4,}"
        )
        print()

    print("STATUS_NORMALIZED distribution:")
    print("  Before:")
    for s, c in city["STATUS_NORMALIZED"].value_counts(dropna=False).items():
        print(f"    {str(s):15s}: {c:>4,}")
    print("  After:")
    for s, c in repaired["STATUS_NORMALIZED"].value_counts(dropna=False).items():
        print(f"    {str(s):15s}: {c:>4,}")

    print("\nSTATUS_NORMALIZED changes (before → after):")
    changed = city["STATUS_NORMALIZED"].fillna("__NA__") != repaired[
        "STATUS_NORMALIZED"
    ].fillna("__NA__")
    if changed.any():
        tmp = pd.DataFrame(
            {
                "before": city.loc[changed, "STATUS_NORMALIZED"].fillna("__NA__"),
                "after": repaired.loc[changed, "STATUS_NORMALIZED"].fillna("__NA__"),
            }
        )
        print(tmp.value_counts().to_string())
    else:
        print("  (none)")

    print("\nFILE_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FILE_DATE"].notna().sum()
        pct = n_has / len(sub) if len(sub) else 0.0
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({pct:.1%})")

    print("\nPERMIT_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["PERMIT_DATE"].notna().sum()
        pct = n_has / len(sub) if len(sub) else 0.0
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({pct:.1%})")

    print("\nFINAL_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FINAL_DATE"].notna().sum()
        pct = n_has / len(sub) if len(sub) else 0.0
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({pct:.1%})")

    final_miss = repaired[
        (repaired["STATUS_NORMALIZED"] == "Final") & repaired["FINAL_DATE"].isna()
    ]
    print(f"\nFinal still missing FINAL_DATE: {len(final_miss)}")

    status_null = repaired["STATUS_NORMALIZED"].isna().sum()
    print(f"STATUS_NORMALIZED still null: {status_null}")

    af_miss = repaired[
        repaired["STATUS_NORMALIZED"].isin(["Active", "Final"])
        & repaired["PERMIT_DATE"].isna()
    ]
    print(f"Active/Final still missing PERMIT_DATE: {len(af_miss)}")

    file_gt_permit = 0
    permit_gt_final = 0
    for idx in repaired.index:
        f = repaired.at[idx, "FILE_DATE"]
        p = repaired.at[idx, "PERMIT_DATE"]
        fin = repaired.at[idx, "FINAL_DATE"]
        if (
            pd.notna(f)
            and pd.notna(p)
            and pd.Timestamp(f).normalize() > pd.Timestamp(p).normalize()
        ):
            file_gt_permit += 1
        if (
            pd.notna(p)
            and pd.notna(fin)
            and pd.Timestamp(p).normalize() > pd.Timestamp(fin).normalize()
        ):
            permit_gt_final += 1
    print(f"\nFILE_DATE > PERMIT_DATE: {file_gt_permit}")
    print(f"PERMIT_DATE > FINAL_DATE: {permit_gt_final}")

    n_open_issued_still_review = 0
    n_final_eq_co = 0
    n_final_with_co = 0
    n_file_eq_app = 0
    n_with_app = 0
    n_permit_eq_issued = 0
    n_with_issued = 0
    for idx in repaired.index:
        d = _safe_parse(repaired.at[idx, "DATA"]) or {}
        pi = _permit_info(d)
        if pi.get("Status") == "Open" and _present(
            _safe_to_datetime(pi.get("Issued Date"))
        ):
            if repaired.at[idx, "STATUS_NORMALIZED"] != "Active":
                n_open_issued_still_review += 1
        app = _safe_to_datetime(pi.get("Application Date"))
        if _present(app):
            n_with_app += 1
            if _dates_equal(repaired.at[idx, "FILE_DATE"], app):
                n_file_eq_app += 1
        issued = _safe_to_datetime(pi.get("Issued Date"))
        if _present(issued):
            n_with_issued += 1
            if _dates_equal(repaired.at[idx, "PERMIT_DATE"], issued):
                n_permit_eq_issued += 1
        if repaired.at[idx, "STATUS_NORMALIZED"] == "Final":
            co = _safe_to_datetime(pi.get("C.O. Issued"))
            if _present(co):
                n_final_with_co += 1
                if _dates_equal(repaired.at[idx, "FINAL_DATE"], co):
                    n_final_eq_co += 1

    print(f"Open+Issued still not Active: {n_open_issued_still_review}")
    print(f"FILE_DATE == Application Date: {n_file_eq_app} / {n_with_app}")
    print(f"PERMIT_DATE == Issued Date: {n_permit_eq_issued} / {n_with_issued}")
    print(f"Final with CO where FINAL_DATE == C.O. Issued: {n_final_eq_co} / {n_final_with_co}")

    if AGENT_DATA_PATH:
        out_path = os.path.join(
            AGENT_DATA_PATH, "lauderhill_permits_repaired.parquet"
        )
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote {out_path}")

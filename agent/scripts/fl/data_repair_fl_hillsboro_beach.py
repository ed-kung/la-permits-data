"""Data repair for Hillsboro Beach (FL) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Hillsboro Beach DATA is a single city-portal schema in this sample:

  - city_portal: top-level Applications, Fees and Payments,
                 Permit Information, Inspections History,
                 Permit Requirements, Plan Review History

Canonical mappings:
  - Permit Information[0].StatusDesc              → STATUS_NORMALIZED
  - earliest Applications[].AppDate               → FILE_DATE
  - earliest Applications[].ApprovedByDate        → PERMIT_DATE
  - latest Passed inspection with "FINAL" in
    inspectiondesc                                → FINAL_DATE

Content suffixes on INFERRED_SCHEMA further split by which canonical
dates are present in DATA (``_issued_finaled``, ``_issued``,
``_finaled``, ``_applied``, ``_empty_apps``).

Known issues repaired:
  - PERMIT_DATE was copied from FILE_DATE on every
    populated row; overwrite from ApprovedByDate when present.
  - Spurious PERMIT_DATE on In Review (unissued)
    rows → cleared.
  - FINAL_DATE missing on all rows → FILLED from
    Passed FINAL inspections for Final records.

Not repairable from DATA:
  - STATUS_NORMALIZED already matches StatusDesc for
    every sample row (no fills/fixes).
  - One Voided shell has an empty Applications list and
    no other date stamps → FILE_DATE / PERMIT_DATE stay
    missing.
  - Most historical Active/Final rows lack
    ApprovedByDate → PERMIT_DATE left as the upstream
    FILE_DATE copy (fee DatePaid is not a reliable
    issuance proxy here).
  - Final rows with empty inspection history or no
    Passed FINAL inspection → FINAL_DATE stays missing.
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
    """Parse a date value, returning pd.NaT on failure / sentinels."""
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


def _present(dt) -> bool:
    return dt is not pd.NaT and not pd.isna(dt)


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


# ── Extractors ───────────────────────────────────────────────────────────────

def _applications(d: dict) -> list:
    apps = d.get("Applications") or []
    return [a for a in apps if isinstance(a, dict)]


def _status_desc(d: dict) -> Optional[str]:
    info = d.get("Permit Information") or []
    if not info or not isinstance(info[0], dict):
        return None
    raw = info[0].get("StatusDesc")
    if raw is None:
        return None
    text = str(raw).strip()
    return text or None


def _earliest_app_date(d: dict):
    dates = [_safe_to_datetime(a.get("AppDate")) for a in _applications(d)]
    dates = [x for x in dates if _present(x)]
    return min(dates) if dates else pd.NaT


def _earliest_approved_by_date(d: dict):
    dates = [_safe_to_datetime(a.get("ApprovedByDate")) for a in _applications(d)]
    dates = [x for x in dates if _present(x)]
    return min(dates) if dates else pd.NaT


def _final_date_from_inspections(d: dict):
    """Latest Passed inspection whose description contains FINAL."""
    hist = d.get("Inspections History") or []
    if not isinstance(hist, list):
        return pd.NaT

    final_dates = []
    for insp in hist:
        if not isinstance(insp, dict):
            continue
        status = str(insp.get("statusdesc") or "").strip()
        if status != "Passed":
            continue
        desc = str(insp.get("inspectiondesc") or "")
        if "FINAL" not in desc.upper():
            continue
        dt = _safe_to_datetime(insp.get("scheduleddate"))
        if _present(dt):
            final_dates.append(dt)

    return max(final_dates) if final_dates else pd.NaT


# ── Schema classification ────────────────────────────────────────────────────

def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    if not isinstance(data_dict, dict):
        return "unknown"

    keys = set(data_dict.keys())
    if "Permit Information" not in keys or "Applications" not in keys:
        return "unknown"

    if not _applications(data_dict):
        return "city_portal_empty_apps"

    issued = _present(_earliest_approved_by_date(data_dict))
    finaled = _present(_final_date_from_inspections(data_dict))
    if issued and finaled:
        return "city_portal_issued_finaled"
    if issued:
        return "city_portal_issued"
    if finaled:
        return "city_portal_finaled"
    return "city_portal_applied"


# ── Status maps ──────────────────────────────────────────────────────────────

# Permit Information.StatusDesc → STATUS_NORMALIZED
_STATUS_MAP = {
    "Permit Complete": "Final",
    "Permit Issued": "Active",
    "Plan Review": "In Review",
    "Application": "In Review",
    "Canceled Permit": "Inactive",
    "Expired": "Inactive",
    "Voided": "Inactive",
}


def _map_status(raw: Optional[str]) -> Optional[str]:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    return _STATUS_MAP.get(text)


# ── Per-schema repair ────────────────────────────────────────────────────────

def _repair_city_portal(row, d: dict, repairs: dict) -> None:
    """Repair a city_portal record."""
    expected = _map_status(_status_desc(d))
    effective_status = _apply_status(repairs, row["STATUS_NORMALIZED"], expected)

    # FILE_DATE: earliest application / submittal date
    _apply_date(repairs, row, "FILE_DATE", _earliest_app_date(d))

    # FINAL_DATE from Passed FINAL inspections (Final only)
    final_src = _final_date_from_inspections(d)
    current_final = row["FINAL_DATE"]
    if effective_status == "Final":
        if _present(final_src):
            if pd.isna(current_final):
                repairs["FINAL_DATE"] = final_src
                repairs["FINAL_DATE_FLAG"] = "FILLED"
            elif not _dates_equal(current_final, final_src):
                repairs["FINAL_DATE"] = final_src
                repairs["FINAL_DATE_FLAG"] = "FIXED"
        elif not pd.isna(current_final):
            _clear_date(repairs, row, "FINAL_DATE")
    elif not pd.isna(current_final):
        _clear_date(repairs, row, "FINAL_DATE")

    # PERMIT_DATE: earliest ApprovedByDate for issued statuses;
    # clear spurious copies on unissued In Review rows.
    approved = _earliest_approved_by_date(d)
    if effective_status in ("Active", "Final"):
        if _present(approved):
            _apply_date(repairs, row, "PERMIT_DATE", approved)
        # else: leave upstream value (often FILE_DATE copy) — no better source
    elif effective_status == "In Review":
        _clear_date(repairs, row, "PERMIT_DATE")
    elif effective_status == "Inactive":
        # Prefer real approval date when present; otherwise leave as-is.
        if _present(approved):
            _apply_date(repairs, row, "PERMIT_DATE", approved)


# ── Main entry point ─────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Hillsboro Beach permit records using information from the raw DATA JSON.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Hillsboro Beach".  Must contain
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
        if d is None:
            continue

        repairs: dict = {}
        if schema.startswith("city_portal"):
            _repair_city_portal(row, d, repairs)

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
        (df["JURISDICTION"] == "Hillsboro Beach") & (df["STATE"] == "FL")
    ].copy()

    print(f"Hillsboro Beach records: {len(city):,}\n")
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

    print("\nFILE_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FILE_DATE"].notna().sum()
        print(
            f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} "
            f"({(n_has / len(sub) if len(sub) else 0):.1%})"
        )

    print("\nPERMIT_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["PERMIT_DATE"].notna().sum()
        print(
            f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} "
            f"({(n_has / len(sub) if len(sub) else 0):.1%})"
        )

    print("\nFINAL_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FINAL_DATE"].notna().sum()
        print(
            f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} "
            f"({(n_has / len(sub) if len(sub) else 0):.1%})"
        )

    both = repaired[repaired["PERMIT_DATE"].notna() & repaired["FINAL_DATE"].notna()]
    n_inv = (
        both["PERMIT_DATE"].dt.normalize() > both["FINAL_DATE"].dt.normalize()
    ).sum()
    print(f"\nPERMIT_DATE > FINAL_DATE inversions after repair: {n_inv}")

    af = repaired[repaired["STATUS_NORMALIZED"].isin(["Active", "Final"])]
    still_eq = (
        af["PERMIT_DATE"].notna()
        & af["FILE_DATE"].notna()
        & (af["PERMIT_DATE"].dt.normalize() == af["FILE_DATE"].dt.normalize())
    ).sum()
    print(f"Active/Final with PERMIT_DATE == FILE_DATE after repair: {still_eq}")

    if agent_data_path:
        out_path = os.path.join(
            agent_data_path, "hillsboro_beach_repaired_sample.parquet"
        )
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote {out_path}")

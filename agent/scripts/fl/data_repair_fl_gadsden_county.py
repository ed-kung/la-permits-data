"""Data repair for Gadsden County (FL) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Gadsden County DATA is a city-portal payload with top-level Applications,
Fees and Payments, Permit Information, Inspections History,
Permit Requirements, and Plan Review History (Pascal key casing on
Permit Information / Applications).

Canonical mappings:
  - Permit Information[0].StatusDesc              → STATUS_NORMALIZED
  - earliest Applications[].AppDate               → FILE_DATE
  - earliest Applications[].ApprovedByDate else
    earliest Fees and Payments[].DatePaid         → PERMIT_DATE
  - latest Passed inspection with "FINAL" in
    inspectiondesc; else (Final only) latest
    Passed inspection of any type                 → FINAL_DATE

INFERRED_SCHEMA is ``city_portal`` plus a content suffix for which
canonical dates are recoverable (``_issued_finaled``, ``_issued``,
``_finaled``, ``_applied``).

Known issues repaired:
  - PERMIT_DATE copied from FILE_DATE on every row
    (ApprovedByDate present on only 1/248 shells)
    → FIXED from earliest fee DatePaid when that
    differs from the FILE_DATE copy.
  - FINAL_DATE missing on all Final rows → FILLED
    from Passed FINAL inspections (fallback: last
    Passed inspection for Permit Complete shells
    whose close-out inspection is not named FINAL,
    e.g. MH Code Compliance / roof coverings).

Not repairable from DATA:
  - Active/Final rows with no fees and no
    ApprovedByDate → PERMIT_DATE left as the
    upstream FILE_DATE copy.
  - Final rows with no Passed inspections →
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


# ── Schema / field extractors ────────────────────────────────────────────────

def _permit_info(d: dict) -> Optional[dict]:
    info = d.get("Permit Information")
    if isinstance(info, list):
        if info and isinstance(info[0], dict):
            return info[0]
        return None
    if isinstance(info, dict):
        return info
    return None


def _applications(d: dict) -> list:
    apps = d.get("Applications") or []
    return [a for a in apps if isinstance(a, dict)]


def _earliest_app_date(d: dict):
    dates = [_safe_to_datetime(a.get("AppDate")) for a in _applications(d)]
    dates = [x for x in dates if _present(x)]
    return min(dates) if dates else pd.NaT


def _earliest_approved_by_date(d: dict):
    dates = [_safe_to_datetime(a.get("ApprovedByDate")) for a in _applications(d)]
    dates = [x for x in dates if _present(x)]
    return min(dates) if dates else pd.NaT


def _earliest_fee_paid(d: dict):
    fees = d.get("Fees and Payments") or []
    if not isinstance(fees, list):
        return pd.NaT
    dates = []
    for f in fees:
        if not isinstance(f, dict):
            continue
        dt = _safe_to_datetime(f.get("DatePaid"))
        if _present(dt):
            dates.append(dt)
    return min(dates) if dates else pd.NaT


def _issuance_date(d: dict):
    """Prefer ApprovedByDate; else earliest settled fee DatePaid."""
    approved = _earliest_approved_by_date(d)
    if _present(approved):
        return approved
    return _earliest_fee_paid(d)


def _final_date_from_inspections(d: dict, allow_last_passed: bool = False):
    """Latest Passed FINAL inspection; optionally last Passed of any type."""
    hist = d.get("Inspections History") or []
    if not isinstance(hist, list):
        return pd.NaT

    final_dates = []
    passed_dates = []
    for insp in hist:
        if not isinstance(insp, dict):
            continue
        status = str(insp.get("statusdesc") or "").strip()
        if status != "Passed":
            continue
        dt = _safe_to_datetime(insp.get("scheduleddate"))
        if not _present(dt):
            continue
        passed_dates.append(dt)
        desc = str(insp.get("inspectiondesc") or "")
        if "FINAL" in desc.upper():
            final_dates.append(dt)

    if final_dates:
        return max(final_dates)
    if allow_last_passed and passed_dates:
        return max(passed_dates)
    return pd.NaT


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    if not isinstance(data_dict, dict):
        return "unknown"

    keys = set(data_dict.keys())
    if "Permit Information" not in keys or "Applications" not in keys:
        return "unknown"

    issued = _present(_issuance_date(data_dict))
    # Schema suffix uses the FINAL-named inspection only (not last-passed
    # fallback) so content labels reflect explicit close-out evidence.
    finaled = _present(_final_date_from_inspections(data_dict, allow_last_passed=False))
    if issued and finaled:
        suffix = "_issued_finaled"
    elif issued:
        suffix = "_issued"
    elif finaled:
        suffix = "_finaled"
    else:
        suffix = "_applied"
    return f"city_portal{suffix}"


# ── Status maps ──────────────────────────────────────────────────────────────

_STATUS_MAP = {
    "Permit Complete": "Final",
    "Permit Closed": "Final",
    "Permit Issued": "Active",
    "Plan Review": "In Review",
    "Application": "In Review",
    "Incomplete": "In Review",
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


def _status_desc(d: dict) -> Optional[str]:
    info = _permit_info(d)
    if info is None:
        return None
    raw = info.get("StatusDesc")
    if raw is None:
        raw = info.get("statusdesc")
    if raw is None:
        return None
    text = str(raw).strip()
    return text or None


# ── Per-schema repair ────────────────────────────────────────────────────────

def _repair_city_portal(row, d: dict, repairs: dict) -> None:
    """Repair a city_portal record."""
    expected = _map_status(_status_desc(d))
    effective_status = _apply_status(repairs, row["STATUS_NORMALIZED"], expected)

    # FILE_DATE: earliest application / submittal date
    _apply_date(repairs, row, "FILE_DATE", _earliest_app_date(d))

    # FINAL_DATE from Passed FINAL inspections; for Final shells without a
    # FINAL-named close-out, fall back to last Passed inspection.
    final_src = _final_date_from_inspections(
        d, allow_last_passed=(effective_status == "Final")
    )
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

    # PERMIT_DATE: ApprovedByDate else earliest fee DatePaid.
    # Clears spurious copies on unissued In Review rows.
    issued = _issuance_date(d)
    if effective_status in ("Active", "Final"):
        if _present(issued):
            _apply_date(repairs, row, "PERMIT_DATE", issued)
        # else: leave upstream value (often FILE_DATE copy) — no better source
    elif effective_status == "In Review":
        _clear_date(repairs, row, "PERMIT_DATE")
    elif effective_status == "Inactive":
        if _present(issued):
            _apply_date(repairs, row, "PERMIT_DATE", issued)


# ── Main entry point ─────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Gadsden County permit records using information from the raw DATA JSON.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Gadsden County".  Must contain
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
        (df["JURISDICTION"] == "Gadsden County") & (df["STATE"] == "FL")
    ].copy()

    print(f"Gadsden County records: {len(city):,}\n")
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

    print("\nSTATUS_NORMALIZED transitions (before → after):")
    transitions = (
        pd.DataFrame({
            "before": city["STATUS_NORMALIZED"].astype("object"),
            "after": repaired["STATUS_NORMALIZED"].astype("object"),
        })
        .groupby(["before", "after"], dropna=False)
        .size()
        .reset_index(name="n")
    )
    changed = transitions[
        transitions["before"].astype(str) != transitions["after"].astype(str)
    ]
    print(changed.sort_values("n", ascending=False).to_string(index=False))

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

    still_null = repaired[repaired["STATUS_NORMALIZED"].isna()]
    print(f"\nRemaining null STATUS_NORMALIZED: {len(still_null):,}")

    if agent_data_path:
        out_dir = Path(agent_data_path) / "repaired"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "permits_fl_gadsden_county_repaired.parquet"
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote {out_path}")

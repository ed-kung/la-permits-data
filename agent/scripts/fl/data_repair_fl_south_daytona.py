"""Data repair for South Daytona (FL) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

South Daytona DATA is a uniform city-portal payload (same family as
Nassau County / Bradenton city_app) with top-level keys app, fees,
permit, init_info, permit_list, and inspection_list. Content variants
(INFERRED_SCHEMA) split by whether ``permit`` carries a parseable
Issued Date and whether ``inspection_list`` has any dated rows:

  - city_app_issued_insp
  - city_app_issued
  - city_app_permit_no_issued
  - city_app_app_only   (empty permit object)

Canonical fields:

  - app.Status + permit.Permit Status (+ Issued Date)
      → STATUS_NORMALIZED
  - app.Application Received Date → FILE_DATE
  - permit.Issued Date            → PERMIT_DATE
  - latest PASSED* inspection
    (floored at Issued Date)      → FINAL_DATE

South Daytona app.Status vocabulary uses CLOSED APPLICATION /
CLOSED COMPLETE / NEW APPLICATION / READY TO ISSUE (vs Nassau's
COMPLETE / PENDING). Mapping still keys on Permit Status COMPLETED,
left-side COMPLETE / WITHDRAWN / EXPIRED / DENIED / ENTERED IN ERROR,
and Issued Date / REVIEWING for Active vs In Review.

Known issues repaired:
  - Null STATUS_NORMALIZED on ~30% of rows (COMPLETE / CLOSED COMPLETE,
    ACTIVE / ISSUED|NEW*, WITHDRAWN / EXPIRED / ENTERED IN ERROR /
    DENIED, ACTIVE / READY TO ISSUE|CLOSE) → FILLED from app.Status
    + Permit Status.
  - Missing PERMIT_DATE filled from Issued Date when present on
    Active / Final / Inactive; spurious In Review PERMIT_DATE cleared.
  - FINAL_DATE never ingested → FILLED from latest PASSED inspection
    for Final rows; non-Final FINAL_DATE cleared.

Not repairable from DATA:
  - Three Final shells have an empty ``app`` object → FILE_DATE stays
    missing (no Application Received Date).
  - Final rows with no dated PASSED inspections → FINAL_DATE stays
    missing.
  - Active / Final shells with blank Issued Date (mostly COMPLETE /
    REVIEWING or empty permit) → PERMIT_DATE stays missing; unissued
    ACTIVE / NEW*|READY TO ISSUE with REVIEWING become In Review.
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
    """Parse a date value, returning pd.NaT on failure / out-of-range."""
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


def _has_insp_date(d: dict) -> bool:
    for row in d.get("inspection_list") or []:
        if isinstance(row, list) and len(row) >= 2 and str(row[1] or "").strip():
            if _present(_safe_to_datetime(row[1])):
                return True
    return False


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())
    if "app" not in keys:
        return "unknown"

    permit = data_dict.get("permit")
    has_permit = isinstance(permit, dict) and bool(permit)
    issued = (
        _safe_to_datetime(permit.get("Issued Date")) if has_permit else pd.NaT
    )
    has_issued = _present(issued)
    has_insp = _has_insp_date(data_dict)

    if has_permit and has_issued and has_insp:
        return "city_app_issued_insp"
    if has_permit and has_issued:
        return "city_app_issued"
    if has_permit:
        return "city_app_permit_no_issued"
    return "city_app_app_only"


# ── Status mapping ───────────────────────────────────────────────────────────

# Base map on app.Status (uppercased). Overrides below refine using
# Permit Status / Issued Date. Includes South Daytona CLOSED* / NEW*
# phrasing plus shared city-portal COMPLETE / PENDING variants.
_APP_STATUS_MAP = {
    "COMPLETE / COMPLETE": "Final",
    "COMPLETE / CLOSED APPLICATION": "Final",
    "COMPLETE / CLOSED COMPLETE": "Final",
    "COMPLETE / NEW APPLICATION": "Final",
    "ACTIVE / ACTIVE": "Active",
    "ACTIVE / ISSUED": "Active",
    "ACTIVE / PENDING": "In Review",
    "ACTIVE / NEW": "In Review",
    "ACTIVE / NEW APPLICATION": "In Review",
    "ACTIVE / READY TO ISSUE": "In Review",
    "ACTIVE / READY TO CLOSE": "Active",
    # ACTIVE / COMPLETE|CLOSED* are not mapped here: COMPLETED is
    # Final via Permit Status; ISSUED stays Active; REVIEWING → In Review.
    "ACTIVE / VOID": "Inactive",
    "HOLD / ACTIVE": "Active",
    "ENTERED IN ERROR / VOID": "Inactive",
    "ENTERED IN ERROR / COMPLETE": "Inactive",
    "ENTERED IN ERROR / CLOSED APPLICATION": "Inactive",
    "ENTERED IN ERROR / CLOSED COMPLETE": "Inactive",
    "WITHDRAWN / VOID": "Inactive",
    "WITHDRAWN / COMPLETE": "Inactive",
    "WITHDRAWN / CLOSED APPLICATION": "Inactive",
    "WITHDRAWN / CLOSED COMPLETE": "Inactive",
    "DENIED / VOID": "Inactive",
    "DENIED / DENIED": "Inactive",
    "DENIED / COMPLETE": "Inactive",
    "DENIED / CLOSED APPLICATION": "Inactive",
    "EXPIRED / EXPIRED": "Inactive",
    "EXPIRED / VOID": "Inactive",
    "EXPIRED / CLOSED APPLICATION": "Inactive",
    "EXPIRED / CLOSED COMPLETE": "Inactive",
    "EXPIRED / NEW APPLICATION": "Inactive",
    "EXPIRED / READY TO ISSUE": "Inactive",
}

_INACTIVE_PERMIT = {"DENIED", "WITHDRAWN", "VOIDED", "REVOKED"}
_INACTIVE_APP_LEFT = {
    "ENTERED IN ERROR",
    "WITHDRAWN",
    "DENIED",
    "EXPIRED",
}


def _expected_status(
    app_status: Optional[str],
    permit_status: Optional[str],
    issued,
) -> Optional[str]:
    app_key = (app_status or "").strip().upper()
    ps = (permit_status or "").strip().upper()
    has_issued = _present(_safe_to_datetime(issued))

    left = app_key.split("/", 1)[0].strip() if app_key else ""
    right = app_key.split("/", 1)[1].strip() if "/" in app_key else ""

    # Strongest signals from permit lifecycle.
    if ps == "COMPLETED":
        return "Final"
    if ps in _INACTIVE_PERMIT:
        return "Inactive"

    # Terminal app prefixes (entered-in-error / withdrawn / denied / expired).
    if left in _INACTIVE_APP_LEFT:
        return "Inactive"
    if right == "VOID":
        return "Inactive"

    if app_key == "COMPLETE / COMPLETE" or left == "COMPLETE":
        return "Final"

    base = _APP_STATUS_MAP.get(app_key)
    if base is None:
        if left == "ACTIVE":
            base = "Active"
        elif left == "HOLD":
            base = "In Review"
        elif left == "COMPLETE":
            base = "Final"
        else:
            base = None

    if base is None:
        if has_issued or ps == "ISSUED":
            return "Active"
        if ps == "REVIEWING":
            return "In Review"
        return None

    # Unissued "Active" / hold shells still in review.
    if base in ("Active", "In Review"):
        if ps == "ISSUED" or has_issued:
            return "Active"
        if ps == "REVIEWING" or right in {"PENDING", "READY TO ISSUE"}:
            return "In Review"
        if base == "Active" and not has_issued and not ps:
            return "In Review"

    return base


def _latest_pass_date(inspection_list) -> pd.Timestamp:
    """Latest inspection date whose result starts with PASS (not FAIL)."""
    dates = []
    for row in inspection_list or []:
        if not isinstance(row, list) or len(row) < 3:
            continue
        result = str(row[2] or "").strip().upper()
        if not result.startswith("PASS"):
            continue
        dt = _safe_to_datetime(row[1])
        if _present(dt):
            dates.append(dt)
    return max(dates) if dates else pd.NaT


# ── Per-record repair ────────────────────────────────────────────────────────

def _repair_record(row, d: dict, repairs: dict) -> None:
    app = d.get("app") if isinstance(d.get("app"), dict) else {}
    permit = d.get("permit") if isinstance(d.get("permit"), dict) else {}

    app_status = app.get("Status") or ""
    permit_status = permit.get("Permit Status")
    issued = permit.get("Issued Date")
    issued_dt = _safe_to_datetime(issued)

    expected = _expected_status(app_status, permit_status, issued)
    effective = _apply_status(repairs, row["STATUS_NORMALIZED"], expected)

    # -- FILE_DATE ← Application Received Date --
    _apply_date(repairs, row, "FILE_DATE", app.get("Application Received Date"))

    # -- PERMIT_DATE ← Issued Date --
    if effective in ("Active", "Final", "Inactive"):
        if _present(issued_dt):
            _apply_date(repairs, row, "PERMIT_DATE", issued_dt)
    elif effective == "In Review":
        _clear_date(repairs, row, "PERMIT_DATE")

    # -- FINAL_DATE ← latest PASSED inspection; Final only --
    # Floor at Issued Date when inspections predate issuance (common
    # same-day / next-day portal quirk that would invert PERMIT vs FINAL).
    if effective == "Final":
        final_src = _latest_pass_date(d.get("inspection_list"))
        if _present(final_src) and _present(issued_dt):
            final_src = max(
                pd.Timestamp(final_src).normalize(),
                pd.Timestamp(issued_dt).normalize(),
            )
        _apply_date(repairs, row, "FINAL_DATE", final_src)
    else:
        _clear_date(repairs, row, "FINAL_DATE")


# ── Main entry point ─────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    South Daytona permit records using information from the raw DATA JSON.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "South Daytona".  Must
        contain columns STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE,
        FINAL_DATE, and DATA.

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
        if d is None or schema in ("missing", "unknown"):
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
    from pathlib import Path

    from dotenv import load_dotenv

    repo_root = Path(__file__).resolve().parents[3]
    load_dotenv(repo_root / ".env")
    my_data_path = os.getenv("MY_DATA_PATH")
    agent_data_path = os.getenv("AGENT_DATA_PATH")
    filepath = os.path.join(
        my_data_path, "processed_data", "permits_fl_sample.parquet"
    )
    df = pd.read_parquet(filepath)
    city = df[
        (df["JURISDICTION"] == "South Daytona") & (df["STATE"] == "FL")
    ].copy()

    print(f"South Daytona records: {len(city):,}\n")
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

    both = repaired[
        repaired["PERMIT_DATE"].notna() & repaired["FINAL_DATE"].notna()
    ]
    n_inv = (
        both["PERMIT_DATE"].dt.normalize() > both["FINAL_DATE"].dt.normalize()
    ).sum()
    print(f"\nPERMIT_DATE > FINAL_DATE inversions after repair: {n_inv}")

    final_miss = repaired[
        (repaired["STATUS_NORMALIZED"] == "Final") & repaired["FINAL_DATE"].isna()
    ]
    print(f"Final still missing FINAL_DATE: {len(final_miss)}")

    af_miss = repaired[
        repaired["STATUS_NORMALIZED"].isin(["Active", "Final"])
        & repaired["PERMIT_DATE"].isna()
    ]
    print(f"Active/Final still missing PERMIT_DATE: {len(af_miss)}")

    status_null = repaired["STATUS_NORMALIZED"].isna().sum()
    print(f"STATUS_NORMALIZED still null: {status_null}")

    if agent_data_path:
        out_path = os.path.join(
            agent_data_path, "south_daytona_repaired_sample.parquet"
        )
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote repaired sample → {out_path}")

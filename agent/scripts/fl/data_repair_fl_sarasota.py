"""Data repair for Sarasota (FL) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Sarasota DATA is a flat Accela-style MHC payload (201 top-level keys,
identical key set for every sample row) with department review fields
plus canonical MHC dates:

  - admin_status              → STATUS_NORMALIZED (with date overrides)
  - mhc_applicationdate       → FILE_DATE
  - mhc_issuedate             → PERMIT_DATE
  - mhc_closedate (fallback
    coissuedate)              → FINAL_DATE

Content suffixes for INFERRED_SCHEMA further split by which canonical
dates are populated (``_issued_closed``, ``_issued``, ``_applied``,
plus optional ``_co`` / ``_nostatus``).

Known issues repaired:
  - Zero Final rows despite ~1,492 closed / CO-issued MHC shells —
    Permit Issued / Plan Approved / etc. with mhc_closedate (or
    coissuedate) reclassified Final.
  - Plan Approved / Pending Plan Review rows that already carry
    mhc_issuedate reclassified Active (not In Review).
  - Null STATUS_NORMALIZED for blank admin_status (47) and Plan
    Conditionally Approved (2) → FILLED from dates / admin_status.
  - Spurious PERMIT_DATE / FINAL_DATE on In Review and FINAL_DATE on
    Inactive Cancel Record cleared.
  - Missing PERMIT_DATE / FINAL_DATE filled from MHC issue / close
    (or CO) dates where status requires them.

Not repairable from DATA:
  - FILE_DATE already matches mhc_applicationdate for every sample row
    (no fills / fixes needed).
  - Remaining PERMIT_DATE / FINAL_DATE gaps are intentional: In Review
    and non-Final rows should not carry those dates after repair.
  - Cancel Record rows stay Inactive even when mhc_closedate is set;
    that close stamp is not treated as a true finalization.
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
        if s.startswith("0001-01-01"):
            return pd.NaT
    try:
        dt = pd.to_datetime(val, errors="coerce")
    except (ValueError, TypeError, OverflowError):
        return pd.NaT
    if pd.isna(dt):
        return pd.NaT
    # Normalize tz-aware values to naive UTC timestamps.
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


def _present(dt) -> bool:
    return dt is not pd.NaT and not pd.isna(dt)


# ── MHC extractors ───────────────────────────────────────────────────────────

def _admin_status(d: dict) -> Optional[str]:
    status = d.get("admin_status")
    if status is None:
        return None
    status = str(status).strip()
    return status or None


def _mhc_dates(d: dict) -> tuple:
    """Return (application, issue, close, co_issue) as datetimes."""
    apply = _safe_to_datetime(d.get("mhc_applicationdate"))
    issue = _safe_to_datetime(d.get("mhc_issuedate"))
    close = _safe_to_datetime(d.get("mhc_closedate"))
    co = _safe_to_datetime(d.get("coissuedate"))
    return apply, issue, close, co


# ── Schema classification ────────────────────────────────────────────────────

def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())
    if "mhc_applicationdate" not in keys and "admin_status" not in keys:
        return "unknown"

    apply, issue, close, co = _mhc_dates(data_dict)
    has_status = _admin_status(data_dict) is not None

    base = "mhc" if has_status else "mhc_nostatus"
    if _present(issue) and _present(close):
        suffix = "issued_closed"
    elif _present(issue):
        suffix = "issued"
    elif _present(close):
        suffix = "closed"
    elif _present(apply):
        suffix = "applied"
    else:
        suffix = "empty"

    schema = f"{base}_{suffix}"
    if _present(co):
        schema = f"{schema}_co"
    return schema


# ── Status mapping ───────────────────────────────────────────────────────────

# Exact admin_status → STATUS_NORMALIZED when dates do not override.
_STATUS_MAP = {
    "Cancel Record": "Inactive",
    "Permit Issued": "Active",
    "Pending Plan Review": "In Review",
    "Plan Approved": "In Review",
    "Plan Conditionally Approved": "In Review",
}


def _expected_status(d: dict) -> Optional[str]:
    """Derive STATUS_NORMALIZED from admin_status with MHC date overrides.

    Priority:
      1. Cancel Record → Inactive (even if a close stamp exists)
      2. mhc_closedate or coissuedate → Final
      3. Permit Issued or mhc_issuedate → Active
      4. Remaining admin_status map / blank → In Review
    """
    raw = _admin_status(d)
    _, issue, close, co = _mhc_dates(d)

    if raw is not None and raw.lower() == "cancel record":
        return "Inactive"

    if _present(close) or _present(co):
        return "Final"

    if (raw is not None and raw.lower() == "permit issued") or _present(issue):
        return "Active"

    if raw is not None:
        if raw in _STATUS_MAP:
            return _STATUS_MAP[raw]
        for key, val in _STATUS_MAP.items():
            if key.lower() == raw.lower():
                return val
        return None

    # Blank admin_status, no issue / close → still in application review.
    return "In Review"


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
    if not _present(cand):
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
    expected = _expected_status(d)
    effective_status = _apply_status(repairs, row["STATUS_NORMALIZED"], expected)

    apply, issue, close, co = _mhc_dates(d)
    final_src = close if _present(close) else co

    # FILE_DATE ← mhc_applicationdate (fallback admin_app / admin_rec / issue)
    file_src = apply
    if not _present(file_src):
        file_src = _safe_to_datetime(d.get("admin_app"))
    if not _present(file_src):
        file_src = _safe_to_datetime(d.get("admin_rec"))
    if not _present(file_src):
        file_src = issue
    if _present(file_src):
        _apply_date(repairs, row, "FILE_DATE", file_src)

    # PERMIT_DATE ← mhc_issuedate for issued / completed / cancelled;
    # clear on In Review (including orphan dates with no MHC issue stamp).
    if effective_status in ("Active", "Final", "Inactive"):
        if _present(issue):
            _apply_date(repairs, row, "PERMIT_DATE", issue)
    elif effective_status == "In Review":
        _clear_date(repairs, row, "PERMIT_DATE")

    # FINAL_DATE ← mhc_closedate / coissuedate for Final only; clear otherwise.
    if effective_status == "Final":
        if _present(final_src):
            _apply_date(repairs, row, "FINAL_DATE", final_src)
    else:
        _clear_date(repairs, row, "FINAL_DATE")


# ── Main entry point ─────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Sarasota permit records using the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Sarasota".  Must contain
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
    from dotenv import load_dotenv, find_dotenv

    load_dotenv(find_dotenv())
    MY_DATA_PATH = os.getenv("MY_DATA_PATH")
    AGENT_DATA_PATH = os.getenv("AGENT_DATA_PATH")
    filepath = os.path.join(
        MY_DATA_PATH, "processed_data", "permits_fl_sample.parquet"
    )
    df = pd.read_parquet(filepath)
    city = df[df["JURISDICTION"] == "Sarasota"].copy()

    print(f"Sarasota records: {len(city):,}\n")

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

    print("\nFINAL_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FINAL_DATE"].notna().sum()
        pct = n_has / len(sub) if len(sub) else 0.0
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({pct:.1%})")

    print("\nPERMIT_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["PERMIT_DATE"].notna().sum()
        pct = n_has / len(sub) if len(sub) else 0.0
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({pct:.1%})")

    print("\nFILE_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FILE_DATE"].notna().sum()
        pct = n_has / len(sub) if len(sub) else 0.0
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({pct:.1%})")

    final_miss = repaired[
        (repaired["STATUS_NORMALIZED"] == "Final") & repaired["FINAL_DATE"].isna()
    ]
    print(f"\nFinal still missing FINAL_DATE: {len(final_miss)}")
    if len(final_miss):
        from collections import Counter

        ps_counts = Counter()
        for idx in final_miss.index:
            d = _safe_parse(repaired.at[idx, "DATA"])
            if d is None:
                continue
            raw = (_admin_status(d) or "").strip() or "__EMPTY__"
            ps_counts[raw] += 1
        print("  by admin_status:", dict(ps_counts))

    status_null = repaired["STATUS_NORMALIZED"].isna().sum()
    print(f"\nSTATUS_NORMALIZED still null: {status_null}")

    af_miss = repaired[
        repaired["STATUS_NORMALIZED"].isin(["Active", "Final"])
        & repaired["PERMIT_DATE"].isna()
    ]
    print(f"Active/Final still missing PERMIT_DATE: {len(af_miss)}")
    if len(af_miss):
        from collections import Counter

        ps_counts = Counter()
        for idx in af_miss.index:
            d = _safe_parse(repaired.at[idx, "DATA"])
            if d is None:
                continue
            raw = (_admin_status(d) or "").strip() or "__EMPTY__"
            ps_counts[raw] += 1
        print("  by admin_status:", dict(ps_counts))

    if AGENT_DATA_PATH:
        out_path = os.path.join(
            AGENT_DATA_PATH, "sarasota_repaired_sample.parquet"
        )
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote repaired sample → {out_path}")

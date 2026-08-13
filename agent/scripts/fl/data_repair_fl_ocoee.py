"""Data repair for Ocoee (FL) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Ocoee DATA is a flat city-portal payload. Every row has:

  Status, Address, Permit #, Permit Type, Project Name,
  Expiration Date, Submission Date

A minority also carry Completed Date / CO Date, and optionally City /
Revision Number.

Canonical fields:

  - Status → STATUS_NORMALIZED
  - Submission Date → FILE_DATE
  - (no issue/approval date in DATA) → PERMIT_DATE cannot be filled
  - Completed Date (fallback CO Date) → FINAL_DATE

Key-set variants (INFERRED_SCHEMA prefixes):
  - portal_basic:            core 7 keys only
  - portal_extended:         + Completed Date / CO Date
  - portal_extended_city:    extended + City
  - portal_extended_city_rev: extended + City + Revision Number

Content suffixes further split by which canonical dates are populated
(``_completed_co``, ``_completed``, ``_submitted``).

Known issues repaired:
  - STATUS_ORIGINAL lagged live DATA Status (Completed still labeled
    issued/approved/in process/rejected; Issued/Approved still labeled
    in process/rejected; Voided/Expired still labeled issued/approved)
    → FIXED; one awaitingcompletion Completed shell with null
    STATUS_NORMALIZED → FILLED to Final.
  - FINAL_DATE was populated from Expiration Date (not a completion /
    sign-off date) on Final / Active / Inactive shells → cleared.
  - True Completed Date / CO Date on extended Completed shells was left
    unused (FINAL_DATE null) → FILLED.

Not repairable from DATA:
  - PERMIT_DATE: DATA has no issue / approval / permit-issuance date.
  - Most Final shells lack Completed Date / CO Date → FINAL_DATE stays
    missing after clearing the Expiration Date mis-copy.
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
    """Parse a date value, returning pd.NaT on failure / blank / OOR."""
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
        if s.startswith("0001-01-01") or s.startswith("1900-01-01"):
            return pd.NaT
    try:
        dt = pd.to_datetime(val, utc=True, errors="coerce")
    except (ValueError, TypeError, OverflowError):
        return pd.NaT
    if pd.isna(dt):
        return pd.NaT
    year = int(dt.year)
    if year < _MIN_YEAR or year > _MAX_YEAR:
        return pd.NaT
    return dt.tz_convert("UTC").tz_localize(None)


def _dates_equal(a, b) -> bool:
    """Compare two datelike values at calendar-day resolution."""
    da = _safe_to_datetime(a)
    db = _safe_to_datetime(b)
    if da is pd.NaT or db is pd.NaT or pd.isna(da) or pd.isna(db):
        return False
    return pd.Timestamp(da).normalize() == pd.Timestamp(db).normalize()


def _present(dt) -> bool:
    return dt is not pd.NaT and not pd.isna(dt)


def _has_usable_date(val) -> bool:
    return _present(_safe_to_datetime(val))


def _raw_status(d: dict) -> Optional[str]:
    status = d.get("Status")
    if status is None:
        return None
    status = str(status).strip()
    return status or None


def _submission_date(d: dict):
    return _safe_to_datetime(d.get("Submission Date"))


def _expiration_date(d: dict):
    return _safe_to_datetime(d.get("Expiration Date"))


def _final_source(d: dict):
    """Prefer Completed Date; fall back to CO Date."""
    completed = _safe_to_datetime(d.get("Completed Date"))
    if _present(completed):
        return completed
    return _safe_to_datetime(d.get("CO Date"))


# ── Schema classification ────────────────────────────────────────────────────

def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())
    if "Status" not in keys or "Submission Date" not in keys:
        return "unknown"

    has_completed_keys = bool(keys & {"Completed Date", "CO Date"})
    has_city = "City" in keys
    has_rev = "Revision Number" in keys

    if has_completed_keys and has_city and has_rev:
        prefix = "portal_extended_city_rev"
    elif has_completed_keys and has_city:
        prefix = "portal_extended_city"
    elif has_completed_keys:
        prefix = "portal_extended"
    else:
        prefix = "portal_basic"

    completed = _safe_to_datetime(data_dict.get("Completed Date"))
    co = _safe_to_datetime(data_dict.get("CO Date"))
    submitted = _submission_date(data_dict)

    if _present(completed) and _present(co):
        suffix = "completed_co"
    elif _present(completed):
        suffix = "completed"
    elif _present(co):
        suffix = "co"
    elif _present(submitted):
        suffix = "submitted"
    else:
        suffix = "status_only"

    return f"{prefix}_{suffix}"


# ── Status mapping ───────────────────────────────────────────────────────────

_STATUS_MAP = {
    "Completed": "Final",
    "Issued": "Active",
    "Approved": "Active",
    "In Process": "In Review",
    "Voided": "Inactive",
    "Rejected": "Inactive",
    "Expired": "Inactive",
}


def _expected_status(d: dict) -> Optional[str]:
    raw = _raw_status(d)
    if raw is None:
        return None
    if raw in _STATUS_MAP:
        return _STATUS_MAP[raw]
    for key, val in _STATUS_MAP.items():
        if key.lower() == raw.lower():
            return val
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
    if not _present(cand):
        return
    current = row[field]
    if pd.isna(current) or not _has_usable_date(current):
        if pd.isna(current):
            repairs[field] = cand
            repairs[f"{field}_FLAG"] = "FILLED"
        else:
            repairs[field] = cand
            repairs[f"{field}_FLAG"] = "FIXED"
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

    submission = _submission_date(d)
    expiration = _expiration_date(d)
    final_src = _final_source(d)

    # FILE_DATE ← Submission Date (already correct on the FL sample).
    if _present(submission):
        _apply_date(repairs, row, "FILE_DATE", submission)

    # PERMIT_DATE — DATA has no issue/approval date. Leave missing; do not
    # invent from Expiration Date or Submission Date.
    # (No fill/fix path available for Ocoee.)

    # FINAL_DATE ← Completed Date / CO Date for Final only.
    # Upstream commonly copied Expiration Date into FINAL_DATE; clear that.
    if effective_status == "Final":
        if _present(final_src):
            _apply_date(repairs, row, "FINAL_DATE", final_src)
        else:
            current_final = row["FINAL_DATE"]
            if not pd.isna(current_final):
                # Clear expiration mis-copies and any other FINAL_DATE that
                # cannot be validated against Completed/CO in DATA.
                if _dates_equal(current_final, expiration) or not _present(final_src):
                    _clear_date(repairs, row, "FINAL_DATE")
    else:
        _clear_date(repairs, row, "FINAL_DATE")


# ── Main entry point ─────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Ocoee permit records using the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Ocoee".  Must contain
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
    MY_DATA_PATH = os.getenv("MY_DATA_PATH")
    AGENT_DATA_PATH = os.getenv("AGENT_DATA_PATH")
    filepath = os.path.join(
        MY_DATA_PATH, "processed_data", "permits_fl_sample.parquet"
    )
    df = pd.read_parquet(filepath)
    city = df[
        (df["JURISDICTION"] == "Ocoee") & (df["STATE"] == "FL")
    ].copy()

    print(f"Ocoee records: {len(city):,}\n")

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
        if field != "STATUS_NORMALIZED":
            before_bad = 0
            for v in city[field].dropna():
                dt = pd.to_datetime(v, errors="coerce")
                if pd.isna(dt) or dt.year < _MIN_YEAR or dt.year > _MAX_YEAR:
                    before_bad += 1
            print(f"  Sentinel/OOR before: {before_bad:>4,}")
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

    print("\nDATA.Status → STATUS_NORMALIZED (after):")
    status_from_data = repaired["DATA"].map(
        lambda x: _raw_status(_safe_parse(x) or {})
    )
    ct = (
        pd.DataFrame({
            "DATA_STATUS": status_from_data,
            "STATUS_NORMALIZED": repaired["STATUS_NORMALIZED"],
        })
        .groupby(["DATA_STATUS", "STATUS_NORMALIZED"], dropna=False)
        .size()
        .reset_index(name="n")
        .sort_values("n", ascending=False)
    )
    print(ct.to_string(index=False))

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
            raw = (_raw_status(d) or "").strip() or "__EMPTY__"
            ps_counts[raw] += 1
        print("  by Status:", dict(ps_counts))

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
            raw = (_raw_status(d) or "").strip() or "__EMPTY__"
            ps_counts[raw] += 1
        print("  by Status:", dict(ps_counts))

    # Residual: FINAL_DATE still equal to Expiration Date?
    n_exp_copy = 0
    for idx in repaired.index:
        fin = repaired.at[idx, "FINAL_DATE"]
        if pd.isna(fin):
            continue
        d = _safe_parse(repaired.at[idx, "DATA"])
        if d is None:
            continue
        if _dates_equal(fin, d.get("Expiration Date")):
            n_exp_copy += 1
    print(f"\nFINAL_DATE still equal to Expiration Date: {n_exp_copy}")

    if AGENT_DATA_PATH:
        out_dir = os.path.join(AGENT_DATA_PATH, "repaired")
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, "permits_fl_ocoee_repaired.parquet")
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote repaired sample → {out_path}")

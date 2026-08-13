"""Data repair for Gulf County (FL) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Gulf County DATA is a flat portal scrape (same family as Franklin County
``simple`` rows) with top-level keys:

  Status, Address , Permit #, Permit Type, Sub Type,
  Issue Date (optional), Work Description (optional)

Canonical fields:

  - Status (fallback Sub Type when Status is missing / garbage /
      owner-name misaligned) → STATUS_NORMALIZED
      (+ upgrade In Review → Active when a real Issue Date exists)
  - Issue Date (parseable only) → FILE_DATE (fallback; portal exposes
      no applied/submittal date) and → PERMIT_DATE
  - FINAL_DATE has no source in this schema (no Inspections / Finaled)

INFERRED_SCHEMA uses the ``simple_*`` prefix (portal family shared with
Franklin County) split by whether a parseable Issue Date is present
(``simple_issued`` vs ``simple_status_only``).

Known issues repaired:
  - Null STATUS_NORMALIZED on column-shifted shells (owner name or
      blank in Status; true lifecycle label in Sub Type) → FILLED.
  - Under Review carrying a real Issue Date → FIXED to Active.
  - Missing FILE_DATE filled from parseable Issue Date (only date
    field the portal exposes).
  - Missing PERMIT_DATE on Active / Final filled from Issue Date.
  - Spurious PERMIT_DATE on In Review cleared.
  - Spurious FINAL_DATE on non-Final cleared (none expected in sample).

Not repairable from DATA:
  - No applied/submittal date field → FILE_DATE only fillable when
    Issue Date parses; true Under Review shells with work-description
    text in the Issue Date column stay missing FILE_DATE.
  - Closed / Final shells have no finaled stamp or inspections →
    FINAL_DATE stays missing.
  - Issue Date column frequently holds work descriptions or names
    when Status is Under Review / Closed (scraping / blank column);
    those values are treated as null dates.
"""

from __future__ import annotations

import json
import math
from typing import Optional

import numpy as np
import pandas as pd


_MIN_YEAR = 1980
_MAX_YEAR = 2035

_STATUS_LIKE_SUBTYPES = {
    "closed",
    "void",
    "issued",
    "co issued",
    "cc issued",
    "under review",
    "denied",
    "online application received",
}


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


def _clean_status_text(val) -> Optional[str]:
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return None
    s = str(val).strip()
    return s or None


# ── Field extractors ─────────────────────────────────────────────────────────

def _raw_status_fields(d: dict):
    """Return (primary_status, subtype, misaligned)."""
    primary = _clean_status_text(d.get("Status") if "Status" in d else d.get("Status:"))
    subtype = _clean_status_text(d.get("Sub Type"))
    misaligned = False
    if subtype is not None and subtype.lower() in _STATUS_LIKE_SUBTYPES:
        if primary is None:
            # Status key absent / blank; lifecycle label landed in Sub Type.
            misaligned = True
        elif primary.lower() not in _STATUS_MAP:
            # Owner name / work description in Status; true label in Sub Type.
            misaligned = True
    return primary, subtype, misaligned


def _issue_date(d: dict):
    """Parseable Issue Date only (non-dates in that column → NaT)."""
    return _safe_to_datetime(d.get("Issue Date"))


# ── Schema classification ────────────────────────────────────────────────────

def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"

    keys = set(data_dict.keys())
    if not ({"Permit #", "Permit Type"} & keys) and "Status" not in keys:
        return "unknown"
    if "Reviews" in keys or "Permit Details" in keys or "Inspections" in keys:
        # Gulf sample is simple-only; keep a distinct tag if rich rows appear.
        base = "rich"
    else:
        base = "simple"

    issued = _issue_date(data_dict)
    if _present(issued):
        return f"{base}_issued"
    return f"{base}_status_only"


# ── Status mapping ───────────────────────────────────────────────────────────

_STATUS_MAP = {
    # Final
    "closed": "Final",
    "co issued": "Final",
    "cc issued": "Final",
    # Active
    "issued": "Active",
    # In Review
    "under review": "In Review",
    "online application received": "In Review",
    "incomplete application": "In Review",
    "approved - awaiting payment": "In Review",
    # Inactive
    "void": "Inactive",
    "denied": "Inactive",
}


def _lookup_status(label: Optional[str]) -> Optional[str]:
    if label is None:
        return None
    return _STATUS_MAP.get(label.strip().lower())


def _expected_status(d: dict) -> Optional[str]:
    primary, subtype, misaligned = _raw_status_fields(d)
    issued = _issue_date(d)

    mapped = _lookup_status(primary)
    if mapped is None and misaligned:
        mapped = _lookup_status(subtype)

    if mapped is None:
        if _present(issued):
            return "Active"
        return None

    if mapped == "Inactive":
        return "Inactive"

    # Pre-issuance labels with a real issue date are post-issuance.
    if mapped == "In Review" and _present(issued):
        return "Active"

    return mapped


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


# ── Per-record repair ───────────────────────────────────────────────────────

def _repair_record(row, d: dict, repairs: dict) -> None:
    expected = _expected_status(d)
    effective_status = _apply_status(repairs, row["STATUS_NORMALIZED"], expected)

    issued = _issue_date(d)

    # -- FILE_DATE ← Issue Date (only applied-date proxy in DATA) --
    if _present(issued):
        if pd.isna(row["FILE_DATE"]):
            repairs["FILE_DATE"] = issued
            repairs["FILE_DATE_FLAG"] = "FILLED"
        elif not _dates_equal(row["FILE_DATE"], issued):
            # No separate applied date; keep Issue Date as the sole proxy.
            repairs["FILE_DATE"] = issued
            repairs["FILE_DATE_FLAG"] = "FIXED"

    # -- PERMIT_DATE ← Issue Date --
    current_permit = row["PERMIT_DATE"]
    if effective_status in ("Active", "Final", "Inactive"):
        if _present(issued):
            if pd.isna(current_permit):
                repairs["PERMIT_DATE"] = issued
                repairs["PERMIT_DATE_FLAG"] = "FILLED"
            elif not _dates_equal(current_permit, issued):
                repairs["PERMIT_DATE"] = issued
                repairs["PERMIT_DATE_FLAG"] = "FIXED"
    elif effective_status == "In Review" and not pd.isna(current_permit):
        # Pre-issuance statuses should not carry an issuance date.
        repairs["PERMIT_DATE"] = pd.NaT
        repairs["PERMIT_DATE_FLAG"] = "FIXED"

    # -- FINAL_DATE: no source in Gulf simple schema --
    current_final = row["FINAL_DATE"]
    if effective_status != "Final" and not pd.isna(current_final):
        repairs["FINAL_DATE"] = pd.NaT
        repairs["FINAL_DATE_FLAG"] = "FIXED"


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Gulf County permit records using information from the raw DATA JSON.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Gulf County".  Must
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
    from dotenv import load_dotenv

    load_dotenv("/Users/ekung/projects/la-permits-data/.env")
    MY_DATA_PATH = os.getenv("MY_DATA_PATH")
    AGENT_DATA_PATH = os.getenv("AGENT_DATA_PATH")
    filepath = os.path.join(
        MY_DATA_PATH, "processed_data", "permits_fl_sample.parquet"
    )
    df = pd.read_parquet(filepath)
    city = df[df["JURISDICTION"] == "Gulf County"].copy()

    print(f"Gulf County records: {len(city):,}\n")

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

    status_null = repaired["STATUS_NORMALIZED"].isna().sum()
    print(f"STATUS_NORMALIZED still null: {status_null}")

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
            raw = (d.get("Status") or "").strip() or "__EMPTY__"
            ps_counts[raw] += 1
        print("  by Status:", dict(ps_counts))

    if AGENT_DATA_PATH:
        out_path = os.path.join(
            AGENT_DATA_PATH, "gulf_county_repaired_sample.parquet"
        )
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote repaired sample → {out_path}")

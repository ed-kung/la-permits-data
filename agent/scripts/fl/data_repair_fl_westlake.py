"""Data repair for Westlake (FL) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Westlake DATA is an EnerGov / Civic platform community-development
payload with top-level keys ``Summary``, ``Contacts``, ``Locations``,
``Related Permit & Planning Applications``, plus either ``Permits``
(list) or ``Permit Info`` (dict), and optionally ``project_id``.
Variants (INFERRED_SCHEMA):

  - energov_permits_project_*: Permits list + project_id
  - energov_permits_*:         Permits list, no project_id
  - energov_permit_info_*:     Permit Info dict
  - Content suffixes:          _issued_finaled / _issued / _finaled /
                               _app_date / _minimal
  - missing / unknown

Canonical mappings:
  - Summary["Application Status"] with Issued Date /
    Date Finaled overrides                    → STATUS_NORMALIZED
  - Summary["Application Date"]               → FILE_DATE
  - Summary["Issued Date"]                    → PERMIT_DATE
  - Summary["Date Finaled"]                   → FINAL_DATE

Known issues repaired:
  - Returned for Correction / Submittals Incomplete left
    STATUS_NORMALIZED missing → FILLED as In Review.
  - One Closed row whose STATUS_ORIGINAL was stale
    "permit(s) issued" labeled Active → FIXED to Final.
  - One Permit(s) Issued row whose STATUS_ORIGINAL was
    "expired" labeled Inactive → FIXED to Active.
  - In Progress / Ready for Issuance / On Hold / In Plan Check
    rows that already carry Issued Date or Date Finaled
    remapped to Active / Final.
  - Spurious PERMIT_DATE on In Review / Inactive cleared.
  - Spurious FINAL_DATE on non-Final statuses cleared.

Not repairable from DATA:
  - ~1,266 Finaled / Closed Final rows with blank
    Summary["Date Finaled"] → FINAL_DATE stays missing
    (Expiration Date is not a completion stamp).
  - Active / Final rows with blank Summary["Issued Date"]
    → PERMIT_DATE stays missing.
"""

from __future__ import annotations

import json
import math
import re
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
    """Parse a date value, returning pd.NaT on failure / sentinel / OOR year."""
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return pd.NaT
    if isinstance(val, dict):
        return pd.NaT
    if isinstance(val, str):
        s = val.strip().replace("\xa0", " ")
        if not s or s.lower() in {"none", "null", "n/a", "na", "nan", "tbd"}:
            return pd.NaT
        if s.startswith("0001-01-01"):
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


def _present(dt) -> bool:
    return dt is not pd.NaT and not pd.isna(dt)


def _dates_equal(a, b) -> bool:
    """Compare two datelike values at calendar-day resolution."""
    da = _safe_to_datetime(a)
    db = _safe_to_datetime(b)
    if not _present(da) or not _present(db):
        return False
    return pd.Timestamp(da).normalize() == pd.Timestamp(db).normalize()


def _normalize_text(raw) -> Optional[str]:
    if raw is None or (isinstance(raw, float) and math.isnan(raw)):
        return None
    s = re.sub(r"\s+", " ", str(raw).replace("\xa0", " ")).strip()
    return s or None


def _summary(d: dict) -> dict:
    s = d.get("Summary")
    return s if isinstance(s, dict) else {}


def _app_status(d: dict) -> Optional[str]:
    return _normalize_text(_summary(d).get("Application Status"))


def _app_date(d: dict):
    return _safe_to_datetime(_summary(d).get("Application Date"))


def _issued_date(d: dict):
    return _safe_to_datetime(_summary(d).get("Issued Date"))


def _finaled_date(d: dict):
    return _safe_to_datetime(_summary(d).get("Date Finaled"))


# ── Status mapping ───────────────────────────────────────────────────────────

# Direct Application Status → STATUS_NORMALIZED (before date overrides).
_STATUS_MAP = {
    "Finaled": "Final",
    "Closed": "Final",
    "Permit(s) Issued": "Active",
    "Issued": "Active",
    "Pending": "In Review",
    "In Plan Check": "In Review",
    "Ready for Issuance": "In Review",
    "Returned for Correction": "In Review",
    "Submittals Incomplete": "In Review",
    "On Hold": "In Review",
    "In Progress": "In Review",
    "Historical": "In Review",
    "Revision – Upload Documents": "In Review",
    "Withdrawn": "Inactive",
    "Expired": "Inactive",
    "Canceled": "Inactive",
    "Cancelled": "Inactive",
    "Abandoned": "Inactive",
    "Denied": "Inactive",
    "Recalled": "Inactive",
}

_INACTIVE = {
    "Withdrawn",
    "Expired",
    "Canceled",
    "Cancelled",
    "Abandoned",
    "Denied",
    "Recalled",
}


def _expected_status(d: dict) -> Optional[str]:
    """Derive STATUS_NORMALIZED from Application Status with date overrides.

    Priority:
      1. Terminal inactive Application Status → Inactive
      2. Date Finaled present, or Finaled/Closed status → Final
      3. Issued Date present, or Permit(s) Issued/Issued → Active
      4. Otherwise map Application Status.
    """
    status = _app_status(d)
    finaled = _finaled_date(d)
    issued = _issued_date(d)

    if status in _INACTIVE:
        return "Inactive"

    if _present(finaled) or status in {"Finaled", "Closed"}:
        return "Final"

    if _present(issued) or status in {"Permit(s) Issued", "Issued"}:
        return "Active"

    if status is not None:
        return _STATUS_MAP.get(status)

    return None


# ── Schema classification ────────────────────────────────────────────────────

def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())
    if "Summary" not in keys:
        return "unknown"

    if "Permits" in keys and "project_id" in keys:
        base = "energov_permits_project"
    elif "Permits" in keys:
        base = "energov_permits"
    elif "Permit Info" in keys:
        base = "energov_permit_info"
    else:
        base = "energov"

    has_app = _present(_app_date(data_dict))
    has_issued = _present(_issued_date(data_dict))
    has_finaled = _present(_finaled_date(data_dict))

    if has_issued and has_finaled:
        return f"{base}_issued_finaled"
    if has_issued:
        return f"{base}_issued"
    if has_finaled:
        return f"{base}_finaled"
    if has_app:
        return f"{base}_app_date"
    return f"{base}_minimal"


# ── Per-record repair logic ─────────────────────────────────────────────────

def _repair_record(row, d: dict, repairs: dict) -> None:
    """Populate *repairs* with corrected values for a single record."""
    current_status = row["STATUS_NORMALIZED"]
    expected = _expected_status(d)

    # -- STATUS_NORMALIZED --
    if expected is not None:
        if pd.isna(current_status):
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"
        elif current_status != expected:
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FIXED"

    effective_status = repairs.get("STATUS_NORMALIZED", current_status)

    app = _app_date(d)
    issued = _issued_date(d)
    finaled = _finaled_date(d)

    # -- FILE_DATE (application / Summary["Application Date"]) --
    if _present(app):
        if pd.isna(row["FILE_DATE"]):
            repairs["FILE_DATE"] = app
            repairs["FILE_DATE_FLAG"] = "FILLED"
        elif not _dates_equal(row["FILE_DATE"], app):
            repairs["FILE_DATE"] = app
            repairs["FILE_DATE_FLAG"] = "FIXED"

    # -- PERMIT_DATE (issuance / Summary["Issued Date"]) --
    current_permit = row["PERMIT_DATE"]
    if effective_status in ("Active", "Final"):
        if _present(issued):
            if pd.isna(current_permit):
                repairs["PERMIT_DATE"] = issued
                repairs["PERMIT_DATE_FLAG"] = "FILLED"
            elif not _dates_equal(current_permit, issued):
                repairs["PERMIT_DATE"] = issued
                repairs["PERMIT_DATE_FLAG"] = "FIXED"
    elif not pd.isna(current_permit):
        # Spurious issuance stamp on In Review / Inactive.
        repairs["PERMIT_DATE"] = pd.NaT
        repairs["PERMIT_DATE_FLAG"] = "FIXED"

    # -- FINAL_DATE (completion / Summary["Date Finaled"]) --
    current_final = row["FINAL_DATE"]
    if effective_status == "Final":
        if _present(finaled):
            if pd.isna(current_final) or not _present(_safe_to_datetime(current_final)):
                repairs["FINAL_DATE"] = finaled
                repairs["FINAL_DATE_FLAG"] = (
                    "FILLED" if pd.isna(current_final) else "FIXED"
                )
            elif not _dates_equal(current_final, finaled):
                repairs["FINAL_DATE"] = finaled
                repairs["FINAL_DATE_FLAG"] = "FIXED"
        elif not pd.isna(current_final) and not _present(
            _safe_to_datetime(current_final)
        ):
            repairs["FINAL_DATE"] = pd.NaT
            repairs["FINAL_DATE_FLAG"] = "FIXED"
    elif not pd.isna(current_final):
        repairs["FINAL_DATE"] = pd.NaT
        repairs["FINAL_DATE_FLAG"] = "FIXED"


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Westlake (FL) permit records using information from the raw DATA JSON.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Westlake". Must contain
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
        _repair_record(row, d, repairs)

        for key, value in repairs.items():
            out.at[idx, key] = value

    for col in ("FILE_DATE", "PERMIT_DATE", "FINAL_DATE"):
        if col in out.columns:
            out[col] = pd.to_datetime(out[col], errors="coerce")

    return out


# ── CLI: run standalone to preview repair stats ─────────────────────────────

if __name__ == "__main__":
    import os
    from pathlib import Path

    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[3] / ".env")
    MY_DATA_PATH = os.getenv("MY_DATA_PATH")
    AGENT_DATA_PATH = os.getenv("AGENT_DATA_PATH")
    filepath = os.path.join(
        MY_DATA_PATH, "processed_data", "permits_fl_sample.parquet"
    )
    df = pd.read_parquet(filepath)
    city = df[(df["JURISDICTION"] == "Westlake") & (df["STATE"] == "FL")].copy()

    print(f"Westlake records: {len(city):,}\n")

    repaired = data_repair(city)

    if AGENT_DATA_PATH:
        out_dir = Path(AGENT_DATA_PATH) / "repaired"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "permits_fl_westlake_repaired.parquet"
        repaired.to_parquet(out_path, index=False)
        print(f"Wrote {out_path}\n")

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

    print("\nStatus transitions (before → after):")
    mask = repaired["STATUS_NORMALIZED_FLAG"].notna()
    if mask.any():
        transitions = (
            pd.DataFrame({
                "before": city.loc[mask, "STATUS_NORMALIZED"].fillna("nan").astype(str),
                "after": repaired.loc[mask, "STATUS_NORMALIZED"].fillna("nan").astype(str),
            })
            .value_counts()
            .reset_index(name="n")
        )
        for _, trow in transitions.iterrows():
            print(f"  {trow['before']:15s} → {trow['after']:15s}: {trow['n']:>4,}")
    else:
        print("  (none)")

    print("\nPERMIT_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["PERMIT_DATE"].notna().sum()
        n = len(sub)
        pct = n_has / n if n else 0.0
        print(f"  {status:15s}: {n_has:>4,} / {n:>4,} ({pct:.1%})")

    print("\nFINAL_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FINAL_DATE"].notna().sum()
        n = len(sub)
        pct = n_has / n if n else 0.0
        print(f"  {status:15s}: {n_has:>4,} / {n:>4,} ({pct:.1%})")

    print("\nFILE_DATE coverage (after repair):")
    n_has = repaired["FILE_DATE"].notna().sum()
    print(f"  {n_has:>4,} / {len(repaired):>4,} ({n_has / len(repaired):.1%})")

    fd = pd.to_datetime(repaired["FILE_DATE"], errors="coerce")
    pd_ = pd.to_datetime(repaired["PERMIT_DATE"], errors="coerce")
    ff = pd.to_datetime(repaired["FINAL_DATE"], errors="coerce")
    both_fp = fd.notna() & pd_.notna()
    both_pf = pd_.notna() & ff.notna()
    print("\nChronology inversions:")
    print(f"  FILE > PERMIT: {(both_fp & (fd.dt.normalize() > pd_.dt.normalize())).sum()}")
    print(f"  PERMIT > FINAL: {(both_pf & (pd_.dt.normalize() > ff.dt.normalize())).sum()}")

    print("\nRemaining ideal-coverage gaps:")
    active_final = repaired["STATUS_NORMALIZED"].isin(["Active", "Final"])
    final = repaired["STATUS_NORMALIZED"] == "Final"
    print(
        f"  Active/Final missing PERMIT_DATE: "
        f"{(active_final & repaired['PERMIT_DATE'].isna()).sum()}"
    )
    print(
        f"  Final missing FINAL_DATE: "
        f"{(final & repaired['FINAL_DATE'].isna()).sum()}"
    )
    print(f"  Any missing FILE_DATE: {repaired['FILE_DATE'].isna().sum()}")
    print(f"  Any missing STATUS_NORMALIZED: {repaired['STATUS_NORMALIZED'].isna().sum()}")

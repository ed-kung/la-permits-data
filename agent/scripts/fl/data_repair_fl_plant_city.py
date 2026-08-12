"""Data repair for Plant City (FL) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Plant City DATA is a CityView / CentralSquare community portal payload
with top-level keys ``id``, ``type``, ``number``, ``status``, ``details``,
``timeline``, ``customFields``, ``contacts``, and optional
``lastUpdDate`` / ``entryForms`` / ``canMakeOperations`` /
``canUpdateCompositeDetails`` / ``isPrimaryContact``. Variants
(INFERRED_SCHEMA):

  - cityview_portal_*: interactive keys (entryForms / canMakeOperations)
  - cityview_updated_*: has lastUpdDate, no portal extras
  - cityview_*:         core payload only
  - Content suffixes:   _issued_closed / _issued / _closed / _created /
                        _minimal
  - missing / unknown

Canonical mappings:
  - DATA["status"] with Inactive detail-status overrides and
    Closed/Issued date overrides          → STATUS_NORMALIZED
  - details.created                       → FILE_DATE
  - details.issued                        → PERMIT_DATE
  - details.closed (rejecting 1899 / <1980
    sentinel placeholders)                → FINAL_DATE

Known issues repaired:
  - Open BDMS / Legacy Building rows with a real Closed stamp mislabeled
    In Review → FIXED to Final (~704).
  - Open rows with Issued but no real Closed → FIXED to Active (~338),
    including shells whose FINAL_DATE was the 1899-11-30 sentinel.
  - Open rows with Expired / Cancelled / Withdrawn detail status →
    FIXED to Inactive (~65).
  - One Issued row with a real Closed stamp labeled Active → Final.
  - 145 FINAL_DATE values of 1899-11-30 (SQL/empty-date sentinel)
    cleared; spurious FINAL_DATE on non-Final statuses cleared.
  - Spurious PERMIT_DATE on In Review / Inactive cleared after
    status overrides.

Not repairable from DATA:
  - FILE_DATE already matches details.created for every sample row.
  - ~4 Issued Active rows with blank details.issued (timeline tasks
    lack timestamps) → PERMIT_DATE stays missing.
  - ~75 Final rows with blank details.issued (mostly Code Enf. /
    Legacy Planning) → PERMIT_DATE stays missing.
  - 5 Closed Finals (Legacy Building COMPLETE) with blank
    details.closed / customFields Closed Date → FINAL_DATE stays
    missing.
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
    # CityView / SQL empty-date sentinel observed as 1899-11-30.
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


def _details(d: dict) -> dict:
    det = d.get("details")
    return det if isinstance(det, dict) else {}


def _normalize_text(raw) -> Optional[str]:
    if raw is None or (isinstance(raw, float) and math.isnan(raw)):
        return None
    s = re.sub(r"\s+", " ", str(raw).replace("\xa0", " ")).strip()
    return s or None


def _detail_status(d: dict) -> Optional[str]:
    det = _details(d)
    return _normalize_text(det.get("status") or det.get("caseStatus"))


def _is_inactive_detail_status(ds: Optional[str]) -> bool:
    if not ds:
        return False
    low = ds.lower()
    if low.startswith("expir"):
        return True
    if low.startswith("cancel"):
        return True
    if "withdraw" in low:
        return True
    if low == "void":
        return True
    return False


def _created(d: dict):
    return _safe_to_datetime(_details(d).get("created"))


def _issued(d: dict):
    return _safe_to_datetime(_details(d).get("issued"))


def _closed(d: dict):
    return _safe_to_datetime(_details(d).get("closed"))


# ── Schema classification ────────────────────────────────────────────────────

def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())
    if "details" not in keys or "status" not in keys:
        return "unknown"

    if "entryForms" in keys or "canMakeOperations" in keys:
        base = "cityview_portal"
    elif "lastUpdDate" in keys:
        base = "cityview_updated"
    else:
        base = "cityview"

    has_created = _present(_created(data_dict))
    has_issued = _present(_issued(data_dict))
    has_closed = _present(_closed(data_dict))

    if has_issued and has_closed:
        return f"{base}_issued_closed"
    if has_issued:
        return f"{base}_issued"
    if has_closed:
        return f"{base}_closed"
    if has_created:
        return f"{base}_created"
    return f"{base}_minimal"


# ── Status mapping ───────────────────────────────────────────────────────────

_TOP_STATUS_MAP = {
    "Closed": "Final",
    "Issued": "Active",
    "Approved": "Active",
    "Open": "In Review",
    "Void": "Inactive",
}


def _expected_status(d: dict) -> Optional[str]:
    """Derive STATUS_NORMALIZED from top-level status with overrides.

    Priority:
      1. Top-level Void / Expired|Cancelled|Withdrawn detail status
         → Inactive
      2. Top-level Closed or a real details.closed stamp → Final
      3. Top-level Issued/Approved or a real details.issued stamp
         → Active
      4. Otherwise map top-level status (Open → In Review).
    """
    top = _normalize_text(d.get("status"))
    ds = _detail_status(d)
    closed = _closed(d)
    issued = _issued(d)

    if top == "Void" or _is_inactive_detail_status(ds):
        return "Inactive"

    if top == "Closed" or _present(closed):
        return "Final"

    if top in ("Issued", "Approved") or _present(issued):
        return "Active"

    if top is not None:
        return _TOP_STATUS_MAP.get(top)

    return None


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

    created = _created(d)
    issued = _issued(d)
    closed = _closed(d)

    # -- FILE_DATE (application / details.created) --
    if _present(created):
        if pd.isna(row["FILE_DATE"]):
            repairs["FILE_DATE"] = created
            repairs["FILE_DATE_FLAG"] = "FILLED"
        elif not _dates_equal(row["FILE_DATE"], created):
            repairs["FILE_DATE"] = created
            repairs["FILE_DATE_FLAG"] = "FIXED"

    # -- PERMIT_DATE (issuance / details.issued) --
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

    # -- FINAL_DATE (completion / details.closed; drop sentinels) --
    current_final = row["FINAL_DATE"]
    if effective_status == "Final":
        if _present(closed):
            if pd.isna(current_final) or not _present(_safe_to_datetime(current_final)):
                # Missing or sentinel (1899) current value.
                repairs["FINAL_DATE"] = closed
                repairs["FINAL_DATE_FLAG"] = (
                    "FILLED" if pd.isna(current_final) else "FIXED"
                )
            elif not _dates_equal(current_final, closed):
                repairs["FINAL_DATE"] = closed
                repairs["FINAL_DATE_FLAG"] = "FIXED"
        elif not pd.isna(current_final) and not _present(_safe_to_datetime(current_final)):
            # Final without a real closed stamp but carrying a sentinel.
            repairs["FINAL_DATE"] = pd.NaT
            repairs["FINAL_DATE_FLAG"] = "FIXED"
    elif not pd.isna(current_final):
        repairs["FINAL_DATE"] = pd.NaT
        repairs["FINAL_DATE_FLAG"] = "FIXED"


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Plant City (FL) permit records using information from the raw DATA JSON.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Plant City". Must contain
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
    city = df[(df["JURISDICTION"] == "Plant City") & (df["STATE"] == "FL")].copy()

    print(f"Plant City records: {len(city):,}\n")

    repaired = data_repair(city)

    if AGENT_DATA_PATH:
        out_dir = Path(AGENT_DATA_PATH) / "repaired"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "permits_fl_plant_city_repaired.parquet"
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

    print("\nFINAL_DATE year < 1980 remaining:", (ff.dt.year < 1980).sum())

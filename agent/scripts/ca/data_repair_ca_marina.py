"""Data repair for Marina (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Marina DATA is a civic portal scrape with two payload families:

  - list_*:    flat list-page rows (``Status``, ``Permit#``, ``Issue Date``)
  - portal_*:  detail-page rows (``Status:``, ``Permit Details``, optional
               ``Reviews`` / ``Inspections`` / form fields / ``Balance Due:``)

Content variants recorded in INFERRED_SCHEMA:

  - list_simple                 list page, no Work Description
  - list_with_work              list page + Work Description
  - portal_reviews_inspections  nonempty Reviews + Inspections
  - portal_reviews              nonempty Reviews only
  - portal_inspections          nonempty Inspections only
  - portal_basic                Status: / Permit Details shell only
  - portal_form                 building-application form fields, no
                                Reviews/Inspections
  - portal_rpir                 Residential Property Inspection Request
                                form, no Reviews/Inspections
  - missing

Canonical mappings:
  - DATA['Status'] / DATA['Status:']              → STATUS_NORMALIZED
  - Earliest Reviews[].Start                      → FILE_DATE
  - Permit Details['Issue Date:'] or parseable
    top-level Issue Date                          → PERMIT_DATE
  - Latest passed Final* inspection (type name
    contains 'Final'), else RPI Pass              → FINAL_DATE

Known issues repaired:
  - FILE_DATE often taken from Issue Date / mid-stream review
    Completion / Final Review Start instead of earliest
    Reviews[].Start → FIXED; missing FILE with Reviews → FILLED.
  - FINAL_DATE missing on every row; Complete/Closed (and stale
    Issued/Approved) with a passed Final* or RPI inspection → FILLED.
  - Issued / Approved shells with a passed Final* inspection left
    Active → FIXED to Final.
  - Online Application Received / Pending / Continued with a real
    Issue Date left In Review → FIXED to Active.

Not repairable / left as-is:
  - 11 blank / garbage Status shells (``Type: Project Description…``
    or empty Status:) → STATUS stays missing.
  - ~1.7k list / detail shells with no Reviews → FILE_DATE stays
    missing (DATA has no application date).
  - 52 Active/Final rows with no parseable Issue Date → PERMIT_DATE
    stays missing.
  - Most Complete list_simple shells have no Inspections → FINAL_DATE
    stays missing.
  - Top-level Issue Date is often work-description text (column
    shift); those values are rejected.
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

_PASS_STATUSES = {"pass", "passed", "completed", "complete"}

# Reject work-description pollution stuffed into Issue Date.
_DATE_LIKE_RE = re.compile(
    r"^\s*\d{1,2}/\d{1,2}/\d{2,4}(?:\s+\d{1,2}:\d{2}(?::\d{2})?)?\s*$"
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
    """Parse a date value, returning pd.NaT on failure or implausible year.

    Rejects long / non-date strings (Marina list-page Issue Date is often
    polluted with work-description text).
    """
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return pd.NaT
    if isinstance(val, str):
        s = val.strip()
        if not s:
            return pd.NaT
        # Strict date-shaped strings only (slash dates from the portal).
        if not _DATE_LIKE_RE.match(s):
            # Also allow ISO YYYY-MM-DD.
            if not re.match(r"^\d{4}-\d{2}-\d{2}", s):
                return pd.NaT
            if len(s) > 32:
                return pd.NaT
        elif len(s) > 32:
            return pd.NaT
    try:
        dt = pd.to_datetime(val, errors="coerce")
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


def _permit_details(d: dict) -> dict:
    pd_ = d.get("Permit Details")
    return pd_ if isinstance(pd_, dict) else {}


def _reviews(d: dict) -> list:
    revs = d.get("Reviews")
    return revs if isinstance(revs, list) else []


def _inspections(d: dict) -> list:
    insp = d.get("Inspections")
    return insp if isinstance(insp, list) else []


def _insp_status_clean(raw) -> str:
    return str(raw or "").split("\n")[0].strip().lower()


def _raw_status(d: dict) -> Optional[str]:
    """Prefer detail-page Status:; fall back to list-page Status."""
    for key in ("Status:", "Status"):
        raw = d.get(key)
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
    return None


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())

    # List-page family (flat Status / Permit#)
    if "Permit Details" not in keys and "Reviews" not in keys and (
        "Status" in keys or "Permit#" in keys
    ):
        if "Work Description" in keys:
            return "list_with_work"
        return "list_simple"

    # Detail-page family
    if "Status:" in keys or "Permit Details" in keys or "Reviews" in keys:
        has_reviews = bool(_reviews(data_dict))
        has_insp = bool(_inspections(data_dict))
        if has_reviews and has_insp:
            return "portal_reviews_inspections"
        if has_reviews:
            return "portal_reviews"
        if has_insp:
            return "portal_inspections"
        if "Residential Property Inspection Request" in keys:
            return "portal_rpir"
        if "Estimated Cost of Construction" in keys or "ADU" in keys:
            return "portal_form"
        return "portal_basic"

    return "unknown"


# ── Status mapping ───────────────────────────────────────────────────────────

_STATUS_MAP = {
    # Final
    "Complete": "Final",
    "Closed": "Final",
    # Active
    "Issued": "Active",
    "Approved": "Active",
    # Inactive
    "Expired": "Inactive",
    "Void": "Inactive",
    "Withdrawn": "Inactive",
    # In Review
    "Under Review": "In Review",
    "Online Application Received": "In Review",
    "Pending": "In Review",
    "Continued": "In Review",
}

_INACTIVE_LABELS = {"Expired", "Void", "Withdrawn"}


def _issue_date(d: dict):
    """Prefer Permit Details Issue Date:; else parseable top-level Issue Date."""
    details = _permit_details(d)
    dt = _safe_to_datetime(details.get("Issue Date:"))
    if dt is not pd.NaT:
        return dt
    return _safe_to_datetime(d.get("Issue Date"))


def _file_date_from_data(d: dict):
    """Earliest Reviews[].Start = application / intake date."""
    starts = []
    for r in _reviews(d):
        if not isinstance(r, dict):
            continue
        dt = _safe_to_datetime(r.get("Start"))
        if dt is not pd.NaT:
            starts.append(dt)
    return min(starts) if starts else pd.NaT


def _final_date_from_data(d: dict):
    """Latest passed Final* inspection; else RPI Pass as completion stamp."""
    final_dates = []
    rpi_dates = []
    for i in _inspections(d):
        if not isinstance(i, dict):
            continue
        if _insp_status_clean(i.get("Status")) not in _PASS_STATUSES:
            continue
        dt = _safe_to_datetime(i.get("Date"))
        if dt is pd.NaT:
            continue
        itype = str(i.get("Inspection Type") or "")
        ilow = itype.lower()
        if "final" in ilow:
            final_dates.append(dt)
        elif "residential property inspection" in ilow:
            rpi_dates.append(dt)
    if final_dates:
        return max(final_dates)
    if rpi_dates:
        return max(rpi_dates)
    return pd.NaT


def _has_passed_final_inspection(d: dict) -> bool:
    for i in _inspections(d):
        if not isinstance(i, dict):
            continue
        itype = str(i.get("Inspection Type") or "")
        if "final" not in itype.lower():
            continue
        if _insp_status_clean(i.get("Status")) not in _PASS_STATUSES:
            continue
        if _safe_to_datetime(i.get("Date")) is not pd.NaT:
            return True
    return False


def _mapped_status(d: dict) -> Optional[str]:
    raw = _raw_status(d)
    if raw is None:
        return None
    # Garbage column-shift Status values are not mappable.
    if raw.lower().startswith("type:"):
        return None
    return _STATUS_MAP.get(raw)


def _expected_status(d: dict) -> Optional[str]:
    """Derive STATUS_NORMALIZED with inspection / Issue Date overrides.

    Inactive terminal labels are sticky. A dated passed Final*
    inspection promotes Issued/Approved (and other non-inactive) shells
    to Final. A real Issue Date promotes review-pipeline labels to
    Active. Otherwise use the Status / Status: map.
    """
    raw = _raw_status(d)
    if raw in _INACTIVE_LABELS:
        return "Inactive"

    if _has_passed_final_inspection(d):
        return "Final"

    mapped = _mapped_status(d)
    if mapped == "Final":
        return "Final"

    # Issuance evidence upgrades review-pipeline labels to Active.
    if _issue_date(d) is not pd.NaT and mapped == "In Review":
        return "Active"

    return mapped


# ── Repair logic ─────────────────────────────────────────────────────────────

def _repair_record(row, d: dict, repairs: dict):
    # -- STATUS_NORMALIZED --
    current_status = row["STATUS_NORMALIZED"]
    expected = _expected_status(d)
    if expected is not None:
        if pd.isna(current_status):
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"
        elif current_status != expected:
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FIXED"

    effective_status = repairs.get("STATUS_NORMALIZED", current_status)

    # -- FILE_DATE (earliest review Start) --
    file_date = _file_date_from_data(d)
    if file_date is not pd.NaT:
        if pd.isna(row["FILE_DATE"]):
            repairs["FILE_DATE"] = file_date
            repairs["FILE_DATE_FLAG"] = "FILLED"
        elif not _dates_equal(row["FILE_DATE"], file_date):
            repairs["FILE_DATE"] = file_date
            repairs["FILE_DATE_FLAG"] = "FIXED"

    # -- PERMIT_DATE (Issue Date) --
    issued = _issue_date(d)
    current_permit = row["PERMIT_DATE"]

    if issued is not pd.NaT:
        if pd.isna(current_permit):
            if effective_status in ("Active", "Final"):
                repairs["PERMIT_DATE"] = issued
                repairs["PERMIT_DATE_FLAG"] = "FILLED"
        elif not _dates_equal(current_permit, issued):
            repairs["PERMIT_DATE"] = issued
            repairs["PERMIT_DATE_FLAG"] = "FIXED"
    elif not pd.isna(current_permit) and effective_status == "In Review":
        # No issuance evidence; clear spurious permit dates on review rows.
        repairs["PERMIT_DATE"] = pd.NaT
        repairs["PERMIT_DATE_FLAG"] = "FIXED"

    # -- FINAL_DATE (passed Final* / RPI inspection) --
    # Only keep FINAL_DATE when status is Final.
    final_date = _final_date_from_data(d)
    current_final = row["FINAL_DATE"]

    if effective_status == "Final":
        if final_date is not pd.NaT:
            if pd.isna(current_final):
                repairs["FINAL_DATE"] = final_date
                repairs["FINAL_DATE_FLAG"] = "FILLED"
            elif not _dates_equal(current_final, final_date):
                repairs["FINAL_DATE"] = final_date
                repairs["FINAL_DATE_FLAG"] = "FIXED"
    elif not pd.isna(current_final):
        repairs["FINAL_DATE"] = pd.NaT
        repairs["FINAL_DATE_FLAG"] = "FIXED"


# ── Main entry point ─────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Marina (CA) permit records using information from the raw DATA JSON.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Marina". Must contain
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
            out[col] = pd.to_datetime(out[col], utc=True, errors="coerce")

    return out


# ── CLI: run standalone to preview repair stats ──────────────────────────────

if __name__ == "__main__":
    import os
    from pathlib import Path

    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[3] / ".env")
    MY_DATA_PATH = os.getenv("MY_DATA_PATH")
    AGENT_DATA_PATH = os.getenv("AGENT_DATA_PATH")
    filepath = os.path.join(
        MY_DATA_PATH, "processed_data", "permits_ca_sample.parquet"
    )
    df = pd.read_parquet(filepath)
    city = df[(df["JURISDICTION"] == "Marina") & (df["STATE"] == "CA")].copy()

    print(f"Marina records: {len(city):,}\n")

    repaired = data_repair(city)

    if AGENT_DATA_PATH:
        out_dir = Path(AGENT_DATA_PATH) / "repaired"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "permits_ca_marina_repaired.parquet"
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

    fd = pd.to_datetime(repaired["FILE_DATE"], utc=True, errors="coerce")
    pd_ = pd.to_datetime(repaired["PERMIT_DATE"], utc=True, errors="coerce")
    ff = pd.to_datetime(repaired["FINAL_DATE"], utc=True, errors="coerce")
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

    from collections import Counter

    print("\nActive/Final still missing PERMIT_DATE (by Status):")
    gap = Counter()
    for idx in repaired.index:
        if repaired.at[idx, "STATUS_NORMALIZED"] not in ("Active", "Final"):
            continue
        if pd.notna(repaired.at[idx, "PERMIT_DATE"]):
            continue
        d = _safe_parse(city.at[idx, "DATA"])
        gap[_raw_status(d or {})] += 1
    for k, v in gap.most_common():
        print(f"  {k}: {v}")

    print("\nFinal still missing FINAL_DATE (by Status / schema):")
    gap = Counter()
    for idx in repaired.index:
        if repaired.at[idx, "STATUS_NORMALIZED"] != "Final":
            continue
        if pd.notna(repaired.at[idx, "FINAL_DATE"]):
            continue
        d = _safe_parse(city.at[idx, "DATA"])
        gap[(_raw_status(d or {}), repaired.at[idx, "INFERRED_SCHEMA"])] += 1
    for k, v in gap.most_common(15):
        print(f"  {k}: {v}")

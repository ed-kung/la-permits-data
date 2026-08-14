"""Data repair for Newberry (FL) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Newberry DATA is a SmartGov community portal payload (same family as
Redington Shores / Longwood / Lighthouse Point) with top-level keys
``Department``, ``My Project``, ``Permit Type``, ``Build Status``,
``Permit Number``, ``Permit Details``, contacts/fees/inspections arrays,
and optionally ``Parcel Number`` / ``ProjectDescription``.

Variants (INFERRED_SCHEMA):
  - smartgov_full:     core keys + ProjectDescription (+ Parcel Number)
  - smartgov_no_desc:  core keys + Parcel Number (no ProjectDescription)
  - smartgov_minimal:  SmartGov core without Parcel Number /
                       ProjectDescription
  - smartgov_empty:    SmartGov keyset present but all canonical fields
                       blank (scraped shell with no permit payload)
  - missing / unknown

Canonical mappings:
  - DATA["Build Status"] (Expired* / Cancelled / Withdrawn sticky
    Inactive; Closed / Certificate of Completion|Occupancy → Final;
    Active / Approved / Issued → Active; review-family → In Review),
    with Closed-date / Issued-date overrides
                                                  → STATUS_NORMALIZED
  - My Project.Submitted (fallback Created)       → FILE_DATE
  - My Project.Issued (fallback Approved)         → PERMIT_DATE
  - My Project.Closed (fallback latest passed
    Building Final / COO inspection)              → FINAL_DATE

Known issues repaired:
  - ~801 null STATUS_NORMALIZED rows (null Build Status /
    STATUS_ORIGINAL) inferred from My Project dates → FILLED
    (Closed→Final, Issued→Active, else Submitted/Created/Approved→
    In Review).
  - Closed Build Status still labeled Active / In Review because
    STATUS_ORIGINAL lagged as "active" / "approved" → FIXED to Final;
    FINAL_DATE filled from Closed.
  - Expired* left null or mislabeled In Review / Active → FIXED/FILLED
    Inactive.
  - Certificate of Completion / Occupancy left Active / In Review →
    FIXED to Final.
  - Issued / Active / Approved Build Status labeled In Review or null
    → FIXED/FILLED Active; PERMIT_DATE filled from Issued.
  - Missing FILE_DATE filled from Submitted/Created; missing
    PERMIT_DATE / FINAL_DATE filled from Issued/Approved / Closed
    for Active/Final (and Inactive when previously issued).
  - Spurious FINAL_DATE on non-Final statuses cleared after status
    resolution.

Not repairable from DATA:
  - Fully empty SmartGov shells (no Build Status, Permit Number,
    Permit Type, or My Project dates) → status/dates stay missing.
  - Final / Certificate of Completion|Occupancy rows with blank Closed
    and no passed Building Final / COO inspection → FINAL_DATE stays
    missing.
  - Active / Final rows with blank Issued and blank Approved →
    PERMIT_DATE stays missing.
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

_BLANK_DATE_STRINGS = {
    "",
    "-",
    "--",
    " - -",
    "None",
    "null",
    "n/a",
    "N/A",
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


def _is_blank_date(val) -> bool:
    if val is None:
        return True
    if isinstance(val, float) and math.isnan(val):
        return True
    s = str(val).strip().replace("\xa0", " ")
    if s in _BLANK_DATE_STRINGS:
        return True
    # SmartGov placeholder: " - -", "- -", "-"
    if re.fullmatch(r"[\s\-]*", s):
        return True
    return False


def _safe_to_datetime(val):
    """Parse a date value, returning pd.NaT on failure or implausible year."""
    if _is_blank_date(val):
        return pd.NaT
    if isinstance(val, dict):
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


def _my_project(d: dict) -> dict:
    mp = d.get("My Project")
    return mp if isinstance(mp, dict) else {}


def _normalize_build_status(raw) -> Optional[str]:
    if raw is None or (isinstance(raw, float) and math.isnan(raw)):
        return None
    s = re.sub(r"\s+", " ", str(raw).replace("\xa0", " ")).strip()
    if not s or s.lower() == "none":
        return None
    if s.lower().startswith("expired"):
        return "Expired"
    return s


def _mp_date(d: dict, key: str):
    return _safe_to_datetime(_my_project(d).get(key))


def _has_usable_payload(d: dict) -> bool:
    """True if DATA carries any status/date/identity signal worth repairing."""
    if _normalize_build_status(d.get("Build Status")) is not None:
        return True
    if d.get("Permit Number"):
        return True
    if d.get("Permit Type"):
        return True
    if d.get("Application Number"):
        return True
    for key in ("Submitted", "Created", "Issued", "Approved", "Closed"):
        if _mp_date(d, key) is not pd.NaT:
            return True
    return False


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())
    if "My Project" not in keys:
        return "unknown"
    if not _has_usable_payload(data_dict):
        return "smartgov_empty"
    if "ProjectDescription" in keys:
        return "smartgov_full"
    if "Parcel Number" in keys:
        return "smartgov_no_desc"
    return "smartgov_minimal"


# ── Status mapping ──────────────────────────────────────────────────────────

# Keys are lower-case. Newberry uses title-case Build Status values plus
# "Expired: M/D/YYYY" and long hearing / completeness phrases.
_STATUS_MAP = {
    "closed": "Final",
    "finaled": "Final",
    "certificate of completion": "Final",
    "certificate of occupancy": "Final",
    "issued": "Active",
    "active": "Active",
    "approved": "Active",
    "renewed": "Active",
    "revised": "Active",
    "expired": "Inactive",
    "denied": "Inactive",
    "disapproved": "Inactive",
    "cancelled": "Inactive",
    "canceled": "Inactive",
    "withdrawn": "Inactive",
    "pending": "In Review",
    "pending review": "In Review",
    "in review": "In Review",
    "under review": "In Review",
    "routed for review": "In Review",
    "payment pending": "In Review",
    "conditions pending": "In Review",
    "additional information required": "In Review",
    "awaiting completeness review": "In Review",
    "pre-application meeting request received": "In Review",
    "administrative processes complete. ready for public hearing(s)": "In Review",
    "appeal period": "In Review",
    "resubmittal": "In Review",
    "ready to issue": "In Review",
    "return to applicant": "In Review",
    "awaiting corrections from applicant": "In Review",
    "incomplete": "In Review",
}

_FINAL_BUILD_STATUSES = {
    "closed",
    "finaled",
    "certificate of completion",
    "certificate of occupancy",
}

_INACTIVE_BUILD_STATUSES = {
    "expired",
    "denied",
    "disapproved",
    "cancelled",
    "canceled",
    "withdrawn",
}


def _map_build_status(bs: Optional[str]) -> Optional[str]:
    if bs is None:
        return None
    low = bs.lower()
    mapped = _STATUS_MAP.get(low)
    if mapped is not None:
        return mapped
    if low.startswith("sent to"):
        return "In Review"
    return None


def _status_from_dates(d: dict) -> Optional[str]:
    """Infer STATUS_NORMALIZED from My Project date availability."""
    if _mp_date(d, "Closed") is not pd.NaT:
        return "Final"
    if _mp_date(d, "Issued") is not pd.NaT:
        return "Active"
    if (
        _mp_date(d, "Submitted") is not pd.NaT
        or _mp_date(d, "Created") is not pd.NaT
        or _mp_date(d, "Approved") is not pd.NaT
    ):
        return "In Review"
    return None


def _expected_status(d: dict) -> Optional[str]:
    """Derive STATUS_NORMALIZED from Build Status with date overrides.

    Sticky Inactive for Expired / Denied / Cancelled / Withdrawn when no
    Closed date. Explicit Closed / Certificate of Completion|Occupancy →
    Final. Otherwise Closed date → Final, Issued date → Active (unless
    Build Status maps to Inactive without an Issued stamp that should
    remain Inactive). Null Build Status falls back to date inference.
    """
    bs = _normalize_build_status(d.get("Build Status"))
    closed = _mp_date(d, "Closed")
    issued = _mp_date(d, "Issued")
    bs_low = bs.lower() if bs is not None else None

    if bs == "Expired" or (bs_low is not None and bs_low in _INACTIVE_BUILD_STATUSES):
        # Terminal inactive statuses remain Inactive even if earlier Issued
        # dates exist, unless the project was later Closed/Finaled.
        if closed is not pd.NaT or (bs_low in _FINAL_BUILD_STATUSES):
            return "Final"
        return "Inactive"

    if bs_low in _FINAL_BUILD_STATUSES:
        return "Final"

    if closed is not pd.NaT:
        return "Final"

    if issued is not pd.NaT:
        mapped = _map_build_status(bs)
        if mapped == "Inactive":
            return "Inactive"
        return "Active"

    mapped = _map_build_status(bs)
    if mapped is not None:
        return mapped

    if bs is None:
        return _status_from_dates(d)

    return None


def _dates_equal(a, b) -> bool:
    """Compare two datelike values at calendar-day resolution."""
    da = _safe_to_datetime(a)
    db = _safe_to_datetime(b)
    if da is pd.NaT or db is pd.NaT or pd.isna(da) or pd.isna(db):
        return False
    return da.date() == db.date()


def _file_date_from_data(d: dict):
    submitted = _mp_date(d, "Submitted")
    if submitted is not pd.NaT:
        return submitted
    return _mp_date(d, "Created")


def _permit_date_from_data(d: dict):
    issued = _mp_date(d, "Issued")
    if issued is not pd.NaT:
        return issued
    return _mp_date(d, "Approved")


def _is_final_inspection_name(name: str) -> bool:
    """True for completion-type inspections; exclude prerequisite noise."""
    n = name.lower()
    if re.search(r"required (before|prior to) final", n):
        return False
    if re.search(r"affidavit required.*final", n):
        return False
    if re.search(r"certificate of occupancy|\bcoo\b|\bcoc\b", n):
        return True
    if re.search(r"building final|\bfinal\b", n):
        return True
    return False


def _final_inspection_date(d: dict):
    """Latest passed Building Final / Certificate of Occupancy inspection."""
    inspections = d.get("Permit Inspections") or []
    dates = []
    for insp in inspections:
        if not isinstance(insp, dict):
            continue
        status = str(insp.get("Status") or "").strip().lower()
        name = str(insp.get("Inspection") or "")
        if status not in ("passed", "approved", "completed"):
            continue
        if not _is_final_inspection_name(name):
            continue
        dt = _safe_to_datetime(insp.get("Date"))
        if dt is not pd.NaT:
            dates.append(dt)
    if not dates:
        return pd.NaT
    return max(dates)


def _final_date_from_data(d: dict):
    closed = _mp_date(d, "Closed")
    if closed is not pd.NaT:
        return closed
    return _final_inspection_date(d)


# ── Per-record repair logic ─────────────────────────────────────────────────

def _repair_record(row, d: dict, repairs: dict):
    """Populate *repairs* with corrected values for a single record."""
    if not _has_usable_payload(d):
        return

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

    # -- FILE_DATE (application / Submitted) --
    file_src = _file_date_from_data(d)
    if file_src is not pd.NaT:
        if pd.isna(row["FILE_DATE"]):
            repairs["FILE_DATE"] = file_src
            repairs["FILE_DATE_FLAG"] = "FILLED"
        elif not _dates_equal(row["FILE_DATE"], file_src):
            repairs["FILE_DATE"] = file_src
            repairs["FILE_DATE_FLAG"] = "FIXED"

    # -- PERMIT_DATE (issuance / Issued, else Approved) --
    permit_src = _permit_date_from_data(d)
    current_permit = row["PERMIT_DATE"]
    issued = _mp_date(d, "Issued")

    if not pd.isna(current_permit):
        if issued is not pd.NaT and not _dates_equal(current_permit, issued):
            repairs["PERMIT_DATE"] = issued
            repairs["PERMIT_DATE_FLAG"] = "FIXED"
        elif effective_status == "In Review" and issued is pd.NaT:
            # Spurious permit stamp on a still-in-review record.
            repairs["PERMIT_DATE"] = pd.NaT
            repairs["PERMIT_DATE_FLAG"] = "FIXED"
    elif effective_status in ("Active", "Final", "Inactive") and permit_src is not pd.NaT:
        # Inactive includes Expired / Withdrawn shells that were
        # previously issued / approved; fill from Issued, else Approved.
        repairs["PERMIT_DATE"] = permit_src
        repairs["PERMIT_DATE_FLAG"] = "FILLED"

    # -- FINAL_DATE (completion / Closed, else Building Final/COO insp) --
    final_src = _final_date_from_data(d)
    closed = _mp_date(d, "Closed")
    current_final = row["FINAL_DATE"]

    if effective_status == "Final":
        if final_src is not pd.NaT:
            if pd.isna(current_final):
                repairs["FINAL_DATE"] = final_src
                repairs["FINAL_DATE_FLAG"] = "FILLED"
            elif closed is not pd.NaT and not _dates_equal(current_final, closed):
                repairs["FINAL_DATE"] = closed
                repairs["FINAL_DATE_FLAG"] = "FIXED"
            elif closed is pd.NaT and not _dates_equal(current_final, final_src):
                repairs["FINAL_DATE"] = final_src
                repairs["FINAL_DATE_FLAG"] = "FIXED"
    elif not pd.isna(current_final):
        repairs["FINAL_DATE"] = pd.NaT
        repairs["FINAL_DATE_FLAG"] = "FIXED"


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Newberry (FL) permit records using information from the raw DATA JSON.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Newberry". Must contain
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
        if d is None or schema in ("missing", "unknown", "smartgov_empty"):
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
    city = df[
        (df["JURISDICTION"] == "Newberry") & (df["STATE"] == "FL")
    ].copy()

    print(f"Newberry records: {len(city):,}\n")

    repaired = data_repair(city)

    if AGENT_DATA_PATH:
        out_dir = Path(AGENT_DATA_PATH) / "repaired"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "permits_fl_newberry_repaired.parquet"
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

    print("\nBuild Status → STATUS_NORMALIZED (after, non-empty only):")
    usable = repaired["INFERRED_SCHEMA"] != "smartgov_empty"
    status_from_data = repaired.loc[usable, "DATA"].map(
        lambda x: _normalize_build_status((_safe_parse(x) or {}).get("Build Status"))
    )
    ct = (
        pd.DataFrame({
            "BUILD_STATUS": status_from_data,
            "STATUS_NORMALIZED": repaired.loc[usable, "STATUS_NORMALIZED"],
        })
        .groupby(["BUILD_STATUS", "STATUS_NORMALIZED"], dropna=False)
        .size()
        .reset_index(name="n")
        .sort_values("n", ascending=False)
    )
    print(ct.to_string(index=False))

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

    print(
        f"\nSTATUS_NORMALIZED still null: "
        f"{repaired['STATUS_NORMALIZED'].isna().sum()}"
    )
    af_miss = repaired[
        repaired["STATUS_NORMALIZED"].isin(["Active", "Final"])
        & repaired["PERMIT_DATE"].isna()
    ]
    print(f"Active/Final still missing PERMIT_DATE: {len(af_miss)}")
    final_miss = repaired[
        (repaired["STATUS_NORMALIZED"] == "Final") & repaired["FINAL_DATE"].isna()
    ]
    print(f"Final still missing FINAL_DATE: {len(final_miss)}")

    file_gt_permit = 0
    permit_gt_final = 0
    file_gt_final = 0
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
        if (
            pd.notna(f)
            and pd.notna(fin)
            and pd.Timestamp(f).normalize() > pd.Timestamp(fin).normalize()
        ):
            file_gt_final += 1
    print(f"\nFILE_DATE > PERMIT_DATE: {file_gt_permit}")
    print(f"PERMIT_DATE > FINAL_DATE: {permit_gt_final}")
    print(f"FILE_DATE > FINAL_DATE: {file_gt_final}")

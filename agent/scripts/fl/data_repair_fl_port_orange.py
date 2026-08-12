"""Data repair for Port Orange (FL) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Port Orange DATA is a SmartGov community portal payload (same family as
Auburndale) with top-level keys ``Department``, ``My Project``,
``Permit Type``, ``Build Status``, ``Permit Number``, ``Permit Details``,
contacts/fees/inspections arrays, and optionally ``Parcel Number`` /
``ProjectDescription``. Variants (INFERRED_SCHEMA):

  - smartgov_full:     core keys + ProjectDescription (+ Parcel Number)
  - smartgov_no_desc:  core keys + Parcel Number (no ProjectDescription)
  - smartgov_minimal:  core keys without Parcel Number / ProjectDescription
  - missing / unknown

Canonical mappings:
  - DATA["Build Status"] (Expired* / Closed / Issued / …),
    with Closed-date / Issued-date overrides → STATUS_NORMALIZED
  - My Project.Submitted (fallback Created) → FILE_DATE
  - My Project.Issued (fallback Approved)   → PERMIT_DATE
  - My Project.Closed (fallback latest
    approved Final / COO inspection)        → FINAL_DATE

Known issues repaired:
  - 127 null STATUS_NORMALIZED rows: Expired* → Inactive; Closed/COO →
    Final; null Build Status inferred from My Project dates; review
    statuses → In Review.
  - Closed / Finaled rows incorrectly labeled Active → FIXED to Final.
  - Ready To Issue row with Issued+Closed stamps still In Review →
    FIXED to Final via Closed-date override.
  - ~946 Final rows missing FINAL_DATE despite blank Closed → FILLED
    from approved Final / Certificate of Occupancy inspections when
    present; Closed→Active mislabels also get FINAL from Closed.
  - Spurious FINAL_DATE on non-Final statuses → cleared.

Not repairable from DATA:
  - 2 empty-shell records with blank My Project → FILE_DATE /
    STATUS_NORMALIZED stay missing.
  - Active/Final/Inactive with blank Issued (and blank Approved) →
    PERMIT_DATE stays missing.
  - Closed / Certificate of Occupancy Finals with blank Closed and no
    usable Final/COO inspection → FINAL_DATE stays missing.
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


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())
    if "My Project" not in keys:
        return "unknown"
    if "ProjectDescription" in keys:
        return "smartgov_full"
    if data_dict.get("Parcel Number") is not None:
        return "smartgov_no_desc"
    return "smartgov_minimal"


# ── Status mapping ──────────────────────────────────────────────────────────

_STATUS_MAP = {
    "Closed": "Final",
    "Closed/COO": "Final",
    "Finaled": "Final",
    "Certificate of Occupancy": "Final",
    "Issued": "Active",
    "Approved": "Active",
    "Expired": "Inactive",
    "Open": "In Review",
    "Pending": "In Review",
    "Ready To Issue": "In Review",
    "Under Review": "In Review",
    "Revision Review": "In Review",
    "Additional Information Requested": "In Review",
    "Request Approved": "In Review",
}


def _mp_date(d: dict, key: str):
    return _safe_to_datetime(_my_project(d).get(key))


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

    Sticky Inactive for Expired. Explicit Closed / Finaled / COO → Final.
    Otherwise Closed date → Final, Issued date → Active. Null Build
    Status falls back to date inference.
    """
    bs = _normalize_build_status(d.get("Build Status"))
    closed = _mp_date(d, "Closed")
    issued = _mp_date(d, "Issued")

    if bs == "Expired":
        return "Inactive"

    if bs in ("Closed", "Closed/COO", "Finaled", "Certificate of Occupancy"):
        return "Final"

    if closed is not pd.NaT:
        return "Final"

    if issued is not pd.NaT:
        mapped = _STATUS_MAP.get(bs) if bs is not None else None
        if mapped == "Inactive":
            return "Inactive"
        return "Active"

    mapped = _STATUS_MAP.get(bs) if bs is not None else None
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


def _final_inspection_date(d: dict):
    """Latest approved Final / Certificate of Occupancy inspection date."""
    inspections = d.get("Permit Inspections") or []
    dates = []
    for insp in inspections:
        if not isinstance(insp, dict):
            continue
        status = str(insp.get("Status") or "").strip().lower()
        name = str(insp.get("Inspection") or "")
        if status not in ("passed", "approved", "completed"):
            continue
        if not (
            re.search(r"\bfinal\b", name, re.IGNORECASE)
            or re.search(r"certificate of occupancy|\bcoo\b", name, re.IGNORECASE)
        ):
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
    elif effective_status in ("Active", "Final") and permit_src is not pd.NaT:
        repairs["PERMIT_DATE"] = permit_src
        repairs["PERMIT_DATE_FLAG"] = "FILLED"

    # -- FINAL_DATE (completion / Closed, else Final/COO inspection) --
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
    Port Orange (FL) permit records using information from the raw DATA JSON.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Port Orange". Must contain
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
    city = df[(df["JURISDICTION"] == "Port Orange") & (df["STATE"] == "FL")].copy()

    print(f"Port Orange records: {len(city):,}\n")

    repaired = data_repair(city)

    if AGENT_DATA_PATH:
        out_dir = Path(AGENT_DATA_PATH) / "repaired"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "permits_fl_port_orange_repaired.parquet"
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

    from collections import Counter

    print("\nActive/Final still missing PERMIT_DATE (by Build Status):")
    gap = Counter()
    for idx in repaired.index:
        if repaired.at[idx, "STATUS_NORMALIZED"] not in ("Active", "Final"):
            continue
        if pd.notna(repaired.at[idx, "PERMIT_DATE"]):
            continue
        d = _safe_parse(city.at[idx, "DATA"])
        gap[_normalize_build_status((d or {}).get("Build Status"))] += 1
    for k, v in gap.most_common():
        print(f"  {k}: {v}")

    print("\nFinal still missing FINAL_DATE (by Build Status):")
    gap = Counter()
    for idx in repaired.index:
        if repaired.at[idx, "STATUS_NORMALIZED"] != "Final":
            continue
        if pd.notna(repaired.at[idx, "FINAL_DATE"]):
            continue
        d = _safe_parse(city.at[idx, "DATA"])
        gap[_normalize_build_status((d or {}).get("Build Status"))] += 1
    for k, v in gap.most_common():
        print(f"  {k}: {v}")

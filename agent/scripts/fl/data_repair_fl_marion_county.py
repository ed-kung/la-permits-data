"""Data repair for Marion County (FL) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Marion County DATA is a CDPlus portal payload with top-level keys
co / reviews / inspections / permit_details, optionally contractor:

  - permit_details: keys apply_date / issued_date / co_date /
    permit_status / last_inspection_result / …
  - co: list of certificate objects (co, co_type, issue_date, status_date)
  - inspections: list with result / result_date / description

Canonical fields:

  - permit_details.permit_status → STATUS_NORMALIZED
  - permit_details.apply_date    → FILE_DATE
  - permit_details.issued_date   → PERMIT_DATE
  - permit_details.co_date / co[].issue_date, else approved FINAL
    inspection result_date, else last_inspection_result → FINAL_DATE

permit_status values observed:
  - COED / FINAL → Final
  - ISSUED / INSPECT → Active
  - APPLY / READY / SUSPEND → In Review
  - CANCEL / VOID / EXPIRED / CWF → Inactive
    (CWF = Closed Without Final)

INFERRED_SCHEMA prefixes:
  - cdplus_contractor / cdplus_no_contractor
further suffixed by permit_status slug.

Known issues repaired:
  - STATUS_NORMALIZED null on CWF (3) — upstream never mapped that code.
  - One COED row still labeled Active (STATUS_ORIGINAL=inspect) despite
    co_date + issued CO — FIXED to Final; FINAL_DATE FILLED from CO.
  - Four permit_status=FINAL rows lack co_date / co[] — FINAL_DATE
    FILLED from approved FINAL inspections (3) or last_inspection_result (1).

Not repairable from DATA:
  - FILE_DATE already equals apply_date for every sample row.
  - PERMIT_DATE already equals issued_date wherever issued_date exists;
    remaining blanks are true nulls on APPLY / VOID / CANCEL pre-issue.
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

_APPROVED_RE = re.compile(
    r"\(90\)|\(00\)|APPROVED",
    re.IGNORECASE,
)
_NOT_APPROVED_RE = re.compile(
    r"DISAPPROVED|DENIED|CANCEL|FAILED|REJECT",
    re.IGNORECASE,
)
_FINAL_INSP_RE = re.compile(r"\bFINAL\b", re.IGNORECASE)


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
    """Parse a date value, returning pd.NaT on failure / blanks / OOR."""
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
    return dt


def _dates_equal(a, b) -> bool:
    """Compare two datelike values at calendar-day resolution."""
    da = _safe_to_datetime(a)
    db = _safe_to_datetime(b)
    if da is pd.NaT or db is pd.NaT or pd.isna(da) or pd.isna(db):
        return False
    return pd.Timestamp(da).normalize() == pd.Timestamp(db).normalize()


def _permit_details(d: dict) -> dict:
    detail = d.get("permit_details")
    return detail if isinstance(detail, dict) else {}


def _inspection_approved(result) -> bool:
    if result is None:
        return False
    text = str(result).strip()
    if not text:
        return False
    if _NOT_APPROVED_RE.search(text):
        return False
    return bool(_APPROVED_RE.search(text))


# ── Status mapping ───────────────────────────────────────────────────────────

_STATUS_MAP = {
    "COED": "Final",
    "FINAL": "Final",
    "ISSUED": "Active",
    "INSPECT": "Active",
    "APPLY": "In Review",
    "READY": "In Review",
    "SUSPEND": "In Review",
    "CANCEL": "Inactive",
    "VOID": "Inactive",
    "EXPIRED": "Inactive",
    # Closed Without Final — administratively closed, no CO / final sign-off.
    "CWF": "Inactive",
}

_SCHEMA_SUFFIX = {
    "COED": "coed",
    "FINAL": "final",
    "ISSUED": "issued",
    "INSPECT": "inspect",
    "APPLY": "apply",
    "READY": "ready",
    "SUSPEND": "suspend",
    "CANCEL": "cancel",
    "VOID": "void",
    "EXPIRED": "expired",
    "CWF": "cwf",
}


def _map_status(raw: Optional[str]) -> Optional[str]:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    expected = _STATUS_MAP.get(text)
    if expected is not None:
        return expected
    return _STATUS_MAP.get(text.upper())


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())
    if not {"co", "inspections", "permit_details", "reviews"} <= keys:
        return "unknown"
    prefix = (
        "cdplus_contractor" if "contractor" in keys else "cdplus_no_contractor"
    )
    ps = str(_permit_details(data_dict).get("permit_status") or "").strip().upper()
    suffix = _SCHEMA_SUFFIX.get(ps)
    if suffix is None:
        slug = re.sub(r"[^a-z0-9]+", "_", ps.lower()).strip("_") or "other"
        return f"{prefix}_{slug}"
    return f"{prefix}_{suffix}"


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
    current = repairs.get(field, row[field])
    if pd.isna(current):
        return
    repairs[field] = pd.NaT
    repairs[f"{field}_FLAG"] = "FIXED"


def _co_date(d: dict, detail: dict):
    """Best certificate / completion date from co[] or permit_details.co_date."""
    dates = []
    for item in d.get("co") or []:
        if not isinstance(item, dict):
            continue
        dt = _safe_to_datetime(item.get("issue_date"))
        if dt is not pd.NaT and not pd.isna(dt):
            dates.append(dt)
    if dates:
        return max(dates)
    return _safe_to_datetime(detail.get("co_date"))


def _final_inspection_date(d: dict):
    """Latest approved inspection whose description mentions FINAL."""
    dates = []
    for insp in d.get("inspections") or []:
        if not isinstance(insp, dict):
            continue
        desc = str(insp.get("description") or "")
        if not _FINAL_INSP_RE.search(desc):
            continue
        if not _inspection_approved(insp.get("result")):
            continue
        dt = _safe_to_datetime(insp.get("result_date"))
        if dt is not pd.NaT and not pd.isna(dt):
            dates.append(dt)
    return max(dates) if dates else pd.NaT


def _final_date_candidate(d: dict, detail: dict):
    """CO date, else approved FINAL inspection, else last_inspection_result."""
    co = _co_date(d, detail)
    if co is not pd.NaT and not pd.isna(co):
        return co
    insp = _final_inspection_date(d)
    if insp is not pd.NaT and not pd.isna(insp):
        return insp
    return _safe_to_datetime(detail.get("last_inspection_result"))


# ── Per-schema repair logic ─────────────────────────────────────────────────

def _repair_cdplus(row, d: dict, repairs: dict) -> None:
    """Repair a CDPlus permit_details record."""
    detail = _permit_details(d)
    expected = _map_status(detail.get("permit_status"))
    effective_status = _apply_status(repairs, row["STATUS_NORMALIZED"], expected)

    # FILE_DATE ← apply_date
    _apply_date(repairs, row, "FILE_DATE", detail.get("apply_date"))

    # PERMIT_DATE ← issued_date (Active / Final / Inactive).
    # In Review may retain a pre-existing issued stamp (e.g. SUSPEND) but
    # we do not require or invent one.
    issued = _safe_to_datetime(detail.get("issued_date"))
    if issued is not pd.NaT and not pd.isna(issued):
        if effective_status in ("Active", "Final", "Inactive"):
            _apply_date(repairs, row, "PERMIT_DATE", issued)

    # FINAL_DATE for Final only; clear spurious non-Final values.
    if effective_status == "Final":
        _apply_date(repairs, row, "FINAL_DATE", _final_date_candidate(d, detail))
    else:
        _clear_date(repairs, row, "FINAL_DATE")


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Marion County permit records using information from the raw DATA JSON.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Marion County".  Must
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
        if d is None:
            continue

        repairs: dict = {}

        if schema.startswith("cdplus"):
            _repair_cdplus(row, d, repairs)

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
    filepath = os.path.join(MY_DATA_PATH, "processed_data", "permits_fl_sample.parquet")
    df = pd.read_parquet(filepath)
    mc = df[df["JURISDICTION"] == "Marion County"].copy()

    print(f"Marion County records: {len(mc):,}\n")

    repaired = data_repair(mc)

    print("INFERRED_SCHEMA:")
    print(repaired["INFERRED_SCHEMA"].value_counts(dropna=False).to_string())
    print()

    for field in ["STATUS_NORMALIZED", "FILE_DATE", "PERMIT_DATE", "FINAL_DATE"]:
        flag_col = f"{field}_FLAG"
        n_filled = (repaired[flag_col] == "FILLED").sum()
        n_fixed = (repaired[flag_col] == "FIXED").sum()
        print(f"{field}:")
        print(f"  FILLED: {n_filled:>4,}   FIXED: {n_fixed:>4,}")

        before_missing = mc[field].isna().sum()
        after_missing = repaired[field].isna().sum()
        print(f"  Missing before: {before_missing:>4,}   Missing after: {after_missing:>4,}")
        print()

    print("STATUS_NORMALIZED distribution:")
    print("  Before:")
    for s, c in mc["STATUS_NORMALIZED"].value_counts(dropna=False).items():
        print(f"    {str(s):15s}: {c:>4,}")
    print("  After:")
    for s, c in repaired["STATUS_NORMALIZED"].value_counts(dropna=False).items():
        print(f"    {str(s):15s}: {c:>4,}")

    print("\nFILE_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FILE_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({n_has/len(sub) if len(sub) else 0:.1%})")

    print("\nPERMIT_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["PERMIT_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({n_has/len(sub) if len(sub) else 0:.1%})")

    print("\nFINAL_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FINAL_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({n_has/len(sub) if len(sub) else 0:.1%})")

    # Sanity checks
    n_unmapped = 0
    n_file_mismatch = 0
    n_permit_mismatch = 0
    n_final_mismatch = 0
    for idx in repaired.index:
        d = _safe_parse(repaired.at[idx, "DATA"]) or {}
        detail = _permit_details(d)
        if _map_status(detail.get("permit_status")) is None:
            n_unmapped += 1
        apply = _safe_to_datetime(detail.get("apply_date"))
        if apply is not pd.NaT and not pd.isna(apply):
            if not _dates_equal(repaired.at[idx, "FILE_DATE"], apply):
                n_file_mismatch += 1
        issued = _safe_to_datetime(detail.get("issued_date"))
        status = repaired.at[idx, "STATUS_NORMALIZED"]
        if (
            status in ("Active", "Final", "Inactive")
            and issued is not pd.NaT
            and not pd.isna(issued)
            and not _dates_equal(repaired.at[idx, "PERMIT_DATE"], issued)
        ):
            n_permit_mismatch += 1
        if status == "Final":
            cand = _final_date_candidate(d, detail)
            if cand is not pd.NaT and not pd.isna(cand):
                if not _dates_equal(repaired.at[idx, "FINAL_DATE"], cand):
                    n_final_mismatch += 1

    print(f"\nUnmapped permit_status values: {n_unmapped}")
    print(f"FILE_DATE != apply_date after repair: {n_file_mismatch}")
    print(f"PERMIT_DATE != issued_date (Active/Final/Inactive): {n_permit_mismatch}")
    print(f"FINAL_DATE != candidate (Final): {n_final_mismatch}")

    # Show flagged rows
    print("\nFlagged STATUS_NORMALIZED rows:")
    flagged = repaired[repaired["STATUS_NORMALIZED_FLAG"].notna()][
        ["PERMIT_NUMBER", "STATUS_ORIGINAL", "STATUS_NORMALIZED", "STATUS_NORMALIZED_FLAG"]
    ]
    print(flagged.to_string(index=False))

    print("\nFlagged FINAL_DATE rows:")
    flagged_f = repaired[repaired["FINAL_DATE_FLAG"].notna()][
        ["PERMIT_NUMBER", "STATUS_NORMALIZED", "FINAL_DATE", "FINAL_DATE_FLAG"]
    ]
    print(flagged_f.to_string(index=False))

    if AGENT_DATA_PATH:
        out_path = os.path.join(AGENT_DATA_PATH, "marion_county_repaired_sample.parquet")
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote {out_path}")

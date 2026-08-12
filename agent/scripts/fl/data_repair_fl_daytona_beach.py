"""Data repair for Daytona Beach (FL) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Daytona Beach DATA has two sub-schemas in this sample:

  - ims: Accela IMS payload from daytonabeach.ims16.com with top-level
         Permit / Parcel / ViewMilestones (optionally CustomFields,
         Contacts, Charges, Review, Inspection)
  - civic: eTRAKiT-style portal extract with permit_info, search_data,
           site_info, contacts, fees, inspections

IMS canonical fields:
  - Permit.Milestone (fallback ViewMilestones.Milestone)
      → STATUS_NORMALIZED
  - ViewMilestones.Created → FILE_DATE
  - ViewMilestones.Issued
    (fallback Approved)            → PERMIT_DATE
  - ViewMilestones.Finaled
    (fallback Closed)              → FINAL_DATE

Civic canonical fields:
  - permit_info.PermitStatus
    (+ issuance gating for APPROVED)
      → STATUS_NORMALIZED
  - permit_info.PermitAppliedDate → FILE_DATE
  - permit_info.PermitIssuedDate
    (fallback PermitApprovedDate) → PERMIT_DATE
  - permit_info.PermitFinaledDate → FINAL_DATE

Key-set variants (INFERRED_SCHEMA prefixes):
  - ims_full: ViewMilestones plus Contacts/Charges/Review/Inspection
  - ims:      ViewMilestones present (often + CustomFields)
  - civic:    permit_info / search_data portal extract

Content suffixes further split by which canonical dates are populated
(``_issued_finaled``, ``_issued``, ``_finaled``, ``_applied``,
``_status_only``).

Known issues repaired:
  - IMS STATUS_ORIGINAL lag: Milestone Finaled / Issued / Expired /
    Closed while STATUS_NORMALIZED still reflects an older label
    → FIXED.
  - Unmapped "Approved Fees Pending" left STATUS_NORMALIZED null
    → FILLED as In Review (and other Milestone-driven fills).
  - APPROVED gated on Issued → Active only when issued, else In Review.
  - ~700 IMS Final rows missing FINAL_DATE despite ViewMilestones.Finaled
    → FILLED.
  - Spurious FINAL_DATE on Denied / other Inactive (Closed stamp)
    → FIXED (cleared).
  - Missing FILE_DATE / PERMIT_DATE filled from canonical date fields.

Not repairable from DATA:
  - 1 civic row with blank PermitAppliedDate → FILE_DATE stays missing.
  - Admin-closed / Finaled rows with neither Finaled nor Closed
    → FINAL_DATE stays missing.
  - Active/Final rows with blank Issued and Approved → PERMIT_DATE
    stays missing.
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


def _view_milestones(d: dict) -> dict:
    vm = d.get("ViewMilestones")
    return vm if isinstance(vm, dict) else {}


def _permit_info(d: dict) -> dict:
    pi = d.get("permit_info")
    return pi if isinstance(pi, dict) else {}


def _extract_ims(d: dict):
    """Return (raw_milestone, applied, issued, finaled)."""
    perm = d.get("Permit") if isinstance(d.get("Permit"), dict) else {}
    vm = _view_milestones(d)

    raw = perm.get("Milestone") or vm.get("Milestone")

    applied = _safe_to_datetime(vm.get("Created"))
    if applied is pd.NaT or pd.isna(applied):
        applied = _safe_to_datetime(vm.get("Submitted"))

    issued = _safe_to_datetime(vm.get("Issued"))
    if issued is pd.NaT or pd.isna(issued):
        issued = _safe_to_datetime(vm.get("Approved"))

    finaled = _safe_to_datetime(vm.get("Finaled"))
    if finaled is pd.NaT or pd.isna(finaled):
        finaled = _safe_to_datetime(vm.get("Closed"))

    return raw, applied, issued, finaled


def _extract_civic(d: dict):
    """Return (raw_status, applied, issued, finaled)."""
    pi = _permit_info(d)
    raw = pi.get("PermitStatus")
    applied = _safe_to_datetime(pi.get("PermitAppliedDate"))
    issued = _safe_to_datetime(pi.get("PermitIssuedDate"))
    if issued is pd.NaT or pd.isna(issued):
        issued = _safe_to_datetime(pi.get("PermitApprovedDate"))
    finaled = _safe_to_datetime(pi.get("PermitFinaledDate"))
    return raw, applied, issued, finaled


def _date_suffix(applied, issued, finaled) -> str:
    has_applied = applied is not pd.NaT and not pd.isna(applied)
    has_issued = issued is not pd.NaT and not pd.isna(issued)
    has_final = finaled is not pd.NaT and not pd.isna(finaled)
    if has_issued and has_final:
        return "issued_finaled"
    if has_issued:
        return "issued"
    if has_final:
        return "finaled"
    if has_applied:
        return "applied"
    return "status_only"


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    if not isinstance(data_dict, dict):
        return "unknown"

    keys = set(data_dict.keys())

    if "permit_info" in keys:
        _, applied, issued, finaled = _extract_civic(data_dict)
        return f"civic_{_date_suffix(applied, issued, finaled)}"

    if "Permit" in keys:
        rich_keys = {"Contacts", "Charges", "Review", "Inspection"}
        if keys & rich_keys:
            base = "ims_full"
        elif "ViewMilestones" in keys:
            base = "ims"
        else:
            base = "ims_basic"
        _, applied, issued, finaled = _extract_ims(data_dict)
        return f"{base}_{_date_suffix(applied, issued, finaled)}"

    return "unknown"


# ── Status mapping ───────────────────────────────────────────────────────────

# Case-insensitive raw status / milestone → STATUS_NORMALIZED.
_STATUS_MAP = {
    # Final
    "finaled": "Final",
    "completed": "Final",
    "co issued": "Final",
    "closed": "Final",
    "admin closed": "Final",
    "administratively closed": "Final",
    # Active
    "issued": "Active",
    "active": "Active",
    "web-issued": "Active",
    "web issued": "Active",
    # Inactive
    "expired": "Inactive",
    "void": "Inactive",
    "cancelled": "Inactive",
    "canceled": "Inactive",
    "denied": "Inactive",
    "withdrawn": "Inactive",
    # In Review
    "under review": "In Review",
    "approved fees pending": "In Review",
    "submitted": "In Review",
    "awaiting resubmittal": "In Review",
    "hold": "In Review",
    "on hold": "In Review",
    "applied": "In Review",
}

# Active only when an issuance date is present; otherwise In Review.
_ISSUANCE_GATED = {
    "approved",
}


def _expected_status(raw_status: Optional[str], issued) -> Optional[str]:
    if raw_status is None:
        return None
    raw = str(raw_status).strip()
    if not raw:
        return None

    raw_key = raw.lower()
    has_issued = issued is not pd.NaT and not pd.isna(issued)

    if raw_key in _ISSUANCE_GATED:
        return "Active" if has_issued else "In Review"

    return _STATUS_MAP.get(raw_key)


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
    if cand is pd.NaT or pd.isna(cand):
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

def _repair_from_fields(row, repairs: dict, raw_status, applied, issued, finaled) -> None:
    expected = _expected_status(raw_status, issued)
    effective_status = _apply_status(repairs, row["STATUS_NORMALIZED"], expected)

    # FILE_DATE ← application / created stamp
    if applied is not pd.NaT and not pd.isna(applied):
        _apply_date(repairs, row, "FILE_DATE", applied)

    # PERMIT_DATE ← Issued / Approved for issued statuses; clear on In Review
    if issued is not pd.NaT and not pd.isna(issued):
        if effective_status in ("Active", "Final", "Inactive"):
            _apply_date(repairs, row, "PERMIT_DATE", issued)
        elif effective_status == "In Review":
            _clear_date(repairs, row, "PERMIT_DATE")
    elif effective_status == "In Review":
        _clear_date(repairs, row, "PERMIT_DATE")

    # FINAL_DATE ← Finaled / Closed for Final only; clear otherwise
    if effective_status == "Final":
        if finaled is not pd.NaT and not pd.isna(finaled):
            _apply_date(repairs, row, "FINAL_DATE", finaled)
    else:
        _clear_date(repairs, row, "FINAL_DATE")


def _repair_record(row, d: dict, schema: str, repairs: dict) -> None:
    if schema.startswith("civic"):
        raw, applied, issued, finaled = _extract_civic(d)
    elif schema.startswith("ims"):
        raw, applied, issued, finaled = _extract_ims(d)
    else:
        return
    _repair_from_fields(row, repairs, raw, applied, issued, finaled)


# ── Main entry point ─────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Daytona Beach permit records using the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Daytona Beach".  Must contain
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
        if d is None or schema in ("unknown", "missing"):
            continue

        repairs: dict = {}
        _repair_record(row, d, schema, repairs)
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
    filepath = os.path.join(MY_DATA_PATH, "processed_data", "permits_fl_sample.parquet")
    df = pd.read_parquet(filepath)
    city = df[df["JURISDICTION"] == "Daytona Beach"].copy()

    print(f"Daytona Beach records: {len(city):,}\n")

    repaired = data_repair(city)

    print("INFERRED_SCHEMA:")
    for s, c in repaired["INFERRED_SCHEMA"].value_counts(dropna=False).items():
        print(f"  {str(s):35s}: {c:>4,}")
    print()

    for field in ["STATUS_NORMALIZED", "FILE_DATE", "PERMIT_DATE", "FINAL_DATE"]:
        flag_col = f"{field}_FLAG"
        n_filled = (repaired[flag_col] == "FILLED").sum()
        n_fixed = (repaired[flag_col] == "FIXED").sum()
        print(f"{field}:")
        print(f"  FILLED: {n_filled:>4,}   FIXED: {n_fixed:>4,}")
        before_missing = city[field].isna().sum()
        after_missing = repaired[field].isna().sum()
        print(f"  Missing before: {before_missing:>4,}   Missing after: {after_missing:>4,}")
        print()

    print("STATUS_NORMALIZED distribution:")
    print("  Before:")
    for s, c in city["STATUS_NORMALIZED"].value_counts(dropna=False).items():
        print(f"    {str(s):15s}: {c:>4,}")
    print("  After:")
    for s, c in repaired["STATUS_NORMALIZED"].value_counts(dropna=False).items():
        print(f"    {str(s):15s}: {c:>4,}")

    print("\nFILE_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FILE_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({(n_has / len(sub) if len(sub) else 0):.1%})")

    print("\nPERMIT_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["PERMIT_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({(n_has / len(sub) if len(sub) else 0):.1%})")

    print("\nFINAL_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FINAL_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({(n_has / len(sub) if len(sub) else 0):.1%})")

    if AGENT_DATA_PATH:
        out_path = os.path.join(AGENT_DATA_PATH, "daytona_beach_repaired_sample.parquet")
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote repaired sample → {out_path}")

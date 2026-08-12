"""Data repair for Palm Bay (FL) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Palm Bay DATA is an Accela IMS payload from ims.palmbayflorida.org.
Every record has top-level ``Permit`` (+ ``Parcel``); richer scrapes also
include ``ViewMilestones`` and optionally CustomFields / Contacts /
Charges / Review / Inspection.

Canonical fields:

  - Permit.Milestone (fallback ViewMilestones.Milestone)
      → STATUS_NORMALIZED
  - ViewMilestones.Created (fallback Submitted) → FILE_DATE
  - ViewMilestones.Issued                       → PERMIT_DATE
  - ViewMilestones.Finaled (fallback Closed)    → FINAL_DATE

Key-set variants (INFERRED_SCHEMA prefixes):
  - ims_full:  ViewMilestones plus Contacts/Charges/Review/Inspection
  - ims:       ViewMilestones present (often + CustomFields)
  - ims_basic: Parcel + Permit only (no milestone dates)

Content suffixes further split by which canonical dates are populated
(``_issued_finaled``, ``_issued``, ``_finaled``, ``_applied``,
``_status_only``).

Known issues repaired:
  - STATUS_ORIGINAL lag: Milestone Finaled / Certificate of Occupancy /
    Withdrawn / Expired / Issued while STATUS_NORMALIZED still reflects
    an older label → FIXED.
  - Unmapped pending-payment / revision milestones left STATUS_NORMALIZED
    null → FILLED as In Review.
  - Approved / Approval Pending without Issued gated to In Review
    (approval ≠ issuance).
  - Missing FINAL_DATE on Final rows filled from Finaled / Closed.
  - Spurious FINAL_DATE on Issued (Closed stamp present) cleared.
  - Missing FILE_DATE / PERMIT_DATE filled from ViewMilestones when
    present.

Not repairable from DATA:
  - ~1,708 ims_basic rows lack ViewMilestones; dates cannot be derived
    from Parcel/Permit alone (Parcel.status is empty).
  - 1 Certificate of Occupancy row has neither Finaled nor Closed.
  - 3 Closed (Final) rows have Approved but no Issued → PERMIT_DATE
    stays missing (Approved is not used as issuance).
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


def _extract_fields(d: dict):
    """Return (raw_milestone, applied, issued, finaled)."""
    perm = d.get("Permit") if isinstance(d.get("Permit"), dict) else {}
    vm = _view_milestones(d)

    raw = perm.get("Milestone") or vm.get("Milestone")

    # Application / file date: Created is the portal application stamp
    # (matches existing FILE_DATE); Submitted can lag when payment /
    # completeness updates rewrite it.
    applied = _safe_to_datetime(vm.get("Created"))
    if applied is pd.NaT or pd.isna(applied):
        applied = _safe_to_datetime(vm.get("Submitted"))

    issued = _safe_to_datetime(vm.get("Issued"))

    finaled = _safe_to_datetime(vm.get("Finaled"))
    if finaled is pd.NaT or pd.isna(finaled):
        finaled = _safe_to_datetime(vm.get("Closed"))

    return raw, applied, issued, finaled


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())
    if "Permit" not in keys:
        return "unknown"

    rich_keys = {"Contacts", "Charges", "Review", "Inspection"}
    if keys & rich_keys:
        base = "ims_full"
    elif "ViewMilestones" in keys:
        base = "ims"
    else:
        base = "ims_basic"

    _, applied, issued, finaled = _extract_fields(data_dict)
    has_applied = applied is not pd.NaT and not pd.isna(applied)
    has_issued = issued is not pd.NaT and not pd.isna(issued)
    has_final = finaled is not pd.NaT and not pd.isna(finaled)

    if has_issued and has_final:
        return f"{base}_issued_finaled"
    if has_issued:
        return f"{base}_issued"
    if has_final:
        return f"{base}_finaled"
    if has_applied:
        return f"{base}_applied"
    return f"{base}_status_only"


# ── Status mapping ───────────────────────────────────────────────────────────

_STATUS_MAP = {
    # Final
    "Completed": "Final",
    "Finaled": "Final",
    "Certificate of Occupancy": "Final",
    "Certificate of Completion": "Final",
    "Closed": "Final",
    # Active
    "Issued": "Active",
    # Inactive
    "Void": "Inactive",
    "Withdrawn": "Inactive",
    "Expired": "Inactive",
    "Expired - Delinquent": "Inactive",
    "Inactive": "Inactive",
    "Denied": "Inactive",
    # In Review
    "Under Review": "In Review",
    "Under Review - Revisions": "In Review",
    "Submitted": "In Review",
    "Submitted - Pending Payment": "In Review",
    "Submitted - Pending Site Visit": "In Review",
    "Approved - Pending Payment": "In Review",
    "Approved Fees Pending": "In Review",
    "Approved Pending Payment": "In Review",
    "On Hold": "In Review",
    "Approval Pending": "In Review",
}

# Active only when an issuance date is present; otherwise In Review.
_ISSUANCE_GATED = {
    "Approved",
}


def _expected_status(raw_status: Optional[str], issued) -> Optional[str]:
    if raw_status is None:
        return None
    raw = str(raw_status).strip()
    if not raw:
        return None

    has_issued = issued is not pd.NaT and not pd.isna(issued)

    if raw in _ISSUANCE_GATED:
        return "Active" if has_issued else "In Review"

    if raw in _STATUS_MAP:
        return _STATUS_MAP[raw]

    for key, val in _STATUS_MAP.items():
        if key.lower() == raw.lower():
            return val

    for key in _ISSUANCE_GATED:
        if key.lower() == raw.lower():
            return "Active" if has_issued else "In Review"

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

def _repair_record(row, d: dict, repairs: dict) -> None:
    raw_status, applied, issued, finaled = _extract_fields(d)
    expected = _expected_status(raw_status, issued)
    effective_status = _apply_status(repairs, row["STATUS_NORMALIZED"], expected)

    # FILE_DATE ← Created / Submitted
    if applied is not pd.NaT and not pd.isna(applied):
        _apply_date(repairs, row, "FILE_DATE", applied)

    # PERMIT_DATE ← Issued for issued / completed / expired statuses.
    # Clear on In Review (should not carry an issuance date).
    if issued is not pd.NaT and not pd.isna(issued):
        if effective_status in ("Active", "Final", "Inactive"):
            _apply_date(repairs, row, "PERMIT_DATE", issued)
        elif effective_status == "In Review":
            _clear_date(repairs, row, "PERMIT_DATE")
    elif effective_status == "In Review":
        _clear_date(repairs, row, "PERMIT_DATE")

    # FINAL_DATE ← Finaled / Closed for Final only; clear otherwise.
    if effective_status == "Final":
        if finaled is not pd.NaT and not pd.isna(finaled):
            _apply_date(repairs, row, "FINAL_DATE", finaled)
    else:
        _clear_date(repairs, row, "FINAL_DATE")


# ── Main entry point ─────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Palm Bay permit records using the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Palm Bay".  Must contain
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
        if d is None or schema == "unknown":
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
    filepath = os.path.join(MY_DATA_PATH, "processed_data", "permits_fl_sample.parquet")
    df = pd.read_parquet(filepath)
    city = df[df["JURISDICTION"] == "Palm Bay"].copy()

    print(f"Palm Bay records: {len(city):,}\n")

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
        out_path = os.path.join(AGENT_DATA_PATH, "palm_bay_repaired_sample.parquet")
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote repaired sample → {out_path}")

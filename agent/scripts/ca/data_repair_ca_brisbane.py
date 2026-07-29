"""Data repair for Brisbane (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Brisbane DATA is a flat city portal payload. Every sample row shares the
same top-level keys:

  - Status            → STATUS_NORMALIZED
  - Date In           → FILE_DATE
  - Check-List        → workflow stages (Fee / Plan Check /
                        Permit Issuance / Inspections / Permit Finaled);
                        used to infer status when Status is blank
  - APN, Address, Description, Project #, Project Type, SQFT, Valuation

Canonical date fields for issuance and finaling are **not** present.
``Permit Issuance`` status text sometimes embeds an expiration date
(``Permit Issued (Expires MM/DD/YYYY)``); that is not an issuance date.

INFERRED_SCHEMA content variants (same keys; differ by Status /
checklist stage population):

  - portal_finaled:           Status / Finaled stage = Permit Finaled
  - portal_issued_active:     inspections / ready-for-inspections
  - portal_expired:           Status = Permit Expired
  - portal_inactive_other:    Cancelled / Voided / On Hold
  - portal_in_review:         pending / plan review / fees / ready to
                              issue / skipped plan review
  - portal_no_status:         blank Status (infer from Check-List)

Known issues repaired:
  - 44 rows with blank STATUS_ORIGINAL / STATUS_NORMALIZED → FILLED
    from DATA.Status or Check-List inference (mostly In Review fee /
    early-stage shells; a few Active issued-in-inspection rows).
  - STATUS_ORIGINAL lagging DATA.Status: Permit Finaled. still Active /
    In Review / Inactive → FIXED to Final; Permit Expired. still Active
    → FIXED to Inactive; Ready for inspections. / Inspections in
    process. still In Review → FIXED to Active.

Not repairable / left as-is:
  - FILE_DATE already complete and matches Date In on all 2,000 rows.
  - PERMIT_DATE missing on every row: DATA has no Issued / Approved
    date field (expiration dates in Permit Issuance text are not used).
  - FINAL_DATE missing on every Final row: DATA has no Finaled /
    completion date field (only a Permit Finaled stage label).
"""

from __future__ import annotations

import json
import math
import re
from typing import Optional

import numpy as np
import pandas as pd


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
    """Parse a date value, returning pd.NaT on failure."""
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return pd.NaT
    if isinstance(val, str) and not val.strip():
        return pd.NaT
    try:
        dt = pd.to_datetime(val)
    except (ValueError, TypeError):
        return pd.NaT
    if dt is pd.NaT or pd.isna(dt):
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
    return da.normalize() == db.normalize()


def _normalize_status_key(raw) -> str:
    if raw is None or (isinstance(raw, float) and math.isnan(raw)):
        return ""
    return re.sub(r"\s+", " ", str(raw).strip().lower())


def _checklist_by_stage(d: dict) -> dict:
    """Return {Stage: Status} from Check-List items."""
    out = {}
    cl = d.get("Check-List")
    if not isinstance(cl, list):
        return out
    for item in cl:
        if not isinstance(item, dict):
            continue
        stage = item.get("Stage")
        if stage:
            out[stage] = item.get("Status")
    return out


def _issuance_is_issued(status_text) -> bool:
    s = _normalize_status_key(status_text)
    return s.startswith("permit issued")


def _finaled_is_finaled(status_text) -> bool:
    s = _normalize_status_key(status_text)
    return s.startswith("permit finaled")


# ── Status mapping ───────────────────────────────────────────────────────────

_STATUS_MAP = {
    "permit finaled.": "Final",
    "permit expired.": "Inactive",
    "cancelled permit.": "Inactive",
    "permit voided.": "Inactive",
    "permit on hold.": "Inactive",
    "inspections in process.": "Active",
    "ready for inspections.": "Active",
    "pending application": "In Review",
    "plan review in process": "In Review",
    "fees are due.": "In Review",
    "ready to issue permit": "In Review",
    "skipped plan review.": "In Review",
}


def _expected_status(d: dict) -> Optional[str]:
    """Map DATA.Status (or Check-List when Status blank) → STATUS_NORMALIZED."""
    key = _normalize_status_key(d.get("Status"))
    if key in _STATUS_MAP:
        return _STATUS_MAP[key]

    # Blank / unknown Status: infer from Check-List workflow stages.
    stages = _checklist_by_stage(d)
    if _finaled_is_finaled(stages.get("Permit Finaled")):
        return "Final"
    iss = stages.get("Permit Issuance")
    if _issuance_is_issued(iss):
        return "Active"
    insp = _normalize_status_key(stages.get("Inspections"))
    if insp.startswith("ready for inspections") or insp.startswith(
        "inspections in process"
    ):
        return "Active"
    # Pre-issuance / fee / empty shells → In Review
    return "In Review"


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())
    if "Date In" not in keys and "Status" not in keys and "Check-List" not in keys:
        return "unknown"

    key = _normalize_status_key(data_dict.get("Status"))
    if not key:
        return "portal_no_status"
    if key.startswith("permit finaled"):
        return "portal_finaled"
    if key.startswith("permit expired"):
        return "portal_expired"
    if key in ("cancelled permit.", "permit voided.", "permit on hold."):
        return "portal_inactive_other"
    if key in ("inspections in process.", "ready for inspections."):
        return "portal_issued_active"
    if key in _STATUS_MAP and _STATUS_MAP[key] == "In Review":
        return "portal_in_review"
    return "portal_other"


# ── Per-row repair ───────────────────────────────────────────────────────────

def _repair_row(row, d: dict, repairs: dict) -> None:
    """Apply Brisbane repairs into *repairs* dict."""
    expected = _expected_status(d)
    current_status = row["STATUS_NORMALIZED"]

    # -- STATUS_NORMALIZED --
    if expected is not None:
        if pd.isna(current_status):
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"
        elif current_status != expected:
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FIXED"

    # -- FILE_DATE --
    date_in = _safe_to_datetime(d.get("Date In"))
    if pd.isna(row["FILE_DATE"]):
        if date_in is not pd.NaT:
            repairs["FILE_DATE"] = date_in
            repairs["FILE_DATE_FLAG"] = "FILLED"
    elif date_in is not pd.NaT and not _dates_equal(row["FILE_DATE"], date_in):
        repairs["FILE_DATE"] = date_in
        repairs["FILE_DATE_FLAG"] = "FIXED"

    # -- PERMIT_DATE / FINAL_DATE --
    # Brisbane DATA has no issuance or finaled date fields. Expiration
    # dates embedded in Permit Issuance status text are intentionally
    # ignored. Nothing to fill or fix from JSON.


# ── Main entry point ─────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Brisbane (CA) permit records using information from the raw DATA JSON.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Brisbane". Must contain
        columns STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, FINAL_DATE,
        and DATA.

    Returns
    -------
    pd.DataFrame
        Copy of *df* with corrected field values, an INFERRED_SCHEMA column
        naming the DATA JSON content variant identified for each record,
        and new flag columns: STATUS_NORMALIZED_FLAG, FILE_DATE_FLAG,
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
        _repair_row(row, d, repairs)

        for key, value in repairs.items():
            out.at[idx, key] = value

    return out


# ── CLI: run standalone to preview repair stats ──────────────────────────────

if __name__ == "__main__":
    import os
    from dotenv import load_dotenv, find_dotenv

    load_dotenv(find_dotenv())
    MY_DATA_PATH = os.getenv("MY_DATA_PATH")
    filepath = os.path.join(
        MY_DATA_PATH, "processed_data", "permits_ca_sample.parquet"
    )
    df = pd.read_parquet(filepath)
    city = df[df["JURISDICTION"] == "Brisbane"].copy()

    print(f"Brisbane records: {len(city):,}\n")

    repaired = data_repair(city)

    print("INFERRED_SCHEMA:")
    for s, c in repaired["INFERRED_SCHEMA"].value_counts(dropna=False).items():
        print(f"  {str(s):30s}: {c:>4,}")
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

    print("\nFILE_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FILE_DATE"].notna().sum()
        print(
            f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} "
            f"({n_has / max(len(sub), 1):.1%})"
        )

    print("\nPERMIT_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["PERMIT_DATE"].notna().sum()
        print(
            f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} "
            f"({n_has / max(len(sub), 1):.1%})"
        )

    print("\nFINAL_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FINAL_DATE"].notna().sum()
        print(
            f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} "
            f"({n_has / max(len(sub), 1):.1%})"
        )

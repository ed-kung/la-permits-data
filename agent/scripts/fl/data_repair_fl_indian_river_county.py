"""Data repair for Indian River County (FL) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Indian River County DATA has three sub-schemas:

  - mgo_project:           MyGovernmentOnline project payload with
                           ProjectStatus, DateCreated, DateIssued, etc.
  - flat_basic:            compact list row with Status, Submission Date,
                           Expiration Date (no completion fields)
  - flat_with_completion:  flat list row plus City / CO Date /
                           Completed Date

Canonical mappings:
  - ProjectStatus / Status              → STATUS_NORMALIZED
  - DateCreated / Submission Date       → FILE_DATE
  - DateIssued (when real)              → PERMIT_DATE
  - Completed Date (Final only)         → FINAL_DATE

Known issues repaired:
  - STATUS_NORMALIZED null for Expired (Older Permits) and Impasse
    → FILLED as Inactive.
  - flat_* FILE_DATE always missing despite Submission Date → FILLED.
  - Upstream PERMIT_DATE on flat_* is a copy of Submission Date (the
    application date), not an issuance date → cleared (FIXED).
  - Upstream FINAL_DATE on flat_* is a copy of Expiration Date (a
    validity window), not a finalization date → replaced with Completed
    Date when present (FIXED), else cleared (FIXED). Non-Final rows
    carrying FINAL_DATE are cleared.

Not repairable / left as-is:
  - mgo_project DateIssued is always the sentinel 0001-01-01 → no
    PERMIT_DATE source; Active/Final stay missing PERMIT_DATE.
  - mgo_project has no completion / CO date → Final FINAL_DATE stays
    missing.
  - flat_basic has no Completed Date → Final FINAL_DATE stays missing
    after clearing Expiration copies.
"""

from __future__ import annotations

import json
import math
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
    """Parse a date value, returning pd.NaT on failure / sentinels."""
    if val is None or (isinstance(val, str) and not str(val).strip()):
        return pd.NaT
    if not isinstance(val, str) and pd.isna(val):
        return pd.NaT
    text = str(val).strip()
    if text.upper() in ("TBD", "NONE", "N/A", "NA", "NULL", "NAN", "00/00/0000", "0/0/0000"):
        return pd.NaT
    # MGO sentinel for "no date"
    if text.startswith("0001-01-01"):
        return pd.NaT
    try:
        return pd.to_datetime(val)
    except (ValueError, TypeError):
        return pd.NaT


def _dates_equal(a, b) -> bool:
    """Compare two datelike values at calendar-day resolution."""
    da = _safe_to_datetime(a)
    db = _safe_to_datetime(b)
    if da is pd.NaT or db is pd.NaT:
        return False
    return da.normalize() == db.normalize()


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())
    if "ProjectStatus" in keys:
        return "mgo_project"
    if "Submission Date" in keys:
        if "CO Date" in keys or "Completed Date" in keys:
            return "flat_with_completion"
        return "flat_basic"
    return "unknown"


def _apply_status(repairs: dict, current, raw_status: Optional[str], status_map: dict):
    """Map raw status → STATUS_NORMALIZED; return effective status."""
    if raw_status is None:
        return current if not (isinstance(current, float) and pd.isna(current)) else None

    expected = status_map.get(raw_status)
    if expected is None:
        expected = status_map.get(str(raw_status).strip())
        if expected is None:
            for k, v in status_map.items():
                if k.lower() == str(raw_status).strip().lower():
                    expected = v
                    break
    if expected is None:
        return current if not (isinstance(current, float) and pd.isna(current)) else None

    if pd.isna(current):
        repairs["STATUS_NORMALIZED"] = expected
        repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"
    elif current != expected:
        repairs["STATUS_NORMALIZED"] = expected
        repairs["STATUS_NORMALIZED_FLAG"] = "FIXED"

    return repairs.get("STATUS_NORMALIZED", current)


def _apply_date(repairs: dict, row, field: str, candidate, *, allow_fill: bool = True) -> None:
    """Fill or fix *field* from *candidate* datetime (pd.NaT = no candidate)."""
    cand = _safe_to_datetime(candidate)
    if cand is pd.NaT:
        return

    current = row[field]
    if pd.isna(current):
        if allow_fill:
            repairs[field] = cand
            repairs[f"{field}_FLAG"] = "FILLED"
    elif not _dates_equal(current, cand):
        repairs[field] = cand
        repairs[f"{field}_FLAG"] = "FIXED"


def _clear_date(repairs: dict, row, field: str) -> None:
    """Clear an incorrect non-null date field."""
    if field in repairs and pd.isna(repairs[field]):
        return
    current = repairs.get(field, row[field])
    if pd.isna(current):
        return
    repairs[field] = pd.NaT
    repairs[f"{field}_FLAG"] = "FIXED"


# ── Status maps ──────────────────────────────────────────────────────────────

# Shared labels across MGO ProjectStatus and flat Status (case-insensitive).
_STATUS_MAP = {
    # Final / completed
    "FINAL": "Final",
    "Final": "Final",
    "COED": "Final",
    "Project Closed/Complete": "Final",
    # Active / issued / under inspection
    "Permit Issued": "Active",
    "ISSUED": "Active",
    "Issued": "Active",
    "INSPECT": "Active",
    # In review / pre-issuance
    "Pending (Under Review)": "In Review",
    "APPLY": "In Review",
    # Inactive / closed without completion
    "Cancel": "Inactive",
    "Canceled": "Inactive",
    "Expired": "Inactive",
    "Expired (Older Permits)": "Inactive",
    "VOID": "Inactive",
    "History": "Inactive",
    "Impasse": "Inactive",
}


# ── Per-schema repair logic ─────────────────────────────────────────────────

def _repair_mgo_project(row, d: dict, repairs: dict) -> None:
    """Repair an MGO project-detail record."""
    effective_status = _apply_status(
        repairs, row["STATUS_NORMALIZED"], d.get("ProjectStatus"), _STATUS_MAP
    )

    # FILE_DATE ← DateCreated (always present and already matched in sample)
    _apply_date(repairs, row, "FILE_DATE", d.get("DateCreated"))

    # PERMIT_DATE ← DateIssued when real (sample: always sentinel → no-op)
    issued = _safe_to_datetime(d.get("DateIssued"))
    if issued is not pd.NaT:
        if pd.isna(row["PERMIT_DATE"]):
            if effective_status in ("Active", "Final"):
                repairs["PERMIT_DATE"] = issued
                repairs["PERMIT_DATE_FLAG"] = "FILLED"
        elif not _dates_equal(row["PERMIT_DATE"], issued):
            repairs["PERMIT_DATE"] = issued
            repairs["PERMIT_DATE_FLAG"] = "FIXED"

    # No completion / CO field in MGO payload. Clear spurious FINAL_DATE.
    if effective_status != "Final" and not pd.isna(row["FINAL_DATE"]):
        _clear_date(repairs, row, "FINAL_DATE")


def _repair_flat(row, d: dict, repairs: dict) -> None:
    """Repair a flat list-row record (basic or with completion fields)."""
    effective_status = _apply_status(
        repairs, row["STATUS_NORMALIZED"], d.get("Status"), _STATUS_MAP
    )

    submission = _safe_to_datetime(d.get("Submission Date"))
    expiration = _safe_to_datetime(d.get("Expiration Date"))
    completed = _safe_to_datetime(d.get("Completed Date"))
    co_date = _safe_to_datetime(d.get("CO Date"))

    # FILE_DATE ← Submission Date
    _apply_date(repairs, row, "FILE_DATE", submission)

    # PERMIT_DATE: no true issuance field. Upstream incorrectly copied
    # Submission Date into PERMIT_DATE for some rows → clear those.
    current_permit = row["PERMIT_DATE"]
    if (
        not pd.isna(current_permit)
        and submission is not pd.NaT
        and _dates_equal(current_permit, submission)
    ):
        _clear_date(repairs, row, "PERMIT_DATE")

    # FINAL_DATE: Expiration is a validity window, NOT finalization.
    # Prefer Completed Date, then CO Date, for Final rows only.
    current_final = row["FINAL_DATE"]
    current_is_expiration = (
        not pd.isna(current_final)
        and expiration is not pd.NaT
        and _dates_equal(current_final, expiration)
    )

    final_candidate = completed if completed is not pd.NaT else co_date

    if effective_status == "Final":
        if final_candidate is not pd.NaT:
            if pd.isna(current_final):
                repairs["FINAL_DATE"] = final_candidate
                repairs["FINAL_DATE_FLAG"] = "FILLED"
            elif not _dates_equal(current_final, final_candidate):
                repairs["FINAL_DATE"] = final_candidate
                repairs["FINAL_DATE_FLAG"] = "FIXED"
        elif current_is_expiration:
            _clear_date(repairs, row, "FINAL_DATE")
    else:
        # Non-Final rows should not carry a finaled date (esp. Expiration).
        if not pd.isna(current_final):
            _clear_date(repairs, row, "FINAL_DATE")


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Indian River County permit records using information from the raw DATA JSON.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Indian River County".  Must
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

        if schema == "mgo_project":
            _repair_mgo_project(row, d, repairs)
        elif schema in ("flat_basic", "flat_with_completion"):
            _repair_flat(row, d, repairs)

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
    irc = df[df["JURISDICTION"] == "Indian River County"].copy()

    print(f"Indian River County records: {len(irc):,}\n")

    repaired = data_repair(irc)

    print("INFERRED_SCHEMA:")
    print(repaired["INFERRED_SCHEMA"].value_counts(dropna=False).to_string())
    print()

    for field in ["STATUS_NORMALIZED", "FILE_DATE", "PERMIT_DATE", "FINAL_DATE"]:
        flag_col = f"{field}_FLAG"
        n_filled = (repaired[flag_col] == "FILLED").sum()
        n_fixed = (repaired[flag_col] == "FIXED").sum()
        print(f"{field}:")
        print(f"  FILLED: {n_filled:>4,}   FIXED: {n_fixed:>4,}")

        before_missing = irc[field].isna().sum()
        after_missing = repaired[field].isna().sum()
        print(f"  Missing before: {before_missing:>4,}   Missing after: {after_missing:>4,}")
        print()

    print("STATUS_NORMALIZED distribution:")
    print("  Before:")
    for s, c in irc["STATUS_NORMALIZED"].value_counts(dropna=False).items():
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

    # Confirm no FINAL_DATE still equals Expiration on flat schemas
    n_exp_left = 0
    n_perm_eq_sub = 0
    for idx in repaired.index:
        schema = repaired.at[idx, "INFERRED_SCHEMA"]
        if schema not in ("flat_basic", "flat_with_completion"):
            continue
        d = _safe_parse(repaired.at[idx, "DATA"]) or {}
        if not pd.isna(repaired.at[idx, "FINAL_DATE"]) and _dates_equal(
            repaired.at[idx, "FINAL_DATE"], d.get("Expiration Date")
        ):
            n_exp_left += 1
        if not pd.isna(repaired.at[idx, "PERMIT_DATE"]) and _dates_equal(
            repaired.at[idx, "PERMIT_DATE"], d.get("Submission Date")
        ):
            n_perm_eq_sub += 1
    print(f"\nflat FINAL_DATE still equal Expiration: {n_exp_left}")
    print(f"flat PERMIT_DATE still equal Submission: {n_perm_eq_sub}")

    if AGENT_DATA_PATH:
        out_path = os.path.join(AGENT_DATA_PATH, "indian_river_county_repaired_sample.parquet")
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote {out_path}")

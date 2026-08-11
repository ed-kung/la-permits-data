"""Data repair for Orlando (FL) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Orlando DATA has two sub-schemas from the city permit portal:

  - empty:         stub payload ``{"empty": ""}`` with no status or dates
                   (legacy / unresolved detail fetches).
  - permit_portal: Application Status plus optional Issued Date,
                   Finaled Date, Expiration Date, Plan Review[], and
                   Inspections[].

Canonical mappings (permit_portal):
  - Application Status (+ Issued Date for Open)  → STATUS_NORMALIZED
  - Earliest Plan Review Due Date                → FILE_DATE
  - Issued Date                                  → PERMIT_DATE
  - Finaled Date (else approved Final inspection
    Scheduled Date)                              → FINAL_DATE

Known issues repaired:
  - Open permits that already have Issued Date were mapped to
    In Review; they are Active once issued → FIXED.
  - Hardhold left STATUS_NORMALIZED null → FILLED as In Review.
  - FINAL_DATE often copied from Final Inspection Scheduled Date while
    Finaled Date (agency closeout) differs by ~1 day → FIXED to
    Finaled Date when present.
  - Missing FINAL_DATE filled from Finaled Date for Final rows.
  - Spurious FINAL_DATE on Active / In Review rows (cancelled or
    partial inspection schedule dates) → cleared (FIXED).
  - Missing FILE_DATE filled from earliest Plan Review Due Date when
    present (zoning / appearance-review style rows).

Not repairable / left as-is:
  - All ``empty`` rows lack status and dates in DATA → fields stay
    missing.
  - Building/trade ``permit_portal`` rows almost never expose an
    application / submittal date → FILE_DATE stays missing.
  - Closed / Completed Final rows without Finaled Date or an approved
    Final inspection → FINAL_DATE stays missing.
  - Approved Active rows with no Issued Date → PERMIT_DATE stays
    missing.
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
    """Parse a date value, returning pd.NaT on failure / sentinel zeros."""
    if val is None or (isinstance(val, str) and not str(val).strip()):
        return pd.NaT
    text = str(val).strip()
    if text.upper() in ("TBD", "NONE", "N/A", "NA", "00/00/0000", "0/0/0000"):
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
    if keys == {"empty"}:
        return "empty"
    if "Application Status" in keys:
        return "permit_portal"
    return "unknown"


# ── Status mapping ───────────────────────────────────────────────────────────

# Direct Application Status → STATUS_NORMALIZED (Open handled separately).
_STATUS_MAP = {
    "Finaled": "Final",
    "Closed": "Final",
    "Completed": "Final",
    "Approved": "Active",
    "Hold": "In Review",
    "Hardhold": "In Review",
    "Open": "In Review",  # overridden to Active when Issued Date present
}


def _expected_status(app_status: Optional[str], issued) -> Optional[str]:
    if app_status is None:
        return None
    if app_status == "Open" and _safe_to_datetime(issued) is not pd.NaT:
        return "Active"
    return _STATUS_MAP.get(app_status)


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


def _file_date_from_data(d: dict):
    """Earliest Plan Review Due Date (only application-like date in portal)."""
    dues = []
    for item in d.get("Plan Review") or []:
        if not isinstance(item, dict):
            continue
        dt = _safe_to_datetime(item.get("Due Date"))
        if dt is not pd.NaT:
            dues.append(dt)
    return min(dues) if dues else pd.NaT


def _final_date_from_data(d: dict):
    """Prefer Finaled Date; else latest approved Final inspection date."""
    finaled = _safe_to_datetime(d.get("Finaled Date"))
    if finaled is not pd.NaT:
        return finaled

    insp_dates = []
    for item in d.get("Inspections") or []:
        if not isinstance(item, dict):
            continue
        name = (item.get("Inspections") or "").lower()
        status = (item.get("Status") or "").lower()
        if "final" in name and status == "approved":
            dt = _safe_to_datetime(item.get("Scheduled Date"))
            if dt is not pd.NaT:
                insp_dates.append(dt)
    return max(insp_dates) if insp_dates else pd.NaT


# ── Per-schema repair logic ─────────────────────────────────────────────────

def _repair_permit_portal(row, d: dict, repairs: dict):
    """Repair a permit_portal detail record."""
    app_status = d.get("Application Status")
    issued = _safe_to_datetime(d.get("Issued Date"))
    expected = _expected_status(app_status, d.get("Issued Date"))
    effective_status = _apply_status(repairs, row["STATUS_NORMALIZED"], expected)

    # -- FILE_DATE ← earliest Plan Review Due Date --
    file_src = _file_date_from_data(d)
    if file_src is not pd.NaT:
        if pd.isna(row["FILE_DATE"]):
            repairs["FILE_DATE"] = file_src
            repairs["FILE_DATE_FLAG"] = "FILLED"
        # Do not FIXED-overwrite existing FILE_DATE: the two observed
        # disagreements look like Due Date sentinels earlier than the
        # true application date already stored upstream.

    # -- PERMIT_DATE ← Issued Date --
    if issued is not pd.NaT:
        if pd.isna(row["PERMIT_DATE"]):
            if effective_status in ("Active", "Final"):
                repairs["PERMIT_DATE"] = issued
                repairs["PERMIT_DATE_FLAG"] = "FILLED"
        elif not _dates_equal(row["PERMIT_DATE"], issued):
            repairs["PERMIT_DATE"] = issued
            repairs["PERMIT_DATE_FLAG"] = "FIXED"

    # -- FINAL_DATE ← Finaled Date / approved Final inspection --
    final_src = _final_date_from_data(d)
    current_final = row["FINAL_DATE"]
    if effective_status == "Final":
        if final_src is not pd.NaT:
            if pd.isna(current_final):
                repairs["FINAL_DATE"] = final_src
                repairs["FINAL_DATE_FLAG"] = "FILLED"
            elif not _dates_equal(current_final, final_src):
                repairs["FINAL_DATE"] = final_src
                repairs["FINAL_DATE_FLAG"] = "FIXED"
    elif not pd.isna(current_final):
        # Spurious FINAL_DATE on non-Final rows (e.g. cancelled Final
        # inspection Scheduled Date copied into FINAL_DATE while status
        # is still Open / Active).
        repairs["FINAL_DATE"] = pd.NaT
        repairs["FINAL_DATE_FLAG"] = "FIXED"


def _repair_empty(row, d: dict, repairs: dict):
    """Empty stubs have no recoverable status or dates."""
    return


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Orlando permit records using information from the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Orlando".  Must contain
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
        if schema == "permit_portal":
            _repair_permit_portal(row, d, repairs)
        elif schema == "empty":
            _repair_empty(row, d, repairs)

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
    orlando = df[df["JURISDICTION"] == "Orlando"].copy()

    print(f"Orlando records: {len(orlando):,}\n")

    repaired = data_repair(orlando)

    print("INFERRED_SCHEMA:")
    for s, c in repaired["INFERRED_SCHEMA"].value_counts(dropna=False).items():
        print(f"  {str(s):20s}: {c:>4,}")
    print()

    for field in ["STATUS_NORMALIZED", "FILE_DATE", "PERMIT_DATE", "FINAL_DATE"]:
        flag_col = f"{field}_FLAG"
        n_filled = (repaired[flag_col] == "FILLED").sum()
        n_fixed = (repaired[flag_col] == "FIXED").sum()
        print(f"{field}:")
        print(f"  FILLED: {n_filled:>4,}   FIXED: {n_fixed:>4,}")

        before_missing = orlando[field].isna().sum()
        after_missing = repaired[field].isna().sum()
        print(f"  Missing before: {before_missing:>4,}   Missing after: {after_missing:>4,}")
        print()

    print("STATUS_NORMALIZED distribution:")
    print("  Before:")
    for s, c in orlando["STATUS_NORMALIZED"].value_counts(dropna=False).items():
        print(f"    {str(s):15s}: {c:>4,}")
    print("  After:")
    for s, c in repaired["STATUS_NORMALIZED"].value_counts(dropna=False).items():
        print(f"    {str(s):15s}: {c:>4,}")

    print("\nFILE_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FILE_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({n_has / max(len(sub), 1):.1%})")

    print("\nPERMIT_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["PERMIT_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({n_has / max(len(sub), 1):.1%})")

    print("\nFINAL_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FINAL_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({n_has / max(len(sub), 1):.1%})")

    if AGENT_DATA_PATH:
        out_path = os.path.join(AGENT_DATA_PATH, "orlando_repaired_sample.parquet")
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote {out_path}")

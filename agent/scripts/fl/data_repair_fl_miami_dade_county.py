"""Data repair for Miami-Dade County (FL) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Miami-Dade County DATA is a flat open-data payload: every field is a
list of strings with a common key set (Issue Date, Request Date,
Inspection Type / Date / Disposition, CO/CC Release Date, etc.).
Inspection arrays hold at most one current inspection (not a full
history). ``Request Date`` is the inspection request date (almost
always on or after Issue Date, and typically one day before Inspection
Date) — not an application / submittal date.

Canonical mappings:
  - STATUS_ORIGINAL / Permit expired / final inspection / CO/CC       → STATUS_NORMALIZED
  - (no application date in DATA)                                     → FILE_DATE
  - DATA["Issue Date"]                                                → PERMIT_DATE
  - CO/CC Release Date / Bldg CO Release Date; else Last Approved
    Inspection Date; else approved Inspection Date                    → FINAL_DATE

Known issues repaired:
  - Null STATUS_NORMALIZED when STATUS_ORIGINAL is missing (issued,
    no inspections yet) or equals an Inspection Type label
    (mid-inspection Active / Final) → FILLED.
  - STATUS_ORIGINAL ``final`` with rejected / corrections / non-approved
    final inspection (and no CO) incorrectly mapped to Final → FIXED
    to Active; expired+failed final → Inactive.
  - FILE_DATE incorrectly copied from Request Date (inspection
    request) → cleared (FIXED). True application dates are absent.
  - Missing FINAL_DATE on Final rows filled from CO/CC or approved
    inspection dates; FINAL_DATE preferring inspection over later
    CO/CC → FIXED to CO/CC; spurious FINAL_DATE on non-Final → cleared.

Not repairable / left as-is:
  - FILE_DATE cannot be filled — DATA has no application / submittal
    date field.
  - One Active row with empty Issue Date and empty PERMIT_DATE →
    PERMIT_DATE stays missing.
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


def _field_vals(d: dict, key: str) -> list[str]:
    """Return non-empty string values from a list-valued DATA field."""
    raw = d.get(key)
    if raw is None:
        return []
    if not isinstance(raw, list):
        raw = [raw]
    out = []
    for item in raw:
        if item is None:
            continue
        text = str(item).strip()
        if text:
            out.append(text)
    return out


def _field_first(d: dict, key: str) -> str:
    vals = _field_vals(d, key)
    return vals[0] if vals else ""


def _classify_schema(d: Optional[dict]) -> str:
    if d is None:
        return "missing"
    has_insp = bool(
        _field_first(d, "Inspection Type")
        or _field_first(d, "Inspection Date")
        or _field_first(d, "Request Date")
    )
    has_issue = bool(_field_first(d, "Issue Date"))
    if has_insp:
        return "mdc_with_inspection"
    if has_issue:
        return "mdc_issued_only"
    return "mdc_minimal"


def _is_final_inspection_type(text: str) -> bool:
    u = text.upper()
    return u == "FINAL" or u.startswith("FIRE FINAL") or "FINAL ZONING" in u


def _is_approved_disposition(text: str) -> bool:
    u = text.upper()
    if not u:
        return False
    if any(k in u for k in ("REJECT", "CORRECTION", "NOT READY", "CANCEL")):
        return False
    return any(k in u for k in ("APPROV", "COMPLET", "PASS"))


def _has_final_signoff(d: dict) -> bool:
    if _field_first(d, "CO/CC Release Date") or _field_first(d, "Bldg CO Release Date"):
        return True
    return _is_final_inspection_type(_field_first(d, "Inspection Type")) and _is_approved_disposition(
        _field_first(d, "Inspection Disposition")
    )


def _expected_status(row, d: dict) -> Optional[str]:
    """Derive STATUS_NORMALIZED from Miami-Dade DATA + STATUS_ORIGINAL."""
    orig = row["STATUS_ORIGINAL"]
    orig_l = str(orig).strip().lower() if pd.notna(orig) else ""
    expired = _field_first(d, "Permit expired (Y/N)").upper() == "Y"

    if expired or orig_l == "expired":
        return "Inactive"

    # Agency "finaled" label is authoritative (payload may still show a
    # non-FINAL current inspection type).
    if orig_l == "finaled":
        return "Final"

    if orig_l == "issued":
        return "Active"

    # STATUS_ORIGINAL "final" often mirrors Inspection Type == FINAL, and
    # inspection-stage labels (rough, fire final, buck and fastener, ...)
    # were copied into STATUS_ORIGINAL without a normalized status.
    if _has_final_signoff(d):
        return "Final"
    if _field_first(d, "Issue Date") or not pd.isna(_safe_to_datetime(row["PERMIT_DATE"])):
        return "Active"
    return None


def _expected_final_date(d: dict) -> pd.Timestamp:
    """Best finaled / completion / signoff date from DATA."""
    for key in ("CO/CC Release Date", "Bldg CO Release Date"):
        dt = _safe_to_datetime(_field_first(d, key))
        if dt is not pd.NaT:
            return dt

    la = _safe_to_datetime(_field_first(d, "Last Approved Inspection Date"))
    if la is not pd.NaT:
        return la

    insp_date = _safe_to_datetime(_field_first(d, "Inspection Date"))
    if insp_date is not pd.NaT and _is_approved_disposition(
        _field_first(d, "Inspection Disposition")
    ):
        return insp_date

    last = _safe_to_datetime(_field_first(d, "Last Inspection Date"))
    if last is not pd.NaT:
        return last
    return pd.NaT


def _permit_date_from_data(d: dict) -> pd.Timestamp:
    issued = _safe_to_datetime(_field_first(d, "Issue Date"))
    if issued is not pd.NaT:
        return issued
    return _safe_to_datetime(_field_first(d, "New Issue Date"))


# ── Per-record repair ────────────────────────────────────────────────────────

def _repair_record(row, d: dict, repairs: dict) -> None:
    # -- STATUS_NORMALIZED --
    current_status = row["STATUS_NORMALIZED"]
    expected = _expected_status(row, d)
    if expected is not None:
        if pd.isna(current_status):
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"
        elif current_status != expected:
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FIXED"

    effective_status = repairs.get("STATUS_NORMALIZED", current_status)

    # -- FILE_DATE --
    # Request Date is an inspection-request date, not application/submittal.
    # Upstream FILE_DATE values that equal Request Date are incorrect.
    current_file = row["FILE_DATE"]
    request_dt = _safe_to_datetime(_field_first(d, "Request Date"))
    if not pd.isna(current_file) and request_dt is not pd.NaT and _dates_equal(
        current_file, request_dt
    ):
        repairs["FILE_DATE"] = pd.NaT
        repairs["FILE_DATE_FLAG"] = "FIXED"

    # -- PERMIT_DATE --
    issued = _permit_date_from_data(d)
    current_permit = row["PERMIT_DATE"]
    if issued is not pd.NaT:
        if pd.isna(current_permit):
            if effective_status in ("Active", "Final"):
                repairs["PERMIT_DATE"] = issued
                repairs["PERMIT_DATE_FLAG"] = "FILLED"
        elif not _dates_equal(current_permit, issued):
            repairs["PERMIT_DATE"] = issued
            repairs["PERMIT_DATE_FLAG"] = "FIXED"

    # -- FINAL_DATE --
    final_src = _expected_final_date(d)
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
        repairs["FINAL_DATE"] = pd.NaT
        repairs["FINAL_DATE_FLAG"] = "FIXED"


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Miami-Dade County permit records using the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Miami-Dade County".  Must
        contain columns STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE,
        FINAL_DATE, and DATA.

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
    filepath = os.path.join(MY_DATA_PATH, "processed_data", "permits_fl_sample.parquet")
    df = pd.read_parquet(filepath)
    mdc = df[df["JURISDICTION"] == "Miami-Dade County"].copy()

    print(f"Miami-Dade County records: {len(mdc):,}\n")

    repaired = data_repair(mdc)

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

        before_missing = mdc[field].isna().sum()
        after_missing = repaired[field].isna().sum()
        print(f"  Missing before: {before_missing:>4,}   Missing after: {after_missing:>4,}")
        print()

    print("STATUS_NORMALIZED distribution:")
    print("  Before:")
    for s, c in mdc["STATUS_NORMALIZED"].value_counts(dropna=False).items():
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

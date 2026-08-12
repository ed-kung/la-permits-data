"""Data repair for Volusia County (FL) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Volusia County DATA has two sub-schemas from the county folder/permit
system (CityView-style FOLDERRSN identifiers):

  - folder_list:   search/list payload with top-level Status, Date,
                   request_date, File Number, Type, etc. No issuance or
                   finalization timestamps.
  - folder_detail: detail payload with Folder details (Status,
                   Application, Issuance, Expiration), Folder
                   information, Parcel details, People details.

Canonical mappings:
  - DATA.Status / Folder details.Status          → STATUS_NORMALIZED
  - Date / request_date / Application            → FILE_DATE
  - Folder details.Issuance                      → PERMIT_DATE
  - (no reliable finalization date in DATA)      → FINAL_DATE

Known issues repaired:
  - folder_list rows have null STATUS_ORIGINAL / STATUS_NORMALIZED and
    null dates despite Status + Date in DATA → FILLED.
  - folder_detail: Dept Review / Final Fees Due left STATUS_NORMALIZED
    null → FILLED (In Review / Active).
  - Upstream FINAL_DATE on folder_detail equals Expiration for every
    non-null value (permit validity window, not completion) → cleared
    (FIXED). Includes spurious FINAL_DATE on Active / Inactive /
    In Review rows.
  - FILE_DATE / PERMIT_DATE already match Application / Issuance when
    present on folder_detail; mismatches overwritten defensively.

Not repairable / left as-is:
  - folder_list has no Issuance / finalization fields → PERMIT_DATE and
    FINAL_DATE stay missing after status fill.
  - folder_detail Active (Approved) rows with empty Issuance →
    PERMIT_DATE stays missing.
  - folder_detail Final rows have no true finaled/signoff date in DATA
    (Last Activity Date is general activity, not used) → FINAL_DATE
    stays missing after clearing Expiration copies.
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


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())
    if "Folder details" in keys:
        return "folder_detail"
    if "Status" in keys and ("Date" in keys or "File Number" in keys):
        return "folder_list"
    return "unknown"


def _apply_status(repairs: dict, current, raw_status: Optional[str], status_map: dict):
    """Map raw status → STATUS_NORMALIZED; return effective status."""
    if raw_status is None:
        return current if not (isinstance(current, float) and pd.isna(current)) else None

    expected = status_map.get(raw_status)
    if expected is None:
        # Case-insensitive fallback (folder_detail STATUS_ORIGINAL is lower).
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

# Shared Volusia Status labels (folder_list top-level + folder_detail.Status).
_STATUS_MAP = {
    # Final / completed
    "Finaled": "Final",
    "Complete": "Final",
    "Cert of Occupancy": "Final",
    "Closed": "Final",
    # Active / issued
    "Issued": "Active",
    "Approved": "Active",
    "Ready Issue": "Active",
    "Dev Order Issued": "Active",
    "Final Fees Due": "Active",
    "Pmt to Complete Reqd": "Active",
    # In review / pre-issuance
    "Plan Review": "In Review",
    "In Review": "In Review",
    "Staff Review": "In Review",
    "Dept Review": "In Review",
    "Zoning Review": "In Review",
    "Revision": "In Review",
    "Application": "In Review",
    "App Incomplete": "In Review",
    "Pending Resubmittal": "In Review",
    "App Fee Due": "In Review",
    "Fees Due": "In Review",
    "TRS Prep": "In Review",
    "Notice of Intent": "In Review",
    "Continued": "In Review",
    "Adopted": "In Review",
    "Proceed": "In Review",
    "Open": "In Review",
    "OOC": "In Review",
    # Inactive / closed without completion
    "Cancelled": "Inactive",
    "Expired": "Inactive",
    "Withdrawn": "Inactive",
    "Closed Administratively": "Inactive",
    "Denied": "Inactive",
    "Dismissed": "Inactive",
    "No Violation Observed": "Inactive",
    "No Violation": "Inactive",
    "Not a Code Violation": "Inactive",
    "Resolved": "Inactive",
    "Referred": "Inactive",
    "Citation": "Inactive",
    "Violation": "Inactive",
    "History": "Inactive",
    "Exempt": "Inactive",
}


# ── Per-schema repair logic ─────────────────────────────────────────────────

def _repair_folder_list(row, d: dict, repairs: dict) -> None:
    """Repair a folder_list (search/list) record."""
    effective_status = _apply_status(
        repairs, row["STATUS_NORMALIZED"], d.get("Status"), _STATUS_MAP
    )

    # FILE_DATE ← Date (identical to request_date in sample)
    file_candidate = d.get("Date")
    if _safe_to_datetime(file_candidate) is pd.NaT:
        file_candidate = d.get("request_date")
    _apply_date(repairs, row, "FILE_DATE", file_candidate)

    # No Issuance / finalization fields in folder_list.
    # Clear any spurious FINAL_DATE on non-Final rows (none expected).
    if effective_status != "Final" and not pd.isna(row["FINAL_DATE"]):
        _clear_date(repairs, row, "FINAL_DATE")


def _repair_folder_detail(row, d: dict, repairs: dict) -> None:
    """Repair a folder_detail record."""
    details = d.get("Folder details") if isinstance(d.get("Folder details"), dict) else {}

    effective_status = _apply_status(
        repairs, row["STATUS_NORMALIZED"], details.get("Status"), _STATUS_MAP
    )

    # FILE_DATE ← Application
    _apply_date(repairs, row, "FILE_DATE", details.get("Application"))

    # PERMIT_DATE ← Issuance (Active / Final; fix mismatches anytime present)
    issued = _safe_to_datetime(details.get("Issuance"))
    if issued is not pd.NaT:
        if pd.isna(row["PERMIT_DATE"]):
            if effective_status in ("Active", "Final"):
                repairs["PERMIT_DATE"] = issued
                repairs["PERMIT_DATE_FLAG"] = "FILLED"
        elif not _dates_equal(row["PERMIT_DATE"], issued):
            repairs["PERMIT_DATE"] = issued
            repairs["PERMIT_DATE_FLAG"] = "FIXED"

    # FINAL_DATE: Expiration is a validity window, NOT a finalization date.
    # Volusia DATA has no Certificate / Final inspection timestamp; Last
    # Activity Date is general activity and is not used as FINAL_DATE.
    expiration = _safe_to_datetime(details.get("Expiration"))
    current_final = row["FINAL_DATE"]
    current_is_expiration = (
        not pd.isna(current_final)
        and expiration is not pd.NaT
        and _dates_equal(current_final, expiration)
    )

    if effective_status == "Final":
        if current_is_expiration:
            _clear_date(repairs, row, "FINAL_DATE")
    else:
        # Non-Final rows should not carry a finaled date (esp. Expiration).
        if not pd.isna(current_final):
            _clear_date(repairs, row, "FINAL_DATE")


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Volusia County permit records using information from the raw DATA JSON.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Volusia County".  Must
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

        if schema == "folder_list":
            _repair_folder_list(row, d, repairs)
        elif schema == "folder_detail":
            _repair_folder_detail(row, d, repairs)

        for key, value in repairs.items():
            out.at[idx, key] = value

    # Normalize date columns to datetime64 (upstream may mix date / Timestamp).
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
    vc = df[df["JURISDICTION"] == "Volusia County"].copy()

    print(f"Volusia County records: {len(vc):,}\n")

    repaired = data_repair(vc)

    print("INFERRED_SCHEMA:")
    print(repaired["INFERRED_SCHEMA"].value_counts(dropna=False).to_string())
    print()

    for field in ["STATUS_NORMALIZED", "FILE_DATE", "PERMIT_DATE", "FINAL_DATE"]:
        flag_col = f"{field}_FLAG"
        n_filled = (repaired[flag_col] == "FILLED").sum()
        n_fixed = (repaired[flag_col] == "FIXED").sum()
        print(f"{field}:")
        print(f"  FILLED: {n_filled:>4,}   FIXED: {n_fixed:>4,}")

        before_missing = vc[field].isna().sum()
        after_missing = repaired[field].isna().sum()
        print(f"  Missing before: {before_missing:>4,}   Missing after: {after_missing:>4,}")
        print()

    print("STATUS_NORMALIZED distribution:")
    print("  Before:")
    for s, c in vc["STATUS_NORMALIZED"].value_counts(dropna=False).items():
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

    # Confirm no FINAL_DATE still equals Expiration on folder_detail
    n_exp_left = 0
    for idx in repaired.index:
        if repaired.at[idx, "INFERRED_SCHEMA"] != "folder_detail":
            continue
        if pd.isna(repaired.at[idx, "FINAL_DATE"]):
            continue
        d = _safe_parse(repaired.at[idx, "DATA"])
        details = (d or {}).get("Folder details") or {}
        if _dates_equal(repaired.at[idx, "FINAL_DATE"], details.get("Expiration")):
            n_exp_left += 1
    print(f"\nfolder_detail FINAL_DATE still equal Expiration: {n_exp_left}")

    if AGENT_DATA_PATH:
        out_path = os.path.join(AGENT_DATA_PATH, "volusia_county_repaired_sample.parquet")
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote {out_path}")

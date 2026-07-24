"""Data repair for Compton permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

The Compton DATA column is a flat JSON with keys:
  Status, Address, Permit#, Sub Type, Issue Date, Permit Type, Work Description

Data-quality issues specific to Compton:

  1. STATUS_NORMALIZED was derived from STATUS_ORIGINAL, which sometimes
     disagrees with DATA.Status (e.g. STATUS_ORIGINAL="issued" but
     DATA.Status="Finaled").  Several DATA.Status values (e.g.
     "Approved As-is", "Voic", "Open Substandard") were never mapped,
     leaving STATUS_NORMALIZED null.

  2. ~417 records have a column-shift defect: the "Issue Date" field
     contains work-description text and "Work Description" is absent.
     These records have no recoverable date.  A handful of records have
     an even more severe shift where "Status" contains a date and
     "Sub Type" contains the actual status.

  3. FILE_DATE and FINAL_DATE are universally missing because the
     Compton data source provides only "Issue Date" (permit issuance).
     No filing or finaling date is available.
"""

import json
import math
from typing import Optional

import pandas as pd
import numpy as np


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
    if val is None or (isinstance(val, str) and not val.strip()):
        return pd.NaT
    try:
        return pd.to_datetime(val)
    except (ValueError, TypeError):
        return pd.NaT


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())
    if "Status" in keys or "Permit#" in keys:
        return "flat"
    return "unknown"


# ── Status mapping ──────────────────────────────────────────────────────────

_STATUS_MAP = {
    "Issued": "Active",
    "Approved": "Active",
    "Approved As-is": "Active",
    "Approved in Full Compliance": "Active",
    "Open Substandard": "Active",
    "Finaled": "Final",
    "Closed": "Final",
    "Closed Substandard": "Final",
    "Under Review": "In Review",
    "Online Application Received": "In Review",
    "Ready to Issue": "In Review",
    "Applied": "In Review",
    "Expired": "Inactive",
    "Void": "Inactive",
    "Voic": "Inactive",
    "Canceled": "Inactive",
    "Withdrawn": "Inactive",
    "Closed File": "Inactive",
    "Expired Online Submitted Application": "Inactive",
}


def _derive_status(d: Optional[dict]) -> Optional[str]:
    """Derive STATUS_NORMALIZED from a parsed DATA dict.

    Uses the primary "Status" key.  When "Status" is garbled (contains a
    date or unrecognised text), falls back to "Sub Type" which sometimes
    holds the real status in column-shifted records.
    """
    if d is None:
        return None

    status = d.get("Status")
    if status is None or (isinstance(status, str) and not status.strip()):
        return None

    status = status.strip()
    if status in _STATUS_MAP:
        return _STATUS_MAP[status]

    sub_type = (d.get("Sub Type") or "").strip()
    if sub_type in _STATUS_MAP:
        return _STATUS_MAP[sub_type]

    return None


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Compton permit records using information from the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Compton".  Must contain
        columns STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, FINAL_DATE,
        and DATA.

    Returns
    -------
    pd.DataFrame
        Copy of *df* with corrected field values, an INFERRED_SCHEMA column
        naming the DATA JSON schema identified for each record, and new
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

        # -- STATUS_NORMALIZED --
        current_status = row["STATUS_NORMALIZED"]
        expected = _derive_status(d)
        if expected is not None:
            if pd.isna(current_status):
                repairs["STATUS_NORMALIZED"] = expected
                repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"
            elif current_status != expected:
                repairs["STATUS_NORMALIZED"] = expected
                repairs["STATUS_NORMALIZED_FLAG"] = "FIXED"

        # -- FILE_DATE --
        # Compton DATA has no filing/application date; nothing to fill.

        # -- PERMIT_DATE --
        # PERMIT_DATE already matches DATA."Issue Date" where parseable.
        # The 417 records with missing PERMIT_DATE have Issue Date fields
        # that contain work-description text, so no repair is possible.

        # -- FINAL_DATE --
        # Compton DATA has no finaling/completion date; nothing to fill.

        for key, value in repairs.items():
            out.at[idx, key] = value

    return out


# ── CLI: run standalone to preview repair stats ─────────────────────────────

if __name__ == "__main__":
    import os
    from dotenv import load_dotenv, find_dotenv

    load_dotenv(find_dotenv())
    MY_DATA_PATH = os.getenv("MY_DATA_PATH")
    filepath = os.path.join(MY_DATA_PATH, "processed_data", "permits_la_sample.parquet")
    df = pd.read_parquet(filepath)
    comp = df[df["JURISDICTION"] == "Compton"].copy()

    print(f"Compton records: {len(comp):,}\n")

    repaired = data_repair(comp)

    for field in ["STATUS_NORMALIZED", "FILE_DATE", "PERMIT_DATE", "FINAL_DATE"]:
        flag_col = f"{field}_FLAG"
        n_filled = (repaired[flag_col] == "FILLED").sum()
        n_fixed = (repaired[flag_col] == "FIXED").sum()
        print(f"{field}:")
        print(f"  FILLED: {n_filled:>4,}   FIXED: {n_fixed:>4,}")

        before_missing = comp[field].isna().sum()
        after_missing = repaired[field].isna().sum()
        print(f"  Missing before: {before_missing:>4,}   Missing after: {after_missing:>4,}")
        print()

    print("STATUS_NORMALIZED distribution:")
    print("  Before:")
    for s, c in comp["STATUS_NORMALIZED"].value_counts(dropna=False).items():
        print(f"    {str(s):15s}: {c:>4,}")
    print("  After:")
    for s, c in repaired["STATUS_NORMALIZED"].value_counts(dropna=False).items():
        print(f"    {str(s):15s}: {c:>4,}")

    print("\nPERMIT_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["PERMIT_DATE"].notna().sum()
        if len(sub) > 0:
            print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({n_has/len(sub):.1%})")

    print("\nFINAL_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FINAL_DATE"].notna().sum()
        if len(sub) > 0:
            print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({n_has/len(sub):.1%})")

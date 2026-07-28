"""Data repair for Belvedere (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Belvedere DATA is a flat civic portal scrape. All rows share core
top-level keys (``Status``, ``Permit Date``, ``Issued Date``,
``CTL Expiration Date``, ``Permit Number``, ``fees``, ``payments``,
``contractors``, ``inspections``, ``property_info``, …). Optional keys
define the INFERRED_SCHEMA variants:

  - portal_reviews:               has ``reviews`` (usually empty)
  - portal_plan_reviews:          has ``plan_reviews`` (no record_type)
  - portal_plan_reviews_rtype:    has ``plan_reviews`` +
                                  ``record_type_from_contractor_box``

Canonical mappings:
  - DATA.Status              → STATUS_NORMALIZED
  - DATA['Permit Date']      → FILE_DATE  (application / submittal)
  - DATA['Issued Date']      → PERMIT_DATE (approval / issuance)
  - (no true final date)     → FINAL_DATE cannot be filled from DATA

Known issues repaired:
  - 50 null STATUS_NORMALIZED rows for unmapped portal statuses
    (Review-*, Comments Sent/Generated, Approved as Essential,
    Final-ReVal Required, Building Final-Planning Required,
    Cancelled & Refunded, Pmt Reminder sent, Set for Hearing) → FILLED.
  - All 82 FINAL_DATE values are incorrectly copied from
    ``CTL Expiration Date`` (construction-time-limit expiry, not
    finalization). Cleared → FIXED. Inspections / reviews are empty
    in the sample, so no real FINAL_DATE source exists.

Not repairable / left as-is:
  - FILE_DATE already matches Permit Date for every populated row;
    one empty-shell record has no dates in DATA.
  - Active/Final missing PERMIT_DATE lack Issued Date in DATA
    (~50 rows); Permit Date is the application date and must not be
    used as a substitute.
  - 7 rows with blank Status remain STATUS_NORMALIZED null.
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
    """Parse a date value, returning pd.NaT on failure."""
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return pd.NaT
    if isinstance(val, str) and not str(val).strip():
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
    if da is pd.NaT or db is pd.NaT:
        return False
    return da.normalize() == db.normalize()


_CORE_KEYS = {
    "Status",
    "Permit Date",
    "Issued Date",
    "CTL Expiration Date",
    "Permit Number",
}


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())
    if not _CORE_KEYS <= keys:
        return "unknown"
    if "reviews" in keys:
        return "portal_reviews"
    if "plan_reviews" in keys and "record_type_from_contractor_box" in keys:
        return "portal_plan_reviews_rtype"
    if "plan_reviews" in keys:
        return "portal_plan_reviews"
    return "portal_core"


# ── Status mapping ──────────────────────────────────────────────────────────

_STATUS_MAP = {
    # Final
    "Finaled": "Final",
    "Complete": "Final",
    "Final-ReVal Required": "Final",
    # Active — approved / issued / near-final still open
    "Approved": "Active",
    "Issued": "Active",
    "Approved as Essential": "Active",
    "Building Final-Planning Required": "Active",
    # In Review — application / plan check / hold / hearing
    "In process": "In Review",
    "Pending": "In Review",
    "Incomplete": "In Review",
    "Hold": "In Review",
    "Review-First": "In Review",
    "Review-Second": "In Review",
    "Review-Third": "In Review",
    "Comments Sent": "In Review",
    "Comments Generated": "In Review",
    "Pmt Reminder sent": "In Review",
    "Set for Hearing": "In Review",
    # Inactive
    "Withdrawn": "Inactive",
    "Voided": "Inactive",
    "Denied": "Inactive",
    "Expired": "Inactive",
    "Cancelled & Refunded": "Inactive",
}


def _expected_status(d: dict) -> Optional[str]:
    raw = d.get("Status")
    if isinstance(raw, str) and raw.strip():
        return _STATUS_MAP.get(raw.strip())
    return None


def _file_date_from_data(d: dict):
    return _safe_to_datetime(d.get("Permit Date"))


def _issued_date(d: dict):
    return _safe_to_datetime(d.get("Issued Date"))


def _ctl_expiration(d: dict):
    return _safe_to_datetime(d.get("CTL Expiration Date"))


# ── Repair logic ────────────────────────────────────────────────────────────

def _repair_record(row, d: dict, repairs: dict):
    # -- STATUS_NORMALIZED --
    current_status = row["STATUS_NORMALIZED"]
    expected = _expected_status(d)
    if expected is not None:
        if pd.isna(current_status):
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"
        elif current_status != expected:
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FIXED"

    effective_status = repairs.get("STATUS_NORMALIZED", current_status)

    # -- FILE_DATE --
    file_date = _file_date_from_data(d)
    if file_date is not pd.NaT:
        if pd.isna(row["FILE_DATE"]):
            repairs["FILE_DATE"] = file_date
            repairs["FILE_DATE_FLAG"] = "FILLED"
        elif not _dates_equal(row["FILE_DATE"], file_date):
            repairs["FILE_DATE"] = file_date
            repairs["FILE_DATE_FLAG"] = "FIXED"

    # -- PERMIT_DATE --
    issued = _issued_date(d)
    if issued is not pd.NaT:
        if pd.isna(row["PERMIT_DATE"]):
            if effective_status in ("Active", "Final"):
                repairs["PERMIT_DATE"] = issued
                repairs["PERMIT_DATE_FLAG"] = "FILLED"
        elif not _dates_equal(row["PERMIT_DATE"], issued):
            repairs["PERMIT_DATE"] = issued
            repairs["PERMIT_DATE_FLAG"] = "FIXED"

    # -- FINAL_DATE --
    # Belvedere has no true finalization date in DATA. Existing FINAL_DATE
    # values are CTL Expiration Date (validity window), not completion.
    ctl = _ctl_expiration(d)
    current_final = row["FINAL_DATE"]
    if not pd.isna(current_final) and (
        (ctl is not pd.NaT and _dates_equal(current_final, ctl))
        or effective_status != "Final"
    ):
        repairs["FINAL_DATE"] = pd.NaT
        repairs["FINAL_DATE_FLAG"] = "FIXED"


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Belvedere (CA) permit records using information from the raw DATA JSON.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Belvedere". Must contain
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

    return out


# ── CLI: run standalone to preview repair stats ─────────────────────────────

if __name__ == "__main__":
    import os
    from pathlib import Path

    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[3] / ".env")
    MY_DATA_PATH = os.getenv("MY_DATA_PATH")
    AGENT_DATA_PATH = os.getenv("AGENT_DATA_PATH")
    filepath = os.path.join(MY_DATA_PATH, "processed_data", "permits_ca_sample.parquet")
    df = pd.read_parquet(filepath)
    bel = df[(df["JURISDICTION"] == "Belvedere") & (df["STATE"] == "CA")].copy()

    print(f"Belvedere records: {len(bel):,}\n")

    repaired = data_repair(bel)

    print("INFERRED_SCHEMA:")
    for s, c in repaired["INFERRED_SCHEMA"].value_counts(dropna=False).items():
        print(f"  {str(s):45s}: {c:>4,}")
    print()

    for field in ["STATUS_NORMALIZED", "FILE_DATE", "PERMIT_DATE", "FINAL_DATE"]:
        flag_col = f"{field}_FLAG"
        n_filled = (repaired[flag_col] == "FILLED").sum()
        n_fixed = (repaired[flag_col] == "FIXED").sum()
        print(f"{field}:")
        print(f"  FILLED: {n_filled:>4,}   FIXED: {n_fixed:>4,}")

        before_missing = bel[field].isna().sum()
        after_missing = repaired[field].isna().sum()
        print(f"  Missing before: {before_missing:>4,}   Missing after: {after_missing:>4,}")
        print()

    print("STATUS_NORMALIZED distribution:")
    print("  Before:")
    for s, c in bel["STATUS_NORMALIZED"].value_counts(dropna=False).items():
        print(f"    {str(s):15s}: {c:>4,}")
    print("  After:")
    for s, c in repaired["STATUS_NORMALIZED"].value_counts(dropna=False).items():
        print(f"    {str(s):15s}: {c:>4,}")

    print("\nPERMIT_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["PERMIT_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} "
              f"({n_has / len(sub) if len(sub) else 0:.1%})")

    print("\nFINAL_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FINAL_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} "
              f"({n_has / len(sub) if len(sub) else 0:.1%})")

    print("\nFILE_DATE coverage after repair: "
          f"{repaired['FILE_DATE'].notna().sum()} / {len(repaired)}")

    if AGENT_DATA_PATH:
        out_path = Path(AGENT_DATA_PATH) / "belvedere_repaired_sample.parquet"
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote repaired sample → {out_path}")

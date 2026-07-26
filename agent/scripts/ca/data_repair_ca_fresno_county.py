"""Data repair for Fresno County (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Fresno County DATA is a flat Accela Citizen Access search-result payload
with a single populated schema plus null DATA rows:

  - citizen_portal: top-level keys include Status, Application Date,
                    Application #, Type, Agency, FOLDERRSN, APN, etc.
  - missing:        DATA is null / NaN (~half the sample)

Canonical mappings (citizen_portal):
  - DATA.Status (fallback: STATUS_ORIGINAL)  → STATUS_NORMALIZED
  - DATA['Application Date']                 → FILE_DATE
  - (no issuance field in DATA)              → PERMIT_DATE unrepairable
  - (no completion / final field in DATA)    → FINAL_DATE unrepairable

Known issues repaired:
  - 143 unmapped STATUS_ORIGINAL values left STATUS_NORMALIZED null
    (Closed Permit → Final; Permit Issuance or Approval / Internet
    Incomplete / Permit Application → In Review; Permit Rider Attached
    → Active; Dummy → Inactive). FILLED from DATA.Status when present,
    else STATUS_ORIGINAL (same vocabulary; needed for missing-DATA rows).
  - 2 rows where DATA.Status='Issued' but STATUS_ORIGINAL='closed' and
    STATUS_NORMALIZED='Final' → FIXED to Active (trust DATA.Status).

Not repairable / left as-is:
  - FILE_DATE already populated for all sample rows and matches
    Application Date wherever DATA is present.
  - PERMIT_DATE and FINAL_DATE are entirely missing. citizen_portal
    exposes only Application Date — no issued / finaled / closed date —
    so Active/Final coverage cannot be improved from DATA alone.
  - 1 row with null STATUS_ORIGINAL and null DATA → status stays missing.
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
    if val is None or (isinstance(val, str) and not str(val).strip()):
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
    if "Status" in keys or "Application Date" in keys:
        return "citizen_portal"
    return "unknown"


# ── Status mapping ──────────────────────────────────────────────────────────

# DATA.Status / STATUS_ORIGINAL (case-insensitive lookup)
_STATUS_MAP = {
    # Final — closed / completed terminal outcomes
    "closed": "Final",
    "closed permit": "Final",
    # Active — issued / permit exists with rider
    "issued": "Active",
    "permit rider attached": "Active",
    # Inactive — expired, cancelled, denied, dummy shells
    "expired": "Inactive",
    "cancelled": "Inactive",
    "cancelled permit": "Inactive",
    "denied": "Inactive",
    "dummy": "Inactive",
    # In Review — pre-issuance / application / incomplete submittal
    "pre-application": "In Review",
    "application": "In Review",
    "permit application": "In Review",
    "pending review": "In Review",
    "ready to issue": "In Review",
    "in process": "In Review",
    "internet incomplete": "In Review",
    "ready for payment": "In Review",
    # Workflow stage at issuance/approval task — not yet Issued
    "permit issuance or approval": "In Review",
}


def _raw_status(d: Optional[dict], row) -> Optional[str]:
    """Prefer DATA.Status; fall back to STATUS_ORIGINAL."""
    if isinstance(d, dict):
        status = d.get("Status")
        if status is not None and str(status).strip():
            return str(status).strip()
    orig = row.get("STATUS_ORIGINAL") if hasattr(row, "get") else row["STATUS_ORIGINAL"]
    if pd.isna(orig):
        return None
    orig = str(orig).strip()
    return orig or None


def _map_status(raw: Optional[str]) -> Optional[str]:
    if raw is None:
        return None
    return _STATUS_MAP.get(raw.casefold())


# ── Per-record repair logic ─────────────────────────────────────────────────

def _repair_record(row, d: Optional[dict], repairs: dict):
    """Populate *repairs* with corrected values for a single Fresno County record."""
    current_status = row["STATUS_NORMALIZED"]
    raw = _raw_status(d, row)
    expected = _map_status(raw)

    # -- STATUS_NORMALIZED --
    if expected is not None:
        if pd.isna(current_status):
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"
        elif current_status != expected:
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FIXED"

    effective_status = repairs.get("STATUS_NORMALIZED", current_status)

    # -- FILE_DATE (Application Date) --
    # Only available on citizen_portal; already matches for all sample rows.
    if isinstance(d, dict):
        app = _safe_to_datetime(d.get("Application Date"))
        if app is not pd.NaT:
            if pd.isna(row["FILE_DATE"]):
                repairs["FILE_DATE"] = app
                repairs["FILE_DATE_FLAG"] = "FILLED"
            elif not _dates_equal(row["FILE_DATE"], app):
                repairs["FILE_DATE"] = app
                repairs["FILE_DATE_FLAG"] = "FIXED"

    # -- PERMIT_DATE / FINAL_DATE --
    # citizen_portal exposes no issuance or final/completion date fields.
    # Nothing to fill or fix from DATA; leave existing (null) values as-is.
    _ = effective_status  # retained for symmetry with other jurisdiction scripts


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Fresno County permit records using information from the raw DATA
    JSON column (with STATUS_ORIGINAL as status fallback when DATA is null).

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Fresno County".  Must
        contain columns STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE,
        FINAL_DATE, DATA, and preferably STATUS_ORIGINAL.

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

        repairs: dict = {}
        _repair_record(row, d, repairs)

        for key, value in repairs.items():
            out.at[idx, key] = value

    return out


# ── CLI: run standalone to preview repair stats ─────────────────────────────

if __name__ == "__main__":
    import os
    from dotenv import load_dotenv

    load_dotenv("/Users/ekung/projects/la-permits-data/.env")
    MY_DATA_PATH = os.getenv("MY_DATA_PATH")
    AGENT_DATA_PATH = os.getenv("AGENT_DATA_PATH")
    filepath = os.path.join(MY_DATA_PATH, "processed_data", "permits_ca_sample.parquet")
    df = pd.read_parquet(filepath)
    city = df[
        (df["JURISDICTION"] == "Fresno County") & (df["STATE"] == "CA")
    ].copy()

    print(f"Fresno County records: {len(city):,}\n")

    repaired = data_repair(city)

    if AGENT_DATA_PATH:
        out_path = os.path.join(
            AGENT_DATA_PATH, "fresno_county_repaired_sample.parquet"
        )
        repaired.to_parquet(out_path, index=False)
        print(f"Wrote {out_path}\n")

    print("INFERRED_SCHEMA:")
    print(repaired["INFERRED_SCHEMA"].value_counts(dropna=False).to_string())
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

    print("\nSTATUS_NORMALIZED change summary (raw → before → after):")
    from collections import Counter

    change_counts: Counter = Counter()
    for idx in repaired.index:
        flag = repaired.at[idx, "STATUS_NORMALIZED_FLAG"]
        if flag not in ("FILLED", "FIXED"):
            continue
        d = _safe_parse(city.at[idx, "DATA"])
        raw = _raw_status(d, city.loc[idx])
        before = city.at[idx, "STATUS_NORMALIZED"]
        after = repaired.at[idx, "STATUS_NORMALIZED"]
        change_counts[(flag, raw, str(before), after)] += 1
    for (flag, raw, before, after), n in sorted(change_counts.items(), key=lambda x: -x[1]):
        print(f"  {flag:6s} n={n:>3}  {raw!r:35s} {before:15s} → {after}")

    print("\nPERMIT_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["PERMIT_DATE"].notna().sum()
        n = len(sub)
        pct = n_has / n if n else 0.0
        print(f"  {status:15s}: {n_has:>4,} / {n:>4,} ({pct:.1%})")

    print("\nFINAL_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FINAL_DATE"].notna().sum()
        n = len(sub)
        pct = n_has / n if n else 0.0
        print(f"  {status:15s}: {n_has:>4,} / {n:>4,} ({pct:.1%})")

    print("\nFILE_DATE coverage (after repair):")
    n_has = repaired["FILE_DATE"].notna().sum()
    print(f"  {n_has:>4,} / {len(repaired):>4,} ({n_has/len(repaired):.1%})")

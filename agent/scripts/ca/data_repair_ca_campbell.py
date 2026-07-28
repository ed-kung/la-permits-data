"""Data repair for Campbell (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Campbell DATA is a flat MyGovOnline (MGO) portal payload. Every sample
row shares the same top-level keys (``ProjectStatus``, ``DateCreated``,
``DateIssued``, ``DateUpdated``, applicant/site fields, etc.). Content
variants (INFERRED_SCHEMA):

  - mgo_imported: TypeList contains ``Imported Fee`` (legacy fee
    shells migrated into MGO; n≈1,476 in sample)
  - mgo_modern:   all other portal records (n≈524)
  - missing / unknown

Canonical mappings:
  - ProjectStatus (whitespace-stripped) → STATUS_NORMALIZED
  - DateCreated                         → FILE_DATE
  - DateIssued (when not the .NET
    sentinel ``0001-01-01``)            → PERMIT_DATE
  - (no final/sign-off timestamp in
    DATA)                               → FINAL_DATE unavailable

Known issues repaired:
  - Two modern rows have ProjectStatus ``Permit Expired`` but
    STATUS_ORIGINAL / STATUS_NORMALIZED still reflect a prior state
    (``approved (ready for issuance)`` → In Review;
    ``permit issued`` → Active). ProjectStatus is authoritative
    → FIXED to Inactive.

Not repairable from DATA:
  - DateIssued is the sentinel ``0001-01-01T00:00:00`` on every sample
    row, including Permit Issued / Permit Finaled/Closed. PERMIT_DATE
    cannot be filled.
  - No finaled / completion / sign-off date field exists in the
    payload. FINAL_DATE cannot be filled.
  - FILE_DATE already matches DateCreated on all sample rows.
"""

from __future__ import annotations

import json
import math
from typing import Optional

import numpy as np
import pandas as pd


_MIN_YEAR = 1900
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
        return json.loads(data)
    return data


def _safe_to_datetime(val):
    """Parse a date value, returning pd.NaT on failure / sentinel / implausible year."""
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return pd.NaT
    if isinstance(val, str):
        s = val.strip()
        if not s or s.startswith("0001-01-01"):
            return pd.NaT
    try:
        dt = pd.to_datetime(val)
    except (ValueError, TypeError):
        return pd.NaT
    if dt is pd.NaT or pd.isna(dt):
        return pd.NaT
    if getattr(dt, "tzinfo", None) is not None:
        dt = dt.tz_convert("UTC").tz_localize(None)
    year = int(dt.year)
    if year < _MIN_YEAR or year > _MAX_YEAR:
        return pd.NaT
    return dt


def _dates_equal(a, b) -> bool:
    """Compare two datelike values at calendar-day resolution."""
    da = _safe_to_datetime(a)
    db = _safe_to_datetime(b)
    if da is pd.NaT or db is pd.NaT or pd.isna(da) or pd.isna(db):
        return False
    return da.normalize() == db.normalize()


def _normalize_project_status(raw) -> str:
    if raw is None or (isinstance(raw, str) and not str(raw).strip()):
        return ""
    # Portal sometimes prefixes status with a tab (e.g. "\\tPending (Under Review)").
    return str(raw).replace("\t", " ").strip()


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())
    if "ProjectStatus" not in keys or "DateCreated" not in keys:
        return "unknown"
    type_list = str(data_dict.get("TypeList") or "")
    if "Imported Fee" in type_list:
        return "mgo_imported"
    return "mgo_modern"


# ── Status mapping ───────────────────────────────────────────────────────────

# ProjectStatus (stripped) → STATUS_NORMALIZED
_STATUS_MAP = {
    "Permit Finaled/Closed": "Final",
    "Permit Issued": "Active",
    "Pending (Under Review)": "In Review",
    "Approved (Ready for Issuance)": "In Review",
    "Plan Check Wait": "In Review",
    "Stop Work": "In Review",
    "Permit Expired": "Inactive",
    "Plan Check Expired": "Inactive",
    "Withdrawn": "Inactive",
}


def _derive_status(d: dict) -> Optional[str]:
    raw = _normalize_project_status(d.get("ProjectStatus"))
    if not raw:
        return None
    if raw in _STATUS_MAP:
        return _STATUS_MAP[raw]
    lower = raw.lower()
    if "final" in lower or "closed" in lower or "complete" in lower:
        return "Final"
    if "issued" in lower and "ready" not in lower:
        return "Active"
    if (
        "expire" in lower
        or "withdraw" in lower
        or "cancel" in lower
        or "void" in lower
        or "denied" in lower
    ):
        return "Inactive"
    if (
        "pending" in lower
        or "review" in lower
        or "plan check" in lower
        or "wait" in lower
        or "hold" in lower
        or "stop work" in lower
        or "ready for issuance" in lower
        or "approved" in lower
    ):
        return "In Review"
    return None


# ── Per-record repair ────────────────────────────────────────────────────────

def _repair_record(row, d: dict, repairs: dict) -> None:
    """Repair one Campbell MGO record in-place into *repairs*."""

    # -- STATUS_NORMALIZED --
    expected = _derive_status(d)
    current_status = row["STATUS_NORMALIZED"]
    if expected is not None:
        if pd.isna(current_status) or (
            isinstance(current_status, float) and math.isnan(current_status)
        ):
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"
        elif current_status != expected:
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FIXED"

    effective_status = repairs.get("STATUS_NORMALIZED", current_status)

    # -- FILE_DATE --
    created = _safe_to_datetime(d.get("DateCreated"))
    if created is not pd.NaT:
        if pd.isna(row["FILE_DATE"]):
            repairs["FILE_DATE"] = created.normalize()
            repairs["FILE_DATE_FLAG"] = "FILLED"
        elif not _dates_equal(row["FILE_DATE"], created):
            repairs["FILE_DATE"] = created.normalize()
            repairs["FILE_DATE_FLAG"] = "FIXED"

    # -- PERMIT_DATE --
    issued = _safe_to_datetime(d.get("DateIssued"))
    if issued is not pd.NaT:
        if pd.isna(row["PERMIT_DATE"]):
            if effective_status in ("Active", "Final", "Inactive"):
                # Expired rows may still have once been issued.
                repairs["PERMIT_DATE"] = issued.normalize()
                repairs["PERMIT_DATE_FLAG"] = "FILLED"
        elif not _dates_equal(row["PERMIT_DATE"], issued):
            repairs["PERMIT_DATE"] = issued.normalize()
            repairs["PERMIT_DATE_FLAG"] = "FIXED"

    # -- FINAL_DATE --
    # No finaled / completion timestamp exists in the Campbell MGO payload.
    # Leave FINAL_DATE unchanged (universally missing in the sample).


# ── Main entry point ─────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Campbell permit records using information from the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Campbell". Must contain
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


# ── CLI: run standalone to preview repair stats ──────────────────────────────

if __name__ == "__main__":
    import os
    from dotenv import load_dotenv, find_dotenv

    load_dotenv(find_dotenv())
    MY_DATA_PATH = os.getenv("MY_DATA_PATH")
    filepath = os.path.join(MY_DATA_PATH, "processed_data", "permits_ca_sample.parquet")
    df = pd.read_parquet(filepath)
    city = df[df["JURISDICTION"] == "Campbell"].copy()

    print(f"Campbell records: {len(city):,}\n")

    repaired = data_repair(city)

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

    print("\nStatus transitions (FIXED):")
    mask = repaired["STATUS_NORMALIZED_FLAG"] == "FIXED"
    if mask.any():
        for (a, b), n in (
            pd.DataFrame(
                {
                    "before": city.loc[mask, "STATUS_NORMALIZED"].values,
                    "after": repaired.loc[mask, "STATUS_NORMALIZED"].values,
                }
            )
            .value_counts()
            .items()
        ):
            print(f"  {a} → {b}: {n}")
    else:
        print("  (none)")

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

    print("\nFILE_DATE coverage after repair:")
    n_has = repaired["FILE_DATE"].notna().sum()
    print(f"  {n_has:>4,} / {len(repaired):>4,} ({n_has / len(repaired):.1%})")

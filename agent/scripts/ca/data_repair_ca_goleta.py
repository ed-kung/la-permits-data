"""Data repair for Goleta (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Goleta DATA is a City of Goleta portal payload keyed by department /
record family. Every sample row has exactly one of these top-level keys:

  - Building & Safety  → nested ``Building & Safety Details`` (+ Inspections,
                         Plan Review)
  - Planning Cases     → nested ``Planning Details`` (most rows) or a flat
                         status/date dict (legacy subset)
  - Business License   → nested ``Business License Details``
  - Permits Cases      → flat status/date dict

Canonical fields (under Details or flat):

  - Status             → STATUS_NORMALIZED
  - Issued date        → PERMIT_DATE
  - (no Applied/Filed) → FILE_DATE not available in DATA
  - passed Final*      → FINAL_DATE (from Case Inspections)

INFERRED_SCHEMA content variants encode department shape + whether Issued /
a usable final inspection date are present.

Known issues repaired:
  - STATUS_NORMALIZED missing on 382 rows where STATUS_ORIGINAL was blank
    (nested Planning Details, all Business License) or unmapped
    (web created / web rejected) → FILLED from Details.Status.
  - Active/Final missing PERMIT_DATE when Issued date is present → FILLED.
  - Final missing FINAL_DATE filled from latest passed final inspection
    (Final Building / bare Final / Planning Department Final preferred;
    other Final* Pass/Conditional as fallback) → FILLED.
  - Spurious FINAL_DATE on Permits Cases rows copied from Expiration Date
    (Issued / Created status) → FIXED (cleared on non-Final; overwritten
    on Final when a better final-inspection date exists).

Not repairable / left as-is:
  - FILE_DATE: DATA has no Applied / Submitted / Filed date field on any
    schema → remains missing for all rows.
  - Many Final (Closed/Finaled) rows lack Case Inspections and have no
    finaled date field → FINAL_DATE stays missing.
  - Active/Final rows with blank Issued date → PERMIT_DATE stays missing.
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


def _top_key(d: dict) -> Optional[str]:
    if not d:
        return None
    return next(iter(d.keys()), None)


def _inner(d: dict) -> dict:
    top = _top_key(d)
    if top is None:
        return {}
    inner = d.get(top)
    return inner if isinstance(inner, dict) else {}


def _details(d: dict) -> dict:
    """Return the status/date dict (Details block or flat case payload)."""
    inner = _inner(d)
    if not inner:
        return {}

    # Prefer explicit *Details blocks (Building & Safety / Planning /
    # Business License nested shape).
    for key, val in inner.items():
        if isinstance(val, dict) and "Status" in val and "Details" in key:
            return val

    # Flat Planning Cases / Permits Cases.
    if "Status" in inner:
        return inner

    # Fallback: any nested dict with Status.
    for val in inner.values():
        if isinstance(val, dict) and "Status" in val:
            return val
    return {}


def _schema_base(d: Optional[dict]) -> str:
    if d is None:
        return "missing"
    top = _top_key(d)
    if top == "Building & Safety":
        return "building_safety"
    if top == "Planning Cases":
        inner = _inner(d)
        if "Planning Details" in inner:
            return "planning_nested"
        return "planning_flat"
    if top == "Business License":
        return "business_license"
    if top == "Permits Cases":
        return "permits_cases"
    return "unknown"


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    base = _schema_base(data_dict)
    if base in ("missing", "unknown"):
        return base

    details = _details(data_dict)
    issued = _safe_to_datetime(details.get("Issued date"))
    final_insp = _final_from_inspections(data_dict)
    has_issued = issued is not pd.NaT
    has_final = final_insp is not pd.NaT

    if has_issued and has_final:
        return f"{base}_issued_finalinsp"
    if has_issued:
        return f"{base}_issued"
    if has_final:
        return f"{base}_finalinsp_only"
    return f"{base}_no_dates"


# ── Status mapping ──────────────────────────────────────────────────────────

_STATUS_MAP = {
    # Final
    "CLOSED": "Final",
    "FINALED": "Final",
    "CLOSED - APPROVED": "Final",
    "CLOSED - ISSUED": "Final",
    "COMPLETED": "Final",
    # Active
    "ISSUED": "Active",
    "APPROVED": "Active",
    "ACTIVE": "Active",  # Business License currently valid
    # In Review
    "PENDING": "In Review",
    "PENDING PAYMENT": "In Review",
    "CREATED": "In Review",
    "WEB CREATED": "In Review",
    "UNDER REVIEW": "In Review",
    "IN REVIEW": "In Review",
    "CORRECTIONS NEEDED": "In Review",
    "READY TO ISSUE": "In Review",
    "AWAITING APPLICANT RESPONSE": "In Review",
    # Inactive
    "EXPIRED": "Inactive",
    "WEB REJECTED": "Inactive",
    "WITHDRAWN": "Inactive",
    "WITHDREW": "Inactive",
    "APPLICATION SUSPENDED": "Inactive",
}

_FINAL_INSP_OK = {
    "",
    "PASS",
    "PASSED",
    "CONDITIONAL",
    "PASS WITH COMMENTS",
    "APPROVED",
    "COMPLETED",
    "COMPLETE",
    "OK",
}

# Prefer permit-level finals over trade finals when choosing FINAL_DATE.
_PREFERRED_FINAL_RE = re.compile(
    r"(?i)^("
    r"final|"
    r"final building inspection|"
    r"planning department final|"
    r"fire department\s*-?\s*final inspection|"
    r"fire department final inspection|"
    r"permit final"
    r")$"
)

_ANY_FINAL_RE = re.compile(r"(?i)\bfinal\b")


def _normalize_status_key(raw) -> str:
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return ""
    return str(raw).strip().upper()


def _lookup_status(raw: str) -> Optional[str]:
    if not raw:
        return None
    if raw in _STATUS_MAP:
        return _STATUS_MAP[raw]
    if "REJECT" in raw or "CANCEL" in raw or raw.startswith("VOID"):
        return "Inactive"
    if "EXPIRE" in raw:
        return "Inactive"
    if "WITHDRAW" in raw or "SUSPEND" in raw:
        return "Inactive"
    if raw.startswith("CLOSED") or raw.startswith("FINAL") or raw == "COMPLETED":
        return "Final"
    if raw.startswith("ISSUED") or raw.startswith("APPROV") or raw == "ACTIVE":
        return "Active"
    if (
        "PENDING" in raw
        or "REVIEW" in raw
        or "CREATED" in raw
        or "CORRECTION" in raw
        or "AWAITING" in raw
        or "READY TO ISSUE" in raw
    ):
        return "In Review"
    return None


def _derive_status(d: dict) -> Optional[str]:
    details = _details(d)
    raw = _normalize_status_key(details.get("Status"))
    return _lookup_status(raw)


def _result_ok(result: str) -> bool:
    result_u = result.strip().upper()
    if result_u in _FINAL_INSP_OK:
        return True
    if result_u.startswith("PASS"):
        return True
    return False


def _case_inspections(d: dict) -> list:
    inner = _inner(d)
    insp = inner.get("Inspections")
    if not isinstance(insp, dict):
        return []
    cases = insp.get("Case Inspections")
    return cases if isinstance(cases, list) else []


def _final_from_inspections(d: dict):
    """Latest completion date from a passed / conditional final inspection.

    Prefers permit-level finals (Final Building, bare Final, Planning /
    Fire Department Final). Falls back to any inspection whose type
    contains ``Final`` (e.g. Final Electrical) when no preferred final
    exists — common for trade-only / solar permits.
    """
    preferred = []
    fallback = []
    for item in _case_inspections(d):
        if not isinstance(item, dict):
            continue
        typ = str(item.get("Inspection Type") or "").strip()
        req = str(item.get("Request Type") or "").strip()
        if not _ANY_FINAL_RE.search(typ):
            continue
        if not _result_ok(req):
            continue
        completed = _safe_to_datetime(
            item.get("Date Called In") or item.get("Requested Date")
        )
        if completed is pd.NaT:
            continue
        if _PREFERRED_FINAL_RE.match(typ):
            preferred.append(completed)
        else:
            fallback.append(completed)
    pool = preferred or fallback
    return max(pool) if pool else pd.NaT


def _preferred_permit_date(d: dict):
    details = _details(d)
    return _safe_to_datetime(details.get("Issued date"))


def _preferred_file_date(d: dict):
    """Goleta DATA has no Applied / Submitted / Filed date field."""
    return pd.NaT


def _preferred_final_date(d: dict):
    return _final_from_inspections(d)


# ── Per-record repair logic ─────────────────────────────────────────────────

def _repair_record(row, d: dict, repairs: dict):
    """Populate *repairs* with corrected values for a single record."""
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

    effective_status = repairs.get("STATUS_NORMALIZED", current_status)

    # -- FILE_DATE --
    # No Applied/Filed field in Goleta DATA; leave as-is (all missing).
    applied = _preferred_file_date(d)
    if applied is not pd.NaT:
        if pd.isna(row["FILE_DATE"]):
            repairs["FILE_DATE"] = applied
            repairs["FILE_DATE_FLAG"] = "FILLED"
        elif not _dates_equal(row["FILE_DATE"], applied):
            repairs["FILE_DATE"] = applied
            repairs["FILE_DATE_FLAG"] = "FIXED"

    # -- PERMIT_DATE (Issued date) --
    issued = _preferred_permit_date(d)

    if not pd.isna(row["PERMIT_DATE"]):
        if issued is not pd.NaT and not _dates_equal(row["PERMIT_DATE"], issued):
            repairs["PERMIT_DATE"] = issued
            repairs["PERMIT_DATE_FLAG"] = "FIXED"
    elif effective_status in ("Active", "Final") and issued is not pd.NaT:
        repairs["PERMIT_DATE"] = issued
        repairs["PERMIT_DATE_FLAG"] = "FILLED"

    # -- FINAL_DATE --
    preferred_final = _preferred_final_date(d)
    current_final = row["FINAL_DATE"]

    if effective_status == "Final":
        if preferred_final is not pd.NaT:
            if pd.isna(current_final):
                repairs["FINAL_DATE"] = preferred_final
                repairs["FINAL_DATE_FLAG"] = "FILLED"
            elif not _dates_equal(current_final, preferred_final):
                repairs["FINAL_DATE"] = preferred_final
                repairs["FINAL_DATE_FLAG"] = "FIXED"
        elif not pd.isna(current_final):
            # Existing FINAL_DATE with no inspection support: check whether
            # it is actually Expiration Date mislabeled.
            details = _details(d)
            expir = _safe_to_datetime(details.get("Expiration Date"))
            if expir is not pd.NaT and _dates_equal(current_final, expir):
                repairs["FINAL_DATE"] = pd.NaT
                repairs["FINAL_DATE_FLAG"] = "FIXED"
    elif not pd.isna(current_final):
        # Spurious FINAL_DATE on non-Final (observed: Expiration Date
        # copied onto Permits Cases Issued/Created rows).
        repairs["FINAL_DATE"] = pd.NaT
        repairs["FINAL_DATE_FLAG"] = "FIXED"


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Goleta permit records using information from the raw DATA JSON.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Goleta".  Must contain
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
    city = df[(df["JURISDICTION"] == "Goleta") & (df["STATE"] == "CA")].copy()

    print(f"Goleta records: {len(city):,}\n")

    repaired = data_repair(city)

    if AGENT_DATA_PATH:
        out_dir = Path(AGENT_DATA_PATH) / "repaired"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "permits_ca_goleta_repaired.parquet"
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

    print("\nSTATUS_NORMALIZED_FLAG breakdown:")
    print(repaired["STATUS_NORMALIZED_FLAG"].value_counts(dropna=False).to_string())

    print("\nSTATUS transitions (where flagged):")
    flagged = repaired[repaired["STATUS_NORMALIZED_FLAG"].notna()].copy()
    flagged["before"] = city.loc[flagged.index, "STATUS_NORMALIZED"]
    print(
        flagged.groupby(
            [flagged["before"].fillna("(null)"), "STATUS_NORMALIZED", "STATUS_NORMALIZED_FLAG"]
        )
        .size()
        .rename("n")
        .reset_index()
        .to_string(index=False)
    )

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
    print(f"  {n_has:>4,} / {len(repaired):>4,} ({n_has / len(repaired):.1%})")

    # Chronology sanity
    print("\nChronology checks (after repair):")
    f = pd.to_datetime(repaired["FILE_DATE"], errors="coerce")
    p = pd.to_datetime(repaired["PERMIT_DATE"], errors="coerce")
    fin = pd.to_datetime(repaired["FINAL_DATE"], errors="coerce")
    inv_fp = f.notna() & p.notna() & (p.dt.normalize() < f.dt.normalize())
    inv_pf = p.notna() & fin.notna() & (fin.dt.normalize() < p.dt.normalize())
    print(f"  PERMIT < FILE: {inv_fp.sum()}")
    print(f"  FINAL < PERMIT: {inv_pf.sum()}")

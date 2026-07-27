"""Data repair for Folsom (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Folsom DATA is a civic portal payload with a single top-level key set:
``fees``, ``contacts``, ``site_info``, ``inspections``, ``permit_info``,
``search_data``. Canonical fields live under ``permit_info`` (with
``search_data`` mirroring Application / Issued):

  - PermitStatus                              → STATUS_NORMALIZED
  - PermitAppliedDate                         → FILE_DATE
  - PermitIssuedDate (fallback: Approved)     → PERMIT_DATE
  - PermitFinaledDate (fallback: FINAL PASS)  → FINAL_DATE

Content variants (same keys; differ by which dates are populated):

  - permit_info_issued_finaled: Applied + Issued + Finaled
  - permit_info_issued:         Applied + Issued, no Finaled
  - permit_info_approved:       Applied + Approved, no Issued
  - permit_info_applied_only:   Applied only (no Issued / Approved / Finaled)
  - permit_info:                other permit_info date combinations
  - unknown / missing

Known issues repaired:
  - Stale STATUS_ORIGINAL (issued / approved / in review) behind a newer
    PermitStatus (FINALED / ISSUED), plus ISSUED / APPROVED rows that
    already carry PermitFinaledDate → FIXED to Final / Active.
  - Active / Final rows missing PERMIT_DATE despite Issued or Approved
    → FILLED (Issued preferred).
  - Final rows missing FINAL_DATE with no PermitFinaledDate but a PASS
    inspection whose Type contains FINAL → FILLED from latest Completed.
  - Spurious FINAL_DATE on Active ISSUED and Inactive CANCELLED rows
    → cleared (CANCELLED keeps Inactive even when Finaled is populated).

Not repairable / left as-is:
  - FILE_DATE already matches PermitAppliedDate for all sample rows.
  - ~80 Active APPROVED / ISSUED shells and ~16 Final FINALED shells have
    neither Issued nor Approved → PERMIT_DATE stays missing.
  - ~108 Final FINALED / BUILDING FINAL / CLOSED rows have blank
    PermitFinaledDate and no FINAL PASS inspection → FINAL_DATE stays
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


def _permit_info(d: dict) -> dict:
    pi = d.get("permit_info")
    return pi if isinstance(pi, dict) else {}


def _search_data(d: dict) -> dict:
    sd = d.get("search_data")
    return sd if isinstance(sd, dict) else {}


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())
    if "permit_info" not in keys:
        return "unknown"
    pi = _permit_info(data_dict)
    if not pi:
        return "permit_info_empty"

    applied = _safe_to_datetime(pi.get("PermitAppliedDate"))
    issued = _safe_to_datetime(pi.get("PermitIssuedDate"))
    approved = _safe_to_datetime(pi.get("PermitApprovedDate"))
    finaled = _safe_to_datetime(pi.get("PermitFinaledDate"))

    has_applied = applied is not pd.NaT
    has_issued = issued is not pd.NaT
    has_approved = approved is not pd.NaT
    has_finaled = finaled is not pd.NaT

    if has_applied and has_issued and has_finaled:
        return "permit_info_issued_finaled"
    if has_applied and has_issued and not has_finaled:
        return "permit_info_issued"
    if has_applied and not has_issued and has_approved and not has_finaled:
        return "permit_info_approved"
    if has_applied and not has_issued and not has_approved and not has_finaled:
        return "permit_info_applied_only"
    return "permit_info"


# ── Status mapping ──────────────────────────────────────────────────────────

# PermitStatus (case-insensitive) → STATUS_NORMALIZED
_STATUS_MAP = {
    # Final
    "finaled": "Final",
    "building final": "Final",
    "closed": "Final",
    "certificate issued": "Final",
    # Active
    "issued": "Active",
    "approved": "Active",
    # In Review
    "paid": "In Review",
    "initial submittal": "In Review",
    "in review": "In Review",
    "projectdox": "In Review",
    "plan check": "In Review",
    "incomplete": "In Review",
    "ready to issue": "In Review",
    "outstanding items": "In Review",
    "hold": "In Review",
    "initial fees due": "In Review",
    "staff review": "In Review",
    # Inactive
    "expired": "Inactive",
    "cancelled": "Inactive",
    "expired application": "Inactive",
    "withdrawn": "Inactive",
}

# Statuses that must not be upgraded to Final solely because Finaled is set
# (CANCELLED often stores a close-out date in PermitFinaledDate).
_INACTIVE_RAW = {
    "expired",
    "cancelled",
    "expired application",
    "withdrawn",
}

_PASS_RESULTS = {
    "PASS",
    "PASS WITH EXCEPTIONS",
}


def _raw_status(d: dict) -> Optional[str]:
    status = _permit_info(d).get("PermitStatus")
    if status is None:
        return None
    status = str(status).strip().lower()
    return status or None


def _pi_date(d: dict, *keys: str):
    pi = _permit_info(d)
    for key in keys:
        dt = _safe_to_datetime(pi.get(key))
        if dt is not pd.NaT:
            return dt
    return pd.NaT


def _sd_date(d: dict, *keys: str):
    sd = _search_data(d)
    for key in keys:
        dt = _safe_to_datetime(sd.get(key))
        if dt is not pd.NaT:
            return dt
    return pd.NaT


def _final_from_inspections(d: dict):
    """Latest Completed date among PASS inspections with FINAL in Type."""
    best = pd.NaT
    for insp in d.get("inspections") or []:
        if not isinstance(insp, dict):
            continue
        typ = str(insp.get("Type", "")).upper()
        res = str(insp.get("Result", "")).upper().strip()
        if "FINAL" not in typ or res not in _PASS_RESULTS:
            continue
        completed = _safe_to_datetime(insp.get("Completed"))
        if completed is pd.NaT:
            continue
        if best is pd.NaT or completed > best:
            best = completed
    return best


def _expected_status(d: dict) -> Optional[str]:
    raw = _raw_status(d)
    expected = _STATUS_MAP.get(raw) if raw else None

    # PermitFinaledDate is a strong Final signal when PermitStatus lags
    # (e.g. still ISSUED / APPROVED after finaling). Do not upgrade
    # cancelled / expired / withdrawn close-outs.
    finaled = _pi_date(d, "PermitFinaledDate")
    if finaled is not pd.NaT and raw not in _INACTIVE_RAW:
        expected = "Final"

    return expected


# ── Per-record repair logic ─────────────────────────────────────────────────

def _repair_record(row, d: dict, repairs: dict):
    """Populate *repairs* with corrected values for a single Folsom record."""
    current_status = row["STATUS_NORMALIZED"]
    expected = _expected_status(d)

    # -- STATUS_NORMALIZED --
    if expected is not None:
        if pd.isna(current_status):
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"
        elif current_status != expected:
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FIXED"

    effective_status = repairs.get("STATUS_NORMALIZED", current_status)

    # -- FILE_DATE (application / PermitAppliedDate) --
    applied = _pi_date(d, "PermitAppliedDate")
    if applied is pd.NaT:
        applied = _sd_date(d, "Application")
    if applied is not pd.NaT:
        if pd.isna(row["FILE_DATE"]):
            repairs["FILE_DATE"] = applied
            repairs["FILE_DATE_FLAG"] = "FILLED"
        elif not _dates_equal(row["FILE_DATE"], applied):
            repairs["FILE_DATE"] = applied
            repairs["FILE_DATE_FLAG"] = "FIXED"

    # -- PERMIT_DATE (issuance / Issued; fallback Approved / SD Issued) --
    issued = _pi_date(d, "PermitIssuedDate")
    if issued is pd.NaT:
        issued = _sd_date(d, "Issued")
    approved = _pi_date(d, "PermitApprovedDate")
    permit_src = issued if issued is not pd.NaT else approved

    if not pd.isna(row["PERMIT_DATE"]):
        if issued is not pd.NaT and not _dates_equal(row["PERMIT_DATE"], issued):
            repairs["PERMIT_DATE"] = issued
            repairs["PERMIT_DATE_FLAG"] = "FIXED"
        elif (
            issued is pd.NaT
            and approved is not pd.NaT
            and not _dates_equal(row["PERMIT_DATE"], approved)
        ):
            repairs["PERMIT_DATE"] = approved
            repairs["PERMIT_DATE_FLAG"] = "FIXED"
    elif effective_status in ("Active", "Final") and permit_src is not pd.NaT:
        repairs["PERMIT_DATE"] = permit_src
        repairs["PERMIT_DATE_FLAG"] = "FILLED"

    # -- FINAL_DATE (finaled; fallback FINAL PASS inspection) --
    finaled = _pi_date(d, "PermitFinaledDate")
    final = finaled
    if final is pd.NaT:
        final = _final_from_inspections(d)
    current_final = row["FINAL_DATE"]

    if effective_status == "Final":
        if final is not pd.NaT:
            if pd.isna(current_final):
                repairs["FINAL_DATE"] = final
                repairs["FINAL_DATE_FLAG"] = "FILLED"
            elif not _dates_equal(current_final, final):
                # Prefer PermitFinaledDate over an inspection-derived value.
                if finaled is not pd.NaT and not _dates_equal(
                    current_final, finaled
                ):
                    repairs["FINAL_DATE"] = finaled
                    repairs["FINAL_DATE_FLAG"] = "FIXED"
                elif finaled is pd.NaT and not _dates_equal(current_final, final):
                    repairs["FINAL_DATE"] = final
                    repairs["FINAL_DATE_FLAG"] = "FIXED"
    elif not pd.isna(current_final):
        repairs["FINAL_DATE"] = pd.NaT
        repairs["FINAL_DATE_FLAG"] = "FIXED"


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Folsom permit records using information from the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Folsom".  Must contain
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
    from dotenv import load_dotenv

    load_dotenv("/Users/ekung/projects/la-permits-data/.env")
    MY_DATA_PATH = os.getenv("MY_DATA_PATH")
    AGENT_DATA_PATH = os.getenv("AGENT_DATA_PATH")
    filepath = os.path.join(
        MY_DATA_PATH, "processed_data", "permits_ca_sample.parquet"
    )
    df = pd.read_parquet(filepath)
    city = df[
        (df["JURISDICTION"] == "Folsom") & (df["STATE"] == "CA")
    ].copy()

    print(f"Folsom records: {len(city):,}\n")

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

    print("\nSTATUS_NORMALIZED changes:")
    changed = city["STATUS_NORMALIZED"].astype(str) != repaired[
        "STATUS_NORMALIZED"
    ].astype(str)
    if changed.any():
        ct = (
            pd.DataFrame(
                {
                    "before": city.loc[changed, "STATUS_NORMALIZED"],
                    "after": repaired.loc[changed, "STATUS_NORMALIZED"],
                }
            )
            .value_counts()
            .reset_index(name="n")
        )
        print(ct.to_string(index=False))
    else:
        print("  (none)")

    print("\nPERMIT_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["PERMIT_DATE"].notna().sum()
        pct = n_has / len(sub) if len(sub) else 0.0
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({pct:.1%})")

    print("\nFINAL_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FINAL_DATE"].notna().sum()
        pct = n_has / len(sub) if len(sub) else 0.0
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({pct:.1%})")

    if AGENT_DATA_PATH:
        out_path = os.path.join(
            AGENT_DATA_PATH, "folsom_repaired_sample.parquet"
        )
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote {out_path}")

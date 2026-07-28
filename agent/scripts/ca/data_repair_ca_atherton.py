"""Data repair for Atherton (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Atherton DATA is a civic portal payload. All sample rows share the same
top-level keys: ``fees``, ``contacts``, ``site_info``, ``inspections``,
``permit_info``, ``search_data``. Canonical fields live under
``permit_info`` (with ``search_data`` mirroring APPLIED / ISSUED /
FINALED on most rows):

  - PermitStatus                          → STATUS_NORMALIZED
  - PermitAppliedDate                     → FILE_DATE
  - PermitIssuedDate (fallback:
    search_data.ISSUED / PermitApprovedDate) → PERMIT_DATE
  - PermitFinaledDate (fallback: latest
    passed FINAL inspection)              → FINAL_DATE

Content variants (same keys; differ by which fields are populated):

  - permit_info_issued_finaled: Issued + Finaled present
  - permit_info_issued:         Issued present, Finaled blank
  - permit_info_finaled_only:   Finaled present, Issued blank
  - permit_info_approved_only:  Approved present, Issued/Finaled blank
  - permit_info_applied_only:   only Applied populated
  - legacy_no_status:           blank PermitStatus but dates present
  - permit_info_empty_dates:    status/desc text, no usable dates

Known issues repaired:
  - 101 blank PermitStatus CONVERTED shells left STATUS_NORMALIZED null;
    rows with Issued → FILLED Active (77).
  - APPROVED-STAFF was mapped to In Review; treat as Active (APPROV*) →
    FIXED.
  - Active/Final missing PERMIT_DATE when Issued blank but Approved
    present → FILLED from Approved.
  - Final missing FINAL_DATE with a passed FINAL inspection but blank
    PermitFinaledDate → FILLED from inspection.
  - Spurious FINAL_DATE on non-Final rows → cleared (FIXED).

Not repairable / left as-is:
  - FILE_DATE already matches PermitAppliedDate wherever Applied exists;
    326 rows lack Applied in both permit_info and search_data.
  - ~156 Final rows (mostly legacy F / FINALED CONVERTED) lack
    PermitFinaledDate and usable final inspections.
  - 24 blank-status shells with no dates stay STATUS_NORMALIZED missing.
  - Active/Final rows with neither Issued nor Approved → PERMIT_DATE
    stays missing.
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
    if da is pd.NaT or db is pd.NaT or pd.isna(da) or pd.isna(db):
        return False
    return da.normalize() == db.normalize()


def _permit_info(d: dict) -> dict:
    pi = d.get("permit_info")
    return pi if isinstance(pi, dict) else {}


def _search_data(d: dict) -> dict:
    sd = d.get("search_data")
    return sd if isinstance(sd, dict) else {}


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


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())
    if "permit_info" not in keys:
        return "unknown"
    pi = _permit_info(data_dict)
    if not pi:
        return "permit_info_empty"

    raw_status = _normalize_status_key(pi.get("PermitStatus"))
    issued = _safe_to_datetime(pi.get("PermitIssuedDate"))
    finaled = _safe_to_datetime(pi.get("PermitFinaledDate"))
    approved = _safe_to_datetime(pi.get("PermitApprovedDate"))
    applied = _safe_to_datetime(pi.get("PermitAppliedDate"))

    has_issued = issued is not pd.NaT
    has_finaled = finaled is not pd.NaT
    has_approved = approved is not pd.NaT
    has_applied = applied is not pd.NaT
    has_any_date = has_issued or has_finaled or has_approved or has_applied

    if not raw_status and has_any_date:
        return "legacy_no_status"
    if not raw_status and not has_any_date:
        if not any(str(pi.get(k) or "").strip() for k in pi):
            return "permit_info_empty"
        return "permit_info_empty_dates"

    if has_issued and has_finaled:
        return "permit_info_issued_finaled"
    if has_issued:
        return "permit_info_issued"
    if has_finaled:
        return "permit_info_finaled_only"
    if has_approved:
        return "permit_info_approved_only"
    if has_applied:
        return "permit_info_applied_only"
    return "permit_info_empty_dates"


# ── Status mapping ──────────────────────────────────────────────────────────

# PermitStatus (uppercased) → STATUS_NORMALIZED
_STATUS_MAP = {
    "F": "Final",
    "FINALED": "Final",
    "FINAL": "Final",
    "ARCHIVE": "Final",
    "HISTORIC RECORD": "Final",
    "ISSUED": "Active",
    "APPROVED": "Active",
    "APPROVED-STAFF": "Active",
    "S": "Active",
    "IN QUEUE": "In Review",
    "UNDER REVIEW": "In Review",
    "A": "In Review",
    "I": "In Review",
    "PARTIAL APPROVAL": "In Review",
    "PENDING": "In Review",
    "X": "Inactive",
    "EXPIRED": "Inactive",
    "EXPIRED PERMIT": "Inactive",
    "EXPIRED APPLICATION": "Inactive",
    "WITHDRAWN": "Inactive",
    "VOID": "Inactive",
    "DENIED-STAFF": "Inactive",
    "V": "Inactive",
    "E": "Inactive",
    "C": "Inactive",
}

# Terminal inactive labels: PermitFinaledDate on these is a close/void
# timestamp, not evidence the permit should be treated as Final.
_INACTIVE_KEEP = {
    "X",
    "EXPIRED",
    "EXPIRED PERMIT",
    "EXPIRED APPLICATION",
    "WITHDRAWN",
    "VOID",
    "DENIED-STAFF",
    "V",
    "E",
    "C",
}

_FINAL_INSP_OK = {
    "",
    "PASS",
    "PASSED",
    "APPROVED",
    "COMPLETED",
    "COMPLETE",
}

_FINAL_TITLE_RE = re.compile(
    r"(?i)("
    r"final\s*inspection|permit\s*final|building\s*final|"
    r"final\s*building|final\s*bldg|\*\*final\b|^final\b|"
    r"c\s*of\s*o|certificate\s*of\s*occupancy"
    r")"
)


def _normalize_status_key(raw) -> str:
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return ""
    return str(raw).strip().upper()


def _derive_status(d: dict) -> Optional[str]:
    """Map PermitStatus; prefer Final when a non-inactive row is finaled.

    Legacy rows with a blank PermitStatus but populated dates are inferred
    from Finaled → Issued/Approved → Applied.
    """
    pi = _permit_info(d)
    raw = _normalize_status_key(pi.get("PermitStatus"))

    status = _STATUS_MAP.get(raw) if raw else None

    if raw in _INACTIVE_KEEP:
        return status or "Inactive"

    finaled = _pi_date(d, "PermitFinaledDate")
    if finaled is not pd.NaT:
        return "Final"

    if status is not None:
        return status

    if raw:
        if "FINAL" in raw or raw in {"CLOSED", "ARCHIVE"} or "HISTORIC" in raw:
            return "Final"
        if (
            "EXPIRE" in raw
            or "VOID" in raw
            or "CANCEL" in raw
            or "WITHDRAW" in raw
            or "DENIED" in raw
        ):
            return "Inactive"
        if "ISSUE" in raw or "APPROV" in raw:
            return "Active"
        if (
            "REVIEW" in raw
            or "QUEUE" in raw
            or "PENDING" in raw
            or "PARTIAL" in raw
        ):
            return "In Review"
        return None

    # Blank status: infer from dates (legacy Atherton CONVERTED shells).
    issued = _pi_date(d, "PermitIssuedDate")
    if issued is pd.NaT:
        issued = _sd_date(d, "ISSUED")
    approved = _pi_date(d, "PermitApprovedDate")
    applied = _pi_date(d, "PermitAppliedDate")
    if applied is pd.NaT:
        applied = _sd_date(d, "APPLIED")

    if issued is not pd.NaT or approved is not pd.NaT:
        return "Active"
    if applied is not pd.NaT:
        return "In Review"
    return None


def _final_from_inspections(d: dict):
    """Latest completion date from a passed FINAL inspection.

    Atherton inspections are list-of-lists:
      [type, result, scheduled?, time?, completed?, ..., "More Info"]
    """
    inspections = d.get("inspections")
    if not isinstance(inspections, list):
        return pd.NaT
    dates = []
    for item in inspections:
        if isinstance(item, dict):
            text = str(item.get("Type") or item.get("Title") or "")
            if not _FINAL_TITLE_RE.search(text.strip()):
                continue
            result = str(item.get("Result") or "").strip().upper()
            if result not in _FINAL_INSP_OK:
                continue
            completed = _safe_to_datetime(
                item.get("Completed") or item.get("CompletedDate")
            )
            if completed is not pd.NaT:
                dates.append(completed)
            continue

        if not isinstance(item, (list, tuple)) or len(item) < 3:
            continue
        text = str(item[0] or "")
        if not _FINAL_TITLE_RE.search(text.strip()):
            continue
        result = str(item[1] or "").strip().upper()
        if result not in _FINAL_INSP_OK:
            continue
        completed = _safe_to_datetime(item[2])
        if completed is pd.NaT and len(item) > 4:
            completed = _safe_to_datetime(item[4])
        if completed is not pd.NaT:
            dates.append(completed)
    return max(dates) if dates else pd.NaT


def _preferred_final_date(d: dict):
    finaled = _pi_date(d, "PermitFinaledDate")
    if finaled is not pd.NaT:
        return finaled
    return _final_from_inspections(d)


def _preferred_permit_date(d: dict):
    issued = _pi_date(d, "PermitIssuedDate")
    if issued is pd.NaT:
        issued = _sd_date(d, "ISSUED")
    if issued is not pd.NaT:
        return issued
    approved = _pi_date(d, "PermitApprovedDate")
    if approved is pd.NaT:
        approved = _sd_date(d, "APPROVED", "Approved Date")
    return approved


def _preferred_file_date(d: dict):
    applied = _pi_date(d, "PermitAppliedDate")
    if applied is not pd.NaT:
        return applied
    return _sd_date(d, "APPLIED", "Applied Date")


# ── Per-record repair logic ─────────────────────────────────────────────────

def _repair_record(row, d: dict, repairs: dict):
    """Populate *repairs* with corrected values for a single Atherton record."""
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

    # -- FILE_DATE (application / PermitAppliedDate) --
    applied = _preferred_file_date(d)
    if applied is not pd.NaT:
        if pd.isna(row["FILE_DATE"]):
            repairs["FILE_DATE"] = applied
            repairs["FILE_DATE_FLAG"] = "FILLED"
        elif not _dates_equal(row["FILE_DATE"], applied):
            repairs["FILE_DATE"] = applied
            repairs["FILE_DATE_FLAG"] = "FIXED"

    # -- PERMIT_DATE (issuance; fallback Approved) --
    issued = _pi_date(d, "PermitIssuedDate")
    if issued is pd.NaT:
        issued = _sd_date(d, "ISSUED")
    permit_src = _preferred_permit_date(d)

    if not pd.isna(row["PERMIT_DATE"]):
        if issued is not pd.NaT and not _dates_equal(row["PERMIT_DATE"], issued):
            repairs["PERMIT_DATE"] = issued
            repairs["PERMIT_DATE_FLAG"] = "FIXED"
        elif (
            issued is pd.NaT
            and permit_src is not pd.NaT
            and not _dates_equal(row["PERMIT_DATE"], permit_src)
        ):
            repairs["PERMIT_DATE"] = permit_src
            repairs["PERMIT_DATE_FLAG"] = "FIXED"
    elif effective_status in ("Active", "Final") and permit_src is not pd.NaT:
        repairs["PERMIT_DATE"] = permit_src
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
        # Spurious FINAL_DATE on non-Final rows.
        repairs["FINAL_DATE"] = pd.NaT
        repairs["FINAL_DATE_FLAG"] = "FIXED"


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Atherton permit records using information from the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Atherton".  Must contain
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
    filepath = os.path.join(MY_DATA_PATH, "processed_data", "permits_ca_sample.parquet")
    df = pd.read_parquet(filepath)
    city = df[(df["JURISDICTION"] == "Atherton") & (df["STATE"] == "CA")].copy()

    print(f"Atherton records: {len(city):,}\n")

    repaired = data_repair(city)

    if AGENT_DATA_PATH:
        out_path = os.path.join(AGENT_DATA_PATH, "atherton_repaired_sample.parquet")
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

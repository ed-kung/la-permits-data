"""Data repair for San Bruno (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

San Bruno DATA is a civic portal payload with top-level keys
``address``, ``permit_no``, ``permit_info``, ``inspections``, plus
parcel / lot metadata. A small minority also carry ``state`` /
``zip_code``. Canonical fields live under ``permit_info``:

  - PermitStatus                         → STATUS_NORMALIZED
  - PermitAppliedDate                    → FILE_DATE
  - PermitIssuedDate (fallback
    PermitApprovedDate)                  → PERMIT_DATE
  - PermitFinaledDate (always blank in
    sample; fallback: latest passed
    final inspection)                    → FINAL_DATE

Content variants (INFERRED_SCHEMA):

  - permit_info_issued_final_insp: Issued + passed final inspection
  - permit_info_issued:            Issued present, no final insp date
  - permit_info_approved_only:     Approved present, Issued blank
  - permit_info_applied_only:      only Applied populated
  - permit_info_empty_dates:       status present, no usable dates
  - legacy_no_status:              blank PermitStatus with dates
  - permit_info_empty:             empty / missing permit_info
  - with_geo_*:                    same variants when state/zip present

Known issues repaired:
  - Null STATUS_NORMALIZED on ADMIN.CLOSE (79) and legacy blank
    PermitStatus shells (mostly pre-2005 ISSUED-equivalent) → FILLED.
  - Pre-issuance labels (ROUTED, PLAN CHECK) that already carry
    PermitIssuedDate → FIXED to Active.
  - FINALED` typo already maps to Final via FINAL* heuristic (kept).
  - Active/Final missing PERMIT_DATE when Issued or Approved present
    → FILLED (common when Issued blank but Approved populated).
  - Final missing FINAL_DATE when a passed final inspection exists
    → FILLED (PermitFinaledDate is null for every sample row).

Not repairable / left as-is:
  - 20 shells with blank PermitAppliedDate (mostly VOID / empty
    permit_info) → FILE_DATE stays missing.
  - Active/Final shells with neither Issued nor Approved → PERMIT_DATE
    stays missing.
  - FINALED shells with neither PermitFinaledDate nor a usable final
    inspection (~half of Final rows; older records often lack
    inspections) → FINAL_DATE stays missing.
  - Empty permit_info shells with no dates (2) → STATUS_NORMALIZED
    stays missing.
  - ADMIN.CLOSE / EXPIRED / VOID / WITHDRAWN stay Inactive even when
    a passed final inspection exists (administrative close, not a
    permit finaled date).
  - OH_SNAP! (2) is an unmapped agency label; status is inferred from
    Issued/Approved dates → Active.
"""

from __future__ import annotations

import json
import math
import re
from typing import Optional

import numpy as np
import pandas as pd


_MIN_YEAR = 1950
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
    """Parse a date value, returning pd.NaT on failure or sentinel year."""
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
    year = getattr(dt, "year", None)
    if year is not None and (year < _MIN_YEAR or year > _MAX_YEAR):
        return pd.NaT
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


def _pi_date(d: dict, *keys: str):
    pi = _permit_info(d)
    for key in keys:
        dt = _safe_to_datetime(pi.get(key))
        if dt is not pd.NaT:
            return dt
    return pd.NaT


def _has_geo(d: dict) -> bool:
    return "zip_code" in d or "state" in d


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())
    if "permit_info" not in keys:
        return "unknown"

    pi = _permit_info(data_dict)
    prefix = "with_geo_" if _has_geo(data_dict) else ""

    if not pi:
        return f"{prefix}permit_info_empty" if prefix else "permit_info_empty"

    raw_status = _raw_status(data_dict)
    issued = _safe_to_datetime(pi.get("PermitIssuedDate"))
    approved = _safe_to_datetime(pi.get("PermitApprovedDate"))
    applied = _safe_to_datetime(pi.get("PermitAppliedDate"))
    finaled = _safe_to_datetime(pi.get("PermitFinaledDate"))
    final_insp = _final_from_inspections(data_dict)

    has_issued = issued is not pd.NaT
    has_approved = approved is not pd.NaT
    has_applied = applied is not pd.NaT
    has_finaled = finaled is not pd.NaT
    has_final_insp = final_insp is not pd.NaT

    if not raw_status:
        if has_issued or has_approved or has_applied or has_finaled:
            return f"{prefix}legacy_no_status"
        return f"{prefix}permit_info_empty_dates"

    if has_issued and (has_finaled or has_final_insp):
        return f"{prefix}permit_info_issued_final_insp"
    if has_issued:
        return f"{prefix}permit_info_issued"
    if has_finaled or has_final_insp:
        return f"{prefix}permit_info_final_insp_only"
    if has_approved:
        return f"{prefix}permit_info_approved_only"
    if has_applied:
        return f"{prefix}permit_info_applied_only"
    return f"{prefix}permit_info_empty_dates"


# ── Status mapping ──────────────────────────────────────────────────────────

# PermitStatus (uppercased) → STATUS_NORMALIZED
_STATUS_MAP = {
    # Final
    "FINALED": "Final",
    "FINAL": "Final",
    "COMPLETE": "Final",
    "CLOSED": "Final",
    # Active
    "ISSUED": "Active",
    "APPROVED": "Active",
    "ACTIVE": "Active",
    # In Review
    "ROUTED": "In Review",
    "PLAN CHECK": "In Review",
    "SUBMITTED": "In Review",
    "READY TO ISSUE": "In Review",
    "IN REVIEW": "In Review",
    "UNDER REVIEW": "In Review",
    # Inactive
    "EXPIRED": "Inactive",
    "VOID": "Inactive",
    "WITHDRAWN": "Inactive",
    "CANCELLED": "Inactive",
    "CANCELED": "Inactive",
    "ADMIN.CLOSE": "Inactive",
    "ADMIN CLOSE": "Inactive",
    "DENIED": "Inactive",
}

# Terminal inactive labels — do not promote to Final on inspection evidence.
_INACTIVE_KEEP = {
    "EXPIRED",
    "VOID",
    "WITHDRAWN",
    "CANCELLED",
    "CANCELED",
    "ADMIN.CLOSE",
    "ADMIN CLOSE",
    "DENIED",
}

_FINAL_INSP_OK = {
    "",
    "PASS",
    "PASSED",
    "PASS WITH COMMENTS",
    "PASS(PARTIAL)",
    "APPROVED",
    "FINAL",
    "FINALED",
    "FIN",
    "COMPLETED",
    "COMPLETE",
    "OK",
}

_FINAL_TITLE_RE = re.compile(
    r"(?i)("
    r"\*{0,2}\s*final\s*inspection|"
    r"^final\s*$|"
    r"^final\*{0,2}\s*$|"
    r"^final-|"
    r"encroachment\s*final|"
    r"permit\s*final|"
    r"building\s*final|"
    r"final\s*building|"
    r"final\s*bldg|"
    r"final\s*approval|"
    r"smoke\s*detect\s*final|"
    r"window\s*final|"
    r"roof\s*covering\s*final|"
    r"fire\s*sprinkler\s*final|"
    r"fireplace\s*final|"
    r"sewer\s*final|"
    r"structural\s*final|"
    r"\bfinal\s*(sfr|bldg|building|elec|electrical|fire|roof|eh|engineering|"
    r"plumbing|plumb|mechanical|mech|interior|exterior|planning|approval|"
    r"sewer)?\b|"
    r"c\s*of\s*o|certificate\s*of\s*occup"
    r")"
)


def _normalize_status_key(raw) -> str:
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return ""
    s = str(raw).strip().upper()
    # Strip trailing junk punctuation (e.g. FINALED`).
    s = s.rstrip("`'\"").strip()
    if s in {"<NONE>", "NONE", "NULL", "N/A", "UNKNOWN"}:
        return ""
    return s


def _raw_status(d: dict) -> str:
    pi = _permit_info(d)
    return _normalize_status_key(pi.get("PermitStatus"))


def _lookup_status(raw: str) -> Optional[str]:
    """Exact map, then CANCEL / EXPIRE / FINAL / ISSUED / APPROV heuristics."""
    if not raw:
        return None
    if raw in _STATUS_MAP:
        return _STATUS_MAP[raw]
    if "ADMIN" in raw and "CLOSE" in raw:
        return "Inactive"
    if "CANCEL" in raw or raw.startswith("VOID"):
        return "Inactive"
    if "EXPIRE" in raw:
        return "Inactive"
    if "REVOKE" in raw or "WITHDRAW" in raw or "ABANDON" in raw:
        return "Inactive"
    if "DENIED" in raw:
        return "Inactive"
    if raw.startswith("FINAL") or "CERTIFICATE OF OCC" in raw:
        return "Final"
    if raw == "COMPLETE" or raw == "CLOSED":
        return "Final"
    if raw.startswith("ISSUED") or raw == "ACTIVE":
        return "Active"
    if "APPROV" in raw and "PEND" not in raw and "READY TO" not in raw:
        return "Active"
    if (
        "SUBMIT" in raw
        or "REVIEW" in raw
        or "PENDING" in raw
        or "WAITING" in raw
        or "INCOMPLETE" in raw
        or "ON HOLD" in raw
        or raw == "HOLD"
        or "ROUTED" in raw
        or "PLAN CHECK" in raw
        or "READY TO" in raw
        or "FEES" in raw
        or "APPLIED" in raw
    ):
        return "In Review"
    return None


def _is_inactive_keep(raw: str) -> bool:
    if not raw:
        return False
    if raw in _INACTIVE_KEEP:
        return True
    if "ADMIN" in raw and "CLOSE" in raw:
        return True
    if "EXPIRE" in raw or "CANCEL" in raw or raw.startswith("VOID"):
        return True
    if "REVOKE" in raw or "WITHDRAW" in raw or "ABANDON" in raw or "DENIED" in raw:
        return True
    return False


def _preferred_permit_date(d: dict):
    issued = _pi_date(d, "PermitIssuedDate")
    if issued is not pd.NaT:
        return issued
    return _pi_date(d, "PermitApprovedDate")


def _preferred_file_date(d: dict):
    """Application / submittal date from PermitAppliedDate."""
    return _pi_date(d, "PermitAppliedDate")


def _result_ok(result: str) -> bool:
    result_u = result.strip().upper()
    if result_u in _FINAL_INSP_OK:
        return True
    if result_u.startswith("PASS"):
        return True
    if result_u.startswith("APPROVED"):
        return True
    return False


def _inspection_type(item: dict) -> str:
    return str(
        item.get("type")
        or item.get("Type")
        or item.get("Title")
        or item.get("title")
        or ""
    ).strip()


def _inspection_result(item: dict) -> str:
    return str(
        item.get("result")
        or item.get("Result")
        or ""
    ).strip()


def _inspection_completed(item: dict):
    """San Bruno uses the oddly keyed 'Completed Date:' field."""
    for key in (
        "Completed Date:",
        "Completed Date",
        "Completed",
        "CompletedDate",
        "completed_date",
        "completedDate",
    ):
        dt = _safe_to_datetime(item.get(key))
        if dt is not pd.NaT:
            return dt
    return pd.NaT


def _is_final_inspection(item: dict) -> bool:
    typ = _inspection_type(item)
    result = _inspection_result(item)
    result_u = result.upper()

    if result_u in ("FINAL", "FINALED", "FIN"):
        return True

    if _FINAL_TITLE_RE.search(typ) and _result_ok(result):
        return True

    return False


def _final_from_inspections(d: dict):
    """Latest completion date from a passed final / C of O inspection."""
    inspections = d.get("inspections")
    if isinstance(inspections, dict):
        inspections = (
            inspections.get("inspections")
            or inspections.get("Inspections")
            or []
        )
    if not isinstance(inspections, list):
        return pd.NaT
    dates = []
    for item in inspections:
        if not isinstance(item, dict):
            continue
        if not _is_final_inspection(item):
            continue
        completed = _inspection_completed(item)
        if completed is not pd.NaT:
            dates.append(completed)
    return max(dates) if dates else pd.NaT


def _preferred_final_date(d: dict):
    finaled = _pi_date(d, "PermitFinaledDate")
    if finaled is not pd.NaT:
        return finaled
    return _final_from_inspections(d)


def _derive_status(d: dict) -> Optional[str]:
    """Map PermitStatus; promote In Review→Active when Issued is present.

    Blank PermitStatus is inferred from dates (legacy shells). Inactive
    labels are never promoted to Final on inspection evidence alone.
    """
    raw = _raw_status(d)
    status = _lookup_status(raw)

    if _is_inactive_keep(raw):
        return status or "Inactive"

    finaled = _pi_date(d, "PermitFinaledDate")
    if finaled is not pd.NaT:
        return "Final"

    issued_only = _pi_date(d, "PermitIssuedDate")
    if status == "In Review" and issued_only is not pd.NaT:
        return "Active"

    if status is not None:
        return status

    # Blank or unmapped agency label (e.g. OH_SNAP!): infer from dates.
    approved = _pi_date(d, "PermitApprovedDate")
    applied = _preferred_file_date(d)
    issued = _preferred_permit_date(d)

    if finaled is not pd.NaT:
        return "Final"
    if issued is not pd.NaT or approved is not pd.NaT:
        return "Active"
    if applied is not pd.NaT:
        return "In Review"
    return None


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
    San Bruno permit records using information from the raw DATA JSON.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "San Bruno".  Must contain
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

    # Normalize date columns (source sample uses datetime.date objects;
    # repairs insert Timestamps — unify for parquet compatibility).
    for col in ["FILE_DATE", "PERMIT_DATE", "FINAL_DATE"]:
        out[col] = pd.to_datetime(out[col], errors="coerce")

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
    city = df[(df["JURISDICTION"] == "San Bruno") & (df["STATE"] == "CA")].copy()

    print(f"San Bruno records: {len(city):,}\n")

    repaired = data_repair(city)

    if AGENT_DATA_PATH:
        out_dir = Path(AGENT_DATA_PATH) / "repaired"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "permits_ca_san_bruno_repaired.parquet"
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

    print("\nFILE_DATE coverage after repair:")
    n_has = repaired["FILE_DATE"].notna().sum()
    print(f"  {n_has:>4,} / {len(repaired):>4,} ({n_has / len(repaired):.1%})")

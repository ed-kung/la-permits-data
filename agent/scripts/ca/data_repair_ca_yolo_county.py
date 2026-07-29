"""Data repair for Yolo County (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Yolo County DATA is a civic portal payload (same shape as Foster City /
Hanford / Butte County). All sample rows share top-level keys:
``fees``, ``contacts``, ``site_info``, ``inspections``,
``permit_info``, ``search_data``. Canonical fields live under
``permit_info``:

  - PermitStatus                          → STATUS_NORMALIZED
  - PermitAppliedDate                     → FILE_DATE
  - PermitIssuedDate (fallback:
    PermitApprovedDate)                   → PERMIT_DATE
  - PermitFinaledDate (fallback: latest
    passed final inspection)              → FINAL_DATE

Content variants (INFERRED_SCHEMA):

  - permit_info_issued_finaled: Issued + Finaled present
  - permit_info_issued:         Issued present, Finaled blank
  - permit_info_finaled_only:   Finaled present, Issued blank
  - permit_info_approved_only:  Approved present, Issued/Finaled blank
  - permit_info_applied_only:   only Applied populated
  - permit_info_empty_dates:    status text, no usable dates
  - unknown / missing

Known issues repaired:
  - ESTIMATE labeled Final despite no issuance / finaling → FIXED to
    In Review.
  - Non-inactive rows carrying PermitFinaledDate (ISSUED / APPROVED)
    → FIXED to Final.
  - Active / Final missing PERMIT_DATE when Issued blank but Approved
    present (mostly FSA / floodplain APPROVED shells) → FILLED.
  - Final missing FINAL_DATE when PermitFinaledDate blank but a passed
    final inspection exists → FILLED.
  - Spurious FINAL_DATE on remaining non-Final rows (EXPIRED close
    stamp) → cleared.

Not repairable from DATA:
  - One VOID encroachment shell with empty PermitAppliedDate →
    FILE_DATE stays missing.
  - Some Active / Final rows lack both Issued and Approved →
    PERMIT_DATE stays missing.
  - Many FINALED / Yes (finaled) / Historic shells lack
    PermitFinaledDate and a usable finaling inspection → FINAL_DATE
    stays missing.
  - Historic-record Applied dates are often the migration stamp
    (e.g. 2004-05-17) while Issued / Finaled are decades earlier;
    FILE_DATE is left as Applied (canonical source).
"""

from __future__ import annotations

import json
import math
import re
from typing import Optional

import numpy as np
import pandas as pd


# Historic Yolo shells go back to the 1960s.
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
    """Parse a date value, returning pd.NaT on failure or implausible year."""
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return pd.NaT
    if isinstance(val, str) and not val.strip():
        return pd.NaT
    try:
        dt = pd.to_datetime(val, errors="coerce")
    except (ValueError, TypeError):
        return pd.NaT
    if dt is pd.NaT or pd.isna(dt):
        return pd.NaT
    year = int(dt.year)
    if year < _MIN_YEAR or year > _MAX_YEAR:
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


def _pi_date(d: dict, *keys: str):
    pi = _permit_info(d)
    for key in keys:
        dt = _safe_to_datetime(pi.get(key))
        if dt is not pd.NaT:
            return dt
    return pd.NaT


def _normalize_status_key(raw) -> str:
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return ""
    s = str(raw).strip().upper()
    if s in {"<NONE>", "NONE", "NULL", "N/A"}:
        return ""
    return s


# ── Schema classification ───────────────────────────────────────────────────

def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys()) if isinstance(data_dict, dict) else set()
    if "permit_info" not in keys:
        return "unknown"

    pi = _permit_info(data_dict)
    if not pi:
        return "permit_info_empty"

    raw_status = _normalize_status_key(pi.get("PermitStatus"))
    has_issued = _pi_date(data_dict, "PermitIssuedDate") is not pd.NaT
    has_finaled = _pi_date(data_dict, "PermitFinaledDate") is not pd.NaT
    has_approved = _pi_date(data_dict, "PermitApprovedDate") is not pd.NaT
    has_applied = _pi_date(data_dict, "PermitAppliedDate") is not pd.NaT

    if not raw_status:
        if has_issued or has_finaled or has_approved or has_applied:
            return "legacy_no_status"
        return "permit_info_empty"

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
    # Final
    "FINALED": "Final",
    "FINAL": "Final",
    "YES (FINALED)": "Final",
    "CLOSED": "Final",
    "CLOSED FILE (WI": "Final",
    "HISTORIC RECORD": "Final",
    # Active
    "ISSUED": "Active",
    "APPROVED": "Active",
    "ACTIVE": "Active",
    "NEW (ACTIVE)": "Active",
    # In Review
    "UNDER REVIEW": "In Review",
    "PENDING PAYMENT": "In Review",
    "PENDING": "In Review",
    "ESTIMATE": "In Review",
    # Inactive
    "EXPIRED": "Inactive",
    "VOID": "Inactive",
    "CANCELLED": "Inactive",
    "CANCELED": "Inactive",
    "WITHDRAWN": "Inactive",
    "ABANDONED": "Inactive",
    "DENIED": "Inactive",
}

# Terminal inactive labels: PermitFinaledDate on these is a close/void
# stamp, not evidence the permit should be treated as Final.
_INACTIVE_KEEP = {
    "EXPIRED",
    "VOID",
    "CANCELLED",
    "CANCELED",
    "WITHDRAWN",
    "ABANDONED",
    "DENIED",
}

_FINAL_INSP_OK = {
    "",
    "PASS",
    "PASSED",
    "PASS WITH COMMENTS",
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
    r"^final[-\s]|"
    r"permit\s*final|"
    r"building\s*final|"
    r"final\s*building|"
    r"final\s*bldg|"
    r"\bfinal\s*(sfr|bldg|building|elec|electrical|fire|roof|"
    r"plumbing|plumb|mechanical|mech|cal-green|solar|elevation)?\b|"
    r"c\s*of\s*o|certificate\s*of\s*occup"
    r")"
)


def _lookup_status(raw: str) -> Optional[str]:
    """Exact map, then CANCEL / EXPIRE / FINAL / ISSUED / APPROV heuristics."""
    if not raw:
        return None
    if raw in _STATUS_MAP:
        return _STATUS_MAP[raw]
    # Truncated labels like "CLOSED FILE (WI"
    if raw.startswith("CLOSED FILE"):
        return "Final"
    if "CANCEL" in raw or raw.startswith("VOID"):
        return "Inactive"
    if "EXPIRE" in raw:
        return "Inactive"
    if "REVOKE" in raw or "WITHDRAW" in raw or "ABANDON" in raw:
        return "Inactive"
    if "DENIED" in raw:
        return "Inactive"
    if "FINAL" in raw or "CERTOF" in raw or "CERTIFICATE OF OCC" in raw:
        return "Final"
    if "HISTORIC" in raw:
        return "Final"
    if raw.startswith("CLOSE"):
        return "Final"
    if raw.startswith("ISSUED") or "APPROV" in raw or "ACTIVE" in raw:
        return "Active"
    if "ESTIMATE" in raw:
        return "In Review"
    if (
        "SUBMIT" in raw
        or "REVIEW" in raw
        or "PENDING" in raw
        or "WAITING" in raw
        or "INCOMPLETE" in raw
        or "ON HOLD" in raw
        or "RECEIVED" in raw
    ):
        return "In Review"
    return None


def _is_inactive_keep(raw: str) -> bool:
    if not raw:
        return False
    if raw in _INACTIVE_KEEP:
        return True
    if "EXPIRE" in raw or "CANCEL" in raw or raw.startswith("VOID"):
        return True
    if "REVOKE" in raw or "WITHDRAW" in raw or "ABANDON" in raw or "DENIED" in raw:
        return True
    return False


def _derive_status(d: dict) -> Optional[str]:
    """Map PermitStatus; prefer Final when a non-inactive row is finaled."""
    pi = _permit_info(d)
    raw = _normalize_status_key(pi.get("PermitStatus"))

    status = _lookup_status(raw)

    if _is_inactive_keep(raw):
        return status or "Inactive"

    finaled = _pi_date(d, "PermitFinaledDate")
    if finaled is not pd.NaT:
        return "Final"

    if status is not None:
        return status

    if raw:
        return None

    # Blank status: infer from dates.
    issued = _pi_date(d, "PermitIssuedDate")
    approved = _pi_date(d, "PermitApprovedDate")
    applied = _pi_date(d, "PermitAppliedDate")

    if finaled is not pd.NaT:
        return "Final"
    if issued is not pd.NaT or approved is not pd.NaT:
        return "Active"
    if applied is not pd.NaT:
        return "In Review"
    return None


def _result_ok(result: str) -> bool:
    result_u = result.strip().upper()
    if result_u in _FINAL_INSP_OK:
        return True
    if result_u.startswith("PASS"):
        return True
    return False


def _inspection_fields(item) -> Optional[tuple]:
    """Return (title, result, date_candidates) for list or dict inspections."""
    if isinstance(item, list):
        title = str(item[0] or "") if len(item) > 0 else ""
        result = str(item[1] or "") if len(item) > 1 else ""
        candidates = []
        for idx in (2, 4):
            if idx < len(item):
                candidates.append(item[idx])
        return title, result, candidates
    if isinstance(item, dict):
        title = str(item.get("Type") or item.get("Title") or "")
        result = str(item.get("Result") or "")
        candidates = [
            item.get("Completed"),
            item.get("CompletedDate"),
            item.get("Scheduled Date"),
        ]
        return title, result, candidates
    return None


def _is_final_inspection(title: str, result: str) -> bool:
    result_u = result.strip().upper()
    if result_u in ("FINAL", "FINALED", "FIN"):
        return True
    if _FINAL_TITLE_RE.search(title.strip()) and _result_ok(result):
        return True
    return False


def _final_from_inspections(d: dict):
    """Latest completion date from a final / C of O inspection."""
    inspections = d.get("inspections")
    if not isinstance(inspections, list):
        return pd.NaT
    dates = []
    for item in inspections:
        fields = _inspection_fields(item)
        if fields is None:
            continue
        title, result, candidates = fields
        if not _is_final_inspection(title, result):
            continue
        for cand in candidates:
            completed = _safe_to_datetime(cand)
            if completed is not pd.NaT:
                dates.append(completed)
                break
    return max(dates) if dates else pd.NaT


def _preferred_final_date(d: dict):
    finaled = _pi_date(d, "PermitFinaledDate")
    if finaled is not pd.NaT:
        return finaled
    return _final_from_inspections(d)


def _preferred_permit_date(d: dict):
    issued = _pi_date(d, "PermitIssuedDate")
    if issued is not pd.NaT:
        return issued
    return _pi_date(d, "PermitApprovedDate")


def _preferred_file_date(d: dict):
    """Application / submittal date from PermitAppliedDate."""
    applied = _pi_date(d, "PermitAppliedDate")
    if applied is not pd.NaT:
        return applied
    return pd.NaT


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
    Yolo County permit records using information from the raw DATA JSON.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Yolo County".  Must contain
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
    city = df[(df["JURISDICTION"] == "Yolo County") & (df["STATE"] == "CA")].copy()

    print(f"Yolo County records: {len(city):,}\n")

    repaired = data_repair(city)

    if AGENT_DATA_PATH:
        out_dir = Path(AGENT_DATA_PATH) / "repaired"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "permits_ca_yolo_county_repaired.parquet"
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

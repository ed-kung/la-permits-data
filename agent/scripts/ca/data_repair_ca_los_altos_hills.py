"""Data repair for Los Altos Hills (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Los Altos Hills DATA is a civic portal payload (same shape as Santa Cruz /
Willows / Hillsborough). All sample rows share top-level keys:
``fees``, ``contacts``, ``site_info``, ``inspections``,
``permit_info``, ``search_data``. Canonical fields live under
``permit_info``; ``search_data`` mirrors APPLIED / ISSUED / FINALED /
APPROVED when the full date block is present (1,890 / 2,000 rows).

  - PermitStatus                         → STATUS_NORMALIZED
  - PermitAppliedDate                    → FILE_DATE
  - PermitIssuedDate (fallback
    PermitApprovedDate)                  → PERMIT_DATE
  - PermitFinaledDate (fallback: latest
    passed final inspection)             → FINAL_DATE

Content variants (INFERRED_SCHEMA):

  - permit_info_issued_finaled: Issued + Finaled present
  - permit_info_issued:         Issued present, Finaled blank
  - permit_info_finaled_only:   Finaled present, Issued blank
  - permit_info_approved_only:  Approved present, Issued/Finaled blank
  - permit_info_applied_only:   only Applied populated
  - permit_info_empty_dates:    status present, no usable dates
  - legacy_no_status:           blank PermitStatus with dates
  - permit_info_empty:          blank status and no dates

Known issues repaired:
  - Blank PermitStatus legacy stubs (applied-only) left null → FILLED
    as In Review.
  - Unmapped ``APPROVED ON HOLD`` left null → FILLED as In Review.
  - Stale STATUS_ORIGINAL mapping: ``FINALED`` shells left Active /
    Inactive → FIXED to Final; ``ISSUED`` left Inactive / In Review →
    FIXED to Active; ``APPROVED`` left In Review → FIXED to Active.
  - Active / Final missing PERMIT_DATE when Issued or Approved is
    present → FILLED.
  - Final missing FINAL_DATE while PermitFinaledDate or a passed
    ``**FINAL`` inspection exists → FILLED.
  - Spurious FINAL_DATE on Inactive (Expired / Void closure stamps)
    → cleared.

Status is not promoted to Final from intermediate inspections alone
(encroachment / sewer finals are common on still-open shells). Inactive
labels (Expired / Void / Cancelled / Withdrawn) are sticky even when
PermitFinaledDate is present as a case-closure stamp.

Not repairable / left as-is:
  - 3 rows lack PermitAppliedDate / APPLIED → FILE_DATE stays missing.
  - Some CLOSED / FINALED shells lack Issued and Approved → PERMIT_DATE
    stays missing.
  - Many CLOSED shells and some FINALED shells lack PermitFinaledDate
    and have no usable final inspection → FINAL_DATE stays missing.
  - PermitExpirationDate is a validity window, not a completion date.
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
    """Parse a date value, returning pd.NaT on failure or implausible year."""
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

    raw_status = _raw_status(data_dict)
    issued = _safe_to_datetime(pi.get("PermitIssuedDate"))
    finaled = _safe_to_datetime(pi.get("PermitFinaledDate"))
    approved = _safe_to_datetime(pi.get("PermitApprovedDate"))
    applied = _safe_to_datetime(pi.get("PermitAppliedDate"))

    has_issued = issued is not pd.NaT
    has_finaled = finaled is not pd.NaT
    has_approved = approved is not pd.NaT
    has_applied = applied is not pd.NaT

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

# PermitStatus (uppercased)
_STATUS_MAP = {
    # Final
    "FINALED": "Final",
    "FINAL": "Final",
    "CLOSED": "Final",
    "COMPLETED": "Final",
    # Active (issued / approved / open work)
    "ISSUED": "Active",
    "NOT FINALED": "Active",
    "APPROVED": "Active",
    "ACTIVE": "Active",
    "LOW FUNDS": "Active",
    # In Review (intake / plan check / hold)
    "RECEIVED": "In Review",
    "RECEIVED ONLINE": "In Review",
    "PLAN CHECK": "In Review",
    "APPROVED ON HOLD": "In Review",
    "UNDER REVIEW": "In Review",
    "SUBMITTED": "In Review",
    "PENDING": "In Review",
    "ON HOLD": "In Review",
    # Inactive
    "CANCELLED": "Inactive",
    "CANCELED": "Inactive",
    "EXPIRED": "Inactive",
    "VOID": "Inactive",
    "WITHDRAWN": "Inactive",
    "DENIED": "Inactive",
}

# Terminal inactive labels: sticky even if a Finaled stamp exists.
_INACTIVE_KEEP = {
    "CANCELLED",
    "CANCELED",
    "EXPIRED",
    "VOID",
    "WITHDRAWN",
    "DENIED",
}

_FINAL_INSP_OK = {
    "PASS",
    "PASSED",
    "PASS WITH COMMENTS",
    "APPROVED",
    "APPROVED/SIGNED OFF",
    "SIGNED OFF",
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
    r"^[\*\s]*final\s*$|"
    r"^final-|"
    r"permit\s*final|"
    r"building\s*final|"
    r"final\s*building|"
    r"final\s*bldg|"
    r"final\s*approval|"
    r"final\s*job|"
    r"encroachment\s*final|"
    r"\*{0,2}\s*(res|com)\s*final|"
    r"\bfinal\s*(sfr|bldg|building|elec|electrical|fire|roof|"
    r"plumbing|plumb|mechanical|mech|approval)?\b|"
    r"c\s*of\s*o|certificate\s*of\s*occup"
    r")"
)


def _normalize_status_key(raw) -> str:
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return ""
    s = str(raw).strip().upper()
    if s in {"<NONE>", "NONE", "NULL", "N/A", "UNKNOWN"}:
        return ""
    return s


def _raw_status(d: dict) -> str:
    """Prefer permit_info.PermitStatus; fall back to search_data.Status."""
    pi = _permit_info(d)
    raw = _normalize_status_key(pi.get("PermitStatus"))
    if raw:
        return raw
    sd = _search_data(d)
    return _normalize_status_key(sd.get("Status"))


def _lookup_status(raw: str) -> Optional[str]:
    """Exact map, then CANCEL / EXPIRE / FINAL / ISSUED / APPROV heuristics."""
    if not raw:
        return None
    if raw in _STATUS_MAP:
        return _STATUS_MAP[raw]
    if "NO PERMIT" in raw:
        return "Inactive"
    if "CANCEL" in raw or raw.startswith("VOID"):
        return "Inactive"
    if "EXPIRE" in raw:
        return "Inactive"
    if "REVOKE" in raw or "WITHDRAW" in raw or "ABANDON" in raw:
        return "Inactive"
    if "DENIED" in raw or "STOP WORK" in raw:
        return "Inactive"
    if (
        raw.startswith("FINAL")
        or raw.startswith("COMPLETED")
        or "CERTIFICATE OF OCC" in raw
    ):
        return "Final"
    if raw == "CLOSED" or raw.startswith("CLOSE"):
        return "Final"
    if raw.startswith("ISSUED") or raw == "ACTIVE" or "NOT FINAL" in raw:
        return "Active"
    if "APPROV" in raw and "HOLD" in raw:
        return "In Review"
    if "APPROV" in raw:
        return "Active"
    if (
        "SUBMIT" in raw
        or "REVIEW" in raw
        or "PENDING" in raw
        or "WAITING" in raw
        or "INCOMPLETE" in raw
        or "ON HOLD" in raw
        or raw == "HOLD"
        or "APPLIED" in raw
        or "RECEIVED" in raw
        or "PLAN CHECK" in raw
        or "LOW FUNDS" in raw
    ):
        return "In Review"
    return None


def _is_inactive_keep(raw: str) -> bool:
    if not raw:
        return False
    if raw in _INACTIVE_KEEP:
        return True
    if "NO PERMIT" in raw:
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
    approved = _pi_date(d, "PermitApprovedDate")
    if approved is not pd.NaT:
        return approved
    # Los Altos Hills search_data uses ISSUED / APPROVED; other cities
    # in this portal family use "Issued Date" / "Issued".
    return _sd_date(d, "ISSUED", "APPROVED", "Issued Date", "Issued")


def _preferred_file_date(d: dict):
    """Application / submittal date from PermitAppliedDate (search fallback)."""
    applied = _pi_date(d, "PermitAppliedDate")
    if applied is not pd.NaT:
        return applied
    return _sd_date(d, "APPLIED", "Applied Date", "Application")


def _result_ok(result: str) -> bool:
    result_u = result.strip().upper()
    if not result_u:
        return False
    if "PARTIAL" in result_u:
        return False
    if "FAIL" in result_u or "CORRECTION" in result_u:
        return False
    if result_u in _FINAL_INSP_OK:
        return True
    if result_u.startswith("PASS"):
        return True
    if result_u.startswith("APPROVED"):
        return True
    if "SIGNED OFF" in result_u:
        return True
    return False


def _is_final_inspection(item: dict) -> bool:
    typ = str(item.get("Type") or item.get("Title") or "").strip()
    result = str(item.get("Result") or "").strip()
    result_u = result.upper()

    if not _result_ok(result):
        return False

    if result_u in ("FINAL", "FINALED", "FIN"):
        return True

    if _FINAL_TITLE_RE.search(typ):
        return True

    return False


def _is_job_final_inspection(item: dict) -> bool:
    """Whole-job / C-of-O / starred FINAL only (not roof/plumbing/dept finals)."""
    if not _is_final_inspection(item):
        return False
    typ = str(item.get("Type") or item.get("Title") or "").strip().upper()
    if re.search(r"FINAL\s*JOB|JOB\s*CO|C\s*OF\s*O|CERTIFICATE\s*OF\s*OCCUP", typ):
        return True
    if re.search(r"(?i)^(final inspection|permit final|building final)\b", typ):
        return True
    # Los Altos Hills uses "**FINAL" as the whole-job final marker.
    if re.fullmatch(r"\*+\s*FINAL", typ):
        return True
    return False


def _final_from_inspections(d: dict, job_only: bool = False):
    """Latest completion date from a final / C of O inspection."""
    inspections = d.get("inspections")
    if not isinstance(inspections, list):
        return pd.NaT
    dates = []
    for item in inspections:
        if not isinstance(item, dict):
            continue
        ok = _is_job_final_inspection(item) if job_only else _is_final_inspection(item)
        if not ok:
            continue
        completed = _safe_to_datetime(
            item.get("Completed") or item.get("CompletedDate")
        )
        if completed is pd.NaT:
            continue  # scheduled-only stamps are not completion evidence
        dates.append(completed)
    return max(dates) if dates else pd.NaT


def _canonical_final_date(d: dict):
    """PermitFinaledDate / search FINALED only (no inspection fallback)."""
    finaled = _pi_date(d, "PermitFinaledDate")
    if finaled is not pd.NaT:
        return finaled
    return _sd_date(d, "FINALED", "Finaled Date", "Finaled")


def _preferred_final_date(d: dict):
    canonical = _canonical_final_date(d)
    if canonical is not pd.NaT:
        return canonical
    # Prefer whole-job finals; fall back to any passed final-titled insp.
    job = _final_from_inspections(d, job_only=True)
    if job is not pd.NaT:
        return job
    return _final_from_inspections(d, job_only=False)


def _derive_status(d: dict) -> Optional[str]:
    """Map PermitStatus; promote to Final only on canonical Finaled stamps.

    Intermediate final inspections are common on still-open Los Altos
    Hills shells and must not override PermitStatus. Pre-issuance labels
    that already carry PermitIssuedDate are promoted to Active. Blank
    statuses are inferred from available dates.
    """
    raw = _raw_status(d)
    status = _lookup_status(raw)

    if _is_inactive_keep(raw):
        return status or "Inactive"

    # Canonical Finaled date (not intermediate inspections) → Final.
    if _canonical_final_date(d) is not pd.NaT:
        return "Final"

    issued = _pi_date(d, "PermitIssuedDate")
    if issued is pd.NaT:
        issued = _sd_date(d, "ISSUED", "Issued Date", "Issued")
    if status == "In Review" and issued is not pd.NaT:
        return "Active"

    if status is not None:
        return status

    if raw:
        return None

    # Blank status: infer from dates.
    approved = _pi_date(d, "PermitApprovedDate")
    if approved is pd.NaT:
        approved = _sd_date(d, "APPROVED", "Approved Date", "Approved")
    applied = _preferred_file_date(d)

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
    if issued is pd.NaT:
        issued = _sd_date(d, "ISSUED", "Issued Date", "Issued")
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
        elif effective_status == "In Review" and issued is pd.NaT:
            # Clear spurious permit dates on non-issued review rows.
            repairs["PERMIT_DATE"] = pd.NaT
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
    Los Altos Hills permit records using information from the raw DATA JSON.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Los Altos Hills".  Must
        contain columns STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE,
        FINAL_DATE, and DATA.

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
    filepath = os.path.join(
        MY_DATA_PATH, "processed_data", "permits_ca_sample.parquet"
    )
    df = pd.read_parquet(filepath)
    city = df[
        (df["JURISDICTION"] == "Los Altos Hills") & (df["STATE"] == "CA")
    ].copy()

    print(f"Los Altos Hills records: {len(city):,}\n")

    repaired = data_repair(city)

    if AGENT_DATA_PATH:
        out_dir = Path(AGENT_DATA_PATH) / "repaired"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "permits_ca_los_altos_hills_repaired.parquet"
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

    print("\nStatus transitions (before → after):")
    mask = repaired["STATUS_NORMALIZED_FLAG"].notna()
    if mask.any():
        transitions = (
            pd.DataFrame({
                "before": city.loc[mask, "STATUS_NORMALIZED"].fillna("nan").astype(str),
                "after": repaired.loc[mask, "STATUS_NORMALIZED"].fillna("nan").astype(str),
            })
            .value_counts()
            .reset_index(name="n")
        )
        for _, trow in transitions.iterrows():
            print(f"  {trow['before']:15s} → {trow['after']:15s}: {trow['n']:>4,}")
    else:
        print("  (none)")

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

    fd = pd.to_datetime(repaired["FILE_DATE"], errors="coerce")
    pd_ = pd.to_datetime(repaired["PERMIT_DATE"], errors="coerce")
    ff = pd.to_datetime(repaired["FINAL_DATE"], errors="coerce")
    both_fp = fd.notna() & pd_.notna()
    both_pf = pd_.notna() & ff.notna()
    print("\nChronology inversions:")
    print(f"  FILE > PERMIT: {(both_fp & (fd.dt.normalize() > pd_.dt.normalize())).sum()}")
    print(f"  PERMIT > FINAL: {(both_pf & (pd_.dt.normalize() > ff.dt.normalize())).sum()}")

    print("\nRemaining ideal-coverage gaps:")
    active_final = repaired["STATUS_NORMALIZED"].isin(["Active", "Final"])
    final = repaired["STATUS_NORMALIZED"] == "Final"
    print(
        f"  Active/Final missing PERMIT_DATE: "
        f"{(active_final & repaired['PERMIT_DATE'].isna()).sum()}"
    )
    print(
        f"  Final missing FINAL_DATE: "
        f"{(final & repaired['FINAL_DATE'].isna()).sum()}"
    )
    print(f"  Any missing FILE_DATE: {repaired['FILE_DATE'].isna().sum()}")
    print(f"  Any missing STATUS: {repaired['STATUS_NORMALIZED'].isna().sum()}")

    from collections import Counter

    print("\nActive/Final still missing PERMIT_DATE (by PermitStatus):")
    gap = Counter()
    for idx in repaired.index:
        if repaired.at[idx, "STATUS_NORMALIZED"] not in ("Active", "Final"):
            continue
        if pd.notna(repaired.at[idx, "PERMIT_DATE"]):
            continue
        d = _safe_parse(city.at[idx, "DATA"])
        pi = (d or {}).get("permit_info") or {}
        gap[pi.get("PermitStatus")] += 1
    for k, v in gap.most_common():
        print(f"  {k!r}: {v}")

    print("\nFinal still missing FINAL_DATE (by PermitStatus):")
    gap2 = Counter()
    for idx in repaired.index:
        if repaired.at[idx, "STATUS_NORMALIZED"] != "Final":
            continue
        if pd.notna(repaired.at[idx, "FINAL_DATE"]):
            continue
        d = _safe_parse(city.at[idx, "DATA"])
        pi = (d or {}).get("permit_info") or {}
        gap2[pi.get("PermitStatus")] += 1
    for k, v in gap2.most_common():
        print(f"  {k!r}: {v}")

    print("\nStatus transitions by PermitStatus:")
    detail = Counter()
    for idx in repaired.index:
        if pd.isna(repaired.at[idx, "STATUS_NORMALIZED_FLAG"]):
            continue
        d = _safe_parse(city.at[idx, "DATA"])
        pi = (d or {}).get("permit_info") or {}
        before = city.at[idx, "STATUS_NORMALIZED"]
        after = repaired.at[idx, "STATUS_NORMALIZED"]
        detail[(
            str(before) if pd.notna(before) else "nan",
            str(after),
            pi.get("PermitStatus") or "(blank)",
        )] += 1
    for (b, a, ps), n in sorted(detail.items(), key=lambda x: -x[1]):
        print(f"  {b:12s} → {a:12s} PS={ps!r}: {n}")

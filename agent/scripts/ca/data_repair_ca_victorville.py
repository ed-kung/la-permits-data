"""Data repair for Victorville (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Victorville DATA is a Tyler EnerGov-style payload with top-level keys
``entity``, ``details``, ``contacts``, ``fees``, and
``processing_status``, plus an optional reviews bundle (``reviews`` /
``holds`` / ``attachments`` / ``more_info``). Two key-set variants
appear in the sample:

  - entity_fees:          entity + details + contacts + fees +
                          processing_status
  - entity_fees_reviews:  entity_fees plus reviews/holds/attachments/
                          more_info

Canonical fields live under ``entity`` (with details fallbacks):
  - CaseStatus / details.PermitStatus  → STATUS_NORMALIZED
  - ApplyDate                          → FILE_DATE
  - IssueDate                          → PERMIT_DATE
  - FinalDate (fallback: details.FinalizeDate) → FINAL_DATE

Known issues repaired:
  - ``Issued`` shells whose details.PermitStatus is ``Finaled`` (and
    FinalizeDate is present) left Active → FIXED to Final.
  - Issued / Inspection shells with FinalDate/FinalizeDate strictly
    after IssueDate left Active → FIXED to Final.
  - Pre-issuance ``Submitted`` / ``Corrections Required`` rows with
    IssueDate left In Review → FIXED to Active (or Final when a
    credible FinalDate/FinalizeDate is also present).
  - Junk FinalDate stamps on non-Final rows (Issued with FinalDate ≤
    IssueDate; Inactive Void / Expired closure stamps; In Review
    Submitted stamps that do not promote) → FINAL_DATE cleared.
  - Newly promoted Final rows missing FINAL_DATE while FinalizeDate is
    present → FILLED.

Not repairable / left as-is:
  - FILE_DATE already matches entity.ApplyDate for every sample row.
  - 19 ``Issued`` Active shells and 21 ``Finaled`` Final shells have
    null IssueDate → PERMIT_DATE stays missing.
  - 135 ``Finaled`` shells have null FinalDate and null FinalizeDate
    → FINAL_DATE stays missing.
  - ExpireDate is a validity window, not a completion date.
  - FinalDate on Expired / Void / Denied is a case-closure stamp, not
    a permit finaled date (status stays Inactive; FINAL_DATE cleared).
"""

from __future__ import annotations

import json
import math
from typing import Optional

import numpy as np
import pandas as pd


_MIN_YEAR = 1990
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
    """Parse a date value as UTC, returning pd.NaT on failure or sentinel."""
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return pd.NaT
    if isinstance(val, str) and not str(val).strip():
        return pd.NaT
    try:
        dt = pd.to_datetime(val, utc=True, errors="coerce")
    except (ValueError, TypeError):
        return pd.NaT
    if dt is pd.NaT or pd.isna(dt):
        return pd.NaT
    year = int(dt.year)
    # EnerGov sometimes uses 1900-01-01 as a null placeholder.
    if year < _MIN_YEAR or year > _MAX_YEAR:
        return pd.NaT
    return dt


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())
    if not {"entity", "details"}.issubset(keys):
        return "unknown"
    has_fees = "fees" in keys
    has_reviews = bool(keys & {"reviews", "holds", "attachments", "more_info"})
    if has_fees and has_reviews:
        return "entity_fees_reviews"
    if has_fees:
        return "entity_fees"
    return "entity_basic"


# ── Status mapping ──────────────────────────────────────────────────────────

# entity.CaseStatus / details.PermitStatus → STATUS_NORMALIZED
_STATUS_MAP = {
    # Final
    "Finaled": "Final",
    "Final": "Final",
    "Finalized": "Final",
    "Complete": "Final",
    "Closed": "Final",
    # Active (post-issuance)
    "Issued": "Active",
    "Issued - Revision": "Active",
    "Inspection": "Active",
    "Active": "Active",
    # Inactive
    "Expired": "Inactive",
    "Void": "Inactive",
    "Voided": "Inactive",
    "Withdrawn": "Inactive",
    "Canceled": "Inactive",
    "Cancelled": "Inactive",
    "Denied": "Inactive",
    "Rejected": "Inactive",
    # In Review (pre-issuance)
    "Submitted": "In Review",
    "Submitted - Online": "In Review",
    "In Review": "In Review",
    "Corrections Required": "In Review",
    "Plan Approved": "In Review",
    "Resubmittal Required": "In Review",
    "On Hold": "In Review",
    "Pending": "In Review",
}

_INACTIVE_LABELS = {
    "Expired",
    "Void",
    "Voided",
    "Withdrawn",
    "Canceled",
    "Cancelled",
    "Denied",
    "Rejected",
}

_FINAL_LABELS = {
    "Finaled",
    "Final",
    "Finalized",
    "Complete",
    "Closed",
}


def _status_strings(d: dict) -> list[str]:
    """Collect non-empty CaseStatus and PermitStatus strings."""
    entity = d.get("entity") if isinstance(d.get("entity"), dict) else {}
    details = d.get("details") if isinstance(d.get("details"), dict) else {}
    out = []
    for raw in (entity.get("CaseStatus"), details.get("PermitStatus")):
        if raw is None:
            continue
        s = str(raw).strip()
        if s:
            out.append(s)
    return out


def _entity_date(d: dict, entity_key: str, *detail_keys: str):
    """UTC datetime from entity.<key>, else first non-null details key."""
    entity = d.get("entity") if isinstance(d.get("entity"), dict) else {}
    dt = _safe_to_datetime(entity.get(entity_key))
    if dt is not pd.NaT and not pd.isna(dt):
        return dt
    details = d.get("details") if isinstance(d.get("details"), dict) else {}
    for key in detail_keys:
        dt = _safe_to_datetime(details.get(key))
        if dt is not pd.NaT and not pd.isna(dt):
            return dt
    return pd.NaT


def _is_issued(d: dict) -> bool:
    return not pd.isna(_entity_date(d, "IssueDate", "IssueDate"))


def _raw_final_stamp(d: dict):
    """Raw FinalDate / FinalizeDate without credibility filter."""
    return _entity_date(d, "FinalDate", "FinalizeDate")


def _has_final_label(d: dict) -> bool:
    return any(label in _FINAL_LABELS for label in _status_strings(d))


def _has_credible_final_stamp(d: dict) -> bool:
    """True when FinalDate/FinalizeDate is credible completion evidence.

    Victorville sometimes stamps FinalDate on still-Issued / Inspection
    shells. Require either an explicit Finaled/Complete label, or
    FinalDate/FinalizeDate strictly after IssueDate. Same-day or earlier
    stamps are treated as junk workflow noise.
    """
    final = _raw_final_stamp(d)
    if pd.isna(final):
        return False
    if _has_final_label(d):
        return True
    issue = _entity_date(d, "IssueDate", "IssueDate")
    if pd.isna(issue):
        return False
    return final.date() > issue.date()


def _is_inactive_label(d: dict) -> bool:
    return any(label in _INACTIVE_LABELS for label in _status_strings(d))


def _mapped_status(d: dict) -> Optional[str]:
    for raw in _status_strings(d):
        mapped = _STATUS_MAP.get(raw)
        if mapped is not None:
            return mapped
        lower = raw.lower()
        if (
            "finalized" in lower
            or "finaled" in lower
            or lower == "final"
            or lower == "closed"
            or "complete" in lower
        ):
            return "Final"
        if any(
            tok in lower
            for tok in (
                "expired",
                "void",
                "denied",
                "withdrawn",
                "cancel",
                "revoked",
                "rejected",
            )
        ):
            return "Inactive"
        if (
            lower.startswith("issued")
            or lower == "active"
            or "inspection" in lower
            or "post-issuance" in lower
        ):
            return "Active"
        if any(
            tok in lower
            for tok in (
                "review",
                "submitted",
                "received",
                "pending",
                "on hold",
                "incomplete",
                "ready to issue",
                "approved",
                "corrections",
                "applied",
                "awaiting",
                "intake",
                "fees due",
                "fees paid",
                "resubmittal",
            )
        ):
            return "In Review"
    return None


def _expected_status(d: dict) -> Optional[str]:
    """Derive STATUS_NORMALIZED from CaseStatus/PermitStatus with date overrides.

    Inactive terminal labels (Expired / Void / Denied) are sticky even
    when FinalDate is present as a case-closure stamp. Explicit Finaled
    / Complete labels (from either CaseStatus or PermitStatus) → Final.
    Otherwise a FinalDate/FinalizeDate strictly after IssueDate → Final
    (stale Issued / Inspection shells). IssueDate → Active overrides
    review-pipeline labels (Submitted / Corrections Required / Plan
    Approved / In Review).
    """
    if _is_inactive_label(d):
        return "Inactive"

    if _has_final_label(d) or _has_credible_final_stamp(d):
        return "Final"

    if _is_issued(d):
        return "Active"

    mapped = _mapped_status(d)
    if mapped is not None:
        return mapped

    if not pd.isna(_entity_date(d, "ApplyDate", "ApplyDate")):
        return "In Review"
    return None


def _dates_equal(a, b) -> bool:
    """Compare two datelike values at calendar-day resolution (UTC)."""
    da = _safe_to_datetime(a)
    db = _safe_to_datetime(b)
    if pd.isna(da) or pd.isna(db):
        return False
    return da.date() == db.date()


# ── Per-record repair logic ─────────────────────────────────────────────────

def _repair_record(row, d: dict, repairs: dict):
    """Populate *repairs* with corrected values for a single Victorville record."""
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

    # -- FILE_DATE (application / ApplyDate) --
    apply = _entity_date(d, "ApplyDate", "ApplyDate")
    if not pd.isna(apply):
        if pd.isna(row["FILE_DATE"]):
            repairs["FILE_DATE"] = apply
            repairs["FILE_DATE_FLAG"] = "FILLED"
        elif not _dates_equal(row["FILE_DATE"], apply):
            repairs["FILE_DATE"] = apply
            repairs["FILE_DATE_FLAG"] = "FIXED"

    # -- PERMIT_DATE (issuance / IssueDate) --
    issue = _entity_date(d, "IssueDate", "IssueDate")
    current_permit = row["PERMIT_DATE"]

    if not pd.isna(current_permit):
        if not pd.isna(issue) and not _dates_equal(current_permit, issue):
            repairs["PERMIT_DATE"] = issue
            repairs["PERMIT_DATE_FLAG"] = "FIXED"
        elif effective_status == "In Review" and not _is_issued(d):
            # Clear spurious permit dates on non-issued review rows.
            repairs["PERMIT_DATE"] = pd.NaT
            repairs["PERMIT_DATE_FLAG"] = "FIXED"
    elif effective_status in ("Active", "Final") and not pd.isna(issue):
        repairs["PERMIT_DATE"] = issue
        repairs["PERMIT_DATE_FLAG"] = "FILLED"

    # -- FINAL_DATE (finaled / FinalDate; not ExpireDate) --
    # Non-Final statuses often carry junk FinalDate stamps; only keep
    # FINAL_DATE when status is Final.
    final = _raw_final_stamp(d)
    current_final = row["FINAL_DATE"]

    if effective_status == "Final":
        if not pd.isna(final):
            if pd.isna(current_final):
                repairs["FINAL_DATE"] = final
                repairs["FINAL_DATE_FLAG"] = "FILLED"
            elif not _dates_equal(current_final, final):
                repairs["FINAL_DATE"] = final
                repairs["FINAL_DATE_FLAG"] = "FIXED"
    elif not pd.isna(current_final):
        repairs["FINAL_DATE"] = pd.NaT
        repairs["FINAL_DATE_FLAG"] = "FIXED"


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Victorville permit records using information from the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Victorville".  Must contain
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
        _repair_record(row, d, repairs)

        for key, value in repairs.items():
            out.at[idx, key] = value

    for col in ("FILE_DATE", "PERMIT_DATE", "FINAL_DATE"):
        if col in out.columns:
            out[col] = pd.to_datetime(out[col], utc=True, errors="coerce")

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
        (df["JURISDICTION"] == "Victorville") & (df["STATE"] == "CA")
    ].copy()

    print(f"Victorville records: {len(city):,}\n")

    repaired = data_repair(city)

    if AGENT_DATA_PATH:
        out_dir = Path(AGENT_DATA_PATH) / "repaired"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "permits_ca_victorville_repaired.parquet"
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

    fd = pd.to_datetime(repaired["FILE_DATE"], utc=True, errors="coerce")
    pd_ = pd.to_datetime(repaired["PERMIT_DATE"], utc=True, errors="coerce")
    ff = pd.to_datetime(repaired["FINAL_DATE"], utc=True, errors="coerce")
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

    from collections import Counter

    print("\nActive/Final still missing PERMIT_DATE (by CaseStatus):")
    gap = Counter()
    for idx in repaired.index:
        if repaired.at[idx, "STATUS_NORMALIZED"] not in ("Active", "Final"):
            continue
        if pd.notna(repaired.at[idx, "PERMIT_DATE"]):
            continue
        d = _safe_parse(city.at[idx, "DATA"])
        entity = (d or {}).get("entity") or {}
        gap[entity.get("CaseStatus")] += 1
    for k, v in gap.most_common():
        print(f"  {k}: {v}")

    print("\nFinal still missing FINAL_DATE (by CaseStatus):")
    gap = Counter()
    for idx in repaired.index:
        if repaired.at[idx, "STATUS_NORMALIZED"] != "Final":
            continue
        if pd.notna(repaired.at[idx, "FINAL_DATE"]):
            continue
        d = _safe_parse(city.at[idx, "DATA"])
        entity = (d or {}).get("entity") or {}
        gap[entity.get("CaseStatus")] += 1
    for k, v in gap.most_common():
        print(f"  {k}: {v}")

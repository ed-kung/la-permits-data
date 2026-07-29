"""Data repair for Murrieta (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Murrieta DATA is a Tyler EnerGov-style payload with top-level keys
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
  - ``Estimate`` shells incorrectly normalized to Final
    (STATUS_ORIGINAL=estimate) → FIXED to In Review (or Active when
    IssueDate is present).
  - ``Applied`` / ``Applied Online`` / ``In Plancheck`` shells with
    IssueDate left In Review → FIXED to Active; PERMIT_DATE FILLED
    when missing.
  - ``Issued`` shells with PermitStatus Finaled, or FinalDate/
    FinalizeDate strictly after IssueDate, left Active → FIXED to
    Final; FINAL_DATE FILLED from FinalizeDate when missing.
  - Missing PERMIT_DATE on Issued shells that already have IssueDate
    → FILLED.
  - Junk FINAL_DATE on non-Final rows (Expired closure stamps; Issued
    with FinalDate before IssueDate) → cleared.

Not repairable / left as-is:
  - FILE_DATE already matches entity.ApplyDate at calendar-day
    resolution for every sample row.
  - Complete / Finaled occupancy-inspection and fire shells with null
    IssueDate → PERMIT_DATE stays missing.
  - ExpireDate is a validity window, not a completion date.
  - FinalDate on Expired is a case-closure stamp, not a permit
    finaled date (status stays Inactive; FINAL_DATE cleared).
  - Trade-specific final inspection Pass (plumbing / electrical /
    sprinkler) without FinalDate is not treated as permit completion;
    Issued stays Active.
  - FinalizeDate often differs from FinalDate by timezone offset; prefer
    entity.FinalDate when present.
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
    # EnerGov sometimes uses 1900-01-01 or far-future years as placeholders.
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
    "Complete": "Final",
    "Closed": "Final",
    "Finaled": "Final",
    "Final": "Final",
    "Finalized": "Final",
    "Legacy": "Final",
    # Active
    "Issued": "Active",
    "Issued - Revision": "Active",
    "Revision Issued": "Active",
    "Fees Due (Post-Issuance)": "Active",
    "Active": "Active",
    "Case Opened": "Active",
    # Inactive
    "Expired": "Inactive",
    "Expired - Plan Check": "Inactive",
    "Plan Approval Expired": "Inactive",
    "Void": "Inactive",
    "Voided": "Inactive",
    "Withdrawn": "Inactive",
    "Cancel": "Inactive",
    "Canceled": "Inactive",
    "Cancelled": "Inactive",
    "Denied": "Inactive",
    "Rejected": "Inactive",
    "Revoked": "Inactive",
    "Refunded": "Inactive",
    # In Review (pre-issuance / plan check / estimate)
    "Applied": "In Review",
    "Applied Online": "In Review",
    "Submitted": "In Review",
    "Submitted Online": "In Review",
    "Submitted - Online": "In Review",
    "Online Submission": "In Review",
    "In Review": "In Review",
    "In Plancheck": "In Review",
    "Ready for Issuance": "In Review",
    "Resubmittal Required": "In Review",
    "Fees Due": "In Review",
    "Fees Paid": "In Review",
    "Deposit Fees Due": "In Review",
    "Deposit Fees Paid": "In Review",
    "Returned to Applicant": "In Review",
    "Other - See Comments": "In Review",
    "OFC": "In Review",
    "On Hold": "In Review",
    "On Hold/Pending": "In Review",
    "Pending": "In Review",
    "Approved": "In Review",
    "Estimate": "In Review",
    "Plan Check": "In Review",
    "Stop Work Order": "In Review",
}

_INACTIVE_LABELS = {
    "Expired",
    "Expired - Plan Check",
    "Plan Approval Expired",
    "Void",
    "Voided",
    "Withdrawn",
    "Cancel",
    "Canceled",
    "Cancelled",
    "Denied",
    "Rejected",
    "Revoked",
    "Refunded",
}

_FINAL_LABELS = {
    "Complete",
    "Closed",
    "Finaled",
    "Final",
    "Finalized",
    "Legacy",
}

# Final* inspection outcomes that count as completion evidence for
# FINAL_DATE fill when status is already Final. Murrieta uses "Pass".
_FINAL_INSPECTION_OK = {"final", "passed", "approved", "pass"}


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
    if dt is not pd.NaT:
        return dt
    details = d.get("details") if isinstance(d.get("details"), dict) else {}
    for key in detail_keys:
        dt = _safe_to_datetime(details.get(key))
        if dt is not pd.NaT:
            return dt
    return pd.NaT


def _is_issued(d: dict) -> bool:
    return _entity_date(d, "IssueDate", "IssueDate") is not pd.NaT


def _raw_final_stamp(d: dict):
    """Raw FinalDate / FinalizeDate without credibility filter."""
    return _entity_date(d, "FinalDate", "FinalizeDate")


def _final_inspection_date(d: dict):
    """Latest successful Final* processing_status item.

    Murrieta populates inspection ``status`` as ``Pass`` (among Failed /
    Not Ready / Cancelled / etc.). Trade-specific finals (plumbing,
    electrical) are not used to upgrade STATUS_NORMALIZED.
    """
    ps = d.get("processing_status")
    if not isinstance(ps, list):
        return pd.NaT
    best = pd.NaT
    for item in ps:
        if not isinstance(item, dict):
            continue
        desc = str(item.get("description") or "")
        status = str(item.get("status") or "").strip().lower()
        if "final" not in desc.lower():
            continue
        if status not in _FINAL_INSPECTION_OK:
            continue
        if "partial" in status:
            continue
        dt = _safe_to_datetime(item.get("scheduled_date"))
        if dt is pd.NaT:
            dt = _safe_to_datetime(item.get("requested_date"))
        if dt is pd.NaT:
            continue
        if best is pd.NaT or dt > best:
            best = dt
    return best


def _has_final_label(d: dict) -> bool:
    return any(label in _FINAL_LABELS for label in _status_strings(d))


def _has_credible_final_stamp(d: dict) -> bool:
    """True when FinalDate/FinalizeDate is credible completion evidence.

    Require either an explicit Final/Complete label, or FinalDate /
    FinalizeDate strictly after IssueDate (stale Issued shells).
    Same-day or inverted stamps are not treated as completion.
    """
    final = _raw_final_stamp(d)
    if final is pd.NaT:
        return False
    if _has_final_label(d):
        return True
    issue = _entity_date(d, "IssueDate", "IssueDate")
    if issue is pd.NaT:
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
            or lower == "legacy"
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
                "refunded",
                "not accepted",
            )
        ):
            return "Inactive"
        if (
            lower.startswith("issued")
            or "revision issued" in lower
            or lower == "active"
            or "post-issuance" in lower
            or lower == "case opened"
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
                "ready for issuance",
                "approved",
                "estimate",
                "corrections",
                "applied",
                "awaiting",
                "intake",
                "fees due",
                "fees paid",
                "deposit fees",
                "returned to applicant",
                "other - see comments",
                "resubmittal",
                "ofc",
                "stop work",
                "plan check",
                "plancheck",
                "online",
            )
        ):
            return "In Review"
    return None


def _expected_status(d: dict) -> Optional[str]:
    """Derive STATUS_NORMALIZED from CaseStatus/PermitStatus with date overrides.

    Inactive terminal labels (Expired / Void / Cancel) are sticky even
    when FinalDate is present as a case-closure stamp. Explicit Finaled /
    Complete labels → Final. Otherwise a FinalDate/FinalizeDate strictly
    after IssueDate → Final (stale Issued shells). IssueDate → Active
    overrides review-pipeline labels (Applied / Applied Online /
    In Plancheck / Estimate when issuance is present).
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

    if _entity_date(d, "ApplyDate", "ApplyDate") is not pd.NaT:
        return "In Review"
    return None


def _dates_equal(a, b) -> bool:
    """Compare two datelike values at calendar-day resolution (UTC)."""
    da = _safe_to_datetime(a)
    db = _safe_to_datetime(b)
    if da is pd.NaT or db is pd.NaT:
        return False
    return da.date() == db.date()


# ── Per-record repair logic ─────────────────────────────────────────────────

def _repair_record(row, d: dict, repairs: dict):
    """Populate *repairs* with corrected values for a single record."""
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
    if apply is not pd.NaT:
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
        if issue is not pd.NaT and not _dates_equal(current_permit, issue):
            repairs["PERMIT_DATE"] = issue
            repairs["PERMIT_DATE_FLAG"] = "FIXED"
        elif effective_status == "In Review" and not _is_issued(d):
            # Clear spurious permit dates on non-issued review rows.
            repairs["PERMIT_DATE"] = pd.NaT
            repairs["PERMIT_DATE_FLAG"] = "FIXED"
    elif effective_status in ("Active", "Final") and issue is not pd.NaT:
        repairs["PERMIT_DATE"] = issue
        repairs["PERMIT_DATE_FLAG"] = "FILLED"

    # -- FINAL_DATE (finaled / FinalDate; not ExpireDate) --
    # Non-Final statuses often carry junk FinalDate stamps; only keep
    # FINAL_DATE when status is Final.
    final = _raw_final_stamp(d)
    if final is pd.NaT:
        final = _final_inspection_date(d)
    current_final = row["FINAL_DATE"]

    if effective_status == "Final":
        if final is not pd.NaT:
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
    Murrieta permit records using information from the raw DATA JSON
    column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Murrieta".  Must
        contain columns STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE,
        FINAL_DATE, and DATA.

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
        (df["JURISDICTION"] == "Murrieta") & (df["STATE"] == "CA")
    ].copy()

    print(f"Murrieta records: {len(city):,}\n")

    repaired = data_repair(city)

    if AGENT_DATA_PATH:
        out_dir = Path(AGENT_DATA_PATH) / "repaired"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "permits_ca_murrieta_repaired.parquet"
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

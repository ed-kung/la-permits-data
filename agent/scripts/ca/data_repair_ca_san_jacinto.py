"""Data repair for San Jacinto (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

San Jacinto DATA is a Tyler EnerGov-style payload with top-level keys
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
  - Stale CaseStatus Issued shells that already carry FinalDate, or
    PermitStatus Complete with FinalizeDate only → FIXED to Final;
    FINAL_DATE FILLED from FinalizeDate when entity.FinalDate is null.
  - Approved encroachment shells left Active while carrying FinalDate
    → FIXED to Final.
  - Fees Due / Fees Paid review-pipeline rows that already carry
    IssueDate (+ FinalDate when present) → FIXED to Final or Active.
  - Fees Due shells with FinalDate ≈ ApplyDate and no IssueDate
    (junk closure stamp) stay In Review; spurious FINAL_DATE cleared.
  - Unmapped Visual Final (missing STATUS_NORMALIZED) → FILLED Final.
  - Unmapped Awaiting 48 Hour Engineering Inspection Notice → FILLED
    In Review.
  - Spurious FINAL_DATE on Inactive rows (Expired / Void / Plan
    Approval Expired closure stamps) → cleared.
  - CaseStatus Complete / Finaled stays Final even when FinalDate is
    absent (do not demote via IssueDate).

Not repairable / left as-is:
  - FILE_DATE already matches entity.ApplyDate for every sample row.
  - Mapped dates that are already populated match entity stamps at
    day resolution (aside from clearing spurious finals / filling
    FinalizeDate-only finals).
  - A few Final rows (Complete / Finaled / Approved-promoted) with
    null IssueDate → PERMIT_DATE stays missing; DATA has no alternate
    issuance stamp.
  - ExpireDate is a validity window, not a completion date.
  - FinalDate on Inactive labels is a case-closure stamp, not a
    permit finaled date (status stays Inactive; FINAL_DATE cleared).
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
    """Parse a date value as UTC, returning pd.NaT on failure."""
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
# Terminal Inactive and Complete/Finaled are authoritative when no
# conflicting date evidence applies; review-pipeline labels are a
# fallback when IssueDate / FinalDate are absent.
_STATUS_MAP = {
    # Final
    "Complete": "Final",
    "Finaled": "Final",
    "Visual Final": "Final",
    # Active
    "Issued": "Active",
    # Inactive
    "Expired": "Inactive",
    "Void": "Inactive",
    "Canceled": "Inactive",
    "Cancelled": "Inactive",
    "Withdrawn": "Inactive",
    "Denied": "Inactive",
    "Plan Approval Expired": "Inactive",
    # In Review (Approved = plan approval, not issuance, unless a
    # final stamp with real chronology is present)
    "Approved": "In Review",
    "In Review": "In Review",
    "Fees Due": "In Review",
    "Fees Paid": "In Review",
    "On Hold": "In Review",
    "Incomplete": "In Review",
    "Ready to Issue": "In Review",
    "Submitted": "In Review",
    "Submitted - Online": "In Review",
    "Resubmittal Required": "In Review",
    "Awaiting 48 Hour Engineering Inspection Notice": "In Review",
}

_INACTIVE_LABELS = {
    "Expired",
    "Void",
    "Canceled",
    "Cancelled",
    "Withdrawn",
    "Denied",
    "Plan Approval Expired",
}

_FINAL_LABELS = {
    "Complete",
    "Finaled",
    "Visual Final",
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


def _has_final_stamp(d: dict) -> bool:
    """True when FinalDate/FinalizeDate is credible completion evidence.

    Rejects same-day ApplyDate stamps with no IssueDate and no explicit
    Complete/Finaled/Visual Final label (seen on Fees Due solar shells
    where FinalDate is set within seconds of ApplyDate).
    """
    final = _raw_final_stamp(d)
    if final is pd.NaT:
        return False
    if _is_issued(d):
        return True
    if any(label in _FINAL_LABELS for label in _status_strings(d)):
        return True
    apply = _entity_date(d, "ApplyDate", "ApplyDate")
    if apply is pd.NaT:
        return True
    return final.date() > apply.date()


def _raw_labels(d: dict) -> list[str]:
    return _status_strings(d)


def _is_inactive_label(d: dict) -> bool:
    return any(label in _INACTIVE_LABELS for label in _raw_labels(d))


def _mapped_status(d: dict) -> Optional[str]:
    for raw in _raw_labels(d):
        mapped = _STATUS_MAP.get(raw)
        if mapped is not None:
            return mapped
        lower = raw.lower()
        if "complete" in lower or "finaled" in lower or lower.endswith(" final"):
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
            )
        ):
            return "Inactive"
        if lower.startswith("issued"):
            return "Active"
        if any(
            tok in lower
            for tok in (
                "review",
                "submitted",
                "fees due",
                "fees paid",
                "pending",
                "on hold",
                "incomplete",
                "ready to issue",
                "approved",
                "resubmittal",
                "awaiting",
            )
        ):
            return "In Review"
    return None


def _expected_status(d: dict) -> Optional[str]:
    """Derive STATUS_NORMALIZED from CaseStatus with date overrides.

    Inactive terminal labels (Expired / Void / Cancelled / Plan Approval
    Expired) are sticky even when FinalDate is present as a case-closure
    stamp. Credible FinalDate / FinalizeDate → Final overrides stale
    Issued / Approved / Fees Due labels. CaseStatus Complete / Finaled /
    Visual Final stays Final even when FinalDate is absent. Otherwise
    IssueDate → Active overrides review-pipeline labels.
    """
    if _is_inactive_label(d):
        return "Inactive"

    if _has_final_stamp(d):
        return "Final"

    mapped = _mapped_status(d)
    # Agency Complete / Finaled / Visual Final is authoritative even
    # without a FinalDate stamp.
    if mapped == "Final":
        return "Final"

    if _is_issued(d):
        return "Active"

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
    """Populate *repairs* with corrected values for a single San Jacinto record."""
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
    elif effective_status in ("Active", "Final") and issue is not pd.NaT:
        repairs["PERMIT_DATE"] = issue
        repairs["PERMIT_DATE_FLAG"] = "FILLED"

    # -- FINAL_DATE (finaled / FinalDate; not ExpireDate) --
    # Non-Final statuses sometimes carry FinalDate as a case-closure
    # or junk stamp; only keep FINAL_DATE when status is Final.
    final = _raw_final_stamp(d) if _has_final_stamp(d) else pd.NaT
    # For Final status, still prefer the raw stamp even if the
    # credibility filter was satisfied via a Final label alone.
    if effective_status == "Final":
        final = _raw_final_stamp(d)
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
    San Jacinto permit records using information from the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "San Jacinto".  Must contain
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
        (df["JURISDICTION"] == "San Jacinto") & (df["STATE"] == "CA")
    ].copy()

    print(f"San Jacinto records: {len(city):,}\n")

    repaired = data_repair(city)

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

    if AGENT_DATA_PATH:
        out_dir = Path(AGENT_DATA_PATH) / "repaired"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "permits_ca_san_jacinto_repaired.parquet"
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote repaired sample → {out_path}")

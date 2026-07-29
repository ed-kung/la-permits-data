"""Data repair for Lake Forest (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Lake Forest DATA is a Tyler EnerGov-style payload with top-level keys
``entity``, ``details``, ``contacts``, ``fees``, and
``processing_status``, plus an optional reviews bundle
(``reviews`` / ``holds`` / ``attachments`` / ``more_info``). Two
key-set variants appear in the sample:

  - entity_fees:          entity + details + fees (+ contacts,
                          processing_status)
  - entity_fees_reviews:  entity_fees plus reviews/holds/attachments/
                          more_info

Canonical fields live under ``entity`` (with details fallbacks):
  - CaseStatus / details.PermitStatus  → STATUS_NORMALIZED
  - ApplyDate                          → FILE_DATE
  - IssueDate                          → PERMIT_DATE
  - FinalDate (fallback: details.FinalizeDate) → FINAL_DATE

Known issues repaired:
  - Missing STATUS_NORMALIZED for CaseStatus ``Active - Expired``
    (9 rows) → FILLED Inactive.
  - In Review (Received Online / Initiated) shells with Issued=True
    / valid IssueDate → FIXED to Active.
  - Active shells that already carry FinalDate / FinalizeDate →
    FIXED to Final (status lag behind completion stamp).
  - Spurious FINAL_DATE on Inactive (Expired / Void) and residual
    non-Final rows copied from entity.FinalDate as a case-closure
    stamp → cleared.

Not repairable / left as-is:
  - FILE_DATE already matches entity.ApplyDate for every sample row.
  - PERMIT_DATE already matches IssueDate when both present; sentinel
    IssueDate ``2999-01-01`` is rejected by the date window, so one
    Active grading shell and a few Void/Expired shells stay without
    PERMIT_DATE.
  - 21 Closed - Finaled rows have null FinalDate / FinalizeDate and
    empty processing_status → FINAL_DATE stays missing.
  - ExpireDate is a validity window, not a completion date.
  - Chronology inversions (PERMIT < FILE, FINAL < PERMIT) mirror
    inverted Apply/Issue/Final timestamps already present in entity.
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
_STATUS_MAP = {
    # Final
    "Closed - Finaled": "Final",
    # Active
    "Active": "Active",
    # Inactive
    "Active - Expired": "Inactive",
    "Closed - Expired": "Inactive",
    "Closed - Withdrawn": "Inactive",
    "Void": "Inactive",
    # In Review
    "Received Online": "In Review",
    "Initiated": "In Review",
    "Ready to Issue": "In Review",
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
    details = d.get("details") if isinstance(d.get("details"), dict) else {}
    if details.get("Issued") is True:
        # Still require a usable IssueDate so 2999 sentinels do not count.
        if _entity_date(d, "IssueDate", "IssueDate") is not pd.NaT:
            return True
        # Issued=True with only a sentinel IssueDate is not real issuance.
        return False
    return _entity_date(d, "IssueDate", "IssueDate") is not pd.NaT


def _has_final_stamp(d: dict) -> bool:
    return _entity_date(d, "FinalDate", "FinalizeDate") is not pd.NaT


def _base_status(d: dict) -> Optional[str]:
    for raw in _status_strings(d):
        mapped = _STATUS_MAP.get(raw)
        if mapped is not None:
            return mapped
        lower = raw.lower()
        if "finaled" in lower or lower.startswith("completed"):
            return "Final"
        if "expired" in lower or "withdrawn" in lower or "void" in lower:
            return "Inactive"
        if "ready to issue" in lower or "received" in lower or "initiated" in lower:
            return "In Review"
        if lower == "active" or lower.startswith("issued"):
            return "Active"
    return None


def _expected_status(d: dict) -> Optional[str]:
    """Map CaseStatus / PermitStatus; upgrade on issuance / final stamps.

    Inactive terminal labels (Expired / Void / Withdrawn / Active -
    Expired) are sticky. In Review shells with real issuance evidence
    promote to Active. Active shells with FinalDate / FinalizeDate
    promote to Final (CaseStatus lag).
    """
    mapped = _base_status(d)
    if mapped == "Inactive":
        return "Inactive"
    if mapped == "Final":
        return "Final"
    if mapped == "Active":
        if _has_final_stamp(d):
            return "Final"
        return "Active"
    if mapped == "In Review":
        if _is_issued(d):
            if _has_final_stamp(d):
                return "Final"
            return "Active"
        return "In Review"
    if mapped is not None:
        return mapped
    if _has_final_stamp(d):
        return "Final"
    if _is_issued(d):
        return "Active"
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
    """Populate *repairs* with corrected values for a single Lake Forest record."""
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
            repairs["PERMIT_DATE"] = pd.NaT
            repairs["PERMIT_DATE_FLAG"] = "FIXED"
    elif effective_status in ("Active", "Final") and issue is not pd.NaT:
        repairs["PERMIT_DATE"] = issue
        repairs["PERMIT_DATE_FLAG"] = "FILLED"

    # -- FINAL_DATE (finaled / FinalDate; not ExpireDate) --
    # Non-Final statuses sometimes carry FinalDate as a case-closure
    # stamp; only keep FINAL_DATE when status is Final.
    final = _entity_date(d, "FinalDate", "FinalizeDate")
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
    Lake Forest permit records using information from the raw DATA JSON
    column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Lake Forest".  Must contain
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
        (df["JURISDICTION"] == "Lake Forest") & (df["STATE"] == "CA")
    ].copy()

    print(f"Lake Forest records: {len(city):,}\n")

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
                "before": city.loc[mask, "STATUS_NORMALIZED"].fillna("(null)"),
                "after": repaired.loc[mask, "STATUS_NORMALIZED"].fillna("(null)"),
                "flag": repaired.loc[mask, "STATUS_NORMALIZED_FLAG"],
            })
            .value_counts(dropna=False)
            .reset_index(name="n")
        )
        for _, trow in transitions.iterrows():
            print(
                f"  {str(trow['before']):15s} → {str(trow['after']):15s} "
                f"[{trow['flag']}]: {trow['n']:>4,}"
            )
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
    print(
        f"  FILE > PERMIT: "
        f"{(both_fp & (fd.dt.normalize() > pd_.dt.normalize())).sum()}"
    )
    print(
        f"  PERMIT > FINAL: "
        f"{(both_pf & (pd_.dt.normalize() > ff.dt.normalize())).sum()}"
    )

    if AGENT_DATA_PATH:
        out_dir = Path(AGENT_DATA_PATH) / "repaired"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "permits_ca_lake_forest_repaired.parquet"
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote repaired sample → {out_path}")

"""Data repair for Mission Viejo (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Mission Viejo DATA is a Tyler EnerGov-style payload with top-level keys
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
  - Stale ``Issued`` shells that already carry a credible FinalDate /
    FinalizeDate → FIXED to Final (upstream left them Active).
  - ``Fees Due`` / ``In Review`` / ``Stop Work Order`` shells that
    already carry IssueDate → FIXED to Active.
  - Sentinel ``1900-01-01`` values in PERMIT_DATE / FINAL_DATE (EnerGov
    null placeholders) → cleared (FIXED); Final rows with only a
    sentinel FinalDate keep status Final but lose the junk FINAL_DATE.
  - Spurious FINAL_DATE on non-Final rows (Active / In Review /
    Inactive closure or sentinel stamps) → cleared.

Not repairable / left as-is:
  - FILE_DATE already matches entity.ApplyDate for every sample row.
  - One CaseStatus ``Final`` row has only sentinel FinalDate → stays
    Final with null FINAL_DATE (agency label authoritative).
  - Inactive / In Review shells with null IssueDate → PERMIT_DATE
    stays missing.
  - ExpireDate is a validity window, not a completion date.
  - FinalDate on Inactive / Expired / Void / Cancelled labels is a
    case-closure stamp, not a permit finaled date (status stays
    Inactive; FINAL_DATE cleared).
"""

from __future__ import annotations

import json
import math
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
    # EnerGov uses 1900-01-01 as a null placeholder.
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
    "Final": "Final",
    "Finaled": "Final",
    "Complete": "Final",
    # Active
    "Issued": "Active",
    "Active": "Active",
    # Inactive
    "Expired": "Inactive",
    "Voided": "Inactive",
    "Void": "Inactive",
    "Canceled": "Inactive",
    "Cancelled": "Inactive",
    "Withdrawn": "Inactive",
    "Denied": "Inactive",
    "Inactive": "Inactive",
    "Approval Expired": "Inactive",
    "Application Expired": "Inactive",
    # In Review
    "Approved": "In Review",
    "In Review": "In Review",
    "Fees Due": "In Review",
    "Fees Paid": "In Review",
    "On Hold": "In Review",
    "Ready to Issue": "In Review",
    "Submitted": "In Review",
    "Submitted - Online": "In Review",
    "Submitted Online - Intake": "In Review",
    "Stop Work Order": "In Review",
}

_INACTIVE_LABELS = {
    "Expired",
    "Voided",
    "Void",
    "Canceled",
    "Cancelled",
    "Withdrawn",
    "Denied",
    "Inactive",
    "Approval Expired",
    "Application Expired",
}

_FINAL_LABELS = {
    "Final",
    "Finaled",
    "Complete",
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
    Final/Finaled/Complete label (junk closure stamps). Sentinel 1900
    dates are already filtered by ``_safe_to_datetime``.
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
        if (
            "complete" in lower
            or "finaled" in lower
            or lower == "final"
            or lower.endswith(" final")
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
            )
        ):
            return "Inactive"
        if lower.startswith("issued") or lower == "active":
            return "Active"
        if any(
            tok in lower
            for tok in (
                "review",
                "submitted",
                "received",
                "fees due",
                "fees paid",
                "pending",
                "on hold",
                "incomplete",
                "ready to issue",
                "approved",
                "resubmit",
                "invoiced",
                "applied",
                "awaiting",
                "intake",
                "stop work",
            )
        ):
            return "In Review"
    return None


def _expected_status(d: dict) -> Optional[str]:
    """Derive STATUS_NORMALIZED from CaseStatus with date overrides.

    Inactive terminal labels (Expired / Void / Cancelled / Denied /
    Inactive) are sticky even when FinalDate is present as a
    case-closure stamp. Credible FinalDate / FinalizeDate → Final
    overrides stale Issued / review labels. CaseStatus Final /
    Finaled / Complete stays Final even when FinalDate is absent /
    sentinel. Otherwise IssueDate → Active overrides review-pipeline
    labels.
    """
    if _is_inactive_label(d):
        return "Inactive"

    if _has_final_stamp(d):
        return "Final"

    mapped = _mapped_status(d)
    # Agency Final / Finaled / Complete is authoritative even without
    # a FinalDate stamp.
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


def _col_date_ok(val) -> bool:
    """True when a column date is present and within the credible year range."""
    return _safe_to_datetime(val) is not pd.NaT


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
    # Sentinel 1900-01-01 values are treated as missing.
    issue = _entity_date(d, "IssueDate", "IssueDate")
    current_permit = row["PERMIT_DATE"]
    permit_ok = _col_date_ok(current_permit)

    if issue is not pd.NaT:
        if pd.isna(current_permit):
            if effective_status in ("Active", "Final"):
                repairs["PERMIT_DATE"] = issue
                repairs["PERMIT_DATE_FLAG"] = "FILLED"
        elif not permit_ok or not _dates_equal(current_permit, issue):
            repairs["PERMIT_DATE"] = issue
            repairs["PERMIT_DATE_FLAG"] = "FIXED"
    elif not pd.isna(current_permit):
        # No credible IssueDate: clear sentinel / leftover permit dates.
        repairs["PERMIT_DATE"] = pd.NaT
        repairs["PERMIT_DATE_FLAG"] = "FIXED"

    # -- FINAL_DATE (finaled / FinalDate; not ExpireDate) --
    # Non-Final statuses sometimes carry FinalDate as a case-closure
    # or 1900 sentinel stamp; only keep FINAL_DATE when status is Final.
    final = _raw_final_stamp(d)
    current_final = row["FINAL_DATE"]
    final_ok = _col_date_ok(current_final)

    if effective_status == "Final":
        if final is not pd.NaT:
            if pd.isna(current_final) or not final_ok:
                repairs["FINAL_DATE"] = final
                repairs["FINAL_DATE_FLAG"] = (
                    "FILLED" if pd.isna(current_final) else "FIXED"
                )
            elif not _dates_equal(current_final, final):
                repairs["FINAL_DATE"] = final
                repairs["FINAL_DATE_FLAG"] = "FIXED"
        elif not pd.isna(current_final):
            # Agency Final/Complete label but only sentinel / junk stamp.
            repairs["FINAL_DATE"] = pd.NaT
            repairs["FINAL_DATE_FLAG"] = "FIXED"
    elif not pd.isna(current_final):
        repairs["FINAL_DATE"] = pd.NaT
        repairs["FINAL_DATE_FLAG"] = "FIXED"


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Mission Viejo permit records using information from the raw DATA JSON.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Mission Viejo".  Must contain
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
        (df["JURISDICTION"] == "Mission Viejo") & (df["STATE"] == "CA")
    ].copy()

    print(f"Mission Viejo records: {len(city):,}\n")

    repaired = data_repair(city)

    if AGENT_DATA_PATH:
        out_dir = Path(AGENT_DATA_PATH) / "repaired"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "permits_ca_mission_viejo_repaired.parquet"
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
        # Also count sentinel years in the raw column as effectively missing
        before_dt = pd.to_datetime(city[field], utc=True, errors="coerce")
        before_eff = (
            before_missing
            + ((before_dt.notna()) & (before_dt.dt.year < _MIN_YEAR)).sum()
        )
        print(
            f"  Missing before: {before_missing:>4,}   "
            f"Missing after: {after_missing:>4,}"
        )
        print(f"  Effective missing before (incl. <{_MIN_YEAR}): {before_eff:>4,}")
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

    print("\nFINAL_DATE_FLAG breakdown:")
    print(repaired["FINAL_DATE_FLAG"].value_counts(dropna=False).to_string())
    print("\nPERMIT_DATE_FLAG breakdown:")
    print(repaired["PERMIT_DATE_FLAG"].value_counts(dropna=False).to_string())

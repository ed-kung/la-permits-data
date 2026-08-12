"""Data repair for Marco Island (FL) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Marco Island DATA is a Tyler EnerGov payload with top-level keys
contacts, details, entity, fees, processing_status (always null in this
sample), and optionally reviews / holds / attachments / more_info.

Canonical fields:

  - entity.CaseStatus (fallback details.PermitStatus)
      → STATUS_NORMALIZED
  - entity.ApplyDate (fallback details.ApplyDate) → FILE_DATE
  - entity.IssueDate (fallback details.IssueDate) → PERMIT_DATE
  - entity.FinalDate (fallback details.FinalizeDate)
      → FINAL_DATE

Key-set variants (INFERRED_SCHEMA prefixes):
  - energov_full: extra reviews/holds/attachments/more_info
  - energov:      fees present, no review extras

Content suffixes further split by which canonical dates are populated
(``_issued_finaled``, ``_issued``, ``_finaled``, ``_applied``,
``_status_only``).

Known issues repaired:
  - Null STATUS_NORMALIZED for Estoppel Closed, Book Permit - UNISSUED,
    WWP Resolved / Permit Needed, Ready - Contractor Notified (+ Digital),
    APP HOLD / Application Hold, MS - PHASE 1, SWO Issued, and a few
    stale STATUS_ORIGINAL mismatches → FILLED / FIXED from CaseStatus.
  - Misclassified CaseStatus rows (Permit Complete→Active/Inactive,
    Permit Active→In Review, Permit Expired/Void→Active, etc.) FIXED.
  - Application Approved always carries IssueDate here → Active (not
    In Review).
  - Missing PERMIT_DATE on Active/Final/Inactive filled from IssueDate.
  - Spurious FINAL_DATE on non-Final (void/cancel FinalDate stamps)
    cleared; Final rows filled from FinalDate / FinalizeDate.

Not repairable from DATA:
  - FILE_DATE already matches ApplyDate for every sample row.
  - processing_status is always null → no inspection-based FINAL_DATE
    fallback.
  - ~4 Final Permit Complete/Closed shells lack a usable IssueDate →
    PERMIT_DATE stays missing.
  - ~3 Permit Closed + ~41 Estoppel Closed Final rows lack FinalDate →
    FINAL_DATE stays missing.
  - One Permit Complete FinalDate year 2916 is rejected as out-of-range.
"""

from __future__ import annotations

import json
import math
from typing import Optional

import numpy as np
import pandas as pd


_MIN_YEAR = 1980
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
        try:
            parsed = json.loads(data)
        except (json.JSONDecodeError, TypeError):
            return None
        return parsed if isinstance(parsed, dict) else None
    return data if isinstance(data, dict) else None


def _safe_to_datetime(val):
    """Parse a date value, returning pd.NaT on failure / out-of-range."""
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return pd.NaT
    if isinstance(val, dict):
        return pd.NaT
    if isinstance(val, str):
        s = val.strip()
        if not s or s.upper() in {
            "TBD", "NULL", "NONE", "N/A", "NA", "NAN",
            "00/00/0000", "0/0/0000",
        }:
            return pd.NaT
        if s.startswith("0001-01-01"):
            return pd.NaT
    try:
        dt = pd.to_datetime(val, utc=True, errors="coerce")
    except (ValueError, TypeError, OverflowError):
        return pd.NaT
    if pd.isna(dt):
        return pd.NaT
    year = int(dt.year)
    if year < _MIN_YEAR or year > _MAX_YEAR:
        return pd.NaT
    return dt.tz_convert("UTC").tz_localize(None)


def _dates_equal(a, b) -> bool:
    """Compare two datelike values at calendar-day resolution."""
    da = _safe_to_datetime(a)
    db = _safe_to_datetime(b)
    if da is pd.NaT or db is pd.NaT or pd.isna(da) or pd.isna(db):
        return False
    return pd.Timestamp(da).normalize() == pd.Timestamp(db).normalize()


def _present(dt) -> bool:
    return dt is not pd.NaT and not pd.isna(dt)


# ── EnerGov extractors ───────────────────────────────────────────────────────

def _case_status(d: dict) -> Optional[str]:
    entity = d.get("entity") if isinstance(d.get("entity"), dict) else {}
    details = d.get("details") if isinstance(d.get("details"), dict) else {}
    status = entity.get("CaseStatus") or details.get("PermitStatus")
    if status is None:
        return None
    status = str(status).strip()
    return status or None


def _entity_date(d: dict, entity_key: str, *detail_keys: str):
    """Naive-UTC datetime from entity.<key>, else first non-null details key."""
    entity = d.get("entity") if isinstance(d.get("entity"), dict) else {}
    dt = _safe_to_datetime(entity.get(entity_key))
    if _present(dt):
        return dt
    details = d.get("details") if isinstance(d.get("details"), dict) else {}
    for key in detail_keys:
        dt = _safe_to_datetime(details.get(key))
        if _present(dt):
            return dt
    return pd.NaT


# ── Schema classification ────────────────────────────────────────────────────

def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())
    if "entity" not in keys:
        return "unknown"

    has_extra = bool(keys & {"reviews", "holds", "attachments", "more_info"})
    base = "energov_full" if has_extra else "energov"

    apply = _entity_date(data_dict, "ApplyDate", "ApplyDate")
    issue = _entity_date(data_dict, "IssueDate", "IssueDate")
    final = _entity_date(data_dict, "FinalDate", "FinalizeDate")
    has_apply = _present(apply)
    has_issue = _present(issue)
    has_final = _present(final)

    if has_issue and has_final:
        return f"{base}_issued_finaled"
    if has_issue:
        return f"{base}_issued"
    if has_final:
        return f"{base}_finaled"
    if has_apply:
        return f"{base}_applied"
    return f"{base}_status_only"


# ── Status mapping ───────────────────────────────────────────────────────────

# Exact CaseStatus → STATUS_NORMALIZED (case-sensitive keys; lookup is
# case-insensitive via _expected_status).
_STATUS_MAP = {
    # Final — completed / closed workflows
    "Permit Complete": "Final",
    "Permit Closed": "Final",
    "Estoppel Closed": "Final",
    "WWP Resolved": "Final",
    # Active — issued / open enforcement
    "Permit Active": "Active",
    "WWP Permit Needed": "Active",
    "SWO Issued": "Active",
    # Application Approved always has IssueDate in this sample → Active
    "Application Approved": "Active",
    # Inactive
    "Permit Expired": "Inactive",
    "Permit Void": "Inactive",
    "Application Voided": "Inactive",
    # In Review — pre-issuance / hold / ready-to-issue
    "Application Review": "In Review",
    "Application Hold": "In Review",
    "APP HOLD - INSUFFICIENT DOCUMENTS": "In Review",
    "Internet Submit - PENDING": "In Review",
    "Request in Process": "In Review",
    "Book Permit - UNISSUED": "In Review",
    "Ready - Contractor Notified": "In Review",
    "Ready - Contractor Notified - Digital": "In Review",
    "MS - PHASE 1 - REPORT RECEIVED": "In Review",
}


def _expected_status(d: dict) -> Optional[str]:
    raw = _case_status(d)
    if raw is None:
        return None
    if raw in _STATUS_MAP:
        return _STATUS_MAP[raw]
    for key, val in _STATUS_MAP.items():
        if key.lower() == raw.lower():
            return val
    return None


def _apply_status(repairs: dict, current, expected: Optional[str]) -> Optional[str]:
    if expected is None:
        return None if pd.isna(current) else current
    if pd.isna(current):
        repairs["STATUS_NORMALIZED"] = expected
        repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"
    elif current != expected:
        repairs["STATUS_NORMALIZED"] = expected
        repairs["STATUS_NORMALIZED_FLAG"] = "FIXED"
    return repairs.get("STATUS_NORMALIZED", current)


def _apply_date(repairs: dict, row, field: str, candidate) -> None:
    cand = _safe_to_datetime(candidate)
    if not _present(cand):
        return
    current = row[field]
    if pd.isna(current):
        repairs[field] = cand
        repairs[f"{field}_FLAG"] = "FILLED"
        return
    if not _dates_equal(current, cand):
        repairs[field] = cand
        repairs[f"{field}_FLAG"] = "FIXED"


def _clear_date(repairs: dict, row, field: str) -> None:
    current = repairs.get(field, row[field])
    if pd.isna(current):
        return
    repairs[field] = pd.NaT
    repairs[f"{field}_FLAG"] = "FIXED"


# ── Per-record repair ────────────────────────────────────────────────────────

def _repair_record(row, d: dict, repairs: dict) -> None:
    expected = _expected_status(d)
    effective_status = _apply_status(repairs, row["STATUS_NORMALIZED"], expected)

    apply = _entity_date(d, "ApplyDate", "ApplyDate")
    issue = _entity_date(d, "IssueDate", "IssueDate")
    final = _entity_date(d, "FinalDate", "FinalizeDate")

    # FILE_DATE ← ApplyDate (fallback IssueDate if apply somehow blank)
    file_src = apply if _present(apply) else issue
    if _present(file_src):
        _apply_date(repairs, row, "FILE_DATE", file_src)

    # PERMIT_DATE ← IssueDate for issued / completed / expired statuses.
    if _present(issue):
        if effective_status in ("Active", "Final", "Inactive"):
            _apply_date(repairs, row, "PERMIT_DATE", issue)
        elif effective_status == "In Review":
            _clear_date(repairs, row, "PERMIT_DATE")
    elif effective_status == "In Review":
        _clear_date(repairs, row, "PERMIT_DATE")

    # FINAL_DATE ← FinalDate / FinalizeDate for Final only; clear otherwise.
    # (processing_status is null in this sample — no inspection fallback.)
    if effective_status == "Final":
        if _present(final):
            _apply_date(repairs, row, "FINAL_DATE", final)
    else:
        _clear_date(repairs, row, "FINAL_DATE")


# ── Main entry point ─────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Marco Island permit records using the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Marco Island".  Must contain
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

    for col in ("FILE_DATE", "PERMIT_DATE", "FINAL_DATE"):
        out[col] = pd.to_datetime(out[col], errors="coerce")

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
        if d is None or schema in ("missing", "unknown"):
            continue

        repairs: dict = {}
        _repair_record(row, d, repairs)

        for key, value in repairs.items():
            out.at[idx, key] = value

    for col in ("FILE_DATE", "PERMIT_DATE", "FINAL_DATE"):
        out[col] = pd.to_datetime(out[col], errors="coerce")

    return out


# ── CLI: run standalone to preview repair stats ─────────────────────────────

if __name__ == "__main__":
    import os
    from dotenv import load_dotenv, find_dotenv

    load_dotenv(find_dotenv())
    MY_DATA_PATH = os.getenv("MY_DATA_PATH")
    AGENT_DATA_PATH = os.getenv("AGENT_DATA_PATH")
    filepath = os.path.join(
        MY_DATA_PATH, "processed_data", "permits_fl_sample.parquet"
    )
    df = pd.read_parquet(filepath)
    city = df[df["JURISDICTION"] == "Marco Island"].copy()

    print(f"Marco Island records: {len(city):,}\n")

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

    print("\nSTATUS_NORMALIZED changes (before → after):")
    changed = city["STATUS_NORMALIZED"].fillna("__NA__") != repaired[
        "STATUS_NORMALIZED"
    ].fillna("__NA__")
    if changed.any():
        tmp = pd.DataFrame(
            {
                "before": city.loc[changed, "STATUS_NORMALIZED"].fillna("__NA__"),
                "after": repaired.loc[changed, "STATUS_NORMALIZED"].fillna("__NA__"),
            }
        )
        print(tmp.value_counts().to_string())
    else:
        print("  (none)")

    print("\nFINAL_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FINAL_DATE"].notna().sum()
        pct = n_has / len(sub) if len(sub) else 0.0
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({pct:.1%})")

    print("\nPERMIT_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["PERMIT_DATE"].notna().sum()
        pct = n_has / len(sub) if len(sub) else 0.0
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({pct:.1%})")

    print("\nFILE_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FILE_DATE"].notna().sum()
        pct = n_has / len(sub) if len(sub) else 0.0
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({pct:.1%})")

    final_miss = repaired[
        (repaired["STATUS_NORMALIZED"] == "Final") & repaired["FINAL_DATE"].isna()
    ]
    print(f"\nFinal still missing FINAL_DATE: {len(final_miss)}")
    if len(final_miss):
        from collections import Counter

        ps_counts = Counter()
        for idx in final_miss.index:
            d = _safe_parse(repaired.at[idx, "DATA"])
            if d is None:
                continue
            raw = (_case_status(d) or "").strip() or "__EMPTY__"
            ps_counts[raw] += 1
        print("  by CaseStatus:", dict(ps_counts))

    status_null = repaired["STATUS_NORMALIZED"].isna().sum()
    print(f"\nSTATUS_NORMALIZED still null: {status_null}")

    af_miss = repaired[
        repaired["STATUS_NORMALIZED"].isin(["Active", "Final"])
        & repaired["PERMIT_DATE"].isna()
    ]
    print(f"Active/Final still missing PERMIT_DATE: {len(af_miss)}")
    if len(af_miss):
        from collections import Counter

        ps_counts = Counter()
        for idx in af_miss.index:
            d = _safe_parse(repaired.at[idx, "DATA"])
            if d is None:
                continue
            raw = (_case_status(d) or "").strip() or "__EMPTY__"
            ps_counts[raw] += 1
        print("  by CaseStatus:", dict(ps_counts))

    if AGENT_DATA_PATH:
        out_path = os.path.join(
            AGENT_DATA_PATH, "marco_island_repaired_sample.parquet"
        )
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote repaired sample → {out_path}")

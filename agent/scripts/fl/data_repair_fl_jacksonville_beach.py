"""Data repair for Jacksonville Beach (FL) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Jacksonville Beach DATA is the same city-portal family as Tarpon Springs /
Lake Worth Beach / Winter Garden / Oviedo, with two sub-schemas in this
sample:

  - permit_status:  detail/fees plus permit_status_detail,
                    insp_status_detail (full permit + inspections)
  - fees_detail:    detail + fees + fees_total only (Application Date /
                    Application Status; no issue/inspection blocks)

Canonical mappings:
  - Inactive or In-Review Application Status
    (INACTIVE - OVER 180 DAYS / REJECTED / …;
    IN PLAN REVIEW / CORRECTIONS REQUIRED / …)
    overrides permit status; else Application/Permit
    Status (or Status) on permit_status_detail; else
    Application Status / Status on detail
                                                → STATUS_NORMALIZED
  - Application Date                            → FILE_DATE
  - Permit Issue Date                           → PERMIT_DATE
  - Latest successful (APPROVED / WAIVED /
    PARTIALLY APPROVED / APPROVED WITH EXCEPTION)
    inspection excluding Notice of Commencement
    (Final rows only)                           → FINAL_DATE

Known issues repaired:
  - STATUS_NORMALIZED null on every sample row
    (STATUS_ORIGINAL also null) → FILLED from portal
    Application Status / Application/Permit Status.
  - PERMIT_DATE / FINAL_DATE null on every sample
    row → FILLED from Permit Issue Date /
    successful inspections where applicable.
  - Spurious PERMIT_DATE on In Review → cleared.
  - FINAL_DATE cleared on non-Final.

Not repairable from DATA:
  - fees_detail rows have Application Date / Status
    but no Issue Date / inspections → PERMIT_DATE /
    FINAL_DATE stay missing.
  - Final rows with empty / non-success
    insp_status_detail (esp. CLOSED-FS 553.79(17)(C)
    batch closes) → FINAL_DATE stays missing.
    Status Date is not used: it is dominated by
    administrative batch stamps (e.g. 01/02/14).
  - Active/Final with blank Permit Issue Date →
    PERMIT_DATE stays missing.
"""

from __future__ import annotations

import json
import math
from typing import Optional

import numpy as np
import pandas as pd


_MIN_YEAR = 1980
_MAX_YEAR = 2035

# Inspection results treated as successful completion signals.
_SUCCESS_RESULTS = {
    "APPROVED",
    "APPROVED WITH EXCEPTION",
    "PARTIALLY APPROVED",
    "WAIVED",
}

# Application-level terminal statuses that should win over a CLOSED
# permit status (portal often leaves Application/Permit Status as
# CLOSED after inactivity / reject / withdraw).
_INACTIVE_APP_STATUSES = {
    "INACTIVE - OVER 180 DAYS",
    "INACTIVE - FEES DUE",
    "REJECTED",
    "CLOSED, PERMIT NOT ISSUED",
    "WITHDRAWN APPLICATION",
    "WITHDRAWN",
    "REVOKED",
    "INSUFFICIENT APPLICATION",
    "DEVELOPMENT REVIEW-DENIED",
    "CLOSED, NO WORK COMMENCED",
    "VARIANCE DENIED",
    "TEST",
}

# Pre-issuance / review Application Status values that should win over a
# stale CLOSED Application/Permit Status on permit_status_detail.
_IN_REVIEW_APP_STATUSES = {
    "IN PLAN REVIEW",
    "CORRECTIONS REQUIRED",
    "PENDING SUFFICIENCY RVW",
    "APPROVED,PENDING ISSUANCE",
    "PENDING APPROVAL",
    "PLAN CHECK/REVIEW FEE DUE",
}


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
    """Parse a date value, returning pd.NaT on failure / blanks / OOR."""
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
        if s.startswith("0001-01-01") or s.startswith("1900-01-01"):
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
    if getattr(dt, "tzinfo", None) is not None:
        dt = dt.tz_convert("UTC").tz_localize(None)
    return dt


def _present(dt) -> bool:
    return dt is not pd.NaT and not pd.isna(dt)


def _dates_equal(a, b) -> bool:
    """Compare two datelike values at calendar-day resolution."""
    da = _safe_to_datetime(a)
    db = _safe_to_datetime(b)
    if not _present(da) or not _present(db):
        return False
    return pd.Timestamp(da).normalize() == pd.Timestamp(db).normalize()


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())
    if "permit_status_detail" in keys:
        return "permit_status"
    if "detail" in keys and "fees" in keys:
        return "fees_detail"
    return "unknown"


def _apply_status(repairs: dict, current, expected: Optional[str]) -> Optional[str]:
    """Apply expected STATUS_NORMALIZED; return effective status."""
    if expected is None:
        if pd.isna(current):
            return None
        return current

    if pd.isna(current):
        repairs["STATUS_NORMALIZED"] = expected
        repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"
    elif current != expected:
        repairs["STATUS_NORMALIZED"] = expected
        repairs["STATUS_NORMALIZED_FLAG"] = "FIXED"

    return repairs.get("STATUS_NORMALIZED", current)


def _apply_date(repairs: dict, row, field: str, candidate) -> None:
    """Fill or fix *field* from *candidate* datetime (pd.NaT = no candidate)."""
    cand = _safe_to_datetime(candidate)
    if not _present(cand):
        return

    current = row[field]
    if pd.isna(current):
        repairs[field] = cand
        repairs[f"{field}_FLAG"] = "FILLED"
    elif not _dates_equal(current, cand):
        repairs[field] = cand
        repairs[f"{field}_FLAG"] = "FIXED"


def _clear_date(repairs: dict, row, field: str) -> None:
    """Clear a spurious date value."""
    current = repairs.get(field, row[field])
    if pd.isna(current):
        return
    repairs[field] = pd.NaT
    repairs[f"{field}_FLAG"] = "FIXED"


# ── Status maps ──────────────────────────────────────────────────────────────

# Portal status strings (exact, then uppercased) → STATUS_NORMALIZED
_STATUS_MAP = {
    # Final / completed
    "FINAL INSPECTION COMPLETE": "Final",
    "CLOSED": "Final",
    "CLOSED BY REPORT": "Final",
    "ADMINISTRATIVELY CLOSED": "Final",
    "C.O. ISSUED": "Final",
    "TEMPORARY C.O. ISSUED": "Final",
    "CO ISSUED": "Final",
    "CERTIFICATE OF OCCUPANCY": "Final",
    "CERTIFICATE OF COMPLETION": "Final",
    "CERTIFICATE ISSUED": "Final",
    "PERMIT COMPLETE/CLOSED": "Final",
    "CLOSED-FS 553.79(17)(C)": "Final",
    "PROCESS COMPLETED-PLANNIN": "Final",
    "PROCESSED BY PUBLIC WORKS": "Final",
    "CONDITIONAL USE APPROVED": "Final",
    "VARIANCE APPROVED": "Final",
    "FINALED": "Final",
    # Active / issued
    "PERMIT PRINTED": "Active",
    "PERMIT ISSUED": "Active",
    "APPROVED FOR PERMIT": "Active",
    "ACTIVE - OUTSTANDING FEES": "Active",
    "ACTIVE/ON HOLD-REQURMNTS": "Active",
    # In review / pre-issuance / hold
    "TO BE ISSUED": "In Review",
    "APPROVED": "In Review",
    "APPROVED,PENDING ISSUANCE": "In Review",
    "PLAN CHECK": "In Review",
    "PLAN CHECK/REVIEW FEE DUE": "In Review",
    "PLAN REVIEW": "In Review",
    "PLANS BEING CHECKED": "In Review",
    "IN PLAN CHECK": "In Review",
    "IN PLAN REVIEW": "In Review",
    "CORRECTIONS REQUIRED": "In Review",
    "PENDING SUFFICIENCY RVW": "In Review",
    "PENDING APPROVAL": "In Review",
    "EPLAN REVIEW": "In Review",
    "ON HOLD": "In Review",
    "PENDING VERIFICATION": "In Review",
    "IN APPROVAL": "In Review",
    # Inactive
    "PERMIT REVOKED": "Inactive",
    "PERMIT EXPIRED": "Inactive",
    "PERMIT EXPIRED NO FINAL": "Inactive",
    "EXPIRED": "Inactive",
    "INACTIVE - OVER 180 DAYS": "Inactive",
    "INACTIVE - FEES DUE": "Inactive",
    "ABANDONED": "Inactive",
    "REJECTED": "Inactive",
    "DENIED": "Inactive",
    "DEVELOPMENT REVIEW-DENIED": "Inactive",
    "VARIANCE DENIED": "Inactive",
    "VOID": "Inactive",
    "VOIDED": "Inactive",
    "VOID-PERMIT NEVER ISSUED": "Inactive",
    "CANCELLED": "Inactive",
    "WITHDRAWN": "Inactive",
    "WITHDRAWN APPLICATION": "Inactive",
    "WITHDRAWN/CANCELLED": "Inactive",
    "CLOSED, PERMIT NOT ISSUED": "Inactive",
    "CLOSED, NO WORK COMMENCED": "Inactive",
    "INSUFFICIENT APPLICATION": "Inactive",
    "REVOKED": "Inactive",
    "TEST": "Inactive",
    "RETURNED": "Inactive",
}


def _map_status(raw: Optional[str]) -> Optional[str]:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    expected = _STATUS_MAP.get(text)
    if expected is not None:
        return expected
    return _STATUS_MAP.get(text.upper())


def _app_status(detail: dict) -> Optional[str]:
    """Application Status, with Status fallback (newer portal rows)."""
    if not isinstance(detail, dict):
        return None
    for key in ("Application Status", "Status"):
        val = detail.get(key)
        if val is None:
            continue
        text = str(val).strip()
        if text:
            return text
    return None


def _permit_status(detail: dict) -> Optional[str]:
    """Application/Permit Status, with Status fallback."""
    if not isinstance(detail, dict):
        return None
    for key in ("Application/Permit Status", "Status"):
        val = detail.get(key)
        if val is None:
            continue
        text = str(val).strip()
        if text:
            return text
    return None


def _expected_status(app_status: Optional[str], permit_status: Optional[str]) -> Optional[str]:
    """Resolve STATUS_NORMALIZED from application + permit status strings."""
    app_text = str(app_status or "").strip()
    app_upper = app_text.upper()
    if app_upper in {s.upper() for s in _INACTIVE_APP_STATUSES}:
        return "Inactive"
    if app_upper in {s.upper() for s in _IN_REVIEW_APP_STATUSES}:
        return "In Review"

    expected = _map_status(permit_status)
    if expected is not None:
        return expected
    return _map_status(app_status)


def _inspection_completion_date(insp_row: list):
    """Pick a completion date from one inspection row.

    Prefer result date (index 3); fall back to schedule date (index 1).
    When the two differ by ~1 year, treat one year as a typo and keep the
    later date (common portal off-by-one-year stamp).
    """
    sched = _safe_to_datetime(insp_row[1] if len(insp_row) > 1 else None)
    result = _safe_to_datetime(insp_row[3] if len(insp_row) > 3 else None)
    if _present(result) and _present(sched):
        delta = abs(
            (pd.Timestamp(sched).normalize() - pd.Timestamp(result).normalize()).days
        )
        if delta in (364, 365, 366):
            return max(pd.Timestamp(sched), pd.Timestamp(result))
        return result
    if _present(result):
        return result
    return sched


def _final_date_from_inspections(insp_detail, issue_date=None) -> pd.Timestamp:
    """Latest successful inspection date, excluding Notice of Commencement.

    If the chosen date falls before *issue_date*, retry using schedule
    dates only (guards against corrupted result-year stamps that are not
    exact ±1 year typos).
    """
    if not isinstance(insp_detail, list):
        return pd.NaT

    success_rows = []
    for row in insp_detail:
        if not isinstance(row, list) or len(row) < 3:
            continue
        name = str(row[0] or "")
        if "NOTICE OF COMMENCEMENT" in name.upper():
            continue
        result = str(row[2] or "").strip().upper()
        if result not in _SUCCESS_RESULTS:
            continue
        success_rows.append(row)

    if not success_rows:
        return pd.NaT

    dates = []
    for row in success_rows:
        dt = _inspection_completion_date(row)
        if _present(dt):
            dates.append(dt)
    if not dates:
        return pd.NaT

    chosen = max(dates)
    if _present(issue_date) and pd.Timestamp(chosen).normalize() < pd.Timestamp(
        issue_date
    ).normalize():
        sched_dates = []
        for row in success_rows:
            dt = _safe_to_datetime(row[1] if len(row) > 1 else None)
            if _present(dt):
                sched_dates.append(dt)
        if sched_dates:
            chosen = max(sched_dates)
    return chosen


def _application_date(d: dict, detail: dict):
    """Application Date from permit_status_detail or detail block."""
    for src in (detail, d.get("detail") if isinstance(d.get("detail"), dict) else {}):
        if not isinstance(src, dict):
            continue
        dt = _safe_to_datetime(src.get("Application Date"))
        if _present(dt):
            return dt
    return pd.NaT


def _issue_date(detail: dict):
    """Permit issuance date (Jacksonville Beach: Permit Issue Date)."""
    for key in ("Permit Issue Date", "Issue Date"):
        dt = _safe_to_datetime(detail.get(key))
        if _present(dt):
            return dt
    return pd.NaT


# ── Per-schema repair logic ─────────────────────────────────────────────────

def _repair_permit_status(row, d: dict, repairs: dict) -> None:
    """Repair a permit_status record (full portal permit + inspections)."""
    detail = d.get("permit_status_detail") or {}
    if not isinstance(detail, dict):
        detail = {}
    app_detail = d.get("detail") if isinstance(d.get("detail"), dict) else {}

    expected = _expected_status(
        _app_status(app_detail),
        _permit_status(detail),
    )
    effective_status = _apply_status(repairs, row["STATUS_NORMALIZED"], expected)

    # FILE_DATE ← Application Date
    _apply_date(repairs, row, "FILE_DATE", _application_date(d, detail))

    # PERMIT_DATE ← Permit Issue Date
    issue = _issue_date(detail)
    if effective_status == "In Review":
        _clear_date(repairs, row, "PERMIT_DATE")
    elif _present(issue) and effective_status in ("Active", "Final", "Inactive"):
        _apply_date(repairs, row, "PERMIT_DATE", issue)

    # FINAL_DATE ← latest non-NOC successful inspection (Final rows only).
    # Do not fall back to Status Date — it is often a batch admin stamp.
    final_src = _final_date_from_inspections(
        d.get("insp_status_detail"), issue_date=issue
    )
    if effective_status == "Final":
        if _present(final_src):
            _apply_date(repairs, row, "FINAL_DATE", final_src)
    else:
        _clear_date(repairs, row, "FINAL_DATE")


def _repair_fees_detail(row, d: dict, repairs: dict) -> None:
    """Repair a fees_detail record (detail/fees; no issue/inspections)."""
    detail = d.get("detail") or {}
    if not isinstance(detail, dict):
        detail = {}

    expected = _expected_status(_app_status(detail), None)
    effective_status = _apply_status(repairs, row["STATUS_NORMALIZED"], expected)

    _apply_date(repairs, row, "FILE_DATE", detail.get("Application Date"))

    # No Issue Date / inspection history in this schema.
    if effective_status == "In Review":
        _clear_date(repairs, row, "PERMIT_DATE")
    elif effective_status in ("Active", "Final", "Inactive"):
        _clear_date(repairs, row, "PERMIT_DATE")
    _clear_date(repairs, row, "FINAL_DATE")


# ── Main entry point ─────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Jacksonville Beach permit records using information from the raw DATA JSON.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Jacksonville Beach".  Must
        contain columns STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE,
        FINAL_DATE, and DATA.

    Returns
    -------
    pd.DataFrame
        Copy of *df* with corrected field values, an INFERRED_SCHEMA
        column naming the DATA JSON sub-schema identified for each
        record, and flag columns: STATUS_NORMALIZED_FLAG, FILE_DATE_FLAG,
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
        if schema == "permit_status":
            _repair_permit_status(row, d, repairs)
        elif schema == "fees_detail":
            _repair_fees_detail(row, d, repairs)

        for key, value in repairs.items():
            out.at[idx, key] = value

    for col in ("FILE_DATE", "PERMIT_DATE", "FINAL_DATE"):
        out[col] = pd.to_datetime(out[col], errors="coerce")

    return out


# ── CLI: run standalone to preview repair stats ─────────────────────────────

if __name__ == "__main__":
    import os

    from dotenv import load_dotenv

    load_dotenv("/Users/ekung/projects/la-permits-data/.env")
    MY_DATA_PATH = os.getenv("MY_DATA_PATH")
    AGENT_DATA_PATH = os.getenv("AGENT_DATA_PATH")
    filepath = os.path.join(
        MY_DATA_PATH, "processed_data", "permits_fl_sample.parquet"
    )
    df = pd.read_parquet(filepath)
    city = df[df["JURISDICTION"] == "Jacksonville Beach"].copy()

    print(f"Jacksonville Beach records: {len(city):,}\n")

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

    print("\nSTATUS_NORMALIZED fills by source status (app → normalized):")
    from collections import Counter

    fill_src = Counter()
    for idx in repaired.index:
        if repaired.at[idx, "STATUS_NORMALIZED_FLAG"] != "FILLED":
            continue
        d = _safe_parse(repaired.at[idx, "DATA"]) or {}
        app = _app_status(d.get("detail") if isinstance(d.get("detail"), dict) else {})
        psd = d.get("permit_status_detail") if isinstance(
            d.get("permit_status_detail"), dict
        ) else {}
        ps = _permit_status(psd)
        fill_src[(app, ps, repaired.at[idx, "STATUS_NORMALIZED"])] += 1
    for (app, ps, norm), n in fill_src.most_common(40):
        print(f"  {n:4d}  app={app!r:40s} psd={ps!r:30s} → {norm}")

    print("\nFILE_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FILE_DATE"].notna().sum()
        pct = n_has / len(sub) if len(sub) else 0.0
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({pct:.1%})")

    print("\nPERMIT_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["PERMIT_DATE"].notna().sum()
        pct = n_has / len(sub) if len(sub) else 0.0
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({pct:.1%})")

    print("\nFINAL_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FINAL_DATE"].notna().sum()
        pct = n_has / len(sub) if len(sub) else 0.0
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({pct:.1%})")

    final_miss = repaired[
        (repaired["STATUS_NORMALIZED"] == "Final") & repaired["FINAL_DATE"].isna()
    ]
    print(f"\nFinal still missing FINAL_DATE: {len(final_miss)}")
    if len(final_miss):
        miss_apps = Counter()
        for idx in final_miss.index:
            d = _safe_parse(repaired.at[idx, "DATA"]) or {}
            app = _app_status(
                d.get("detail") if isinstance(d.get("detail"), dict) else {}
            )
            miss_apps[app] += 1
        print("  by Application Status:")
        for k, v in miss_apps.most_common():
            print(f"    {v:4d}  {k!r}")

    status_null = repaired["STATUS_NORMALIZED"].isna().sum()
    print(f"STATUS_NORMALIZED still null: {status_null}")

    af_miss = repaired[
        repaired["STATUS_NORMALIZED"].isin(["Active", "Final"])
        & repaired["PERMIT_DATE"].isna()
    ]
    print(f"Active/Final still missing PERMIT_DATE: {len(af_miss)}")

    file_gt_permit = 0
    permit_gt_final = 0
    for idx in repaired.index:
        f = repaired.at[idx, "FILE_DATE"]
        p = repaired.at[idx, "PERMIT_DATE"]
        fin = repaired.at[idx, "FINAL_DATE"]
        if (
            pd.notna(f)
            and pd.notna(p)
            and pd.Timestamp(f).normalize() > pd.Timestamp(p).normalize()
        ):
            file_gt_permit += 1
        if (
            pd.notna(p)
            and pd.notna(fin)
            and pd.Timestamp(p).normalize() > pd.Timestamp(fin).normalize()
        ):
            permit_gt_final += 1
    print(f"\nFILE_DATE > PERMIT_DATE: {file_gt_permit}")
    print(f"PERMIT_DATE > FINAL_DATE: {permit_gt_final}")

    mismatch = 0
    n_issue = 0
    for idx in repaired.index:
        d = _safe_parse(repaired.at[idx, "DATA"])
        if d is None:
            continue
        psd = d.get("permit_status_detail")
        if not isinstance(psd, dict):
            continue
        issue = _issue_date(psd)
        p = repaired.at[idx, "PERMIT_DATE"]
        if _present(issue):
            n_issue += 1
            if pd.notna(p) and not _dates_equal(p, issue):
                mismatch += 1
    print(
        f"PERMIT_DATE ≠ Permit Issue Date (when both present): "
        f"{mismatch} (of {n_issue})"
    )

    n_file_eq_app = 0
    n_with_app = 0
    for idx in repaired.index:
        d = _safe_parse(repaired.at[idx, "DATA"]) or {}
        detail = d.get("detail") if isinstance(d.get("detail"), dict) else {}
        app = _safe_to_datetime(detail.get("Application Date"))
        if _present(app):
            n_with_app += 1
            if _dates_equal(repaired.at[idx, "FILE_DATE"], app):
                n_file_eq_app += 1
    print(f"FILE_DATE == Application Date: {n_file_eq_app} / {n_with_app}")

    if AGENT_DATA_PATH:
        out_path = os.path.join(
            AGENT_DATA_PATH, "jacksonville_beach_permits_repaired.parquet"
        )
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote {out_path}")

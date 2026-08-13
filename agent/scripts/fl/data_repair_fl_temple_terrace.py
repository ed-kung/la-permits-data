"""Data repair for Temple Terrace (FL) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Temple Terrace DATA is the same city-portal family as Lake Worth Beach /
Jacksonville Beach / Tarpon Springs, with two sub-schemas in this sample:

  - permit_status:  detail/fees plus permit_status_detail,
                    insp_status_detail (full permit + inspections)
  - fees_detail:    detail + fees + fees_total only (Application Date /
                    Application Status; no issue/inspection blocks)

Canonical mappings:
  - Inactive Application Status (VOID / …)
    overrides permit status; else
    Status for Permit Number; else Application Status
                                                → STATUS_NORMALIZED
  - Application Date                            → FILE_DATE
  - Issue Date                                  → PERMIT_DATE
  - Latest successful (APPROVED / COMPLETED /
    PARTIALLY APPROVED / APPROVED WITH EXCEPTION)
    inspection excluding Notice of Commencement
    (Final rows only)                           → FINAL_DATE

Known issues repaired:
  - STATUS_NORMALIZED null on fees_detail rows
    and one permit_status row → FILLED from
    Application Status / Status for Permit Number.
  - Stale STATUS_ORIGINAL mislabels (CLOSED /
    C.O. ISSUED / FINAL INSPECTION COMPLETE kept
    as Active because STATUS_ORIGINAL was still
    "permit printed") → FIXED from portal status.
  - PERMIT_DATE was populated from the portal
    "Permit Date" field (often a later admin /
    closeout stamp) instead of "Issue Date"
    → FIXED to Issue Date for Active / Final /
    Inactive.
  - Spurious PERMIT_DATE when Issue Date is blank
    (copied from "Permit Date") → cleared.
  - FINAL_DATE missing on Final rows that only
    have COMPLETED close-out inspections (e.g.
    EXPIRED PERMIT/CLOSE NO INSP) → FILLED;
    FINAL_DATE corrected when a later successful
    non-NOC inspection exists; cleared on non-Final.

Not repairable from DATA:
  - fees_detail rows have Application Date / Status
    but no Issue Date / inspections → PERMIT_DATE /
    FINAL_DATE stay missing (or are cleared).
  - CLOSED Final rows with empty / non-success
    insp_status_detail → FINAL_DATE stays missing.
  - Active/Final/Inactive with blank Issue Date →
    PERMIT_DATE stays missing (or is cleared if it
    only reflected "Permit Date").
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
# Temple Terrace uses COMPLETED for administrative close-outs
# (EXPIRED PERMIT/CLOSE NO INSP, CLOSE PERMIT NO INSP REQUIRED, …).
_SUCCESS_RESULTS = {
    "APPROVED",
    "APPROVED WITH EXCEPTION",
    "PARTIALLY APPROVED",
    "WAIVED",
    "COMPLETED",
}

# Application-level terminal statuses that should win over a CLOSED
# permit-number status (portal often leaves Status for Permit Number
# as CLOSED after void / expire / cancel).
_INACTIVE_APP_STATUSES = {
    "VOIDED",
    "VOID",
    "EXPIRED",
    "CANCELLED",
    "PERMIT REVOKED",
    "WITHDRAWN",
    "ABANDONED",
    "DENIED",
    "REJECTED",
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
    if val is None:
        return pd.NaT
    if isinstance(val, float) and math.isnan(val):
        return pd.NaT
    if isinstance(val, dict):
        return pd.NaT
    if isinstance(val, str):
        text = val.strip().replace("\xa0", " ")
        if not text:
            return pd.NaT
        if text.upper() in {
            "TBD", "NONE", "N/A", "NA", "NULL", "NAN",
            "00/00/0000", "0/0/0000",
        }:
            return pd.NaT
        if text.startswith("0001-01-01") or text.startswith("1900-01-01"):
            return pd.NaT
    elif not isinstance(val, str) and pd.isna(val):
        return pd.NaT
    try:
        dt = pd.to_datetime(val, errors="coerce")
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

# Portal status strings (uppercased) → STATUS_NORMALIZED
_STATUS_MAP = {
    # Final / completed
    "FINAL INSPECTION COMPLETE": "Final",
    "CLOSED": "Final",
    "CLOSED BY REPORT": "Final",
    "COMPLETE/CLOSED BY REPORT": "Final",
    "ADMINISTRATIVELY CLOSED": "Final",
    "C.O. ISSUED": "Final",
    "CO ISSUED": "Final",
    "CERT COMPLETION": "Final",
    "CERTIFICATE OF OCCUPANCY": "Final",
    "CERTIFICATE OF COMPLETION": "Final",
    "CERTIFICATE ISSUED": "Final",
    "FINALED": "Final",
    # Active / issued
    "PERMIT PRINTED": "Active",
    "PERMIT ISSUED": "Active",
    # In review / pre-issuance / hold
    "TO BE ISSUED": "In Review",
    "APPROVED": "In Review",
    "PLAN CHECK": "In Review",
    "PLAN REVIEW": "In Review",
    "PLANS BEING CHECKED": "In Review",
    "IN PLAN CHECK": "In Review",
    "EPLAN REVIEW": "In Review",
    "HOLD": "In Review",
    "ON HOLD": "In Review",
    "PENDING VERIFICATION": "In Review",
    "IN APPROVAL": "In Review",
    # Inactive
    "PERMIT REVOKED": "Inactive",
    "PERMIT EXPIRED": "Inactive",
    "PERMIT EXPIRED NO FINAL": "Inactive",
    "EXPIRED": "Inactive",
    "EXPIRED PERMIT LETTER": "Inactive",
    "ABANDONED": "Inactive",
    "REJECTED": "Inactive",
    "DENIED": "Inactive",
    "VOID": "Inactive",
    "VOIDED": "Inactive",
    "VOID-PERMIT NEVER ISSUED": "Inactive",
    "CANCELLED": "Inactive",
    "WITHDRAWN": "Inactive",
    "WITHDRAWN/CANCELLED": "Inactive",
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


def _expected_status(app_status: Optional[str], permit_status: Optional[str]) -> Optional[str]:
    """Resolve STATUS_NORMALIZED from application + permit status strings."""
    app_text = str(app_status or "").strip()
    if app_text.upper() in _INACTIVE_APP_STATUSES:
        return "Inactive"

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
    """Permit issuance date (Temple Terrace field name: Issue Date)."""
    for key in ("Issue Date", "Permit Issue Date"):
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
        app_detail.get("Application Status"),
        detail.get("Status for Permit Number"),
    )
    effective_status = _apply_status(repairs, row["STATUS_NORMALIZED"], expected)

    # FILE_DATE ← Application Date
    _apply_date(repairs, row, "FILE_DATE", _application_date(d, detail))

    # PERMIT_DATE ← Issue Date (not the portal "Permit Date" stamp).
    issue = _issue_date(detail)
    if effective_status == "In Review":
        _clear_date(repairs, row, "PERMIT_DATE")
    elif _present(issue) and effective_status in ("Active", "Final", "Inactive"):
        _apply_date(repairs, row, "PERMIT_DATE", issue)
    elif effective_status in ("Active", "Final", "Inactive") and not _present(issue):
        # Upstream often copied "Permit Date"; clear when Issue Date absent.
        permit_stamp = _safe_to_datetime(detail.get("Permit Date"))
        current = row["PERMIT_DATE"]
        if pd.notna(current) and (
            not _present(permit_stamp) or _dates_equal(current, permit_stamp)
        ):
            _clear_date(repairs, row, "PERMIT_DATE")

    # FINAL_DATE ← latest non-NOC successful inspection (Final rows only).
    final_src = _final_date_from_inspections(
        d.get("insp_status_detail"), issue_date=issue
    )
    if effective_status == "Final":
        if _present(final_src):
            _apply_date(repairs, row, "FINAL_DATE", final_src)
        elif pd.notna(row["FINAL_DATE"]) and _present(issue):
            if pd.Timestamp(row["FINAL_DATE"]).normalize() < pd.Timestamp(
                issue
            ).normalize():
                _clear_date(repairs, row, "FINAL_DATE")
    else:
        _clear_date(repairs, row, "FINAL_DATE")


def _repair_fees_detail(row, d: dict, repairs: dict) -> None:
    """Repair a fees_detail record (detail/fees; no issue/inspections)."""
    detail = d.get("detail") or {}
    if not isinstance(detail, dict):
        detail = {}

    expected = _expected_status(detail.get("Application Status"), None)
    effective_status = _apply_status(repairs, row["STATUS_NORMALIZED"], expected)

    _apply_date(repairs, row, "FILE_DATE", detail.get("Application Date"))

    # No Issue Date / inspection history in this schema.
    if effective_status == "In Review":
        _clear_date(repairs, row, "PERMIT_DATE")
    elif effective_status in ("Active", "Final", "Inactive"):
        # Cannot invent issuance; clear any unsupported stamp.
        _clear_date(repairs, row, "PERMIT_DATE")
    # No inspection history — clear unsupported FINAL stamps.
    _clear_date(repairs, row, "FINAL_DATE")


# ── Main entry point ─────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Temple Terrace permit records using information from the raw DATA JSON.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Temple Terrace".  Must contain
        columns STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, FINAL_DATE,
        and DATA.

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
    from pathlib import Path

    from dotenv import load_dotenv

    repo_root = Path(__file__).resolve().parents[3]
    load_dotenv(repo_root / ".env")
    MY_DATA_PATH = os.getenv("MY_DATA_PATH")
    AGENT_DATA_PATH = os.getenv("AGENT_DATA_PATH")
    filepath = os.path.join(
        MY_DATA_PATH, "processed_data", "permits_fl_sample.parquet"
    )
    df = pd.read_parquet(filepath)
    city = df[
        (df["JURISDICTION"] == "Temple Terrace") & (df["STATE"] == "FL")
    ].copy()

    print(f"Temple Terrace records: {len(city):,}\n")

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
        f"PERMIT_DATE ≠ Issue Date (when both present): {mismatch} (of {n_issue})"
    )

    n_file_eq_app = 0
    n_with_app = 0
    for idx in repaired.index:
        d = _safe_parse(repaired.at[idx, "DATA"]) or {}
        detail = (
            d.get("permit_status_detail")
            if isinstance(d.get("permit_status_detail"), dict)
            else {}
        )
        app = _application_date(d, detail if detail else (
            d.get("detail") if isinstance(d.get("detail"), dict) else {}
        ))
        if _present(app):
            n_with_app += 1
            if _dates_equal(repaired.at[idx, "FILE_DATE"], app):
                n_file_eq_app += 1
    print(f"FILE_DATE == Application Date: {n_file_eq_app} / {n_with_app}")

    if AGENT_DATA_PATH:
        out_dir = Path(AGENT_DATA_PATH) / "repaired"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "permits_fl_temple_terrace_repaired.parquet"
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote {out_path}")

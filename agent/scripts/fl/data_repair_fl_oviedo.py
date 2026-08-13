"""Data repair for Oviedo (FL) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Oviedo DATA is the same city-portal family as Lake Mary / Punta Gorda,
with three sub-schemas in this sample:

  - permit_status:  detail/fees plus permit_status_detail,
                    insp_status_detail (full permit + inspections)
  - fees_detail:    detail + fees + fees_total only (Application Date /
                    Application Status; no issue/inspection blocks)
  - application:    mini_set with application_status / application_type
                    (status only; no dates)

Canonical mappings:
  - Status for Permit Number (permit_status); else
    Application Status / application_status     → STATUS_NORMALIZED
  - Application Date                            → FILE_DATE
  - Permit Issue Date                           → PERMIT_DATE
  - Latest successful (APPROVED / WAIVED) inspection
    excluding Notice of Commencement
    (Final rows only)                           → FINAL_DATE

Known issues repaired:
  - STATUS_NORMALIZED null on all fees_detail /
    application rows → FILLED from Application Status /
    application_status.
  - PERMIT_DATE missing on every sample row → FILLED from
    Permit Issue Date for Active / Final / Inactive.
  - FINAL_DATE filled / corrected from latest non-NOC
    APPROVED inspection; pre-issue FINAL stamps that only
    reflect Notice of Commencement → cleared.
  - Spurious PERMIT_DATE on In Review (none expected) cleared;
    spurious FINAL_DATE on non-Final cleared.

Not repairable from DATA:
  - application mini_set rows have status only → FILE_DATE /
    PERMIT_DATE / FINAL_DATE stay missing.
  - fees_detail rows have Application Date but no Issue Date /
    inspections → PERMIT_DATE / FINAL_DATE stay missing.
  - CLOSED Final rows with empty / non-APPROVED (non-NOC)
    insp_status_detail → FINAL_DATE stays missing.
    (CO Issue Date is often a multi-year admin batch stamp and
    is not used as a completion date.)
  - Active/Final with blank Permit Issue Date → PERMIT_DATE
    stays missing.
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
    if "mini_set" in keys or "application_status" in keys:
        return "application"
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
    "C.O. ISSUED": "Final",
    "CERTIFICATE OF OCCUPANCY": "Final",
    "CERTIFICATE OF COMPLETION": "Final",
    "FINALED": "Final",
    # Active / issued
    "PERMIT PRINTED": "Active",
    "PERMIT ISSUED": "Active",
    # In review / pre-issuance
    "TO BE ISSUED": "In Review",
    "APPROVED": "In Review",
    "PLAN CHECK": "In Review",
    "PLANS BEING CHECKED": "In Review",
    "IN PLAN CHECK": "In Review",
    "EPLAN REVIEW": "In Review",
    # Inactive
    "PERMIT REVOKED": "Inactive",
    "PERMIT EXPIRED": "Inactive",
    "EXPIRED": "Inactive",
    "ABANDONED": "Inactive",
    "REJECTED": "Inactive",
    "VOID": "Inactive",
    "WITHDRAWN": "Inactive",
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


def _final_date_from_inspections(insp_detail) -> pd.Timestamp:
    """Latest successful inspection date, excluding Notice of Commencement.

    Oviedo often records a later BACKFLOW / misc stamp after an earlier
    ``* FINAL`` row; taking max(FINAL-named) alone can move FINAL_DATE
    backwards. NOC dates frequently pre-date issuance and are not
    completion signals. WAIVED rows are treated as success (common
    final-adjacent portal result).
    """
    if not isinstance(insp_detail, list):
        return pd.NaT

    success_dates = []
    for row in insp_detail:
        if not isinstance(row, list) or len(row) < 3:
            continue
        name = str(row[0] or "")
        if "NOTICE OF COMMENCEMENT" in name.upper():
            continue
        result = str(row[2] or "").strip().upper()
        if result not in _SUCCESS_RESULTS:
            continue
        # Prefer completion/result date (index 3) when present.
        dt = _safe_to_datetime(row[3] if len(row) > 3 else None)
        if not _present(dt):
            dt = _safe_to_datetime(row[1])
        if not _present(dt):
            continue
        success_dates.append(dt)

    return max(success_dates) if success_dates else pd.NaT


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
    """Permit issuance date (Oviedo field name: Permit Issue Date)."""
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

    # Prefer Status for Permit Number; fall back to Application Status.
    raw_status = detail.get("Status for Permit Number")
    expected = _map_status(raw_status)
    if expected is None:
        expected = _map_status(app_detail.get("Application Status"))
    effective_status = _apply_status(repairs, row["STATUS_NORMALIZED"], expected)

    # FILE_DATE ← Application Date
    _apply_date(repairs, row, "FILE_DATE", _application_date(d, detail))

    # PERMIT_DATE ← Permit Issue Date
    issue = _issue_date(detail)
    if effective_status == "In Review":
        _clear_date(repairs, row, "PERMIT_DATE")
    elif _present(issue) and effective_status in ("Active", "Final", "Inactive"):
        _apply_date(repairs, row, "PERMIT_DATE", issue)

    # FINAL_DATE ← latest non-NOC APPROVED inspection (Final rows only).
    # Clear pre-issue stamps when no usable inspection source exists
    # (upstream sometimes copied Notice of Commencement).
    final_src = _final_date_from_inspections(d.get("insp_status_detail"))
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

    expected = _map_status(detail.get("Application Status"))
    effective_status = _apply_status(repairs, row["STATUS_NORMALIZED"], expected)

    _apply_date(repairs, row, "FILE_DATE", detail.get("Application Date"))

    # No Issue Date / inspection history in this schema.
    if effective_status == "In Review":
        _clear_date(repairs, row, "PERMIT_DATE")
    elif effective_status in ("Active", "Final", "Inactive"):
        # Cannot invent issuance; clear any unsupported stamp.
        _clear_date(repairs, row, "PERMIT_DATE")
    if effective_status != "Final":
        _clear_date(repairs, row, "FINAL_DATE")


def _repair_application(row, d: dict, repairs: dict) -> None:
    """Repair an application mini_set record (status only)."""
    expected = _map_status(d.get("application_status"))
    effective_status = _apply_status(repairs, row["STATUS_NORMALIZED"], expected)
    # No date fields in this schema — clear unsupported stamps.
    if effective_status == "In Review":
        _clear_date(repairs, row, "PERMIT_DATE")
    if effective_status != "Final":
        _clear_date(repairs, row, "FINAL_DATE")


# ── Main entry point ─────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Oviedo permit records using information from the raw DATA JSON.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Oviedo".  Must contain
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
        elif schema == "application":
            _repair_application(row, d, repairs)

        for key, value in repairs.items():
            out.at[idx, key] = value

    for col in ("FILE_DATE", "PERMIT_DATE", "FINAL_DATE"):
        out[col] = pd.to_datetime(out[col], errors="coerce")

    return out


# ── CLI: run standalone to preview repair stats ─────────────────────────────

if __name__ == "__main__":
    import os
    from collections import Counter

    from dotenv import load_dotenv

    load_dotenv("/Users/ekung/projects/la-permits-data/.env")
    MY_DATA_PATH = os.getenv("MY_DATA_PATH")
    AGENT_DATA_PATH = os.getenv("AGENT_DATA_PATH")
    filepath = os.path.join(
        MY_DATA_PATH, "processed_data", "permits_fl_sample.parquet"
    )
    df = pd.read_parquet(filepath)
    city = df[df["JURISDICTION"] == "Oviedo"].copy()

    print(f"Oviedo records: {len(city):,}\n")

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
    print(f"PERMIT_DATE ≠ Permit Issue Date (when both present): {mismatch} (of {n_issue})")

    if AGENT_DATA_PATH:
        out_path = os.path.join(
            AGENT_DATA_PATH, "oviedo_permits_repaired.parquet"
        )
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote {out_path}")

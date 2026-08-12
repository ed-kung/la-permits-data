"""Data repair for Boca Raton (FL) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Boca Raton DATA comes from the same city portal family as Lake Mary,
with two sub-schemas in this sample:

  - permit_status:  detail/fees plus permit_status_detail,
                    insp_status_detail (full permit + inspections)
  - fees_detail:    detail + fees + fees_total only (most rows are
                    empty shells; a few have Application Date/Status)

Canonical mappings:
  - Status for Permit Number (permit_status) /
    Application Status (fees_detail)            → STATUS_NORMALIZED
  - Application Date                            → FILE_DATE
  - Issue Date (fallback: Permit Date for
    Active/Final when Issue Date blank)         → PERMIT_DATE
  - Latest APPROVED inspection whose name
    contains FINAL / FNL / CLOSEOUT; else
    latest non-NOC APPROVED insp (Final only)   → FINAL_DATE

Known issues repaired:
  - STATUS_NORMALIZED null on fees_detail rows
    with Application Status WITHDRAWN /
    CLOSED MANUALLY - FINALED → FILLED.
  - PERMIT_DATE was ingested from portal "Permit Date",
    which often post-dates finalization (and creates
    PERMIT > FINAL inversions); FIXED to Issue Date.
  - Spurious PERMIT_DATE on unissued In Review rows
    (PLAN CHECK / TO BE ISSUED, no Issue Date) → cleared.
  - Blank-Issue fallback skips the 2011-05-03 batch
    Permit Date stamp and any Permit Date after FINAL.
  - FINAL_DATE off-by-one / non-inspection values and
    NOC-only "finals" → FIXED or cleared from
    inspection history.

Not repairable / left as-is:
  - ~1,166 fees_detail shells have only an Application #
    → status and all dates stay missing.
  - CLOSED Final rows with empty / non-APPROVED
    completion inspections → FINAL_DATE stays missing.
  - Active/Final rows with blank Issue Date and no
    usable Permit Date → PERMIT_DATE stays missing.
  - A few legacy rows have Issue Date after an approved
    final inspection (source chronology); left as-is.
"""

from __future__ import annotations

import json
import math
import re
from typing import Optional

import numpy as np
import pandas as pd


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
    """Parse a date value, returning pd.NaT on failure / blanks."""
    if val is None or (isinstance(val, str) and not str(val).strip()):
        return pd.NaT
    if not isinstance(val, str) and pd.isna(val):
        return pd.NaT
    text = str(val).strip()
    if text.upper() in ("TBD", "NONE", "N/A", "NA", "NULL", "NAN", "00/00/0000", "0/0/0000"):
        return pd.NaT
    try:
        return pd.to_datetime(val)
    except (ValueError, TypeError, OverflowError):
        return pd.NaT


def _dates_equal(a, b) -> bool:
    """Compare two datelike values at calendar-day resolution."""
    da = _safe_to_datetime(a)
    db = _safe_to_datetime(b)
    if da is pd.NaT or db is pd.NaT:
        return False
    return da.normalize() == db.normalize()


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())
    if "permit_status_detail" in keys:
        return "permit_status"
    if "application_status" in keys:
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
    if cand is pd.NaT:
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
    if not pd.isna(row[field]):
        repairs[field] = pd.NaT
        repairs[f"{field}_FLAG"] = "FIXED"


# ── Status maps ──────────────────────────────────────────────────────────────

# Portal "Status for Permit Number" (and close synonyms) → STATUS_NORMALIZED
_STATUS_MAP = {
    # Final / completed
    "FINAL INSPECTION COMPLETE": "Final",
    "CLOSED": "Final",
    "C.O. ISSUED": "Final",
    "FINALED": "Final",
    "CLOSED MANUALLY - FINALED": "Final",
    "CERTIFICATE OF COMPLETION": "Final",
    "CHECK FINALS": "Final",
    "AX TO MICROFILM": "Final",
    "EXPIRED TO MICROFILM": "Final",
    # Active / issued
    "PERMIT PRINTED": "Active",
    "PERMIT ISSUED": "Active",
    # In review / pre-issuance
    "TO BE ISSUED": "In Review",
    "PLAN CHECK": "In Review",
    "PLANS BEING CHECKED": "In Review",
    "PRESCREENING REVIEW": "In Review",
    # Inactive
    "PERMIT REVOKED": "Inactive",
    "PERMIT EXPIRED": "Inactive",
    "WITHDRAWN": "Inactive",
    "WITHDRAWN DESTROYED": "Inactive",
    "EXPIRED APP DESTROYED": "Inactive",
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


def _is_final_inspection_name(name: str) -> bool:
    """True if inspection title looks like a final / closeout inspection."""
    upper = str(name or "").upper()
    if "FINAL" in upper:
        return True
    # Boca abbreviates some finals as FNL (e.g. "COMP AND CLADDNG FLD FNL").
    if re.search(r"(^|[^A-Z])FNL([^A-Z]|$)", upper):
        return True
    if "CLOSEOUT" in upper:
        return True
    return False


def _is_noc_inspection_name(name: str) -> bool:
    """Notice-of-commencement / admin recordings are not completion events."""
    return "NOC" in str(name or "").upper()


# Portal batch "Permit Date" stamped on many CLOSED rows during a 2011 migration.
_BATCH_PERMIT_DATE = pd.Timestamp("2011-05-03")


def _final_date_from_inspections(insp_detail) -> pd.Timestamp:
    """Latest APPROVED FINAL/FNL/CLOSEOUT date; else latest non-NOC APPROVED."""
    if not isinstance(insp_detail, list):
        return pd.NaT

    final_dates = []
    approved_dates = []
    for row in insp_detail:
        if not isinstance(row, list) or len(row) < 3:
            continue
        name = str(row[0] or "")
        result = str(row[2] or "").strip().upper()
        if result != "APPROVED":
            continue
        # Prefer completion/result date (index 3) when present.
        dt = _safe_to_datetime(row[3] if len(row) > 3 else None)
        if dt is pd.NaT:
            dt = _safe_to_datetime(row[1])
        if dt is pd.NaT:
            continue
        if _is_final_inspection_name(name):
            final_dates.append(dt)
        elif not _is_noc_inspection_name(name):
            approved_dates.append(dt)

    if final_dates:
        return max(final_dates)
    if approved_dates:
        return max(approved_dates)
    return pd.NaT


# ── Per-schema repair logic ─────────────────────────────────────────────────

def _repair_permit_status(row, d: dict, repairs: dict) -> None:
    """Repair a permit_status record (full portal permit + inspections)."""
    detail = d.get("permit_status_detail") or {}
    if not isinstance(detail, dict):
        detail = {}

    # Prefer permit-number status; Application Status is often stale/withdrawn
    # even when Status for Permit Number is CLOSED / PERMIT PRINTED.
    raw_status = detail.get("Status for Permit Number")
    expected = _map_status(raw_status)
    effective_status = _apply_status(repairs, row["STATUS_NORMALIZED"], expected)

    # FILE_DATE ← Application Date (also mirrored under detail)
    app_date = detail.get("Application Date")
    if not app_date:
        top_detail = d.get("detail") or {}
        if isinstance(top_detail, dict):
            app_date = top_detail.get("Application Date")
    _apply_date(repairs, row, "FILE_DATE", app_date)

    # FINAL_DATE ← approved inspections (Final rows only). Computed before
    # PERMIT_DATE so we can reject a post-finalization Permit Date fallback.
    final_src = _final_date_from_inspections(d.get("insp_status_detail"))
    current_final = row["FINAL_DATE"]
    if effective_status == "Final":
        if final_src is not pd.NaT:
            if pd.isna(current_final):
                repairs["FINAL_DATE"] = final_src
                repairs["FINAL_DATE_FLAG"] = "FILLED"
            elif not _dates_equal(current_final, final_src):
                repairs["FINAL_DATE"] = final_src
                repairs["FINAL_DATE_FLAG"] = "FIXED"
        elif not pd.isna(current_final):
            # Drop FINAL that only reflected NOC / non-completion events.
            _clear_date(repairs, row, "FINAL_DATE")
    elif not pd.isna(current_final):
        _clear_date(repairs, row, "FINAL_DATE")

    effective_final = repairs.get("FINAL_DATE", current_final)

    # PERMIT_DATE ← Issue Date (true issuance). Portal "Permit Date" often
    # post-dates finalization and was the incorrect upstream source.
    issue = _safe_to_datetime(detail.get("Issue Date"))
    permit_date_field = _safe_to_datetime(detail.get("Permit Date"))

    if issue is not pd.NaT:
        _apply_date(repairs, row, "PERMIT_DATE", issue)
    elif effective_status in ("Active", "Final") and permit_date_field is not pd.NaT:
        # Skip the 2011-05-03 migration batch stamp and any Permit Date that
        # lands after an already-known finalization date.
        batch = _dates_equal(permit_date_field, _BATCH_PERMIT_DATE)
        after_final = (
            effective_final is not pd.NaT
            and not pd.isna(effective_final)
            and permit_date_field.normalize() > _safe_to_datetime(effective_final).normalize()
        )
        if not batch and not after_final:
            _apply_date(repairs, row, "PERMIT_DATE", permit_date_field)
        elif not pd.isna(row["PERMIT_DATE"]) and (
            batch or after_final or not _dates_equal(row["PERMIT_DATE"], permit_date_field)
        ):
            # Drop a previously ingested bad Permit Date when we have no Issue Date.
            if batch or after_final:
                _clear_date(repairs, row, "PERMIT_DATE")
    elif effective_status == "In Review":
        # Unissued rows sometimes carry a processing "Permit Date".
        _clear_date(repairs, row, "PERMIT_DATE")


def _repair_fees_detail(row, d: dict, repairs: dict) -> None:
    """Repair a fees_detail record (detail/fees; usually sparse)."""
    detail = d.get("detail") or {}
    if not isinstance(detail, dict):
        detail = {}

    expected = _map_status(detail.get("Application Status"))
    effective_status = _apply_status(repairs, row["STATUS_NORMALIZED"], expected)

    _apply_date(repairs, row, "FILE_DATE", detail.get("Application Date"))

    # No Issue Date / inspection history in this schema.
    if effective_status == "In Review":
        _clear_date(repairs, row, "PERMIT_DATE")
    if effective_status not in (None, "Final") and not pd.isna(row["FINAL_DATE"]):
        _clear_date(repairs, row, "FINAL_DATE")


def _repair_application(row, d: dict, repairs: dict) -> None:
    """Repair an application mini_set record (status only)."""
    expected = _map_status(d.get("application_status"))
    _apply_status(repairs, row["STATUS_NORMALIZED"], expected)


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Boca Raton permit records using information from the raw DATA JSON.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Boca Raton".  Must
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
    from dotenv import load_dotenv

    load_dotenv("/Users/ekung/projects/la-permits-data/.env")
    MY_DATA_PATH = os.getenv("MY_DATA_PATH")
    AGENT_DATA_PATH = os.getenv("AGENT_DATA_PATH")
    filepath = os.path.join(MY_DATA_PATH, "processed_data", "permits_fl_sample.parquet")
    df = pd.read_parquet(filepath)
    city = df[df["JURISDICTION"] == "Boca Raton"].copy()

    print(f"Boca Raton records: {len(city):,}\n")

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
        print(f"  Missing before: {before_missing:>4,}   Missing after: {after_missing:>4,}")
        print()

    print("STATUS_NORMALIZED distribution:")
    print("  Before:")
    for s, c in city["STATUS_NORMALIZED"].value_counts(dropna=False).items():
        print(f"    {str(s):15s}: {c:>4,}")
    print("  After:")
    for s, c in repaired["STATUS_NORMALIZED"].value_counts(dropna=False).items():
        print(f"    {str(s):15s}: {c:>4,}")

    print("\nFILE_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FILE_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({n_has / len(sub) if len(sub) else 0:.1%})")

    print("\nPERMIT_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["PERMIT_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({n_has / len(sub) if len(sub) else 0:.1%})")

    print("\nFINAL_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FINAL_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({n_has / len(sub) if len(sub) else 0:.1%})")

    # Chronology check
    both = repaired[repaired["PERMIT_DATE"].notna() & repaired["FINAL_DATE"].notna()]
    n_inv = (both["PERMIT_DATE"].dt.normalize() > both["FINAL_DATE"].dt.normalize()).sum()
    print(f"\nPERMIT_DATE > FINAL_DATE inversions after repair: {n_inv}")

    still_null = repaired[repaired["STATUS_NORMALIZED"].isna()]
    print(f"\nRemaining null STATUS_NORMALIZED: {len(still_null):,}")
    print("  by schema:")
    print(still_null["INFERRED_SCHEMA"].value_counts().to_string())

    if AGENT_DATA_PATH:
        out_path = os.path.join(AGENT_DATA_PATH, "boca_raton_repaired_sample.parquet")
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote {out_path}")

"""Data repair for Thousand Oaks (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Thousand Oaks DATA has three schemas:

  - entity_full:    Tyler EnerGov-style payload with top-level keys
                    ``entity``, ``details``, ``contacts``, ``fees``,
                    ``processing_status``, ``reviews``, ``holds``,
                    ``attachments``, ``more_info``.
  - permit_status:  Legacy portal scrape with ``detail``,
                    ``permit_status_detail``, ``insp_status_detail``,
                    ``permit_status``, ``insp_status``, ``fees``.
  - detail_only:    Sparse legacy stub with only ``detail`` (+ empty
                    ``fees`` / null ``fees_total``); no permit or
                    inspection blocks.

Canonical mappings by schema:

  entity_full
    - details.PermitStatus / entity.CaseStatus → STATUS_NORMALIZED
    - entity.ApplyDate                         → FILE_DATE
    - entity.IssueDate / details.IssueDate     → PERMIT_DATE
    - entity.FinalDate / details.FinalizeDate  → FINAL_DATE

  permit_status
    - Status for Permit Number                 → STATUS_NORMALIZED
    - Application Date                         → FILE_DATE
    - Issue Date (NOT Permit Date)             → PERMIT_DATE
    - Final / last approved inspection
      (fallback: Permit Date)                  → FINAL_DATE

  detail_only
    - Application Status                       → STATUS_NORMALIZED
    - Application Date                         → FILE_DATE
    - (no issuance / final fields available)

Known issues repaired:
  - STATUS_NORMALIZED missing for 23 ``Permit Approval Expired``
    entity_full rows → FILLED as Inactive.
  - STATUS_NORMALIZED missing for 14 detail_only stubs → FILLED from
    Application Status (IN PLAN CHECK → In Review; CLOSED → Inactive).
  - 3 entity_full rows where CaseStatus=Issued but PermitStatus=Finaled
    (and FinalizeDate present) were labeled Active → FIXED to Final;
    FINAL_DATE FILLED from details.FinalizeDate.
  - permit_status PERMIT_DATE was set from ``Permit Date``, which for
    Final (and some Active) rows is a finaling / last-activity date,
    not issuance. Overwrite with ``Issue Date`` when present → FIXED
    (~560 rows).
  - Spurious PERMIT_DATE on In Review rows with no Issue Date → FIXED
    (cleared).
  - Spurious FINAL_DATE on non-Final entity_full rows (Expired /
    Issued / etc., often mirroring IssueDate) → FIXED (cleared).
  - Missing FINAL_DATE on Final permit_status rows whose final
    inspection is ``APPROVED WITH EXCEPTION`` → FILLED from that
    inspection (or last approved / Permit Date fallback).
  - A few Final FINAL_DATE values earlier than the latest approved
    final inspection → FIXED to the later inspection date.

Not repairable / left as-is:
  - FILE_DATE already matches ApplyDate / Application Date for all
    sample rows.
  - entity_full Active/Final rows already have PERMIT_DATE from
    IssueDate when issued; unissued Inactive / In Review rows correctly
    lack PERMIT_DATE.
  - detail_only stubs have no Issue Date or inspections, so
    PERMIT_DATE / FINAL_DATE stay missing (status is In Review /
    Inactive after fill).
"""

import json
import math
from typing import Optional

import pandas as pd
import numpy as np


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
    """Parse a date value, returning pd.NaT on failure."""
    if val is None or (isinstance(val, str) and not str(val).strip()):
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
    if "entity" in keys or "processing_status" in keys:
        return "entity_full"
    if "permit_status" in keys or "permit_status_detail" in keys:
        return "permit_status"
    if "detail" in keys:
        return "detail_only"
    return "unknown"


# ── Status mapping tables ────────────────────────────────────────────────────

# entity_full: CaseStatus / PermitStatus → STATUS_NORMALIZED
_ENTITY_STATUS_MAP = {
    "Finaled": "Final",
    "Issued": "Active",
    "Expired": "Inactive",
    "Expired Application": "Inactive",
    "Permit Approval Expired": "Inactive",
    "Permit Revoked": "Inactive",
    "Void": "Inactive",
    "Withdrawn": "Inactive",
    "In Review": "In Review",
    "Application Incomplete": "In Review",
    "Pending Approval": "In Review",
}

# permit_status: Status for Permit Number → STATUS_NORMALIZED
_PERMIT_NUM_STATUS_MAP = {
    "FINAL INSPECTION COMPLETE": "Final",
    "PERMIT PRINTED": "Active",
    "PERMIT REVOKED": "Inactive",
    "PLAN CHECK": "In Review",
    "TO BE ISSUED": "In Review",
}

# detail_only / Application Status fallback
_APP_STATUS_MAP = {
    "IN PLAN CHECK": "In Review",
    "CLOSED": "Inactive",
    "APPROVED": "Active",
    "PERMIT ISSUED": "Active",
}


def _set_status(repairs: dict, current, expected: Optional[str]):
    if expected is None:
        return
    if pd.isna(current):
        repairs["STATUS_NORMALIZED"] = expected
        repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"
    elif current != expected:
        repairs["STATUS_NORMALIZED"] = expected
        repairs["STATUS_NORMALIZED_FLAG"] = "FIXED"


def _set_date(repairs: dict, field: str, current, canonical):
    """Fill or fix *field* from *canonical* when canonical is valid."""
    if canonical is pd.NaT or canonical is None:
        return
    flag = f"{field}_FLAG"
    if pd.isna(current):
        repairs[field] = canonical
        repairs[flag] = "FILLED"
    elif not _dates_equal(current, canonical):
        repairs[field] = canonical
        repairs[flag] = "FIXED"


def _clear_date(repairs: dict, field: str, current):
    if pd.isna(current):
        return
    repairs[field] = pd.NaT
    repairs[f"{field}_FLAG"] = "FIXED"


# ── entity_full helpers ──────────────────────────────────────────────────────

def _entity_raw_status(d: dict) -> Optional[str]:
    """Prefer details.PermitStatus (more current) over entity.CaseStatus."""
    details = d.get("details") if isinstance(d.get("details"), dict) else {}
    entity = d.get("entity") if isinstance(d.get("entity"), dict) else {}
    status = details.get("PermitStatus") or entity.get("CaseStatus")
    if status is None:
        return None
    status = str(status).strip()
    return status or None


def _entity_date(d: dict, entity_key: str, *detail_keys: str):
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


# ── permit_status helpers ────────────────────────────────────────────────────

def _psd(d: dict) -> dict:
    psd = d.get("permit_status_detail")
    return psd if isinstance(psd, dict) else {}


def _detail(d: dict) -> dict:
    det = d.get("detail")
    return det if isinstance(det, dict) else {}


def _final_inspection_date(d: dict):
    """Latest approved final-named inspection date, else last approved."""
    insp = d.get("insp_status_detail") or []
    if not isinstance(insp, list):
        return pd.NaT

    final_dates = []
    approved_dates = []
    for row in insp:
        if not isinstance(row, (list, tuple)) or len(row) < 3:
            continue
        name = str(row[0]).upper()
        status = str(row[2]).upper()
        if not status.startswith("APPROVED"):
            continue
        dates = []
        for i in (1, 3):
            if len(row) > i:
                dt = _safe_to_datetime(row[i])
                if dt is not pd.NaT:
                    dates.append(dt)
        if not dates:
            continue
        latest = max(dates)
        approved_dates.append(latest)
        if "FINAL" in name:
            final_dates.append(latest)

    if final_dates:
        return max(final_dates)
    if approved_dates:
        return max(approved_dates)
    return pd.NaT


# ── Per-schema repair ────────────────────────────────────────────────────────

def _repair_entity_full(row, d: dict, repairs: dict):
    raw = _entity_raw_status(d)
    expected = _ENTITY_STATUS_MAP.get(raw) if raw else None
    _set_status(repairs, row["STATUS_NORMALIZED"], expected)
    effective = repairs.get("STATUS_NORMALIZED", row["STATUS_NORMALIZED"])

    apply = _entity_date(d, "ApplyDate", "ApplyDate")
    _set_date(repairs, "FILE_DATE", row["FILE_DATE"], apply)

    issue = _entity_date(d, "IssueDate", "IssueDate")
    if effective in ("Active", "Final"):
        _set_date(repairs, "PERMIT_DATE", row["PERMIT_DATE"], issue)
    elif effective == "In Review" and pd.isna(issue):
        _clear_date(repairs, "PERMIT_DATE", row["PERMIT_DATE"])
    elif not pd.isna(row["PERMIT_DATE"]) and issue is not pd.NaT and not _dates_equal(
        row["PERMIT_DATE"], issue
    ):
        # Keep Inactive issuance dates accurate when IssueDate exists.
        _set_date(repairs, "PERMIT_DATE", row["PERMIT_DATE"], issue)

    final = _entity_date(d, "FinalDate", "FinalizeDate")
    if effective == "Final":
        _set_date(repairs, "FINAL_DATE", row["FINAL_DATE"], final)
    else:
        _clear_date(repairs, "FINAL_DATE", row["FINAL_DATE"])


def _repair_permit_status(row, d: dict, repairs: dict):
    psd = _psd(d)
    det = _detail(d)

    raw = (psd.get("Status for Permit Number") or "").strip()
    expected = _PERMIT_NUM_STATUS_MAP.get(raw) if raw else None
    if expected is None:
        app = (det.get("Application Status") or "").strip()
        expected = _APP_STATUS_MAP.get(app) if app else None
    _set_status(repairs, row["STATUS_NORMALIZED"], expected)
    effective = repairs.get("STATUS_NORMALIZED", row["STATUS_NORMALIZED"])

    app_date = _safe_to_datetime(det.get("Application Date") or psd.get("Application Date"))
    _set_date(repairs, "FILE_DATE", row["FILE_DATE"], app_date)

    # Issue Date is true issuance; Permit Date often stores finaling date.
    issue = _safe_to_datetime(psd.get("Issue Date"))
    if effective in ("Active", "Final"):
        _set_date(repairs, "PERMIT_DATE", row["PERMIT_DATE"], issue)
    elif effective == "In Review":
        if issue is pd.NaT:
            _clear_date(repairs, "PERMIT_DATE", row["PERMIT_DATE"])
        else:
            _set_date(repairs, "PERMIT_DATE", row["PERMIT_DATE"], issue)
    elif issue is not pd.NaT:
        _set_date(repairs, "PERMIT_DATE", row["PERMIT_DATE"], issue)

    permit_date_field = _safe_to_datetime(psd.get("Permit Date"))
    final = _final_inspection_date(d)
    if final is pd.NaT:
        final = permit_date_field  # legacy finaling proxy when no inspections

    if effective == "Final":
        _set_date(repairs, "FINAL_DATE", row["FINAL_DATE"], final)
    else:
        _clear_date(repairs, "FINAL_DATE", row["FINAL_DATE"])


def _repair_detail_only(row, d: dict, repairs: dict):
    det = _detail(d)
    app = (det.get("Application Status") or "").strip()
    expected = _APP_STATUS_MAP.get(app) if app else None
    _set_status(repairs, row["STATUS_NORMALIZED"], expected)
    effective = repairs.get("STATUS_NORMALIZED", row["STATUS_NORMALIZED"])

    app_date = _safe_to_datetime(det.get("Application Date"))
    _set_date(repairs, "FILE_DATE", row["FILE_DATE"], app_date)

    # No issuance / final fields in this schema.
    if effective == "In Review":
        _clear_date(repairs, "PERMIT_DATE", row["PERMIT_DATE"])
    if effective != "Final":
        _clear_date(repairs, "FINAL_DATE", row["FINAL_DATE"])


# ── Main entry point ─────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Thousand Oaks permit records using information from the raw DATA JSON.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Thousand Oaks".  Must contain
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
        if schema == "entity_full":
            _repair_entity_full(row, d, repairs)
        elif schema == "permit_status":
            _repair_permit_status(row, d, repairs)
        elif schema == "detail_only":
            _repair_detail_only(row, d, repairs)

        for key, value in repairs.items():
            out.at[idx, key] = value

    return out


# ── CLI: run standalone to preview repair stats ─────────────────────────────

if __name__ == "__main__":
    import os
    from dotenv import load_dotenv

    load_dotenv("/Users/ekung/projects/la-permits-data/.env")
    MY_DATA_PATH = os.getenv("MY_DATA_PATH")
    filepath = os.path.join(MY_DATA_PATH, "processed_data", "permits_ca_sample.parquet")
    df = pd.read_parquet(filepath)
    city = df[(df["JURISDICTION"] == "Thousand Oaks") & (df["STATE"] == "CA")].copy()

    print(f"Thousand Oaks records: {len(city):,}\n")

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

    print("\nPERMIT_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["PERMIT_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({n_has/len(sub) if len(sub) else 0:.1%})")

    print("\nFINAL_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FINAL_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({n_has/len(sub) if len(sub) else 0:.1%})")

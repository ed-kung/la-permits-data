"""Data repair for Oxnard (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Oxnard DATA has three schemas:

  - permit_status:  Legacy portal scrape with ``detail``,
                    ``permit_status_detail``, ``insp_status_detail``,
                    ``permit_status``, ``insp_status``, ``fees``.
  - detail_only:    Sparse legacy stub with only ``detail`` (+ ``fees`` /
                    ``fees_total``); no permit or inspection blocks.
  - project:        Newer tracking payload with ``project`` +
                    ``description`` (plan-check / issuance workflow).

Canonical mappings by schema:

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

  project
    - Permit Center Tracking ``Type``
      (fallback: description Types)            → STATUS_NORMALIZED
    - (no application date in DATA)            → FILE_DATE unfillable
    - PCT / Approved ``Last Action``           → PERMIT_DATE (fill only)
    - (no finaling signal in DATA)             → FINAL_DATE unfillable

Known issues repaired:
  - 669 detail_only rows missing STATUS_NORMALIZED → FILLED from
    Application Status (CLOSED→Inactive; IN PLAN CHECK→In Review;
    APPROVED→Active).
  - 40 project rows missing STATUS_NORMALIZED → FILLED from description
    workflow Types.
  - 3 permit_status rows where Status for Permit Number disagrees with
    STATUS_ORIGINAL / STATUS_NORMALIZED → FIXED to the permit-number
    status (canonical).
  - permit_status PERMIT_DATE was set from ``Permit Date``, which for
    Final (and some Active) rows is a finaling / last-activity date,
    not issuance. Overwrite with ``Issue Date`` when present → FIXED.
  - Spurious PERMIT_DATE on In Review / Inactive rows with no Issue
    Date → FIXED (cleared).
  - Missing FINAL_DATE on Final permit_status rows → FILLED from
    approved final / last approved inspection, else Permit Date.
  - Spurious FINAL_DATE on non-Final rows → FIXED (cleared).
  - project Active/Final-to-be rows missing PERMIT_DATE → FILLED from
    PCT / Approved Last Action.

Not repairable / left as-is:
  - FILE_DATE already correct for all permit_status / detail_only rows.
  - All 306 project rows lack an application / file date in DATA.
  - detail_only stubs have no Issue Date or inspections, so
    PERMIT_DATE / FINAL_DATE stay missing after status fill.
  - project rows have no finaling signal → FINAL_DATE stays missing
    (none are classified Final).
  - 16 Final permit_status rows lack Issue Date → PERMIT_DATE left as
    the existing Permit Date value (cannot confirm true issuance).
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
    if "permit_status" in keys or "permit_status_detail" in keys:
        return "permit_status"
    if "project" in keys:
        return "project"
    if "detail" in keys:
        return "detail_only"
    return "unknown"


# ── Status mapping tables ────────────────────────────────────────────────────

# permit_status: Status for Permit Number → STATUS_NORMALIZED
_PERMIT_NUM_STATUS_MAP = {
    "CLOSED": "Final",
    "FINAL INSPECTION COMPLETE": "Final",
    "C.O. ISSUED": "Final",
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
    "CERTIFICATE ISSUED": "Final",
}

# project: Permit Center Tracking / description Type → STATUS_NORMALIZED
_PROJECT_ACTIVE_TYPES = {
    "Approved",
    "Approved with conditions",
    "Notified client of issuance",
}
_PROJECT_INACTIVE_TYPES = {
    "Withdrawn from plan check",
    "Expired Plan Check",
    "Rejected",
}
_PROJECT_REVIEW_TYPES = {
    "Corrections",
    "Plan check is on hold",
    "Called client to pick up department corrections",
    "Plan check corrections picked up by contact",
    "Mailed plan check corrections",
    "Routed to department for review",
    "New/Resubmittal items received",
    "CONTINUED",
    "PLAN CHECK TIME",
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


def _fill_date_only(repairs: dict, field: str, current, canonical):
    """Fill *field* when missing; do not overwrite an existing value."""
    if canonical is pd.NaT or canonical is None:
        return
    if pd.isna(current):
        repairs[field] = canonical
        repairs[f"{field}_FLAG"] = "FILLED"


def _clear_date(repairs: dict, field: str, current):
    if pd.isna(current):
        return
    repairs[field] = pd.NaT
    repairs[f"{field}_FLAG"] = "FIXED"


# ── Shared extractors ────────────────────────────────────────────────────────

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


def _project_pct_item(desc) -> Optional[dict]:
    if not isinstance(desc, list):
        return None
    for item in desc:
        if isinstance(item, dict) and item.get("Description") == (
            "Permit Center Tracking Information"
        ):
            return item
    for item in desc:
        if isinstance(item, dict) and item.get("Subtype") == "A 0":
            return item
    return None


def _derive_project_status(d: dict) -> Optional[str]:
    desc = d.get("description") or []
    if not isinstance(desc, list):
        return None
    pct = _project_pct_item(desc)
    pct_type = pct.get("Type") if isinstance(pct, dict) else None
    types = [i.get("Type") for i in desc if isinstance(i, dict)]

    if pct_type in _PROJECT_ACTIVE_TYPES:
        return "Active"
    if pct_type in _PROJECT_INACTIVE_TYPES:
        return "Inactive"
    if pct_type in _PROJECT_REVIEW_TYPES:
        return "In Review"
    if any(t in _PROJECT_INACTIVE_TYPES for t in types):
        return "Inactive"
    if any(t in _PROJECT_REVIEW_TYPES for t in types):
        return "In Review"
    if any(t in _PROJECT_ACTIVE_TYPES for t in types):
        return "Active"
    return None


def _project_permit_date(d: dict):
    """Best available issuance-like date from description Last Action."""
    desc = d.get("description") or []
    if not isinstance(desc, list):
        return pd.NaT

    pct = _project_pct_item(desc)
    if isinstance(pct, dict) and pct.get("Type") in _PROJECT_ACTIVE_TYPES:
        dt = _safe_to_datetime(pct.get("Last Action"))
        if dt is not pd.NaT:
            return dt

    approved = []
    for item in desc:
        if not isinstance(item, dict):
            continue
        if item.get("Type") not in _PROJECT_ACTIVE_TYPES:
            continue
        dt = _safe_to_datetime(item.get("Last Action"))
        if dt is not pd.NaT:
            approved.append(dt)
    if approved:
        return max(approved)
    return pd.NaT


# ── Per-schema repair ────────────────────────────────────────────────────────

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

    app_date = _safe_to_datetime(
        det.get("Application Date") or psd.get("Application Date")
    )
    _set_date(repairs, "FILE_DATE", row["FILE_DATE"], app_date)

    # Issue Date is true issuance; Permit Date often stores finaling date.
    issue = _safe_to_datetime(psd.get("Issue Date"))
    if effective in ("Active", "Final"):
        if issue is not pd.NaT:
            _set_date(repairs, "PERMIT_DATE", row["PERMIT_DATE"], issue)
        # else: leave existing Permit Date value (cannot confirm issuance)
    elif effective == "In Review":
        if issue is pd.NaT:
            _clear_date(repairs, "PERMIT_DATE", row["PERMIT_DATE"])
        else:
            _set_date(repairs, "PERMIT_DATE", row["PERMIT_DATE"], issue)
    elif effective == "Inactive":
        if issue is pd.NaT:
            _clear_date(repairs, "PERMIT_DATE", row["PERMIT_DATE"])
        else:
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


def _repair_project(row, d: dict, repairs: dict):
    expected = _derive_project_status(d)
    _set_status(repairs, row["STATUS_NORMALIZED"], expected)
    effective = repairs.get("STATUS_NORMALIZED", row["STATUS_NORMALIZED"])

    # No application / file date in this schema.
    if effective in ("Active", "Final"):
        _fill_date_only(
            repairs, "PERMIT_DATE", row["PERMIT_DATE"], _project_permit_date(d)
        )
    elif effective == "In Review":
        _clear_date(repairs, "PERMIT_DATE", row["PERMIT_DATE"])

    if effective != "Final":
        _clear_date(repairs, "FINAL_DATE", row["FINAL_DATE"])


# ── Main entry point ─────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Oxnard permit records using information from the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Oxnard".  Must contain
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
        if schema == "permit_status":
            _repair_permit_status(row, d, repairs)
        elif schema == "detail_only":
            _repair_detail_only(row, d, repairs)
        elif schema == "project":
            _repair_project(row, d, repairs)

        for key, value in repairs.items():
            out.at[idx, key] = value

    return out


# ── CLI: run standalone to preview repair stats ─────────────────────────────

if __name__ == "__main__":
    import os
    from dotenv import load_dotenv

    load_dotenv("/Users/ekung/projects/la-permits-data/.env")
    MY_DATA_PATH = os.getenv("MY_DATA_PATH")
    AGENT_DATA_PATH = os.getenv("AGENT_DATA_PATH")
    filepath = os.path.join(MY_DATA_PATH, "processed_data", "permits_ca_sample.parquet")
    df = pd.read_parquet(filepath)
    city = df[(df["JURISDICTION"] == "Oxnard") & (df["STATE"] == "CA")].copy()

    print(f"Oxnard records: {len(city):,}\n")

    repaired = data_repair(city)

    if AGENT_DATA_PATH:
        out_path = os.path.join(AGENT_DATA_PATH, "oxnard_repaired_sample.parquet")
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
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({n_has/len(sub) if len(sub) else 0:.1%})")

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

"""Data repair for North Port (FL) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

North Port DATA has two portal families in this sample:

  - Legacy city portal (same family as Boca Raton / Lake Mary):
      permit_status: detail/fees + permit_status_detail +
                     insp_status_detail
      fees_detail:   detail + fees + fees_total only
  - Accela Citizen Access (same family as Brevard County):
      accela_full:   dated task events + inspections list
      accela_basic:  dated task events, empty inspections

Canonical mappings (legacy):
  - Status for Permit Number, overridden to Inactive when
    Application Status is VOID / CANCELLED / ABANDONED /
    EXPIRED/4YEARS                                   → STATUS_NORMALIZED
  - Application Date                                 → FILE_DATE
  - Issue Date (fallback: Permit Date for Active /
    Final when Issue blank and not after FINAL)      → PERMIT_DATE
  - Latest APPROVED FINAL/FNL/CLOSEOUT inspection;
    else latest non-NOC APPROVED                     → FINAL_DATE

Canonical mappings (Accela):
  - DATA.status (else search_data.Status)            → STATUS_NORMALIZED
  - search_data.Date else DATA.date else earliest
    Application Intake Accepted/Submitted            → FILE_DATE
  - Earliest Issuance ``Issued``                     → PERMIT_DATE
  - Latest of: Closed ``Closed``; Certification
    ``CO Issued`` / ``CC Issued``; Inspection
    ``Closed``; Pass inspections with FINAL in title → FINAL_DATE

Known issues repaired:
  - Legacy CLOSED + VOID/CANCELLED/ABANDONED/EXPIRED
    incorrectly labeled Final → FIXED to Inactive.
  - A handful of CLOSED / C.O. ISSUED / PERMIT PRINTED
    rows with the wrong STATUS_NORMALIZED → FIXED.
  - fees_detail null STATUS_NORMALIZED filled from
    Application Status (SUBMITTED / VOID / CANCELLED).
  - Accela ``Schedule Inspection`` (issued, awaiting
    inspection) left null → FILLED as Active.
  - Accela ``Approved`` (plans approved, not issued)
    was Active → FIXED to In Review.
  - Legacy PERMIT_DATE ingested from portal "Permit Date"
    (often post-dates FINAL) → FIXED to Issue Date.
  - Missing Accela FINAL_DATE on Closed / CO Issued
    rows filled from Closed-task / final inspections.

Not repairable from DATA:
  - Two legacy Inactive rows have blank Application Date
    → FILE_DATE stays missing.
  - Accela ``Approved`` Active→In Review rows and a few
    Final shells have no Issuance ``Issued`` event
    → PERMIT_DATE stays missing.
  - Legacy Final rows with empty / non-APPROVED inspection
    history → FINAL_DATE stays missing.
  - Four Accela shells have null status → STATUS stays null.
"""

from __future__ import annotations

import json
import math
import re
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
    """Parse a date value, returning pd.NaT on failure / sentinels."""
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


def _dates_equal(a, b) -> bool:
    """Compare two datelike values at calendar-day resolution."""
    da = _safe_to_datetime(a)
    db = _safe_to_datetime(b)
    if da is pd.NaT or db is pd.NaT or pd.isna(da) or pd.isna(db):
        return False
    return pd.Timestamp(da).normalize() == pd.Timestamp(db).normalize()


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
    if cand is pd.NaT or pd.isna(cand):
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


# ── Accela task helpers ──────────────────────────────────────────────────────

def _event_field(event: dict, *labels: str):
    for label in labels:
        for k, v in event.items():
            if not isinstance(k, str):
                continue
            if k.replace("\xa0", " ").strip().lower() == label.lower():
                if isinstance(v, str):
                    return v.replace("\xa0", " ").strip()
                return v
    return None


def _parse_event(event: dict):
    """Return (marked_as, on_date_str) from an Accela task event."""
    html = (event.get("html") or "").replace("\xa0", " ")
    m = re.search(
        r"Marked as\s*<span[^>]*>([^<]*)</span>\s*on\s*<span[^>]*>([^<]*)</span>",
        html,
        flags=re.I,
    )
    if m:
        return m.group(1).strip(), m.group(2).strip()

    marked = _event_field(event, "Marked as")
    on_val = _event_field(event, "on")
    return marked, on_val


def _iter_task_nodes(tasks: list):
    for t in tasks or []:
        if not isinstance(t, dict):
            continue
        yield (t.get("name") or "").replace("\xa0", " ").strip(), t
        for st in t.get("subtasks") or []:
            if isinstance(st, dict):
                yield (st.get("name") or "").replace("\xa0", " ").strip(), st


def _has_dated_task_event(tasks: list) -> bool:
    for _, t in _iter_task_nodes(tasks):
        for e in t.get("events") or []:
            if not isinstance(e, dict):
                continue
            _, on_val = _parse_event(e)
            if _safe_to_datetime(on_val) is not pd.NaT:
                return True
    return False


def _event_dates(tasks: list, task_names, marked_pred) -> list:
    if isinstance(task_names, str):
        task_names = {task_names}
    else:
        task_names = set(task_names)
    dates = []
    for name, t in _iter_task_nodes(tasks):
        if name not in task_names:
            continue
        for e in t.get("events") or []:
            if not isinstance(e, dict):
                continue
            marked, on_val = _parse_event(e)
            marked = (marked or "").strip() if isinstance(marked, str) else marked
            if not marked or not marked_pred(marked):
                continue
            dt = _safe_to_datetime(on_val)
            if dt is not pd.NaT and not pd.isna(dt):
                dates.append(dt)
    return dates


# ── Schema classification ────────────────────────────────────────────────────

def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    if not isinstance(data_dict, dict):
        return "unknown"

    keys = set(data_dict.keys())

    # Accela Citizen Access
    if "tasks" in keys or (
        "status" in keys and "search_data" in keys and "date" in keys
    ):
        tasks = data_dict.get("tasks") or []
        inspections = data_dict.get("inspections")
        has_inspections = isinstance(inspections, list) and len(inspections) > 0
        has_dated_event = _has_dated_task_event(tasks)
        if has_dated_event and has_inspections:
            return "accela_full"
        if has_dated_event:
            return "accela_basic"
        return "accela_shell"

    # Legacy city portal
    if "permit_status_detail" in keys:
        return "permit_status"
    if "detail" in keys and "fees" in keys:
        return "fees_detail"
    return "unknown"


# ── Status maps ──────────────────────────────────────────────────────────────

# Legacy "Status for Permit Number"
_LEGACY_SP_MAP = {
    "FINAL INSPECTION COMPLETE": "Final",
    "CLOSED": "Final",
    "C.O. ISSUED": "Final",
    "FINALED": "Final",
    "CLOSED MANUALLY - FINALED": "Final",
    "CERTIFICATE OF COMPLETION": "Final",
    "PERMIT PRINTED": "Active",
    "PERMIT ISSUED": "Active",
    "TO BE ISSUED": "In Review",
    "PLAN CHECK": "In Review",
    "PLANS BEING CHECKED": "In Review",
    "PERMIT REVOKED": "Inactive",
    "PERMIT EXPIRED": "Inactive",
    "WITHDRAWN": "Inactive",
}

# Legacy / fees_detail "Application Status"
_LEGACY_APP_MAP = {
    "CO ISSUED": "Final",
    "CERTIFICATE OF COMPLETION": "Final",
    "COMPLETED": "Final",
    "CLOSED": "Final",
    "ISSUED": "Active",
    "READY FOR PICKUP": "In Review",
    "SUBMITTED": "In Review",
    "HOLD FOR INFORMATION": "In Review",
    "VOID": "Inactive",
    "CANCELLED": "Inactive",
    "ABANDONED": "Inactive",
    "EXPIRED/4YEARS": "Inactive",
    "WITHDRAWN": "Inactive",
}

# Application Status values that mean the permit never completed, even when
# Status for Permit Number says CLOSED.
_INACTIVE_APP_OVERRIDE = {
    "VOID",
    "CANCELLED",
    "ABANDONED",
    "EXPIRED/4YEARS",
    "WITHDRAWN",
}

# Accela DATA.status
_ACCELA_STATUS_MAP = {
    "Closed": "Final",
    "CO Issued": "Final",
    "CC Issued": "Final",
    "Complete": "Final",
    "Issued": "Active",
    "Schedule Inspection": "Active",
    # Plans approved but not yet issued — not Active (no issuance date).
    "Approved": "In Review",
    "Waiting for Payment": "In Review",
    "Awaiting Plans": "In Review",
    "Revisions Received": "In Review",
    "Withdrawn": "Inactive",
    "Expired": "Inactive",
    "Disapproved": "Inactive",
    "Void": "Inactive",
}

_ACCELA_STATUS_MAP_LOWER = {k.lower(): v for k, v in _ACCELA_STATUS_MAP.items()}


def _map_legacy_sp(raw: Optional[str]) -> Optional[str]:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    return _LEGACY_SP_MAP.get(text) or _LEGACY_SP_MAP.get(text.upper())


def _map_legacy_app(raw: Optional[str]) -> Optional[str]:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    return _LEGACY_APP_MAP.get(text) or _LEGACY_APP_MAP.get(text.upper())


def _legacy_expected_status(sp_raw, app_raw) -> Optional[str]:
    """Status for Permit Number, overridden by terminal Application Status."""
    app = (str(app_raw).strip() if app_raw is not None else "")
    sp_expected = _map_legacy_sp(sp_raw)
    if app.upper() in _INACTIVE_APP_OVERRIDE or app in _INACTIVE_APP_OVERRIDE:
        # Prefer Inactive when the application was voided/cancelled even if
        # the permit-number status still reads CLOSED.
        return "Inactive"
    if sp_expected is not None:
        return sp_expected
    return _map_legacy_app(app_raw)


def _accela_raw_status(d: dict) -> str:
    status = d.get("status")
    if isinstance(status, str) and status.strip():
        return status.strip()
    sd = d.get("search_data") if isinstance(d.get("search_data"), dict) else {}
    sd_status = sd.get("Status")
    if isinstance(sd_status, str) and sd_status.strip():
        return sd_status.strip()
    return ""


def _map_accela_status(data_status: str) -> Optional[str]:
    if not data_status:
        return None
    return (
        _ACCELA_STATUS_MAP.get(data_status)
        or _ACCELA_STATUS_MAP_LOWER.get(data_status.lower())
    )


# ── Legacy date extractors ───────────────────────────────────────────────────

def _is_final_inspection_name(name: str) -> bool:
    upper = str(name or "").upper()
    if "FINAL" in upper:
        return True
    if re.search(r"(^|[^A-Z])FNL([^A-Z]|$)", upper):
        return True
    if "CLOSEOUT" in upper:
        return True
    return False


def _is_noc_inspection_name(name: str) -> bool:
    return "NOC" in str(name or "").upper()


def _final_date_from_legacy_inspections(insp_detail) -> pd.Timestamp:
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


# ── Accela date extractors ───────────────────────────────────────────────────

def _file_date_from_accela(d: dict):
    sd = d.get("search_data") if isinstance(d.get("search_data"), dict) else {}
    dt = _safe_to_datetime(sd.get("Date"))
    if dt is not pd.NaT and not pd.isna(dt):
        return dt

    dt = _safe_to_datetime(d.get("date"))
    if dt is not pd.NaT and not pd.isna(dt):
        return dt

    tasks = d.get("tasks") or []
    intake = _event_dates(
        tasks,
        {"Application Intake"},
        lambda m: (m or "").strip().lower()
        in {"accepted", "submitted", "additional info received"},
    )
    if intake:
        return min(intake)
    return pd.NaT


def _permit_date_from_accela(tasks: list):
    issued = _event_dates(
        tasks,
        {"Issuance"},
        lambda m: (m or "").strip().lower() == "issued",
    )
    if issued:
        return min(issued)
    return pd.NaT


def _final_insp_dates_from_accela(d: dict) -> list:
    dates = []
    for insp in d.get("inspections") or []:
        if not isinstance(insp, dict):
            continue
        title = insp.get("Title") or ""
        status = (insp.get("Status") or "").strip()
        if status != "Pass":
            continue
        if not _is_final_inspection_name(title):
            continue
        # Skip soil-erosion etc. that match via "CONTROL" false positive — only
        # titles that actually contain FINAL/FNL/CLOSEOUT are kept by helper.
        dt = _safe_to_datetime(insp.get("Status Date"))
        if dt is not pd.NaT and not pd.isna(dt):
            dates.append(dt)
    return dates


def _final_date_from_accela(d: dict):
    """Latest closeout date from Closed task / CO / Inspection Closed / finals."""
    tasks = d.get("tasks") or []
    dates: list = []

    dates.extend(
        _event_dates(
            tasks,
            {"Closed"},
            lambda m: (m or "").strip().lower() == "closed",
        )
    )
    dates.extend(
        _event_dates(
            tasks,
            {"Certification"},
            lambda m: (m or "").strip().lower()
            in {"co issued", "cc issued"},
        )
    )
    dates.extend(
        _event_dates(
            tasks,
            {"Inspection"},
            lambda m: (m or "").strip().lower() == "closed",
        )
    )
    dates.extend(_final_insp_dates_from_accela(d))

    if dates:
        return max(dates)
    return pd.NaT


# ── Per-schema repair ────────────────────────────────────────────────────────

def _repair_permit_status(row, d: dict, repairs: dict) -> None:
    """Repair a legacy permit_status record."""
    detail = d.get("permit_status_detail") or {}
    if not isinstance(detail, dict):
        detail = {}
    top_detail = d.get("detail") or {}
    if not isinstance(top_detail, dict):
        top_detail = {}

    expected = _legacy_expected_status(
        detail.get("Status for Permit Number"),
        top_detail.get("Application Status"),
    )
    effective_status = _apply_status(repairs, row["STATUS_NORMALIZED"], expected)

    app_date = detail.get("Application Date") or top_detail.get("Application Date")
    _apply_date(repairs, row, "FILE_DATE", app_date)

    final_src = _final_date_from_legacy_inspections(d.get("insp_status_detail"))
    current_final = row["FINAL_DATE"]
    if effective_status == "Final":
        if final_src is not pd.NaT and not pd.isna(final_src):
            if pd.isna(current_final):
                repairs["FINAL_DATE"] = final_src
                repairs["FINAL_DATE_FLAG"] = "FILLED"
            elif not _dates_equal(current_final, final_src):
                repairs["FINAL_DATE"] = final_src
                repairs["FINAL_DATE_FLAG"] = "FIXED"
        elif not pd.isna(current_final):
            # Drop FINAL that is not supported by any APPROVED inspection.
            _clear_date(repairs, row, "FINAL_DATE")
    elif not pd.isna(current_final):
        _clear_date(repairs, row, "FINAL_DATE")

    effective_final = repairs.get("FINAL_DATE", current_final)

    issue = _safe_to_datetime(detail.get("Issue Date"))
    permit_date_field = _safe_to_datetime(detail.get("Permit Date"))

    if issue is not pd.NaT and not pd.isna(issue):
        _apply_date(repairs, row, "PERMIT_DATE", issue)
    elif effective_status in ("Active", "Final") and permit_date_field is not pd.NaT:
        after_final = (
            effective_final is not pd.NaT
            and not pd.isna(effective_final)
            and permit_date_field.normalize()
            > _safe_to_datetime(effective_final).normalize()
        )
        if not after_final:
            _apply_date(repairs, row, "PERMIT_DATE", permit_date_field)
        elif not pd.isna(row["PERMIT_DATE"]):
            _clear_date(repairs, row, "PERMIT_DATE")
    elif effective_status == "In Review":
        # Unissued rows sometimes carry a processing "Permit Date".
        if issue is pd.NaT or pd.isna(issue):
            _clear_date(repairs, row, "PERMIT_DATE")


def _repair_fees_detail(row, d: dict, repairs: dict) -> None:
    """Repair a sparse fees_detail record."""
    detail = d.get("detail") or {}
    if not isinstance(detail, dict):
        detail = {}

    expected = _map_legacy_app(detail.get("Application Status"))
    # Also honor inactive override language if somehow SP-like text appears.
    app = (detail.get("Application Status") or "").strip()
    if app.upper() in _INACTIVE_APP_OVERRIDE or app in _INACTIVE_APP_OVERRIDE:
        expected = "Inactive"
    effective_status = _apply_status(repairs, row["STATUS_NORMALIZED"], expected)

    _apply_date(repairs, row, "FILE_DATE", detail.get("Application Date"))

    if effective_status == "In Review":
        _clear_date(repairs, row, "PERMIT_DATE")
    if effective_status != "Final" and not pd.isna(row["FINAL_DATE"]):
        _clear_date(repairs, row, "FINAL_DATE")


def _repair_accela(row, d: dict, repairs: dict) -> None:
    """Repair an Accela Citizen Access record."""
    tasks = d.get("tasks") or []

    expected = _map_accela_status(_accela_raw_status(d))
    effective_status = _apply_status(repairs, row["STATUS_NORMALIZED"], expected)

    _apply_date(repairs, row, "FILE_DATE", _file_date_from_accela(d))

    issued = _permit_date_from_accela(tasks)
    current_permit = row["PERMIT_DATE"]
    if issued is not pd.NaT and not pd.isna(issued):
        if pd.isna(current_permit):
            if effective_status in ("Active", "Final"):
                repairs["PERMIT_DATE"] = issued
                repairs["PERMIT_DATE_FLAG"] = "FILLED"
        elif not _dates_equal(current_permit, issued):
            repairs["PERMIT_DATE"] = issued
            repairs["PERMIT_DATE_FLAG"] = "FIXED"
    elif effective_status == "In Review" and not pd.isna(current_permit):
        # Approved / pre-issuance rows should not carry a PERMIT_DATE.
        _clear_date(repairs, row, "PERMIT_DATE")

    final_src = _final_date_from_accela(d)
    if effective_status == "Final":
        _apply_date(repairs, row, "FINAL_DATE", final_src)
    else:
        _clear_date(repairs, row, "FINAL_DATE")


# ── Main entry point ─────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    North Port permit records using information from the raw DATA JSON.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "North Port".  Must contain
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
        elif schema.startswith("accela"):
            _repair_accela(row, d, repairs)

        for key, value in repairs.items():
            out.at[idx, key] = value

    for col in ("FILE_DATE", "PERMIT_DATE", "FINAL_DATE"):
        out[col] = pd.to_datetime(out[col], errors="coerce")

    return out


# ── CLI: run standalone to preview repair stats ──────────────────────────────

if __name__ == "__main__":
    import os
    from pathlib import Path

    from dotenv import load_dotenv

    repo_root = Path(__file__).resolve().parents[3]
    load_dotenv(repo_root / ".env")
    my_data_path = os.getenv("MY_DATA_PATH")
    agent_data_path = os.getenv("AGENT_DATA_PATH")
    filepath = os.path.join(my_data_path, "processed_data", "permits_fl_sample.parquet")
    df = pd.read_parquet(filepath)
    city = df[
        (df["JURISDICTION"] == "North Port") & (df["STATE"] == "FL")
    ].copy()

    print(f"North Port records: {len(city):,}\n")
    repaired = data_repair(city)

    print("INFERRED_SCHEMA:")
    print(repaired["INFERRED_SCHEMA"].value_counts(dropna=False).to_string())
    print()

    for field in ["STATUS_NORMALIZED", "FILE_DATE", "PERMIT_DATE", "FINAL_DATE"]:
        flag_col = f"{field}_FLAG"
        n_filled = (repaired[flag_col] == "FILLED").sum()
        n_fixed = (repaired[flag_col] == "FIXED").sum()
        before_missing = city[field].isna().sum()
        after_missing = repaired[field].isna().sum()
        print(f"{field}:")
        print(f"  FILLED: {n_filled:>4,}   FIXED: {n_fixed:>4,}")
        print(f"  Missing before: {before_missing:>4,}   Missing after: {after_missing:>4,}")
        print()

    print("STATUS_NORMALIZED distribution:")
    print("  Before:")
    for s, c in city["STATUS_NORMALIZED"].value_counts(dropna=False).items():
        print(f"    {str(s):15s}: {c:>4,}")
    print("  After:")
    for s, c in repaired["STATUS_NORMALIZED"].value_counts(dropna=False).items():
        print(f"    {str(s):15s}: {c:>4,}")

    print("\nSTATUS_NORMALIZED transitions (before → after):")
    transitions = (
        pd.DataFrame({
            "before": city["STATUS_NORMALIZED"].astype("object"),
            "after": repaired["STATUS_NORMALIZED"].astype("object"),
        })
        .groupby(["before", "after"], dropna=False)
        .size()
        .reset_index(name="n")
    )
    changed = transitions[
        transitions["before"].astype(str) != transitions["after"].astype(str)
    ]
    print(changed.sort_values("n", ascending=False).to_string(index=False))

    print("\nFILE_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FILE_DATE"].notna().sum()
        print(
            f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} "
            f"({(n_has / len(sub) if len(sub) else 0):.1%})"
        )

    print("\nPERMIT_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["PERMIT_DATE"].notna().sum()
        print(
            f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} "
            f"({(n_has / len(sub) if len(sub) else 0):.1%})"
        )

    print("\nFINAL_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FINAL_DATE"].notna().sum()
        print(
            f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} "
            f"({(n_has / len(sub) if len(sub) else 0):.1%})"
        )

    both = repaired[repaired["PERMIT_DATE"].notna() & repaired["FINAL_DATE"].notna()]
    n_inv = (
        both["PERMIT_DATE"].dt.normalize() > both["FINAL_DATE"].dt.normalize()
    ).sum()
    print(f"\nPERMIT_DATE > FINAL_DATE inversions after repair: {n_inv}")

    before_both = city[city["PERMIT_DATE"].notna() & city["FINAL_DATE"].notna()]
    n_inv_before = (
        pd.to_datetime(before_both["PERMIT_DATE"]).dt.normalize()
        > pd.to_datetime(before_both["FINAL_DATE"]).dt.normalize()
    ).sum()
    print(f"PERMIT_DATE > FINAL_DATE inversions before repair: {n_inv_before}")

    still_null = repaired[repaired["STATUS_NORMALIZED"].isna()]
    print(f"\nRemaining null STATUS_NORMALIZED: {len(still_null):,}")
    if len(still_null):
        print(still_null["INFERRED_SCHEMA"].value_counts().to_string())

    if agent_data_path:
        out_path = os.path.join(agent_data_path, "north_port_repaired_sample.parquet")
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote repaired sample → {out_path}")

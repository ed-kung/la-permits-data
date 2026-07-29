"""Data repair for Pittsburg (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Pittsburg DATA is an Accela Citizen Access scrape (same family as
Martinez / Yuba City / Solano County). Most sample rows share the full
portal key set (``address``, ``date``, ``status``, ``tasks``,
``inspections``, ``search_data``, …); a minority of TMP shells are
``search_data``-only. Content variants (INFERRED_SCHEMA):

  - portal_issued_finaled:   Permit Issuance / License Renewal Issued +
                             final-inspection / closure evidence
  - portal_issued:           Issued present, no finaling date
  - portal_final_insp_only:  Final evidence present, no Issued
  - portal_application_only: Application Intake / top-level date only
  - portal_empty_tasks:      tasks present but undated (TBD / empty)
  - search_data_only:        status-blank TMP shells with only search_data
  - missing

Canonical mappings:
  - DATA.status / search_data.Status (+ workflow upgrade when Issued /
    Final Inspection Complete / Passed final inspection exists)
                                                         → STATUS_NORMALIZED
  - Earliest of DATA.date / search_data.Date / Application /
    Application Intake Accepted*                         → FILE_DATE
  - Earliest Permit Issuance / Issuance / License Renewal
    Marked as Issued / Renewed / Permit Issued           → PERMIT_DATE
  - Earliest Inspection(s) Final Inspection Complete
    (fallback: Closure Closed - Complete / In Compliance /
    Closed; Application Intake Closed - Owner Occupied /
    Closed - Exempt; Passed final inspections[])         → FINAL_DATE

Known issues repaired:
  - Null STATUS_NORMALIZED (Closed - Exempt, Closed – No Activity,
    blank TMP shells, enforcement / fee shells) → FILLED.
  - Active / Issued / Renewed shells with Final Inspection Complete
    or Passed final inspection (portal CaseStatus lag) → FIXED to Final.
  - Notice Issued / Inspection Required code-violation shells wrongly
    labeled Final → FIXED to Active / In Review.
  - Renewed Active shells missing PERMIT_DATE while License Renewal
    Issued exists → FILLED.
  - Final rows missing FINAL_DATE while Closure Closed - Complete /
    Owner Occupied / Closed - Exempt / Passed final inspection
    exists → FILLED.
  - FILE_DATE pulled forward from DATA.date to an earlier Application
    Intake Accepted stamp (4 rows) → FIXED.
  - Spurious FINAL_DATE on non-Final (withdrawn, expired) → FIXED
    (cleared).

Not repairable / left as-is:
  - ~457 Active/Final shells (mostly STATUS_ORIGINAL=active rental /
    inspection program records, or Issued with Permit Issuance TBD)
    have no dated Issued mark → PERMIT_DATE stays missing.
  - 4 Final shells (Closed - Complete / Closed / Final Inspection
    Complete with no dated completion mark or Passed final
    inspection) → FINAL_DATE stays missing.
  - search_data-only TMP shells have no status and no workflow dates
    beyond the opened Date (already on FILE_DATE) → stay In Review
    with blank PERMIT_DATE / FINAL_DATE.
"""

from __future__ import annotations

import json
import math
import re
from typing import Optional

import numpy as np
import pandas as pd


_MIN_YEAR = 1990
_MAX_YEAR = 2035

# Accela HTML sometimes includes inline styles on the <span> tags.
_MARKED_RE = re.compile(
    r"Marked as\s*<span[^>]*>([^<]*)</span>\s*on\s*<span[^>]*>([^<]*)</span>",
    re.I,
)

_INACTIVE = {
    "Expired",
    "Permit Expired",
    "Application Expired",
    "About to Expire",
    "Void",
    "Closed - Void",
    "Withdrawn",
    "Application Withdrawn",
    "Canceled",
    "Cancelled",
    "CANCELLED",
    "Revoked",
    "Denied",
    "Closed - Denied",
    "Inactive",
    "Closed - No Activity",
    "Closed – No Activity",  # en-dash variant
    "Closed - Withdrawn",
    "Closed - Exempt",
    "Closed-Exempt",
    "Exempt-Sold",
    "Exempt-Subsidized",
}

_FINAL_STATUSES = {
    "Final Inspection Complete",
    "Closed - Complete",
    "Closed - Owner Occupied",
    "Closed - In Compliance",
    "Closed",
    "Finaled",
    "Finalled",
    "Complete",
    "CLOSED",
}

_ACTIVE_STATUSES = {
    "Issued",
    "Permit Issued",
    "Active",
    "Renewed",
    "Inspection Pending",
    "Citation Issued",
    "Permit Issued CV Pending",
    "Notice Issued",
}

_ISSUE_TASKS = {
    "Permit Issuance",
    "Issuance",
    "License Renewal",
}
_ISSUE_MARKS = {"Issued", "Renewed", "Permit Issued"}

_FINAL_INSP_TASKS = {"Inspection", "Inspections"}
_FINAL_INSP_MARKS = {"Final Inspection Complete"}

_CLOSURE_TASKS = {"Closure", "Inspection", "Inspections", "Investigation"}
_CLOSURE_MARKS = {
    "Closed - Complete",
    "Closed - In Compliance",
    "Closed - Owner Occupied",
    "Closed",
}

# Rental / admin closures often stamp Closed - Exempt on Application
# Intake even when portal status reads Closed - Owner Occupied.
_ADMIN_CLOSE_TASKS = {"Application Intake", "Application", "Closure"}
_ADMIN_CLOSE_MARKS = {
    "Closed - Owner Occupied",
    "Closed - Exempt",
    "Closed-Exempt",
}

_FILE_TASKS = {"Application", "Application Intake"}
_FILE_MARK_PREFIXES = (
    "accepted",
    "submitted",
    "initiated",
    "fees paid",
    "fees invoiced",
    "received",
)


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
        if not data.strip():
            return None
        return json.loads(data)
    return data


def _safe_to_datetime(val):
    """Parse a date value, returning pd.NaT on failure / TBD / bad year."""
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return pd.NaT
    if isinstance(val, dict):
        return pd.NaT
    if isinstance(val, str):
        s = val.strip()
        if not s or s.upper() in {"TBD", "NULL", "NONE", "N/A", "NA"}:
            return pd.NaT
    try:
        dt = pd.to_datetime(val, errors="coerce")
    except (ValueError, TypeError):
        return pd.NaT
    if dt is pd.NaT or pd.isna(dt):
        return pd.NaT
    dt = pd.Timestamp(dt)
    if getattr(dt, "tzinfo", None) is not None:
        dt = dt.tz_convert("UTC").tz_localize(None)
    year = int(dt.year)
    if year < _MIN_YEAR or year > _MAX_YEAR:
        return pd.NaT
    return dt


def _dates_equal(a, b) -> bool:
    da = _safe_to_datetime(a)
    db = _safe_to_datetime(b)
    if da is pd.NaT or db is pd.NaT or pd.isna(da) or pd.isna(db):
        return False
    return da.normalize() == db.normalize()


def _event_field(event: dict, *names: str):
    """Read an Accela event field; keys are often padded with spaces/nbsp."""
    normalized = {
        k.replace("\xa0", " ").strip(): v
        for k, v in event.items()
        if isinstance(k, str)
    }
    for name in names:
        if name.strip() in normalized:
            return normalized[name.strip()]
    return None


def _iter_tasks(tasks: list):
    for t in tasks or []:
        if not isinstance(t, dict):
            continue
        yield t
        for st in t.get("subtasks") or []:
            if isinstance(st, dict):
                yield st


def _event_mark_and_date(event: dict):
    """Return (marked_as, event_date).

    Prefer the Accela ``on`` key and fall back to HTML
    ``Marked as … on …`` spans, including styled spans.
    """
    if not isinstance(event, dict):
        return None, pd.NaT

    mark = _event_field(event, "Marked as", "status", "Status")
    on = _safe_to_datetime(_event_field(event, "on"))

    html = event.get("html") or ""
    if isinstance(html, str) and html:
        m = _MARKED_RE.search(html)
        if m:
            if not (isinstance(mark, str) and mark.strip()):
                mark = m.group(1)
            html_on = _safe_to_datetime(m.group(2))
            if on is pd.NaT and html_on is not pd.NaT:
                on = html_on

    if isinstance(mark, str):
        mark = (
            mark.replace("&amp;", "&")
            .replace("&nbsp;", " ")
            .strip()
        )
    else:
        mark = None
    return mark, on


def _event_dates(tasks: list, task_names, statuses):
    if isinstance(task_names, str):
        task_names = {task_names}
    if isinstance(statuses, str):
        statuses = {statuses}
    statuses_l = {s.lower() for s in statuses}
    dates = []
    for t in _iter_tasks(tasks):
        if t.get("name") not in task_names:
            continue
        for e in t.get("events") or []:
            mark, on = _event_mark_and_date(e)
            if not mark or mark.lower() not in statuses_l:
                continue
            if on is not pd.NaT:
                dates.append(on)
    return dates


def _first_event_date(tasks: list, task_names, statuses):
    dates = _event_dates(tasks, task_names, statuses)
    return min(dates) if dates else pd.NaT


def _has_dated_events(d: dict) -> bool:
    for t in _iter_tasks(d.get("tasks") or []):
        for e in t.get("events") or []:
            _, on = _event_mark_and_date(e)
            if on is not pd.NaT:
                return True
    return False


def _normalize_status_key(raw: str) -> str:
    """Collapse whitespace / dash variants for fuzzy lookup."""
    s = raw.replace("\u2013", "-").replace("\u2014", "-")
    s = " ".join(s.strip().split())
    return s


# ── Date extractors ──────────────────────────────────────────────────────────

def _application_file_dates(tasks: list) -> list:
    dates = []
    for t in _iter_tasks(tasks):
        if t.get("name") not in _FILE_TASKS:
            continue
        for e in t.get("events") or []:
            mark, on = _event_mark_and_date(e)
            if on is pd.NaT or not mark:
                continue
            ml = mark.lower()
            if any(ml.startswith(p) or p in ml for p in _FILE_MARK_PREFIXES):
                dates.append(on)
    return dates


def _file_date_from_data(d: dict):
    """Earliest application / opened date from Accela fields."""
    candidates = []

    top = _safe_to_datetime(d.get("date"))
    if top is not pd.NaT:
        candidates.append(top)

    sd = d.get("search_data")
    if isinstance(sd, dict):
        for key in ("Date", "Opened Date", "Submitted Date", "Application Date"):
            opened = _safe_to_datetime(sd.get(key))
            if opened is not pd.NaT:
                candidates.append(opened)

    candidates.extend(_application_file_dates(d.get("tasks") or []))
    return min(candidates) if candidates else pd.NaT


def _permit_date_from_data(d: dict):
    """Earliest Permit Issuance / Issuance / License Renewal Issued date."""
    return _first_event_date(d.get("tasks") or [], _ISSUE_TASKS, _ISSUE_MARKS)


def _passed_final_inspection_dates(d: dict) -> list:
    """Dates from inspections[] with Passed/Approved and a final-titled row."""
    dates = []
    for insp in d.get("inspections") or []:
        if not isinstance(insp, dict):
            continue
        title = str(insp.get("Title") or "").lower()
        status = str(insp.get("Status") or "").strip().lower()
        if "final" not in title:
            continue
        if status not in {"passed", "approved", "completed"}:
            continue
        dt = _safe_to_datetime(insp.get("Status Date"))
        if dt is not pd.NaT:
            dates.append(dt)
    return dates


def _final_date_from_data(d: dict):
    """Prefer Inspection Final Inspection Complete, then closure /
    owner-occupied marks, then Passed final inspections[]."""
    tasks = d.get("tasks") or []

    final = _first_event_date(tasks, _FINAL_INSP_TASKS, _FINAL_INSP_MARKS)
    if final is not pd.NaT:
        return final

    final = _first_event_date(tasks, _CLOSURE_TASKS, _CLOSURE_MARKS)
    if final is not pd.NaT:
        return final

    final = _first_event_date(tasks, _ADMIN_CLOSE_TASKS, _ADMIN_CLOSE_MARKS)
    if final is not pd.NaT:
        return final

    co = _first_event_date(
        tasks, {"Certificate of Occupancy"}, {"C of O Issued"}
    )
    if co is not pd.NaT:
        return co

    passed = _passed_final_inspection_dates(d)
    return min(passed) if passed else pd.NaT


def _final_task_date(d: dict):
    """Completion evidence used for status promotion (tasks + Passed final).

    Prefer Accela Final Inspection Complete; also accept Passed
    final-titled inspections when the portal status already says Final
    Inspection Complete but the workflow Marked-as stamp is TBD.
    """
    tasks = d.get("tasks") or []
    final = _first_event_date(tasks, _FINAL_INSP_TASKS, _FINAL_INSP_MARKS)
    if final is not pd.NaT:
        return final
    final = _first_event_date(tasks, {"Closure"}, {"Closed - Complete"})
    if final is not pd.NaT:
        return final
    passed = _passed_final_inspection_dates(d)
    return min(passed) if passed else pd.NaT


# ── Schema classification ───────────────────────────────────────────────────

def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"

    keys = set(data_dict.keys())
    if keys <= {"search_data"}:
        return "search_data_only"

    tasks = data_dict.get("tasks") or []
    has_tasks = isinstance(tasks, list) and len(tasks) > 0
    issued = _permit_date_from_data(data_dict) is not pd.NaT
    finaled = _final_date_from_data(data_dict) is not pd.NaT

    if issued and finaled:
        return "portal_issued_finaled"
    if issued and not finaled:
        return "portal_issued"
    if finaled and not issued:
        return "portal_final_insp_only"
    if _has_dated_events(data_dict) or _safe_to_datetime(data_dict.get("date")) is not pd.NaT:
        return "portal_application_only"
    if has_tasks:
        return "portal_empty_tasks"
    return "portal_empty_tasks"


# ── Status mapping ──────────────────────────────────────────────────────────

_STATUS_MAP = {
    # Final
    "Final Inspection Complete": "Final",
    "Closed - Complete": "Final",
    "Closed - Owner Occupied": "Final",
    "Closed - In Compliance": "Final",
    "Closed": "Final",
    "Finaled": "Final",
    "Finalled": "Final",
    "Complete": "Final",
    "CLOSED": "Final",
    # Active
    "Issued": "Active",
    "Permit Issued": "Active",
    "Active": "Active",
    "Renewed": "Active",
    "Inspection Pending": "Active",
    "Citation Issued": "Active",
    "Permit Issued CV Pending": "Active",
    "Notice Issued": "Active",
    # Inactive
    "Expired": "Inactive",
    "Permit Expired": "Inactive",
    "Application Expired": "Inactive",
    "About to Expire": "Inactive",
    "Void": "Inactive",
    "Closed - Void": "Inactive",
    "Withdrawn": "Inactive",
    "Application Withdrawn": "Inactive",
    "Closed - Withdrawn": "Inactive",
    "Canceled": "Inactive",
    "Cancelled": "Inactive",
    "Denied": "Inactive",
    "Closed - Denied": "Inactive",
    "Inactive": "Inactive",
    "Closed - No Activity": "Inactive",
    "Closed – No Activity": "Inactive",
    "Closed - Exempt": "Inactive",
    "Closed-Exempt": "Inactive",
    "Exempt-Sold": "Inactive",
    "Exempt-Subsidized": "Inactive",
    "Property Lien": "Inactive",
    # In Review
    "In Review": "In Review",
    "Additional Info Required": "In Review",
    "Revisions Required": "In Review",
    "Preliminary Revisions Required": "In Review",
    "Received": "In Review",
    "Fees Invoiced": "In Review",
    "Accepted - Fees Invoiced": "In Review",
    "Reinspection Fees Invoiced": "In Review",
    "Plans Approved": "In Review",
    "Pending": "In Review",
    "Pending Planning Application": "In Review",
    "Under Preliminary Review": "In Review",
    "Stop Work Order": "In Review",
    "Refund Requested": "In Review",
    "Inspection Required": "In Review",
}


def _raw_status(d: dict) -> Optional[str]:
    raw = d.get("status")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    sd = d.get("search_data")
    if isinstance(sd, dict):
        sd_status = sd.get("Status")
        if isinstance(sd_status, str) and sd_status.strip():
            return sd_status.strip()
    return None


def _base_status(d: dict) -> Optional[str]:
    raw = _raw_status(d)
    if raw is None:
        return None
    mapped = _STATUS_MAP.get(raw)
    if mapped is not None:
        return mapped
    # Case / dash-insensitive fallback.
    norm = _normalize_status_key(raw).lower()
    for k, v in _STATUS_MAP.items():
        if _normalize_status_key(k).lower() == norm:
            return v
    # Closed-* without an explicit map: treat withdrawn/denied/void/
    # no-activity/exempt as Inactive; other Closed as Final.
    if norm.startswith("closed"):
        if any(
            tok in norm
            for tok in (
                "withdrawn",
                "denied",
                "void",
                "no activity",
                "exempt",
            )
        ):
            return "Inactive"
        return "Final"
    if norm.startswith("exempt"):
        return "Inactive"
    return None


def _has_issuance(d: dict) -> bool:
    return _permit_date_from_data(d) is not pd.NaT


def _has_final_evidence(d: dict) -> bool:
    return _final_task_date(d) is not pd.NaT


def _status_original_hint(status_original) -> Optional[str]:
    if status_original is None or (
        isinstance(status_original, float) and math.isnan(status_original)
    ):
        return None
    so = _normalize_status_key(str(status_original)).lower()
    if not so:
        return None
    # Reuse the DATA.status map via title-case-ish keys when possible.
    for k, v in _STATUS_MAP.items():
        if _normalize_status_key(k).lower() == so:
            return v
    if so.startswith("closed"):
        if any(
            tok in so
            for tok in (
                "withdrawn",
                "denied",
                "void",
                "no activity",
                "exempt",
            )
        ):
            return "Inactive"
        return "Final"
    if so.startswith("exempt"):
        return "Inactive"
    if so in {"issued", "permit issued", "active", "renewed"}:
        return "Active"
    if any(tok in so for tok in ("expired", "void", "withdrawn", "denied")):
        return "Inactive"
    return "In Review"


def _expected_status(d: dict, status_original=None) -> Optional[str]:
    """Map DATA.status, then upgrade / infer from workflow evidence.

    Inactive terminal labels are sticky. Final Inspection Complete /
    Closed - Complete → Final. Issued / Active / Renewed → Active unless
    a dated Final Inspection Complete or Passed final inspection exists
    (portal CaseStatus lag), in which case → Final. In Review upgrades
    to Final / Active from workflow. Blank TMP shells → In Review.
    """
    mapped = _base_status(d)
    raw = _raw_status(d) or ""
    raw_norm = _normalize_status_key(raw)

    if raw_norm in _INACTIVE or mapped == "Inactive":
        return "Inactive"

    if mapped == "Final" or raw_norm in _FINAL_STATUSES:
        return "Final"

    if mapped == "Active" or raw_norm in _ACTIVE_STATUSES:
        if _has_final_evidence(d):
            return "Final"
        return "Active"

    # In Review / unmapped: upgrade from workflow, else STATUS_ORIGINAL.
    if mapped == "In Review" or mapped is None:
        if _has_final_evidence(d):
            return "Final"
        if _has_issuance(d):
            return "Active"
        hint = _status_original_hint(status_original)
        if hint in {"Final", "Active", "Inactive"}:
            return hint
        if mapped == "In Review":
            return "In Review"

    if mapped is not None:
        return mapped

    if (
        _safe_to_datetime(d.get("date")) is not pd.NaT
        or _has_dated_events(d)
        or _has_final_evidence(d)
        or (
            isinstance(d.get("search_data"), dict)
            and _safe_to_datetime(d["search_data"].get("Date")) is not pd.NaT
        )
    ):
        if _has_final_evidence(d):
            return "Final"
        if _has_issuance(d):
            return "Active"
        hint = _status_original_hint(status_original)
        if hint is not None:
            return hint
        return "In Review"

    return None


# ── Per-record repair logic ─────────────────────────────────────────────────

def _repair_record(row, d: dict, repairs: dict):
    current_status = row["STATUS_NORMALIZED"]
    status_original = (
        row["STATUS_ORIGINAL"] if "STATUS_ORIGINAL" in row.index else None
    )
    expected = _expected_status(d, status_original=status_original)

    # -- STATUS_NORMALIZED --
    if expected is not None:
        if pd.isna(current_status):
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"
        elif current_status != expected:
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FIXED"

    effective_status = repairs.get("STATUS_NORMALIZED", current_status)

    # -- FILE_DATE --
    file_date = _file_date_from_data(d)
    if file_date is not pd.NaT:
        if pd.isna(row["FILE_DATE"]):
            repairs["FILE_DATE"] = file_date
            repairs["FILE_DATE_FLAG"] = "FILLED"
        elif not _dates_equal(row["FILE_DATE"], file_date):
            # Prefer the top-level Accela opened date when it disagrees
            # with a later Application Intake stamp that pulled FILE_DATE
            # forward; use the earliest candidate (canonical extractor).
            repairs["FILE_DATE"] = file_date
            repairs["FILE_DATE_FLAG"] = "FIXED"

    # -- PERMIT_DATE --
    issued = _permit_date_from_data(d)
    current_permit = row["PERMIT_DATE"]
    if not pd.isna(current_permit):
        if issued is not pd.NaT and not _dates_equal(current_permit, issued):
            repairs["PERMIT_DATE"] = issued
            repairs["PERMIT_DATE_FLAG"] = "FIXED"
        elif effective_status == "In Review" and not _has_issuance(d):
            repairs["PERMIT_DATE"] = pd.NaT
            repairs["PERMIT_DATE_FLAG"] = "FIXED"
    elif effective_status in ("Active", "Final") and issued is not pd.NaT:
        repairs["PERMIT_DATE"] = issued
        repairs["PERMIT_DATE_FLAG"] = "FILLED"

    # -- FINAL_DATE --
    current_final = row["FINAL_DATE"]
    if effective_status == "Final":
        final_date = _final_date_from_data(d)
        if final_date is not pd.NaT:
            if pd.isna(current_final):
                repairs["FINAL_DATE"] = final_date
                repairs["FINAL_DATE_FLAG"] = "FILLED"
            elif not _dates_equal(current_final, final_date):
                repairs["FINAL_DATE"] = final_date
                repairs["FINAL_DATE_FLAG"] = "FIXED"
    elif not pd.isna(current_final):
        repairs["FINAL_DATE"] = pd.NaT
        repairs["FINAL_DATE_FLAG"] = "FIXED"


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Pittsburg permit records using information from the raw DATA JSON.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Pittsburg".  Must contain
        columns STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, FINAL_DATE,
        STATUS_ORIGINAL, and DATA.

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
        (df["JURISDICTION"] == "Pittsburg") & (df["STATE"] == "CA")
    ].copy()

    print(f"Pittsburg records: {len(city):,}\n")

    repaired = data_repair(city)

    if AGENT_DATA_PATH:
        out_dir = Path(AGENT_DATA_PATH) / "repaired"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "permits_ca_pittsburg_repaired.parquet"
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
                "before": city.loc[mask, "STATUS_NORMALIZED"].fillna("nan").astype(str),
                "after": repaired.loc[mask, "STATUS_NORMALIZED"].fillna("nan").astype(str),
                "original": city.loc[mask, "STATUS_ORIGINAL"].fillna("nan").astype(str),
            })
            .value_counts()
            .reset_index(name="n")
        )
        for _, trow in transitions.iterrows():
            print(
                f"  {trow['before']:15s} → {trow['after']:15s} "
                f"(STATUS_ORIGINAL={trow['original']}): {trow['n']:>4,}"
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

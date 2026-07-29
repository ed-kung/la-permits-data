"""Data repair for Menlo Park (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Menlo Park DATA is an Accela Citizen Access scrape. All sample rows share
the same top-level keys (``address``, ``date``, ``status``, ``tasks``,
``search_data``, ``inspections``, …). Content variants (INFERRED_SCHEMA):

  - portal_issued_finaled:   dated Issued* + final-date evidence
  - portal_issued:           Issued present, no final date
  - portal_final_only:       Final date present, no Issued
  - portal_application_only: Application / top-level date only
  - portal_empty_tasks:      tasks present but undated (TBD / empty)
  - missing

Canonical mappings:
  - DATA.status / search_data.Status (+ workflow upgrades from dated
    Issued* / Finaled)                                      → STATUS_NORMALIZED
  - Earliest of DATA.date / search_data.Date / Submittal
    Accepted / Submitted / Fees Confirmed first-touch marks → FILE_DATE
  - Earliest Ready to Issue (any task) Issued* Completed on → PERMIT_DATE
  - Earliest Construction Phase Finaled (fallback: Close out
    Complete/Closed, final-titled inspection Pass*, Convert
    to Building Permit Complete)                            → FINAL_DATE

Known issues repaired:
  - STATUS_NORMALIZED derived from lagged STATUS_ORIGINAL while
    DATA.status already advanced (Issued/Finaled/Void/Expired).
  - Approved (plans approved, not issued) previously Active
    → FIXED to In Review (unless a dated Issued event exists).
  - Missing STATUS_NORMALIZED for Pending Fee Payment / Issuance
    Preparation / No Violations/Damage / Expired (pending-
    expiration) → FILLED.
  - Red Tag previously Final → FIXED to Active (open enforcement).
  - FILE_DATE lagging original Submittal Accepted / Submitted after
    Accela re-open bumped DATA.date → FIXED to earliest.
  - PERMIT_DATE often set to Issuance Preparation / Payment Received
    / Incomplete rather than Issued Completed on → FIXED.
  - Spurious PERMIT_DATE on In Review / Inactive shells without
    Issued evidence → cleared.
  - FINAL_DATE entirely missing; fill from Finaled / Close out /
    final inspection / Convert Complete when available.

Not repairable / left as-is:
  - Most older Finaled / Issued shells have empty or TBD-only task
    histories → PERMIT_DATE / FINAL_DATE stay missing.
  - Converted Building Pre-Application rows map to Final; FINAL_DATE
    filled from Convert Complete when dated, else stays missing.
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

# Accela HTML: Completed on <span>…</span> … as <span>…</span>
_COMPLETED_AS_RE = re.compile(
    r"Completed on\s*<span[^>]*>([^<]*)</span>"
    r".*?as\s*<span[^>]*>([^<]*)</span>",
    re.I | re.S,
)

_ISSUE_MARKS = {"Issued", "Issued Revision", "Issued Deferred"}
_FINAL_MARKS = {"Finaled"}
_CLOSE_MARKS = {"Complete", "Closed", "Finaled"}
_FILE_MARKS = {
    "Submittal Accepted",
    "Submitted",
    "Fees Confirmed- Send Email",
    "Cleared for Review",
    "Assigned to Tech",
    "Payment Received",
}
_FILE_TASKS = {
    "Application Intake",
    "Submittal",
    "Assignment",
}

_FINAL_INSP_TITLE = re.compile(r"\bfinal\b", re.I)
_FINAL_INSP_STATUS = {
    "pass",
    "pass-final",
    "approved",
    "passed",
    "finaled",
    "complete",
    "completed",
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
        return json.loads(data)
    return data


def _safe_to_datetime(val):
    """Parse a date value, returning pd.NaT on failure / TBD / bad year."""
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return pd.NaT
    if isinstance(val, dict):
        return pd.NaT
    if isinstance(val, str):
        s = val.strip().rstrip(",")
        if not s or s.upper() in {"TBD", "NULL", "NONE", "N/A", "NA"}:
            return pd.NaT
        val = s
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
    """Return (marked_as, event_date) for Menlo Park Accela events.

    Prefer structured ``as`` / ``Completed on`` keys; fall back to HTML
    ``Completed on … as …`` spans.
    """
    if not isinstance(event, dict):
        return None, pd.NaT

    mark = _event_field(event, "as", "Marked as", "status", "Status")
    on = _safe_to_datetime(
        _event_field(event, "Completed on", "on", "Completed On")
    )

    html = event.get("html") or ""
    if isinstance(html, str) and html:
        m = _COMPLETED_AS_RE.search(html)
        if m:
            if not (isinstance(mark, str) and mark.strip()):
                mark = m.group(2)
            html_on = _safe_to_datetime(m.group(1))
            if on is pd.NaT and html_on is not pd.NaT:
                on = html_on

    if isinstance(mark, str):
        mark = mark.strip()
    else:
        mark = None
    return mark, on


def _all_mark_dates(tasks: list, statuses) -> list:
    if isinstance(statuses, str):
        statuses = {statuses}
    statuses_l = {s.lower() for s in statuses}
    dates = []
    for t in _iter_tasks(tasks):
        for e in t.get("events") or []:
            mark, on = _event_mark_and_date(e)
            if not mark or mark.lower() not in statuses_l:
                continue
            if on is not pd.NaT:
                dates.append(on)
    return dates


def _first_mark_date(tasks: list, statuses):
    dates = _all_mark_dates(tasks, statuses)
    return min(dates) if dates else pd.NaT


def _event_dates(tasks: list, task_names, statuses):
    if isinstance(task_names, str):
        task_names = {task_names}
    if isinstance(statuses, str):
        statuses = {statuses}
    names_l = {n.lower() for n in task_names}
    statuses_l = {s.lower() for s in statuses}
    dates = []
    for t in _iter_tasks(tasks):
        tname = t.get("name") or ""
        if not isinstance(tname, str) or tname.lower() not in names_l:
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


# ── Schema classification ───────────────────────────────────────────────────

def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"

    tasks = data_dict.get("tasks") or []
    has_tasks = isinstance(tasks, list) and len(tasks) > 0
    issued = _permit_date_from_data(data_dict) is not pd.NaT
    finaled = _final_date_from_data(data_dict) is not pd.NaT

    if issued and finaled:
        return "portal_issued_finaled"
    if issued and not finaled:
        return "portal_issued"
    if finaled and not issued:
        return "portal_final_only"
    if _has_dated_events(data_dict) or _safe_to_datetime(data_dict.get("date")) is not pd.NaT:
        return "portal_application_only"
    if has_tasks:
        return "portal_empty_tasks"
    return "portal_empty_tasks"


# ── Status mapping ──────────────────────────────────────────────────────────

_STATUS_MAP = {
    # Final
    "Finaled": "Final",
    "Closed": "Final",
    "Complete": "Final",
    "Converted": "Final",
    # Active
    "Issued": "Active",
    "Issued Revision": "Active",
    "Inspection": "Active",
    "Red Tag": "Active",
    # Inactive
    "Expired": "Inactive",
    "Expired Permit": "Inactive",
    "Void": "Inactive",
    "Withdrawn": "Inactive",
    "Canceled": "Inactive",
    "Cancelled": "Inactive",
    "No Violations/Damage": "Inactive",
    # In Review (plans approved / fee / quote stages — not yet issued)
    "Approved": "In Review",
    "Applied": "In Review",
    "In Review": "In Review",
    "Received": "In Review",
    "Pending Resubmittal": "In Review",
    "Pending Fee Payment": "In Review",
    "Pending Payment": "In Review",
    "Action Required": "In Review",
    "Quote": "In Review",
    "Ready to Issue": "In Review",
    "Ready": "In Review",
    "Issuance Preparation": "In Review",
    "Pending Expiration": "In Review",
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
    for k, v in _STATUS_MAP.items():
        if k.lower() == raw.lower():
            return v
    return None


def _has_issuance(d: dict) -> bool:
    return _permit_date_from_data(d) is not pd.NaT


def _has_final_evidence(d: dict) -> bool:
    """True when a dated Finaled workflow mark exists."""
    return _first_mark_date(d.get("tasks") or [], _FINAL_MARKS) is not pd.NaT


def _expected_status(d: dict) -> Optional[str]:
    """Map DATA.status, then upgrade from workflow evidence.

    Inactive terminal labels are sticky. DATA.status Finaled / Closed /
    Converted maps to Final. A dated Issued* promotes In Review → Active.
    A dated Finaled promotes In Review → Final (status lag). Finaled alone
    does **not** promote Issued → Final when the portal status is still
    Issued.
    """
    mapped = _base_status(d)
    raw = _raw_status(d) or ""

    if mapped == "Inactive":
        return "Inactive"

    if mapped == "Final":
        return "Final"

    if mapped == "Active":
        return "Active"

    # Status lag: review-stage labels still showing while Finaled / Issued
    # already fired in the task history.
    if mapped == "In Review" and _has_final_evidence(d):
        return "Final"

    if mapped == "In Review" and _has_issuance(d):
        return "Active"

    if mapped is not None:
        return mapped

    if _safe_to_datetime(d.get("date")) is not pd.NaT or _has_dated_events(d):
        if _has_final_evidence(d):
            return "Final"
        if _has_issuance(d):
            return "Active"
        return "In Review"

    return None


# ── Date extractors ──────────────────────────────────────────────────────────

def _file_date_from_data(d: dict):
    """Earliest application / opened date from Accela fields.

    Prefer the minimum of ``DATA.date``, ``search_data.Date``, and the
    earliest Application Intake / Submittal first-touch marks. Accela
    sometimes bumps the top-level date on re-open while the original
    submittal remains in the task history.
    """
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

    tasks = d.get("tasks") or []
    app = _first_event_date(tasks, _FILE_TASKS, _FILE_MARKS)
    if app is not pd.NaT:
        candidates.append(app)

    return min(candidates) if candidates else pd.NaT


def _permit_date_from_data(d: dict):
    """Earliest Issued* Completed-on date across all workflow tasks."""
    return _first_mark_date(d.get("tasks") or [], _ISSUE_MARKS)


def _final_insp_status_date(d: dict):
    """Earliest Status Date on a final-titled inspection that passed."""
    dates = []
    for insp in d.get("inspections") or []:
        if not isinstance(insp, dict):
            continue
        title = insp.get("Title") or ""
        if not isinstance(title, str) or not _FINAL_INSP_TITLE.search(title):
            continue
        status = insp.get("Status") or ""
        if not isinstance(status, str) or status.strip().lower() not in _FINAL_INSP_STATUS:
            continue
        dt = _safe_to_datetime(insp.get("Status Date"))
        if dt is not pd.NaT:
            dates.append(dt)
    return min(dates) if dates else pd.NaT


def _final_date_from_data(d: dict):
    """Final / completion date for Menlo Park Accela records.

    Prefer any task ``Finaled`` mark (typically Construction Phase), then
    Close out Complete/Closed/Finaled, then a final-titled inspection
    Status Date, then Convert to Building Permit Complete (pre-apps).
    """
    tasks = d.get("tasks") or []

    finaled = _first_mark_date(tasks, _FINAL_MARKS)
    if finaled is not pd.NaT:
        return finaled

    closed = _first_event_date(
        tasks, {"Close out", "Close Out", "Closeout"}, _CLOSE_MARKS
    )
    if closed is not pd.NaT:
        return closed

    insp = _final_insp_status_date(d)
    if insp is not pd.NaT:
        return insp

    convert = _first_event_date(
        tasks, {"Convert to Building Permit"}, {"Complete"}
    )
    if convert is not pd.NaT:
        return convert

    return pd.NaT


# ── Per-record repair logic ─────────────────────────────────────────────────

def _repair_record(row, d: dict, repairs: dict):
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

    # -- FILE_DATE --
    file_date = _file_date_from_data(d)
    if file_date is not pd.NaT:
        if pd.isna(row["FILE_DATE"]):
            repairs["FILE_DATE"] = file_date
            repairs["FILE_DATE_FLAG"] = "FILLED"
        elif not _dates_equal(row["FILE_DATE"], file_date):
            # Only pull FILE_DATE earlier (Accela re-open bump); do not
            # overwrite with a later candidate.
            current_file = _safe_to_datetime(row["FILE_DATE"])
            if current_file is pd.NaT or file_date.normalize() < current_file.normalize():
                repairs["FILE_DATE"] = file_date
                repairs["FILE_DATE_FLAG"] = "FIXED"

    # -- PERMIT_DATE --
    issued = _permit_date_from_data(d)
    current_permit = row["PERMIT_DATE"]
    if not pd.isna(current_permit):
        if issued is not pd.NaT and not _dates_equal(current_permit, issued):
            repairs["PERMIT_DATE"] = issued
            repairs["PERMIT_DATE_FLAG"] = "FIXED"
        elif issued is pd.NaT and effective_status in ("In Review", "Inactive"):
            # Spurious permit stamp from Issuance Preparation / Approval.
            repairs["PERMIT_DATE"] = pd.NaT
            repairs["PERMIT_DATE_FLAG"] = "FIXED"
    elif effective_status in ("Active", "Final") and issued is not pd.NaT:
        repairs["PERMIT_DATE"] = issued
        repairs["PERMIT_DATE_FLAG"] = "FILLED"
    elif effective_status == "Inactive" and issued is not pd.NaT:
        # Expired after issuance — still record the issue date.
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
    Menlo Park permit records using information from the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Menlo Park".  Must contain
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
    city = df[(df["JURISDICTION"] == "Menlo Park") & (df["STATE"] == "CA")].copy()

    print(f"Menlo Park records: {len(city):,}\n")

    repaired = data_repair(city)

    if AGENT_DATA_PATH:
        out_dir = Path(AGENT_DATA_PATH) / "repaired"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "permits_ca_menlo_park_repaired.parquet"
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

    print("\nSTATUS transitions (where flagged):")
    flagged = repaired[repaired["STATUS_NORMALIZED_FLAG"].notna()].copy()
    if len(flagged):
        flagged["before"] = city.loc[flagged.index, "STATUS_NORMALIZED"]
        print(
            flagged.groupby(
                [
                    flagged["before"].fillna("(null)"),
                    "STATUS_NORMALIZED",
                    "STATUS_NORMALIZED_FLAG",
                ]
            )
            .size()
            .rename("n")
            .reset_index()
            .to_string(index=False)
        )

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

    print("\nChronology checks (after repair):")
    f = pd.to_datetime(repaired["FILE_DATE"], errors="coerce")
    p = pd.to_datetime(repaired["PERMIT_DATE"], errors="coerce")
    fin = pd.to_datetime(repaired["FINAL_DATE"], errors="coerce")
    inv_fp = f.notna() & p.notna() & (p.dt.normalize() < f.dt.normalize())
    inv_pf = p.notna() & fin.notna() & (fin.dt.normalize() < p.dt.normalize())
    print(f"  PERMIT < FILE: {inv_fp.sum()}")
    print(f"  FINAL < PERMIT: {inv_pf.sum()}")

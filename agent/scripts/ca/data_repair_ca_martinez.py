"""Data repair for Martinez (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Martinez DATA is an Accela Citizen Access scrape (same family as Eastvale /
Lincoln). Most sample rows share core top-level keys (``address``,
``date``, ``status``, ``tasks``, ``inspections``, ``search_data``, …);
a minority of shells are ``search_data``-only. Content variants
(INFERRED_SCHEMA):

  - portal_issued_finaled:   Permit Issuance Permit Issued + final date
  - portal_issued:           Issued present, no final-completion date
  - portal_final_insp_only:  Final evidence present, no Issued
  - portal_application_only: Application Submittal / top-level date only
  - portal_empty_tasks:      tasks present but undated (TBD / empty)
  - search_data_only:        status-blank shells with only search_data
  - missing

Canonical mappings:
  - DATA.status / search_data.Status (+ workflow inference for blank /
    Reactivated / In Review lags)                        → STATUS_NORMALIZED
  - Earliest of DATA.date / search_data.Date / Application
    Submittal Submitted*                                 → FILE_DATE
  - Earliest Permit Issuance Marked as Permit Issued     → PERMIT_DATE
  - Earliest Inspection Marked as Final Approved
    (fallback: Final Permit Status Pmt Complete & Apprvd;
    then Approved / Passed final inspection Status Date) → FINAL_DATE

Known issues repaired:
  - Blank DATA.status / STATUS_ORIGINAL (421 rows) inferred from
    workflow / inspections → FILLED (Final / Active / Inactive /
    In Review).
  - ``Fee Estimate`` mapped Inactive → FIXED to In Review.
  - ``Reactivated`` In Review shell with dated Final Approved →
    FIXED to Final.
  - Finaled shells missing FINAL_DATE while Approved final inspection
    or Pmt Complete & Apprvd exists → FILLED.
  - Spurious FINAL_DATE on non-Final rows → cleared.

Not repairable / left as-is:
  - FILE_DATE already matches DATA.date / search_data.Date for every
    sample row.
  - PERMIT_DATE already matches Permit Issued whenever that event
    exists; Active coverage is complete. Many legacy Final / blank-
    status finals lack a dated Permit Issuance event → PERMIT_DATE
    stays missing.
  - One Finaled row (Denied-only final inspection, no completion mark)
    cannot get FINAL_DATE.
  - Issued Active shells are not promoted to Final even if a final
    inspection exists (portal CaseStatus lag); none observed in sample.
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
    "Void",
    "Withdrawn",
    "Canceled",
    "Cancelled",
    "CANCELLED",
    "Revoked",
}

_FINAL_STATUSES = {
    "Finaled",
    "Finalled",
    "Complete",
    "CLOSED",
    "Closed",
    "Closed - Complete",
}

_ACTIVE_STATUSES = {
    "Issued",
    "Permit Issued",
}

_ISSUE_MARKS = {"Permit Issued", "Issued"}
_FINAL_INSP_MARKS = {"Final Approved"}
_FINAL_STATUS_MARKS = {
    "Pmt Complete & Apprvd",
    "Pmt Complete & Approved",
}
_FILE_MARK_PREFIXES = (
    "submitted",
    "accepted",
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
        # Accela sometimes HTML-escapes ampersands in Marked as.
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


def _application_submittal_dates(tasks: list) -> list:
    dates = []
    for t in _iter_tasks(tasks):
        if t.get("name") != "Application Submittal":
            continue
        for e in t.get("events") or []:
            mark, on = _event_mark_and_date(e)
            if on is pd.NaT or not mark:
                continue
            ml = mark.lower()
            if any(ml.startswith(p) for p in _FILE_MARK_PREFIXES):
                dates.append(on)
    return dates


def _approved_final_inspection_dates(d: dict) -> list:
    """Dates from inspections[] with Approved/Passed/Final Approved and
    a final-titled inspection (or Status == Final Approved)."""
    dates = []
    for insp in d.get("inspections") or []:
        if not isinstance(insp, dict):
            continue
        title = str(insp.get("Title") or "").lower()
        status = str(insp.get("Status") or "").strip()
        status_l = status.lower()
        is_final_status = status_l in {"approved", "passed", "final approved"}
        if not is_final_status:
            continue
        if "final" not in title and status_l != "final approved":
            continue
        dt = _safe_to_datetime(insp.get("Status Date"))
        if dt is not pd.NaT:
            dates.append(dt)
    return dates


def _has_expired_mark(d: dict) -> bool:
    for t in _iter_tasks(d.get("tasks") or []):
        for e in t.get("events") or []:
            mark, on = _event_mark_and_date(e)
            if on is pd.NaT or not mark:
                continue
            if mark in {"Expired", "Permit Expired"}:
                return True
    return False


# ── Date extractors ──────────────────────────────────────────────────────────

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

    candidates.extend(_application_submittal_dates(d.get("tasks") or []))
    return min(candidates) if candidates else pd.NaT


def _permit_date_from_data(d: dict):
    """Earliest Permit Issuance Permit Issued / Issued date."""
    return _first_event_date(d.get("tasks") or [], {"Permit Issuance"}, _ISSUE_MARKS)


def _final_date_from_data(d: dict):
    """Prefer Inspection Final Approved, then completion marks, then
    Approved final inspection Status Date."""
    tasks = d.get("tasks") or []

    final = _first_event_date(tasks, {"Inspection"}, _FINAL_INSP_MARKS)
    if final is not pd.NaT:
        return final

    final = _first_event_date(tasks, {"Inspections"}, {"Inspections Complete"})
    if final is not pd.NaT:
        return final

    final = _first_event_date(tasks, {"Final Permit Status"}, _FINAL_STATUS_MARKS)
    if final is not pd.NaT:
        return final

    # Variant completion marks (HTML entities / wording differences).
    completion = []
    for t in _iter_tasks(tasks):
        if t.get("name") != "Final Permit Status":
            continue
        for e in t.get("events") or []:
            mark, on = _event_mark_and_date(e)
            if on is pd.NaT or not mark:
                continue
            ml = mark.lower()
            if "complete" in ml and ("apprvd" in ml or "approved" in ml):
                completion.append(on)
    if completion:
        return min(completion)

    passed = _approved_final_inspection_dates(d)
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
    "Closed - Complete": "Final",
    "Finaled": "Final",
    "Finalled": "Final",
    "Complete": "Final",
    "CLOSED": "Final",
    "Closed": "Final",
    # Active
    "Issued": "Active",
    "Permit Issued": "Active",
    # Inactive
    "Expired": "Inactive",
    "Void": "Inactive",
    "Withdrawn": "Inactive",
    "Canceled": "Inactive",
    "Cancelled": "Inactive",
    "CANCELLED": "Inactive",
    "Revoked": "Inactive",
    # In Review
    "Plan Review": "In Review",
    "Ready to Issue": "In Review",
    "Submitted": "In Review",
    "Fee Estimate": "In Review",
    "Pending": "In Review",
    "In Review": "In Review",
    "Reactivated": "In Review",  # may upgrade via workflow
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
    if raw.lower().startswith("closed"):
        return "Final"
    return None


def _has_issuance(d: dict) -> bool:
    return _permit_date_from_data(d) is not pd.NaT


def _has_final_evidence(d: dict) -> bool:
    return _final_date_from_data(d) is not pd.NaT


def _expected_status(d: dict) -> Optional[str]:
    """Map DATA.status, then upgrade / infer from workflow evidence.

    Inactive terminal labels are sticky. Finaled maps to Final. Issued
    maps to Active and is not promoted to Final from inspections alone.
    Blank / Reactivated / other In Review labels upgrade to Final when
    a dated completion exists, else Active when Permit Issued exists.
    """
    mapped = _base_status(d)
    raw = _raw_status(d) or ""

    if raw in _INACTIVE or mapped == "Inactive":
        return "Inactive"

    if mapped == "Final" or raw in _FINAL_STATUSES:
        return "Final"

    if mapped == "Active" or raw in _ACTIVE_STATUSES:
        return "Active"

    # In Review (including Reactivated) / unmapped: upgrade from workflow.
    if mapped == "In Review" or mapped is None:
        if _has_final_evidence(d):
            return "Final"
        if _has_expired_mark(d) and mapped is None:
            return "Inactive"
        if _has_issuance(d):
            return "Active"
        if mapped == "In Review":
            return "In Review"

    if mapped is not None:
        return mapped

    # Blank portal status with a filed Accela / search shell.
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
        if _has_expired_mark(d):
            return "Inactive"
        if _has_issuance(d):
            return "Active"
        return "In Review"

    return None


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
    Martinez permit records using information from the raw DATA JSON.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Martinez".  Must contain
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
    city = df[(df["JURISDICTION"] == "Martinez") & (df["STATE"] == "CA")].copy()

    print(f"Martinez records: {len(city):,}\n")

    repaired = data_repair(city)

    if AGENT_DATA_PATH:
        out_dir = Path(AGENT_DATA_PATH) / "repaired"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "permits_ca_martinez_repaired.parquet"
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
                ["STATUS_NORMALIZED_FLAG", "before", "STATUS_NORMALIZED"],
                dropna=False,
            )
            .size()
            .to_string()
        )

    print("\nDate coverage by status (after):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        print(
            f"  {status:10s} n={len(sub):4d}  "
            f"FILE={sub['FILE_DATE'].notna().sum():4d}  "
            f"PERMIT={sub['PERMIT_DATE'].notna().sum():4d}  "
            f"FINAL={sub['FINAL_DATE'].notna().sum():4d}"
        )

    # Chronology checks
    both = repaired[
        repaired["PERMIT_DATE"].notna() & repaired["FILE_DATE"].notna()
    ].copy()
    if len(both):
        n_bad = (
            pd.to_datetime(both["PERMIT_DATE"]).dt.normalize()
            < pd.to_datetime(both["FILE_DATE"]).dt.normalize()
        ).sum()
        print(f"\nPERMIT_DATE < FILE_DATE: {n_bad}")

    both_f = repaired[
        repaired["FINAL_DATE"].notna() & repaired["PERMIT_DATE"].notna()
    ].copy()
    if len(both_f):
        n_bad = (
            pd.to_datetime(both_f["FINAL_DATE"]).dt.normalize()
            < pd.to_datetime(both_f["PERMIT_DATE"]).dt.normalize()
        ).sum()
        print(f"FINAL_DATE < PERMIT_DATE: {n_bad}")

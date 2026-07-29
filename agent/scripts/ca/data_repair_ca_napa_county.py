"""Data repair for Napa County (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Napa County DATA is an Accela Citizen Access scrape. Nearly all sample
rows share the full key set (``address``, ``date``, ``status``,
``tasks``, ``inspections``, ``search_data``, …); one sparse row omits
optional blocks. Content variants (INFERRED_SCHEMA):

  - accela_full_issued_finaled:  Issuance/Issued + final mark / insp
  - accela_full_issued:          issuance present, no final date source
  - accela_full_finaled_only:    final date source, no issuance
  - accela_full_other_events:    other dated workflow events only
  - accela_full_empty_tasks:     tasks present but undated / empty
  - accela_partial_*:            same tags on the sparse key set

Canonical mappings:
  - DATA.status / search_data.Status
    (+ Issuance Issued/Re-Issued upgrade)               → STATUS_NORMALIZED
  - DATA.date / search_data['File Date']                → FILE_DATE
  - Issuance Issued|Re-Issued
    (fallback: Issued task Approved*)                   → PERMIT_DATE
  - Time Tracking Permit Final
    (fallback: Closure CLOSED; approved Final*
    inspection Status Date)                             → FINAL_DATE

Known issues repaired:
  - Review to Applicant / Pending Documents left null
    → FILLED In Review.
  - Issuance Extended / Revision Process (with Issued events)
    left In Review → FIXED to Active.
  - Approved (plans / history shells, no issuance) left Active
    → FIXED to In Review.
  - Finaled / Expired shells with Issued-task Approved* but no
    Issuance block → PERMIT_DATE FILLED.
  - All FINAL_DATE missing upstream; Final rows filled from Time
    Tracking / Closure / approved Final* inspections (inspection
    finals earlier than issuance/file date are ignored).

Not repairable / left as-is:
  - FILE_DATE already matches DATA.date for every sample row.
  - Issued / Finaled shells with empty Issuance and Issued tasks
    (esp. recent OTC replacements and older conversions) → PERMIT_DATE
    stays missing.
  - ~21 Finaled shells with no Permit Final / Closure / post-issuance
    approved Final* inspection → FINAL_DATE stays missing.
  - Code-enforcement ``Issued`` marks (Active / Passed) are not
    treated as building-permit issuance.
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

# Accela HTML sometimes includes inline styles on the <span> tags.
_MARKED_RE = re.compile(
    r"Marked as\s*<span[^>]*>([^<]*)</span>\s*on\s*<span[^>]*>([^<]*)</span>",
    re.I,
)

_ISSUE_MARKS = {"Issued", "Re-Issued"}
# Older Accela workflow used an "Issued" task with Approved* marks.
# Exclude Active/Passed — those appear on code-enforcement shells.
_ISSUED_TASK_MARKS = {
    "Approved",
    "Approved - Final Required",
    "Approved - No Final Required",
    "Approved-Billable",
    "Approved-Non Billable",
    "Issued",
}
_FINAL_TT_MARKS = {"Permit Final"}
_CLOSURE_MARKS = {"CLOSED", "Closed"}

_FINAL_INSP_PREF = re.compile(
    r"(permit\s*final|final\s*building|final\s*occupancy|"
    r"a7[–\-]?final\s*building)",
    re.I,
)
_ANY_FINAL_INSP = re.compile(r"\bfinal\b", re.I)
_PASS_INSP = {"approved", "passed", "pass", "complete", "completed"}


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

    Prefer the Accela ``on`` key (not ``Due on``) and fall back to HTML
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
        mark = mark.strip()
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


def _latest_event_date(tasks: list, task_names, statuses):
    dates = _event_dates(tasks, task_names, statuses)
    return max(dates) if dates else pd.NaT


def _has_dated_events(d: dict) -> bool:
    for t in _iter_tasks(d.get("tasks") or []):
        for e in t.get("events") or []:
            _, on = _event_mark_and_date(e)
            if on is not pd.NaT:
                return True
    return False


# ── Schema classification ───────────────────────────────────────────────────

def _key_set_tag(data_dict: dict) -> str:
    keys = set(data_dict.keys())
    if "inspections" in keys and "contacts" in keys:
        return "accela_full"
    return "accela_partial"


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"

    base = _key_set_tag(data_dict)
    issued = _permit_date_from_data(data_dict) is not pd.NaT
    finaled = _final_date_from_data(data_dict) is not pd.NaT

    if issued and finaled:
        return f"{base}_issued_finaled"
    if issued:
        return f"{base}_issued"
    if finaled:
        return f"{base}_finaled_only"
    if _has_dated_events(data_dict) or _safe_to_datetime(data_dict.get("date")) is not pd.NaT:
        return f"{base}_other_events"
    return f"{base}_empty_tasks"


# ── Status mapping ──────────────────────────────────────────────────────────

_STATUS_MAP = {
    # Final
    "Finaled": "Final",
    # Active
    "Issued": "Active",
    "Re-Issued": "Active",
    "Renewed": "Active",
    "Issuance Extended": "Active",
    # Inactive
    "Expired Permit": "Inactive",
    "Closed Application": "Inactive",
    "Expired Application": "Inactive",
    "Denied Application": "Inactive",
    "Void": "Inactive",
    "Denied": "Inactive",
    "Expired": "Inactive",
    # In Review (incl. plans-approved / fee / revision stages)
    "Accepted": "In Review",
    "Review Process": "In Review",
    "Review to Applicant": "In Review",
    "Incomplete": "In Review",
    "Ready to Issue": "In Review",
    "Received": "In Review",
    "Pending": "In Review",
    "Pending Documents": "In Review",
    "Pending Payment": "In Review",
    "Revision Process": "In Review",
    "Submitted": "In Review",
    "Appointment Made": "In Review",
    "Plan Check": "In Review",
    "Resolved": "In Review",
    "PC Approved": "In Review",
    "Approved": "In Review",
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


def _has_building_issuance(d: dict) -> bool:
    """True when Issuance Issued/Re-Issued or Issued-task Approved* exists."""
    return _permit_date_from_data(d) is not pd.NaT


def _expected_status(d: dict) -> Optional[str]:
    """Map DATA.status, then upgrade In Review → Active on issuance evidence.

    Inactive terminal labels are sticky. Finaled maps to Final. Issued /
    Re-Issued / Renewed / Issuance Extended map to Active. A dated
    Issuance Issued|Re-Issued (or Issued-task Approved*) promotes
    Revision Process and similar In Review labels to Active. Final
    inspection evidence alone does **not** promote Issued → Final when
    DATA.status is still Issued.
    """
    mapped = _base_status(d)
    raw = _raw_status(d) or ""

    if mapped == "Inactive":
        return "Inactive"

    if mapped == "Final":
        return "Final"

    if mapped == "Active":
        return "Active"

    if mapped == "In Review" and _has_building_issuance(d):
        # Prefer Issuance Issued/Re-Issued for the upgrade; Issued-task
        # Approved* also counts (older building workflow). Code-enforcement
        # Active/Passed marks are excluded by _ISSUED_TASK_MARKS.
        tasks = d.get("tasks") or []
        if _first_event_date(tasks, "Issuance", _ISSUE_MARKS) is not pd.NaT:
            return "Active"
        # Issued-task Approved* on building records → Active
        if _first_event_date(tasks, "Issued", _ISSUED_TASK_MARKS) is not pd.NaT:
            # Skip code-enforcement / citation record types
            rtype = str(d.get("record_type") or "").lower()
            if "code enforcement" in rtype or "citation" in rtype:
                return mapped
            return "Active"
        return mapped

    if mapped is not None:
        return mapped

    if _safe_to_datetime(d.get("date")) is not pd.NaT or _has_dated_events(d):
        if _has_building_issuance(d):
            return "Active"
        return "In Review"

    return None


# ── Date extractors ──────────────────────────────────────────────────────────

def _file_date_from_data(d: dict):
    """Application / file date from Accela top-level and search fields."""
    candidates = []

    top = _safe_to_datetime(d.get("date"))
    if top is not pd.NaT:
        candidates.append(top)

    sd = d.get("search_data")
    if isinstance(sd, dict):
        for key in ("File Date", "Date", "Opened Date", "Submitted Date"):
            opened = _safe_to_datetime(sd.get(key))
            if opened is not pd.NaT:
                candidates.append(opened)

    return min(candidates) if candidates else pd.NaT


def _permit_date_from_data(d: dict):
    """Earliest building-permit issuance date.

    Prefer Issuance Marked as Issued / Re-Issued. Fall back to the older
    Issued-task Approved* marks used on converted historic records.
    """
    tasks = d.get("tasks") or []
    issued = _first_event_date(tasks, "Issuance", _ISSUE_MARKS)
    if issued is not pd.NaT:
        return issued
    return _first_event_date(tasks, "Issued", _ISSUED_TASK_MARKS)


def _final_insp_date(d: dict, floor=None):
    """Latest approved Final* inspection Status Date.

    Prefer Permit Final / Final Building / Final Occupancy titles; else
    any inspection whose title contains ``final``. When *floor* is set
    (typically PERMIT_DATE or FILE_DATE), ignore inspection dates strictly
    before that day so pre-issuance fire/review finals are not treated as
    permit completion.
    """
    insp = d.get("inspections")
    if not isinstance(insp, list):
        return pd.NaT

    floor_dt = _safe_to_datetime(floor)
    preferred = []
    other = []
    for row in insp:
        if not isinstance(row, dict):
            continue
        title = str(row.get("Title") or "")
        status = str(row.get("Status") or "").lower()
        if status not in _PASS_INSP:
            continue
        dt = _safe_to_datetime(row.get("Status Date") or row.get("Last Update Date"))
        if dt is pd.NaT:
            continue
        if floor_dt is not pd.NaT and dt.normalize() < floor_dt.normalize():
            continue
        if _FINAL_INSP_PREF.search(title):
            preferred.append(dt)
        elif _ANY_FINAL_INSP.search(title):
            other.append(dt)

    if preferred:
        return max(preferred)
    if other:
        return max(other)
    return pd.NaT


def _final_date_from_data(d: dict):
    """Administrative final / completion date.

    Prefer Time Tracking ``Permit Final``, then Closure CLOSED/Closed,
    then an approved Final* inspection Status Date on/after issuance
    (or file date when issuance is unknown).
    """
    tasks = d.get("tasks") or []
    tt = _latest_event_date(tasks, "Time Tracking", _FINAL_TT_MARKS)
    if tt is not pd.NaT:
        return tt
    closure = _latest_event_date(tasks, "Closure", _CLOSURE_MARKS)
    if closure is not pd.NaT:
        return closure

    floor = _permit_date_from_data(d)
    if floor is pd.NaT:
        floor = _file_date_from_data(d)
    return _final_insp_date(d, floor=floor)


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
        elif effective_status == "In Review" and not _has_building_issuance(d):
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
    Napa County permit records using information from the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Napa County".  Must contain
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
    city = df[(df["JURISDICTION"] == "Napa County") & (df["STATE"] == "CA")].copy()

    print(f"Napa County records: {len(city):,}\n")

    repaired = data_repair(city)

    if AGENT_DATA_PATH:
        out_dir = Path(AGENT_DATA_PATH) / "repaired"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "permits_ca_napa_county_repaired.parquet"
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

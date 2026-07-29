"""Data repair for Chino (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Chino DATA is an Accela Citizen Access scrape. Nearly all sample rows
share core top-level keys (``address``, ``date``, ``status``, ``tasks``,
``search_data``, …); a handful of sparse rows omit optional blocks
(``inspections``, ``fees_details``, ``contacts``, …). Content variants
(INFERRED_SCHEMA):

  - portal_issued_finaled:   Permit Issuance Issued* + final date
                             (Inspections Finaled / Closed Close /
                             final-titled inspection)
  - portal_issued:           Issued present, no final date
  - portal_final_only:       Final date present, no Issued
  - portal_application_only: Application Submittal / top-level date only
  - portal_empty_tasks:      tasks present but undated (TBD / empty)
  - missing

Canonical mappings:
  - DATA.status / search_data.Status (+ workflow upgrades from dated
    Permit Issuance Issued* / Inspections Finaled)           → STATUS_NORMALIZED
  - Earliest of DATA.date / search_data.Date / Application
    Submittal Accepted* / first-touch marks                  → FILE_DATE
  - Earliest Permit Issuance Issued / Issued Revision /
    Issued Deferred                                          → PERMIT_DATE
  - Earliest Inspections Finaled (fallback: Closed Close,
    then final-titled inspection Status Date)                → FINAL_DATE

Known issues repaired:
  - Approved (plans approved, not issued) previously Active
    → FIXED to In Review (unless a dated Issued event exists).
  - Applied / In Review status lagging Issued + Finaled
    workflow → FIXED to Final; keep PERMIT_DATE / FINAL_DATE.
  - FILE_DATE lagging original Application Submittal after Accela
    re-open bumped DATA.date → FIXED to earliest submittal.
  - Final missing FINAL_DATE when Closed Close or a final-titled
    inspection Status Date is available → FILLED.
  - Spurious PERMIT_DATE / FINAL_DATE on In Review after status
    remapping (or when no issuance/final evidence) → cleared.

Not repairable / left as-is:
  - A few Finaled / Closed shells lack Permit Issuance Issued*
    (TBD or absent) → PERMIT_DATE stays missing.
  - Rare Finaled shells lack Inspections Finaled, Closed Close,
    and final-titled inspections → FINAL_DATE stays missing.
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
    "Expired Permit",
    "Expired",
    "Void",
    "Withdrawn",
    "Canceled",
    "Cancelled",
}

_FINAL_STATUSES = {
    "Finaled",
    "Closed",
    "Complete",
    "CLOSED",
}

_ACTIVE_STATUSES = {
    "Issued",
    "Issued Revision",
}

_ISSUE_MARKS = {"Issued", "Issued Revision", "Issued Deferred"}
_FINAL_MARKS = {"Finaled"}
_CLOSE_MARKS = {"Close"}
_FILE_MARKS = {
    "Accepted for Review",
    "Pending Payment",
    "Incomplete Submittal",
    "Routed and Pending",
    "Pre-Check Stamp",
    "Reserved",
    "Notified",
}

_FINAL_INSP_TITLE = re.compile(r"\bfinal\b", re.I)
_FINAL_INSP_STATUS = {
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
    "CLOSED": "Final",
    # Active
    "Issued": "Active",
    "Issued Revision": "Active",
    # Inactive
    "Expired Permit": "Inactive",
    "Expired": "Inactive",
    "Void": "Inactive",
    "Withdrawn": "Inactive",
    "Canceled": "Inactive",
    "Cancelled": "Inactive",
    # In Review (including plans-approved / fee stages — not yet issued)
    "Approved": "In Review",
    "Applied": "In Review",
    "In Review": "In Review",
    "Pending": "In Review",
    "Corrections Required": "In Review",
    "Incomplete Submittal": "In Review",
    "Pending Payment": "In Review",
    "Reserved": "In Review",
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
    """True when Inspections Finaled is dated (primary final signal)."""
    tasks = d.get("tasks") or []
    return _first_event_date(tasks, {"Inspections"}, _FINAL_MARKS) is not pd.NaT


def _expected_status(d: dict) -> Optional[str]:
    """Map DATA.status, then upgrade from workflow evidence.

    Inactive terminal labels are sticky. DATA.status Finaled/Closed maps
    to Final. A dated Permit Issuance Issued* promotes In Review → Active.
    A dated Inspections Finaled promotes In Review → Final (status lag).
    Inspections Finaled alone does **not** promote Issued → Final when
    the portal status is still Issued.
    """
    mapped = _base_status(d)
    raw = _raw_status(d) or ""

    if raw in _INACTIVE or mapped == "Inactive":
        return "Inactive" if mapped == "Inactive" else mapped

    if mapped == "Final" or raw in _FINAL_STATUSES:
        return "Final"

    if mapped == "Active" or raw in _ACTIVE_STATUSES:
        return "Active"

    # Status lag: Applied / Approved / Pending still showing while
    # Inspections Finaled already fired.
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
    earliest Application Submittal first-touch marks. Accela sometimes
    bumps the top-level date on re-open while the original submittal
    remains in the task history.
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
    app = _first_event_date(tasks, {"Application Submittal"}, _FILE_MARKS)
    if app is not pd.NaT:
        candidates.append(app)

    return min(candidates) if candidates else pd.NaT


def _permit_date_from_data(d: dict):
    """Earliest Permit Issuance Issued* date."""
    tasks = d.get("tasks") or []
    return _first_event_date(tasks, {"Permit Issuance"}, _ISSUE_MARKS)


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
    """Final / completion date for Chino Accela records.

    Prefer Inspections ``Finaled``, then Closed ``Close``, then a
    final-titled inspection Status Date.
    """
    tasks = d.get("tasks") or []
    finaled = _first_event_date(tasks, {"Inspections"}, _FINAL_MARKS)
    if finaled is not pd.NaT:
        return finaled

    closed = _first_event_date(tasks, {"Closed"}, _CLOSE_MARKS)
    if closed is not pd.NaT:
        return closed

    return _final_insp_status_date(d)


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
    Chino permit records using information from the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Chino".  Must contain
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
    city = df[(df["JURISDICTION"] == "Chino") & (df["STATE"] == "CA")].copy()

    print(f"Chino records: {len(city):,}\n")

    repaired = data_repair(city)

    if AGENT_DATA_PATH:
        out_dir = Path(AGENT_DATA_PATH) / "repaired"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "permits_ca_chino_repaired.parquet"
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

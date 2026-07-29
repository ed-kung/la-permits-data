"""Data repair for Yuba City (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Yuba City DATA is an Accela Citizen Access scrape (same family as
Martinez / Lake County / Eastvale). Most sample rows share the full
portal key set (``address``, ``date``, ``status``, ``tasks``,
``inspections``, ``fees_details``, ``search_data``, …); a handful omit
fees/inspections or contacts. Content variants (INFERRED_SCHEMA):

  - portal_issued_finaled:   Issued + final-completion evidence
  - portal_issued:           Issued present, no final-completion date
  - portal_final_insp_only:  Final evidence present, no Issued
  - portal_application_only: Application / top-level date only
  - portal_empty_tasks:      tasks present but undated (TBD / empty)
  - missing

Canonical mappings:
  - DATA.status / search_data.Status (+ workflow overrides) →
    STATUS_NORMALIZED
  - Earliest of DATA.date / search_data.Date / Application
    Acceptance|Submittal Accepted*                          → FILE_DATE
  - Earliest Permit Issuance Issued (fallback: Application
    Submittal Issued for online shells)                     → PERMIT_DATE
  - Earliest Inspection Final Inspection Complete
    (fallback: Inspections Finaled; Certificate of Occupancy
    Final CO Issued; Passed/Approved final inspection
    Status Date)                                            → FINAL_DATE

Known issues repaired:
  - ``Issued`` shells with Inspection Final Inspection Complete left
    Active (portal lag) → FIXED to Final.
  - ``Ready to Issue`` with dated Permit Issuance Issued left
    In Review → FIXED to Active.
  - ``Issued`` / ``Ready to Issue`` shells whose Permit Issuance events
    are all Void → FIXED to Inactive.
  - Online Application Submittal Issued rows missing PERMIT_DATE
    → FILLED.
  - Finaled rows missing FINAL_DATE while a Passed Final -
    Building inspection Status Date exists → FILLED.
  - FILE_DATE later than Application Acceptance/Submittal
    Accepted* by 1–5 days → FIXED to the earlier date.

Not repairable / left as-is:
  - Two Finaled shells without any Issued mark → PERMIT_DATE stays
    missing.
  - Issued shells with only a Passed Final - Building inspection (no
    Accela Final Inspection Complete task) stay Active; inspections[]
    alone are not treated as status-promotion evidence.
  - One Submitted / STATUS_ORIGINAL=issued row has PERMIT_DATE but no
    Issued task event; STATUS_ORIGINAL keeps it Active.
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
    "CofO Issued",
}

_ACTIVE_STATUSES = {
    "Issued",
    "Permit Issued",
}

_ISSUE_MARKS = {"Permit Issued", "Issued"}
_FINAL_INSP_MARKS = {"Final Inspection Complete", "Finaled"}
_FINAL_CO_MARKS = {"Final CO Issued"}
_FILE_MARK_PREFIXES = (
    "submitted",
    "accepted",
    "application accepted",
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


def _application_file_dates(tasks: list) -> list:
    """Accepted / submitted dates from Application Acceptance or Submittal."""
    dates = []
    for t in _iter_tasks(tasks):
        if t.get("name") not in {
            "Application Acceptance",
            "Application Submittal",
        }:
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
    """Dates from inspections[] with Passed/Approved and a final title."""
    dates = []
    for insp in d.get("inspections") or []:
        if not isinstance(insp, dict):
            continue
        title = str(insp.get("Title") or "").lower()
        status = str(insp.get("Status") or "").strip()
        status_l = status.lower()
        if status_l not in {"approved", "passed", "final approved"}:
            continue
        if "final" not in title and status_l != "final approved":
            continue
        dt = _safe_to_datetime(insp.get("Status Date"))
        if dt is not pd.NaT:
            dates.append(dt)
    return dates


def _permit_issuance_marks(d: dict) -> list[str]:
    marks = []
    for t in _iter_tasks(d.get("tasks") or []):
        if t.get("name") != "Permit Issuance":
            continue
        for e in t.get("events") or []:
            mark, _ = _event_mark_and_date(e)
            if mark and mark != "TBD":
                marks.append(mark)
    return marks


def _is_voided_issuance_shell(d: dict) -> bool:
    """Issued portal status whose Permit Issuance events are all Void."""
    marks = _permit_issuance_marks(d)
    if not marks:
        return False
    if any(m in _ISSUE_MARKS for m in marks):
        return False
    return all(m == "Void" for m in marks)


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

    candidates.extend(_application_file_dates(d.get("tasks") or []))
    return min(candidates) if candidates else pd.NaT


def _permit_date_from_data(d: dict):
    """Earliest Permit Issuance Issued; fallback Application Submittal Issued."""
    tasks = d.get("tasks") or []
    issued = _first_event_date(tasks, {"Permit Issuance"}, _ISSUE_MARKS)
    if issued is not pd.NaT:
        return issued
    return _first_event_date(tasks, {"Application Submittal"}, _ISSUE_MARKS)


def _final_date_from_data(d: dict):
    """Prefer Inspection Final Inspection Complete, then other completion marks."""
    tasks = d.get("tasks") or []

    final = _first_event_date(tasks, {"Inspection"}, {"Final Inspection Complete"})
    if final is not pd.NaT:
        return final

    final = _first_event_date(tasks, {"Inspections"}, {"Finaled"})
    if final is not pd.NaT:
        return final

    final = _first_event_date(
        tasks, {"Certificate of Occupancy"}, _FINAL_CO_MARKS
    )
    if final is not pd.NaT:
        return final

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
    # Schema "finaled" follows workflow task marks (same bar as status
    # promotion); inspections[] alone do not flip the schema label.
    finaled = _has_final_evidence(data_dict)

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
    "CofO Issued": "Final",
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
    "Applied": "In Review",
    "Pending": "In Review",
    "In Review": "In Review",
    "Revisions Required": "In Review",
    "Waiting for Payment": "In Review",
    "Reactivated": "In Review",
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
    if "cofo" in raw.lower() or "c of o" in raw.lower():
        return "Final"
    return None


def _has_issuance(d: dict) -> bool:
    return _permit_date_from_data(d) is not pd.NaT


def _final_task_date(d: dict):
    """Completion date from workflow tasks only (not inspections[]).

    Used for status promotion so a stray Passed Final - Building row
    cannot upgrade Ready to Issue / Issued shells that never received
    Accela's Final Inspection Complete / Finaled / Final CO mark.
    """
    tasks = d.get("tasks") or []
    final = _first_event_date(tasks, {"Inspection"}, {"Final Inspection Complete"})
    if final is not pd.NaT:
        return final
    final = _first_event_date(tasks, {"Inspections"}, {"Finaled"})
    if final is not pd.NaT:
        return final
    return _first_event_date(
        tasks, {"Certificate of Occupancy"}, _FINAL_CO_MARKS
    )


def _has_final_evidence(d: dict) -> bool:
    return _final_task_date(d) is not pd.NaT


def _status_original_hint(status_original) -> Optional[str]:
    if status_original is None or (isinstance(status_original, float) and math.isnan(status_original)):
        return None
    so = str(status_original).strip().lower()
    if not so:
        return None
    if so in {"finaled", "finalled", "complete", "closed", "cofo issued"}:
        return "Final"
    if so in {"issued", "permit issued"}:
        return "Active"
    if so in {"expired", "void", "withdrawn", "canceled", "cancelled", "revoked"}:
        return "Inactive"
    return "In Review"


def _expected_status(d: dict, status_original=None) -> Optional[str]:
    """Map DATA.status, then upgrade / infer from workflow evidence.

    Inactive terminal labels are sticky. Finaled / CofO Issued → Final.
    Issued → Active unless a dated final-completion mark exists (portal
    lag), in which case → Final. Issued shells whose Permit Issuance
    events are all Void → Inactive. In Review upgrades to Final / Active
    from workflow. STATUS_ORIGINAL rescues Submitted/Issued scrape lag
    when workflow Issued events are absent.
    """
    mapped = _base_status(d)
    raw = _raw_status(d) or ""

    if raw in _INACTIVE or mapped == "Inactive":
        return "Inactive"

    if _is_voided_issuance_shell(d):
        return "Inactive"

    if mapped == "Final" or raw in _FINAL_STATUSES:
        return "Final"

    if mapped == "Active" or raw in _ACTIVE_STATUSES:
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
        if _is_voided_issuance_shell(d):
            return "Inactive"
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
    status_original = row["STATUS_ORIGINAL"] if "STATUS_ORIGINAL" in row.index else None
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
    Yuba City permit records using information from the raw DATA JSON.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Yuba City".  Must contain
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
        (df["JURISDICTION"] == "Yuba City") & (df["STATE"] == "CA")
    ].copy()

    print(f"Yuba City records: {len(city):,}\n")

    repaired = data_repair(city)

    if AGENT_DATA_PATH:
        out_dir = Path(AGENT_DATA_PATH) / "repaired"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "permits_ca_yuba_city_repaired.parquet"
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
            })
            .value_counts()
            .reset_index(name="n")
        )
        for _, trow in transitions.iterrows():
            print(f"  {trow['before']:15s} → {trow['after']:15s}: {trow['n']:>4,}")
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

    fd = pd.to_datetime(repaired["FILE_DATE"], utc=True, errors="coerce")
    pd_ = pd.to_datetime(repaired["PERMIT_DATE"], utc=True, errors="coerce")
    ff = pd.to_datetime(repaired["FINAL_DATE"], utc=True, errors="coerce")
    both_fp = fd.notna() & pd_.notna()
    both_pf = pd_.notna() & ff.notna()
    print("\nChronology inversions:")
    print(f"  FILE > PERMIT: {(both_fp & (fd.dt.normalize() > pd_.dt.normalize())).sum()}")
    print(f"  PERMIT > FINAL: {(both_pf & (pd_.dt.normalize() > ff.dt.normalize())).sum()}")

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

    from collections import Counter

    print("\nActive/Final still missing PERMIT_DATE (by DATA.status):")
    gap = Counter()
    for idx in repaired.index:
        if repaired.at[idx, "STATUS_NORMALIZED"] not in ("Active", "Final"):
            continue
        if pd.notna(repaired.at[idx, "PERMIT_DATE"]):
            continue
        d = _safe_parse(city.at[idx, "DATA"])
        gap[(d or {}).get("status")] += 1
    for k, v in gap.most_common():
        print(f"  {k}: {v}")

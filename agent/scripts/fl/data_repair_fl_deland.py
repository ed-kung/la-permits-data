"""Data repair for DeLand (FL) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

DeLand DATA is an Accela Citizen Access payload (status / date / tasks /
search_data / more_details / inspections / fees_details). Canonical
fields:

  - DATA.status (fallback search_data.Status)          → STATUS_NORMALIZED
  - search_data.Date else DATA.date else earliest
    Application Submittal Accepted                     → FILE_DATE
  - Earliest Permit Issuance Issued /
    Permit Issued / Issued Missing NOC                 → PERMIT_DATE
  - Latest of Close Closed / C of O / C of C;
    Closed.Completed; Inspection Final Inspection
    Complete; Review Consolidation Pre-Check Complete;
    Declarations Review Completed; Follow Up
    Investigation Violation Corrected; passed final-ish
    inspections; else Inspection Complete              → FINAL_DATE

Content variants (INFERRED_SCHEMA):
  - accela_permit_full / accela_permit_basic
  - accela_code_enforcement
  - accela_lien_history
  - accela_declarations
  - accela_precheck
  - accela_other / accela_shell
  - missing / unknown
  Suffixes ``_issued_finaled``, ``_issued``, ``_finaled``,
  ``_applied`` reflect which canonical dates are recoverable.

Known issues repaired:
  - Unmapped statuses (Issued Missing NOC, Additional Info
    Needed, Home Business, Declarations Due) → FILLED.
  - Stale STATUS_ORIGINAL ``in review`` while DATA.status is
    Issued → FIXED to Active.
  - Upstream PERMIT_DATE often copied Permit Issuance
    ``Ready to Issue`` instead of ``Issued`` → FIXED.
  - Spurious Ready-to-Issue PERMIT_DATE on In Review with no
    Issued event → cleared.
  - FINAL_DATE often equal to Inspection Complete one day
    (or more) before Close / C of O → FIXED to later of
    Close and Final Inspection Complete (plus precheck /
    lien / CE / declarations closure marks).
  - Spurious FINAL_DATE on Active / Inactive → cleared.

Not repairable from DATA:
  - FILE_DATE already matches DATA.date / search_data.Date
    for every sample row.
  - Business Tax Receipt / Inspection Template ``Active``
    shells have no Permit Issuance Issued event →
    PERMIT_DATE stays missing.
  - Some Closed pre-check / zoning shells lack Close /
    Inspection final marks beyond Pre-Check Complete
    (those are filled when Pre-Check Complete exists).
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

_FINAL_INSP_RE = re.compile(
    r"final|fnl|c of o|c of c|certificate|\bco\b|\bcc\b|\bcoc\b|cofo",
    re.IGNORECASE,
)

_INSP_PASS = {
    "APPROVED",
    "APPROVED WITH EXCEPTION",
    "PASS",
    "PASSED",
    "COMPLETE",
    "COMPLETED",
    "SATISFACTORY",
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


def _event_field(event: dict, *labels: str):
    """Read an Accela event field, tolerating leading/trailing spaces / NBSP."""
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


def _task_names(d: dict) -> set:
    return {name for name, _ in _iter_task_nodes(d.get("tasks") or [])}


# ── Schema classification ────────────────────────────────────────────────────

def _base_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    if not isinstance(data_dict, dict):
        return "unknown"

    keys = set(data_dict.keys())
    if "tasks" not in keys and "status" not in keys and "search_data" not in keys:
        return "unknown"

    tasks = data_dict.get("tasks") or []
    names = _task_names(data_dict)
    inspections = data_dict.get("inspections")
    has_inspections = isinstance(inspections, list) and len(inspections) > 0
    has_dated_event = _has_dated_task_event(tasks)

    if "Case Intake" in names:
        family = "accela_code_enforcement"
    elif "Utility Lien" in names or "Building Permit History" in names:
        family = "accela_lien_history"
    elif "Declarations Review" in names and "Permit Issuance" not in names:
        family = "accela_declarations"
    elif (
        "Review Consolidation" in names
        and "Permit Issuance" not in names
        and "Close" not in names
    ):
        family = "accela_precheck"
    elif "Permit Issuance" in names:
        family = "accela_permit_full" if has_inspections else "accela_permit_basic"
    elif has_dated_event:
        family = "accela_other"
    elif "tasks" in keys or "status" in keys:
        family = "accela_shell"
    elif "search_data" in keys:
        family = "search_only"
    else:
        family = "unknown"

    return family


def _classify_schema(data_dict: Optional[dict]) -> str:
    base = _base_schema(data_dict)
    if base in {"missing", "unknown"} or data_dict is None:
        return base

    tasks = data_dict.get("tasks") or []
    issued = _permit_date_from_tasks(tasks)
    final = _final_date_from_data(data_dict)
    has_issued = issued is not pd.NaT and not pd.isna(issued)
    has_final = final is not pd.NaT and not pd.isna(final)

    if has_issued and has_final:
        suffix = "issued_finaled"
    elif has_issued:
        suffix = "issued"
    elif has_final:
        suffix = "finaled"
    else:
        suffix = "applied"
    return f"{base}_{suffix}"


# ── Status mapping ───────────────────────────────────────────────────────────

_STATUS_MAP = {
    # Final
    "Closed": "Final",
    "Case Closed": "Final",
    "Completed": "Final",
    "CofO Issued": "Final",
    "C of C Issued": "Final",
    "Inspections Complete": "Final",
    # Active
    "Issued": "Active",
    "Issued Missing NOC": "Active",
    "Active": "Active",
    # In Review
    "In Review": "In Review",
    "Pending": "In Review",
    "Ready to Issue": "In Review",
    "Awaiting Plans": "In Review",
    "Resubmittal Required": "In Review",
    "Waiting on Customer": "In Review",
    "Additional Info Needed": "In Review",
    "Revision Submitted": "In Review",
    "Balance Due": "In Review",
    "Declarations Due": "In Review",
    "Home Business": "In Review",
    "Open": "In Review",
    # Inactive
    "Void": "Inactive",
    "Expired": "Inactive",
    "Permit Expired": "Inactive",
    "Withdrawn": "Inactive",
}

_STATUS_MAP_LOWER = {k.lower(): v for k, v in _STATUS_MAP.items()}


def _raw_status(d: dict) -> str:
    status = d.get("status")
    if isinstance(status, str) and status.strip():
        return status.strip()
    sd = d.get("search_data") if isinstance(d.get("search_data"), dict) else {}
    sd_status = sd.get("Status")
    if isinstance(sd_status, str):
        return sd_status.strip()
    return ""


def _map_status(data_status: str) -> Optional[str]:
    if not data_status:
        return None
    return _STATUS_MAP.get(data_status) or _STATUS_MAP_LOWER.get(data_status.lower())


# ── Date extractors ──────────────────────────────────────────────────────────

def _file_date_from_data(d: dict):
    """Best available application / file date from Accela payload."""
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
        {"Application Submittal", "Case Intake"},
        lambda m: (m or "").strip().lower()
        in {"accepted", "accepted-otc", "assigned", "plans received"},
    )
    if intake:
        return min(intake)
    return pd.NaT


def _permit_date_from_tasks(tasks: list):
    """Earliest Permit Issuance Issued / Issued Missing NOC date."""

    def _is_issued(m: str) -> bool:
        return (m or "").strip().lower() in {
            "issued",
            "permit issued",
            "issued missing noc",
        }

    issued = _event_dates(tasks, {"Permit Issuance"}, _is_issued)
    if issued:
        return min(issued)
    return pd.NaT


def _final_inspection_list_dates(d: dict) -> list:
    dates = []
    for insp in d.get("inspections") or []:
        if not isinstance(insp, dict):
            continue
        status = (insp.get("Status") or "").strip().upper()
        if status not in _INSP_PASS:
            continue
        title = insp.get("Title") or ""
        if not _FINAL_INSP_RE.search(title):
            continue
        dt = _safe_to_datetime(
            insp.get("Status Date") or insp.get("Last Update Date")
        )
        if dt is not pd.NaT and not pd.isna(dt):
            dates.append(dt)
    return dates


def _final_date_from_data(d: dict):
    """Latest closure / final-inspection / certificate-adjacent mark."""
    tasks = d.get("tasks") or []
    dates: list = []

    dates.extend(
        _event_dates(
            tasks,
            {"Close"},
            lambda m: (m or "").strip().lower()
            in {"closed", "c of o issued", "c of c issued"},
        )
    )
    dates.extend(
        _event_dates(
            tasks,
            {"Closed"},
            lambda m: (m or "").strip().lower() == "completed",
        )
    )
    dates.extend(
        _event_dates(
            tasks,
            {"Inspection"},
            lambda m: (m or "").strip().lower()
            in {"final inspection complete", "inspections complete"},
        )
    )
    dates.extend(
        _event_dates(
            tasks,
            {"Review Consolidation"},
            lambda m: (m or "").strip().lower() == "pre-check complete",
        )
    )
    dates.extend(
        _event_dates(
            tasks,
            {"Declarations Review"},
            lambda m: (m or "").strip().lower() == "completed",
        )
    )
    dates.extend(
        _event_dates(
            tasks,
            {"Follow Up Investigation"},
            lambda m: (m or "").strip().lower() == "violation corrected",
        )
    )
    dates.extend(_final_inspection_list_dates(d))

    if dates:
        return max(dates)

    # Fallback: Inspection workflow Complete (used heavily upstream).
    complete = _event_dates(
        tasks,
        {"Inspection"},
        lambda m: (m or "").strip().lower() == "complete",
    )
    if complete:
        return max(complete)
    return pd.NaT


# ── Per-record repair ────────────────────────────────────────────────────────

def _apply_date(repairs: dict, row, field: str, candidate, *, allow_fill: bool = True) -> None:
    cand = _safe_to_datetime(candidate)
    if cand is pd.NaT or pd.isna(cand):
        return
    current = row[field]
    if pd.isna(current):
        if allow_fill:
            repairs[field] = cand
            repairs[f"{field}_FLAG"] = "FILLED"
    elif not _dates_equal(current, cand):
        repairs[field] = cand
        repairs[f"{field}_FLAG"] = "FIXED"


def _clear_date(repairs: dict, row, field: str) -> None:
    current = repairs.get(field, row[field])
    if pd.isna(current):
        return
    repairs[field] = pd.NaT
    repairs[f"{field}_FLAG"] = "FIXED"


def _apply_status(repairs: dict, current, expected: Optional[str]) -> Optional[str]:
    if expected is None:
        return current if not (isinstance(current, float) and pd.isna(current)) else None
    if pd.isna(current):
        repairs["STATUS_NORMALIZED"] = expected
        repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"
        return expected
    if current != expected:
        repairs["STATUS_NORMALIZED"] = expected
        repairs["STATUS_NORMALIZED_FLAG"] = "FIXED"
        return expected
    return current


def _repair_record(row, d: dict, repairs: dict) -> None:
    tasks = d.get("tasks") or []
    expected = _map_status(_raw_status(d))
    effective = _apply_status(repairs, row["STATUS_NORMALIZED"], expected)

    _apply_date(repairs, row, "FILE_DATE", _file_date_from_data(d))

    issued = _permit_date_from_tasks(tasks)
    current_permit = row["PERMIT_DATE"]

    if issued is not pd.NaT and not pd.isna(issued):
        # Real issuance date: keep/fix for Active/Final/Inactive, and for
        # In Review rows that were previously issued (e.g. Revision Submitted).
        if effective in ("Active", "Final", "Inactive", "In Review"):
            if effective == "In Review" and pd.isna(current_permit):
                # Do not invent PERMIT_DATE on In Review; only correct bad ones.
                pass
            else:
                _apply_date(
                    repairs,
                    row,
                    "PERMIT_DATE",
                    issued,
                    allow_fill=effective in ("Active", "Final", "Inactive"),
                )
    else:
        # No Issued event: clear Ready-to-Issue / other unsupported stamps.
        if not pd.isna(current_permit):
            _clear_date(repairs, row, "PERMIT_DATE")

    final_src = _final_date_from_data(d)
    if effective == "Final":
        _apply_date(repairs, row, "FINAL_DATE", final_src)
    else:
        _clear_date(repairs, row, "FINAL_DATE")


# ── Main entry point ─────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    DeLand permit records using information from the raw DATA JSON.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "DeLand".  Must contain
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
        _repair_record(row, d, repairs)
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
    filepath = os.path.join(
        my_data_path, "processed_data", "permits_fl_sample.parquet"
    )
    df = pd.read_parquet(filepath)
    city = df[
        (df["JURISDICTION"] == "DeLand") & (df["STATE"] == "FL")
    ].copy()

    print(f"DeLand records: {len(city):,}\n")
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

    print("\nDATA.status → STATUS_NORMALIZED (after):")
    status_from_data = repaired["DATA"].map(
        lambda x: (_safe_parse(x) or {}).get("status")
    )
    ct = (
        pd.DataFrame({
            "DATA_STATUS": status_from_data,
            "STATUS_NORMALIZED": repaired["STATUS_NORMALIZED"],
        })
        .groupby(["DATA_STATUS", "STATUS_NORMALIZED"], dropna=False)
        .size()
        .reset_index(name="n")
        .sort_values("n", ascending=False)
    )
    print(ct.to_string(index=False))

    print("\nFILE_DATE coverage by status (after):")
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

    # Sanity: PERMIT_DATE should equal Issued when both exist
    issued_vals = []
    for x in repaired["DATA"]:
        d = _safe_parse(x) or {}
        issued_vals.append(_permit_date_from_tasks(d.get("tasks") or []))
    issued_s = pd.Series(
        pd.to_datetime(issued_vals, errors="coerce"), index=repaired.index
    )
    both = repaired["PERMIT_DATE"].notna() & issued_s.notna()
    match = int(
        (
            repaired.loc[both, "PERMIT_DATE"].dt.normalize()
            == issued_s.loc[both].dt.normalize()
        ).sum()
    )
    print(f"\nPERMIT_DATE == Issued event (both present): {match} / {int(both.sum())}")

    # Inversions
    inv_fp = (
        repaired["FILE_DATE"].notna()
        & repaired["PERMIT_DATE"].notna()
        & (repaired["FILE_DATE"].dt.normalize() > repaired["PERMIT_DATE"].dt.normalize())
    ).sum()
    inv_pf = (
        repaired["PERMIT_DATE"].notna()
        & repaired["FINAL_DATE"].notna()
        & (
            repaired["PERMIT_DATE"].dt.normalize()
            > repaired["FINAL_DATE"].dt.normalize()
        )
    ).sum()
    print(f"FILE_DATE > PERMIT_DATE inversions: {inv_fp}")
    print(f"PERMIT_DATE > FINAL_DATE inversions: {inv_pf}")

    if agent_data_path:
        out_dir = Path(agent_data_path) / "repaired"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "permits_fl_deland_repaired.parquet"
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote repaired sample → {out_path}")

"""Data repair for Clearwater (FL) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Clearwater DATA is an Accela Citizen Access payload (status / date /
tasks / search_data / more_details, usually with inspections and
fees_details). Canonical fields:

  - DATA.status (fallback search_data.Status)     → STATUS_NORMALIZED
  - DATA.date (fallback search_data.Date)         → FILE_DATE
  - more_details PERMIT DATES.Issued; else
    Permit Verification ``Issue``; else
    Enforcement ``Permit Issued``; else
    Digital Plan Review ``Permit Issued``         → PERMIT_DATE
  - more_details PERMIT DATES.Finaled; else
    Active Permit completion / CO / CC marks;
    else Passed final-ish inspections; else
    enforcement compliance / abatement marks;
    else (Closed-family) latest Pass/DONE insp.   → FINAL_DATE

Key-set / content variants (INFERRED_SCHEMA):
  - accela_full:   inspections present + dated task events
  - accela_basic:  dated task events, no inspections list
  - accela_sparse: status/date/tasks present, little else
  - accela_shell:  blank status
  Suffixes ``_issued_finaled``, ``_issued``, ``_finaled``,
  ``_applied`` reflect which canonical dates are recoverable.

Known issues repaired:
  - 38 null STATUS_NORMALIZED (Revisions Needed, License Holder
    Self Certify, Building Repaired, Compliant, …) → FILLED.
  - Retired / Complied / Completed mislabeled as In Review or
    Active → FIXED to Inactive / Final.
  - Stale STATUS_ORIGINAL lagging DATA.status (expired /
    additional info / revisions needed while status is Active)
    → FIXED to Active.
  - Hold / Revisions Needed after Permit Verification Issue
    upgraded to Active.
  - PERMIT_DATE and FINAL_DATE never ingested upstream → FILLED
    from PERMIT DATES / workflow tasks / inspections.

Not repairable from DATA:
  - Many Completed / Closed / No Violation rows have no Issued
    or Finaled fields and no usable task/inspection dates
    → PERMIT_DATE / FINAL_DATE stay missing.
  - FILE_DATE already matches DATA.date for every sample row.
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
    r"final|fnl|closeout|certificate|\bco\b|\bcc\b|\bcoc\b",
    re.IGNORECASE,
)

_INSP_PASS = {"PASS", "DONE"}

_ACTIVE_PERMIT_FINAL_MARKS = {
    "Completed",
    "Certificate of Completion",
    "Certificate of Occupancy",
    "Temp Certificate of Occupancy",
    "License Holder Self Certify",
    "Clear Permit",
}

_ENFORCEMENT_FINAL_MARKS = {
    "Complied",
    "Complied No Permit Required",
    "No Violation",
    "Conditions Met",
    "Green Card Signed",
    "Repaired",
    "Building Repaired",
}

# Statuses where any successful inspection may stand in for FINAL_DATE.
_ENFORCEMENT_FINAL_STATUSES = {
    "closed",
    "no violation",
    "complied",
    "building repaired",
    "owner demo",
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
    da = _safe_to_datetime(a)
    db = _safe_to_datetime(b)
    if da is pd.NaT or db is pd.NaT or pd.isna(da) or pd.isna(db):
        return False
    return pd.Timestamp(da).normalize() == pd.Timestamp(db).normalize()


def _apply_status(repairs: dict, current, expected: Optional[str]) -> Optional[str]:
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


def _event_dates(tasks: list, task_names, marked_values) -> list:
    if isinstance(task_names, str):
        task_names = {task_names}
    else:
        task_names = set(task_names)
    if isinstance(marked_values, str):
        marked_values = {marked_values}
    else:
        marked_values = set(marked_values)

    dates = []
    for name, t in _iter_task_nodes(tasks):
        if name not in task_names:
            continue
        for e in t.get("events") or []:
            if not isinstance(e, dict):
                continue
            marked, on_val = _parse_event(e)
            marked = (marked or "").strip() if isinstance(marked, str) else marked
            if not marked or marked not in marked_values:
                continue
            dt = _safe_to_datetime(on_val)
            if dt is not pd.NaT and not pd.isna(dt):
                dates.append(dt)
    return dates


def _event_dates_any_task(tasks: list, marked_values) -> list:
    if isinstance(marked_values, str):
        marked_values = {marked_values}
    else:
        marked_values = set(marked_values)
    dates = []
    for _, t in _iter_task_nodes(tasks):
        for e in t.get("events") or []:
            if not isinstance(e, dict):
                continue
            marked, on_val = _parse_event(e)
            marked = (marked or "").strip() if isinstance(marked, str) else marked
            if not marked or marked not in marked_values:
                continue
            dt = _safe_to_datetime(on_val)
            if dt is not pd.NaT and not pd.isna(dt):
                dates.append(dt)
    return dates


# ── more_details PERMIT DATES ────────────────────────────────────────────────

def _permit_dates_block(d: dict) -> Optional[dict]:
    stack = [d.get("more_details") or {}]
    while stack:
        obj = stack.pop()
        if isinstance(obj, dict):
            for k, v in obj.items():
                key = str(k).replace("\xa0", " ").strip().upper()
                if key == "PERMIT DATES" and isinstance(v, dict):
                    return v
                if isinstance(v, (dict, list)):
                    stack.append(v)
        elif isinstance(obj, list):
            stack.extend(item for item in obj if isinstance(item, (dict, list)))
    return None


# ── Schema classification ────────────────────────────────────────────────────

def _accela_raw_status(d: dict) -> str:
    status = d.get("status")
    if isinstance(status, str) and status.strip():
        return status.strip()
    sd = d.get("search_data") if isinstance(d.get("search_data"), dict) else {}
    sd_status = sd.get("Status")
    if isinstance(sd_status, str) and sd_status.strip():
        return sd_status.strip()
    return ""


def _content_suffix(d: dict, tasks: list) -> str:
    has_issued = _permit_date_from_accela(d, tasks)
    has_final = _final_date_from_accela(d, tasks)
    issued_ok = has_issued is not pd.NaT and not pd.isna(has_issued)
    final_ok = has_final is not pd.NaT and not pd.isna(has_final)
    if issued_ok and final_ok:
        return "issued_finaled"
    if issued_ok:
        return "issued"
    if final_ok:
        return "finaled"
    return "applied"


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    if not isinstance(data_dict, dict):
        return "unknown"

    keys = set(data_dict.keys())
    if "tasks" not in keys and "status" not in keys and "search_data" not in keys:
        return "unknown"

    tasks = data_dict.get("tasks") or []
    has_inspections = isinstance(data_dict.get("inspections"), list)
    has_dated = _has_dated_task_event(tasks)
    raw = _accela_raw_status(data_dict)

    if not raw:
        base = "accela_shell"
    elif has_dated and has_inspections:
        base = "accela_full"
    elif has_dated:
        base = "accela_basic"
    elif "inspections" not in keys and "fees_details" not in keys:
        base = "accela_sparse"
    else:
        base = "accela_basic"

    return f"{base}_{_content_suffix(data_dict, tasks)}"


# ── Status maps ──────────────────────────────────────────────────────────────

_STATUS_MAP = {
    # Final
    "Completed": "Final",
    "Closed": "Final",
    "No Violation": "Final",
    "Complied": "Final",
    "Building Repaired": "Final",
    "Compliant": "Final",
    "License Holder Self Certify": "Final",
    # Active
    "Active": "Active",
    "Permit issued": "Active",
    "In Violation": "Active",
    "Stop Work Order": "Active",
    "Owner Demo": "Active",
    # In Review
    "In Review": "In Review",
    "Received": "In Review",
    "Additional Info Required": "In Review",
    "Revisions Needed": "In Review",
    "Hold": "In Review",
    "Review Approved": "In Review",
    "Referred": "In Review",
    "Economic Development": "In Review",
    "No Access - Owner Refused": "In Review",
    # Inactive
    "Expired": "Inactive",
    "Void": "Inactive",
    "Withdrawn": "Inactive",
    "Denied": "Inactive",
    "Retired": "Inactive",
}

_STATUS_MAP_LOWER = {k.lower(): v for k, v in _STATUS_MAP.items()}


def _map_status(data_status: str) -> Optional[str]:
    if not data_status:
        return None
    return (
        _STATUS_MAP.get(data_status)
        or _STATUS_MAP_LOWER.get(data_status.lower())
    )


# ── Date extractors ──────────────────────────────────────────────────────────

def _file_date_from_accela(d: dict):
    dt = _safe_to_datetime(d.get("date"))
    if dt is not pd.NaT and not pd.isna(dt):
        return dt
    sd = d.get("search_data") if isinstance(d.get("search_data"), dict) else {}
    dt = _safe_to_datetime(sd.get("Date"))
    if dt is not pd.NaT and not pd.isna(dt):
        return dt
    intake = _event_dates(
        d.get("tasks") or [],
        {"Application Submittal", "Record Submittal"},
        {
            "Accepted",
            "Approved",
            "Online Submittal Processed",
            "Route to Review",
            "Need Addtl Info",
            "Notification Sent",
        },
    )
    return min(intake) if intake else pd.NaT


def _permit_date_from_accela(d: dict, tasks: list):
    dates = []
    block = _permit_dates_block(d)
    if block:
        for key in ("Issued", "Issued Date"):
            dt = _safe_to_datetime(block.get(key))
            if dt is not pd.NaT and not pd.isna(dt):
                dates.append(dt)

    dates.extend(_event_dates(tasks, {"Permit Verification"}, {"Issue"}))
    dates.extend(_event_dates(tasks, {"Enforcement"}, {"Permit Issued"}))
    dates.extend(
        _event_dates(tasks, {"Digital Plan Review"}, {"Permit Issued"})
    )
    return min(dates) if dates else pd.NaT


def _final_inspection_dates(d: dict) -> list:
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


def _any_pass_inspection_dates(d: dict) -> list:
    dates = []
    for insp in d.get("inspections") or []:
        if not isinstance(insp, dict):
            continue
        status = (insp.get("Status") or "").strip().upper()
        if status not in _INSP_PASS:
            continue
        dt = _safe_to_datetime(
            insp.get("Status Date") or insp.get("Last Update Date")
        )
        if dt is not pd.NaT and not pd.isna(dt):
            dates.append(dt)
    return dates


def _final_date_from_accela(d: dict, tasks: list):
    block = _permit_dates_block(d)
    if block:
        for key in ("Finaled", "CO Date"):
            dt = _safe_to_datetime(block.get(key))
            if dt is not pd.NaT and not pd.isna(dt):
                return dt

    completed = _event_dates(
        tasks, {"Active Permit"}, _ACTIVE_PERMIT_FINAL_MARKS
    )
    if completed:
        return max(completed)

    milestone = _event_dates(
        tasks, {"Phase 1 Inspection Review"}, {"Approved"}
    )
    if milestone:
        return max(milestone)

    fin_insp = _final_inspection_dates(d)
    if fin_insp:
        return max(fin_insp)

    enf = _event_dates_any_task(tasks, _ENFORCEMENT_FINAL_MARKS)
    # Prefer Abatement ``Repaired`` when present.
    abatement = _event_dates(tasks, {"Abatement"}, {"Repaired"})
    if abatement:
        return max(abatement)
    if enf:
        return max(enf)

    raw = _accela_raw_status(d).lower()
    if raw in _ENFORCEMENT_FINAL_STATUSES:
        any_pass = _any_pass_inspection_dates(d)
        if any_pass:
            return max(any_pass)

    return pd.NaT


# ── Per-schema repair ────────────────────────────────────────────────────────

def _repair_accela(row, d: dict, repairs: dict) -> None:
    tasks = d.get("tasks") or []
    raw = _accela_raw_status(d)
    expected = _map_status(raw)
    issued = _permit_date_from_accela(d, tasks)

    # Post-issuance review/hold statuses are still issued permits.
    if (
        expected == "In Review"
        and issued is not pd.NaT
        and not pd.isna(issued)
        and raw.lower() in {"hold", "revisions needed", "additional info required"}
    ):
        expected = "Active"

    effective = _apply_status(repairs, row["STATUS_NORMALIZED"], expected)

    _apply_date(repairs, row, "FILE_DATE", _file_date_from_accela(d))

    permit_src = issued
    current_permit = row["PERMIT_DATE"]
    if effective in ("Active", "Final", "Inactive"):
        if permit_src is not pd.NaT and not pd.isna(permit_src):
            _apply_date(repairs, row, "PERMIT_DATE", permit_src)
    elif effective == "In Review":
        if not pd.isna(current_permit) and (
            permit_src is pd.NaT or pd.isna(permit_src)
        ):
            _clear_date(repairs, row, "PERMIT_DATE")

    if effective == "Final":
        _apply_date(repairs, row, "FINAL_DATE", _final_date_from_accela(d, tasks))
    else:
        _clear_date(repairs, row, "FINAL_DATE")


def _repair_accela_shell(row, d: dict, repairs: dict) -> None:
    _apply_date(repairs, row, "FILE_DATE", _file_date_from_accela(d))


# ── Main entry point ─────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Clearwater permit records using information from the raw DATA JSON.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Clearwater".  Must contain
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
        if schema.startswith("accela_shell"):
            _repair_accela_shell(row, d, repairs)
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
    filepath = os.path.join(
        my_data_path, "processed_data", "permits_fl_sample.parquet"
    )
    df = pd.read_parquet(filepath)
    city = df[
        (df["JURISDICTION"] == "Clearwater") & (df["STATE"] == "FL")
    ].copy()

    print(f"Clearwater records: {len(city):,}\n")
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

    print("\nSTATUS_NORMALIZED transitions (before → after):")
    transitions = (
        pd.DataFrame({
            "before": city["STATUS_NORMALIZED"].astype("object"),
            "after": repaired["STATUS_NORMALIZED"].astype("object"),
            "data_status": [
                (_safe_parse(x) or {}).get("status") for x in city["DATA"]
            ],
        })
        .groupby(["before", "after", "data_status"], dropna=False)
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

    both = repaired[
        repaired["PERMIT_DATE"].notna() & repaired["FINAL_DATE"].notna()
    ]
    n_inv = (
        both["PERMIT_DATE"].dt.normalize() > both["FINAL_DATE"].dt.normalize()
    ).sum()
    print(f"\nPERMIT_DATE > FINAL_DATE inversions after repair: {n_inv}")

    still_null = repaired[repaired["STATUS_NORMALIZED"].isna()]
    print(f"Remaining null STATUS_NORMALIZED: {len(still_null):,}")

    if agent_data_path:
        out_path = os.path.join(
            agent_data_path, "clearwater_repaired_sample.parquet"
        )
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote {out_path}")

"""Data repair for Manatee County (FL) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Manatee County DATA is an Accela Citizen Access payload. In this sample
all rows share the same top-level key set; a small shell subset has a
blank status:

  - accela:       status / date / tasks / search_data / more_details
  - accela_shell: same keys, but status (and search_data.Status) blank

Canonical mappings:
  - DATA.status (else search_data.Status)            → STATUS_NORMALIZED
  - DATA.date (else search_data.Date)                → FILE_DATE
  - earliest Permit Issuance ``Issued``; else
    Application ``Issue Permit``; else earliest
    ``Permit Issued Date`` under more_details        → PERMIT_DATE
  - latest Closure CofC/CO/Closed; Inspection
    CofC/Final Passed; Construction Work Completed;
    else Plan Re-Review ``Re-Review Complete``;
    else Fiscal Processing Complete                  → FINAL_DATE

Known issues repaired:
  - Unmapped pre-acceptance / review-verification /
    awaiting-documents / more-info / inspection-passed
    statuses left STATUS_NORMALIZED null → FILLED.
  - Stale STATUS_ORIGINAL: Closed/Complete labeled
    Active or In Review; Permit Issued labeled In
    Review; Canceled/Expired mislabeled → FIXED.
  - Approved permit/application extensions labeled
    Active with no issuance → FIXED to In Review.
  - More Info Required after Permit Issuance Issued
    upgraded to Active (permit already issued).
  - PERMIT_DATE missing on most Active/Final despite
    task / more_details issuance dates → FILLED.
  - FINAL_DATE almost entirely missing; a few Closed
    rows have stale FINAL_DATE → FILLED / FIXED from
    Closure / Inspection / Construction / Re-Review
    task events.

Not repairable from DATA:
  - 7 blank-status miscellaneous shells → STATUS /
    PERMIT / FINAL stay missing (FILE_DATE recoverable).
  - Some Active/Final rows have no issuance fields
    → PERMIT_DATE stays missing.
  - Complete - Sent to Clerk / a few Closed rows with
    no dated completion event → FINAL_DATE stays
    missing.
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


# ── Schema classification ────────────────────────────────────────────────────

def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    if not isinstance(data_dict, dict):
        return "unknown"

    keys = set(data_dict.keys())
    if "tasks" in keys or (
        "status" in keys and "search_data" in keys and "date" in keys
    ):
        if _accela_raw_status(data_dict):
            return "accela"
        return "accela_shell"
    return "unknown"


# ── Status maps ──────────────────────────────────────────────────────────────

_STATUS_MAP = {
    "Closed": "Final",
    "Complete": "Final",
    "Complete - Sent to Clerk": "Final",
    "CC Issued": "Final",
    "CO Issued": "Final",
    "Work Completed": "Final",
    "Pending Closure": "Final",
    "Permit Issued": "Active",
    "Work Started": "Active",
    # Issued + inspections done, but not yet closed / CofC.
    "Inspection Passed": "Active",
    # Plans / extensions approved but not issued.
    "Approved": "In Review",
    "In Review": "In Review",
    "Pre-Acceptance Review": "In Review",
    "New": "In Review",
    "Revisions Required": "In Review",
    "Review Verification": "In Review",
    "Awaiting Required Documents": "In Review",
    "Ready to Issue": "In Review",
    "More Info Required": "In Review",
    "Pending Approval": "In Review",
    "Canceled": "Inactive",
    "Cancelled": "Inactive",
    "Expired": "Inactive",
}

_STATUS_MAP_LOWER = {k.lower(): v for k, v in _STATUS_MAP.items()}


def _accela_raw_status(d: dict) -> str:
    status = d.get("status")
    if isinstance(status, str) and status.strip():
        return status.strip()
    sd = d.get("search_data") if isinstance(d.get("search_data"), dict) else {}
    sd_status = sd.get("Status")
    if isinstance(sd_status, str) and sd_status.strip():
        return sd_status.strip()
    return ""


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
    return _safe_to_datetime(sd.get("Date"))


def _permit_date_from_tasks(tasks: list):
    issued = _event_dates(tasks, {"Permit Issuance"}, {"Issued"})
    if issued:
        return min(issued)
    app_issue = _event_dates(tasks, {"Application"}, {"Issue Permit"})
    return min(app_issue) if app_issue else pd.NaT


def _permit_date_from_more_details(d: dict):
    """Earliest non-expiration 'Permit Issued Date*' under more_details."""
    dates = []

    def walk(obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                key = str(k).replace("\xa0", " ").strip().lower()
                if "permit issued date" in key and "expir" not in key:
                    dt = _safe_to_datetime(v)
                    if dt is not pd.NaT and not pd.isna(dt):
                        dates.append(dt)
                else:
                    walk(v)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)

    walk(d.get("more_details") or {})
    return min(dates) if dates else pd.NaT


def _permit_date_from_accela(d: dict, tasks: list):
    task_dt = _permit_date_from_tasks(tasks)
    if task_dt is not pd.NaT and not pd.isna(task_dt):
        return task_dt
    return _permit_date_from_more_details(d)


def _final_date_from_accela(tasks: list):
    """Latest completion / signoff event from Accela workflow tasks."""
    closure = _event_dates(
        tasks,
        {"Closure"},
        {
            "Certificate of Completion Issued",
            "Issue Certificate of Occupancy",
            "Issue Certificate of Completion",
            "Closed",
        },
    )
    inspection = _event_dates(
        tasks,
        {"Inspection"},
        {
            "Inspection Passed and CofC Issued",
            "Final Inspection Passed",
            "Inspection Passed – Pending Closure",
            "Inspection Passed - Pending Closure",
        },
    )
    construction = _event_dates(tasks, {"Construction"}, {"Work Completed"})
    rereview = _event_dates(
        tasks,
        {"Plan Re - Review Verification"},
        {"Re-Review Complete"},
    )
    fiscal = _event_dates(
        tasks,
        {"Fiscal Processing"},
        {"Fiscal Processing Complete"},
    )

    dates = closure + inspection + construction
    if dates:
        return max(dates)
    if rereview:
        return max(rereview)
    if fiscal:
        return max(fiscal)
    return pd.NaT


# ── Per-schema repair ────────────────────────────────────────────────────────

def _repair_accela(row, d: dict, repairs: dict) -> None:
    tasks = d.get("tasks") or []

    expected = _map_status(_accela_raw_status(d))
    issued = _permit_date_from_tasks(tasks)
    # Post-issuance "More Info Required" (etc.) is still an issued permit.
    if (
        expected == "In Review"
        and issued is not pd.NaT
        and not pd.isna(issued)
    ):
        expected = "Active"

    effective = _apply_status(repairs, row["STATUS_NORMALIZED"], expected)

    _apply_date(repairs, row, "FILE_DATE", _file_date_from_accela(d))

    permit_src = _permit_date_from_accela(d, tasks)
    current_permit = row["PERMIT_DATE"]
    if effective in ("Active", "Final", "Inactive"):
        if permit_src is not pd.NaT and not pd.isna(permit_src):
            _apply_date(repairs, row, "PERMIT_DATE", permit_src)
    elif effective == "In Review":
        # Unissued review rows should not carry an issuance date.
        if pd.isna(current_permit) or (
            permit_src is pd.NaT or pd.isna(permit_src)
        ):
            if not pd.isna(current_permit):
                _clear_date(repairs, row, "PERMIT_DATE")
        else:
            # Rare: md-only issuance while status remains In Review — keep
            # status, but prefer the real task issuance if it appears later.
            pass

    if effective == "Final":
        _apply_date(repairs, row, "FINAL_DATE", _final_date_from_accela(tasks))
    else:
        _clear_date(repairs, row, "FINAL_DATE")


def _repair_accela_shell(row, d: dict, repairs: dict) -> None:
    """Blank-status shells: only FILE_DATE is reliably recoverable."""
    _apply_date(repairs, row, "FILE_DATE", _file_date_from_accela(d))


# ── Main entry point ─────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Manatee County permit records using information from the raw DATA JSON.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Manatee County".  Must contain
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
        if schema == "accela":
            _repair_accela(row, d, repairs)
        elif schema == "accela_shell":
            _repair_accela_shell(row, d, repairs)

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
        (df["JURISDICTION"] == "Manatee County") & (df["STATE"] == "FL")
    ].copy()

    print(f"Manatee County records: {len(city):,}\n")
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
            agent_data_path, "manatee_county_repaired_sample.parquet"
        )
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote {out_path}")

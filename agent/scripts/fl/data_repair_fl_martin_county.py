"""Data repair for Martin County (FL) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Martin County DATA is an Accela Citizen Access payload (status / date /
tasks / search_data / more_details, usually with inspections and
fees_details). Canonical fields:

  - DATA.status (fallback search_data.Status)     → STATUS_NORMALIZED
  - DATA.date (fallback search_data.Application
    Date)                                         → FILE_DATE
  - Permit Issuance task ``Issued`` /
    ``Issued - Revised``                          → PERMIT_DATE
  - Certificate Issuance ``Certificate Issued`` /
    ``Closed Conditionally``; else Inspections
    ``Completed``; else Passed final-ish insp.    → FINAL_DATE

Key-set / content variants (INFERRED_SCHEMA):
  - accela_full:   inspections present + dated task events
  - accela_basic:  dated task events, no inspections list
  - accela_sparse: status/date/tasks present, little else
  - accela_shell:  blank status
  Suffixes ``_issued_finaled``, ``_issued``, ``_finaled``,
  ``_applied`` reflect which canonical dates are recoverable.

Known issues repaired:
  - DONE mislabeled as In Review (966) despite Certificate
    Issuance → FIXED to Final; FINAL_DATE FILLED from that
    certificate date; spurious PERMIT_DATE (certificate date
    used as issue date) cleared.
  - Closed-Certificate Issued lagging as Active / In Review /
    Inactive → FIXED to Final.
  - Issued lagging as In Review → FIXED to Active.
  - Unmapped statuses (COND, Closed Conditionally, Awaiting
    Resubmittals, CLOS, …) → FILLED.
  - PERMIT_DATE often set to Certificate Issued instead of
    Permit Issuance Issued → FIXED to Issued or cleared when
    no Issued event exists.
  - Missing PERMIT_DATE / FINAL_DATE filled from workflow tasks
    where available.

Not repairable from DATA:
  - FILE_DATE already matches DATA.date for every sample row.
  - Legacy DONE / Closed-CH 2019-45 / CNCL-era rows have no
    Permit Issuance Issued event → PERMIT_DATE stays missing
    after clearing the certificate-sourced value.
  - Phantom Certificate Issued dates on CNCL / VOID /
    Closed-Cancelled (often 02/17/2018) are not used as
    FINAL_DATE (Inactive family).
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

_INSP_PASS = {"PASS", "PASSED", "APPROVED", "DONE", "COMPLETE", "COMPLETED"}


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
    has_issued = _permit_date_from_accela(tasks)
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
    # Final — completed / certificate / closed-complete family
    "DONE": "Final",
    "Closed-Certificate Issued": "Final",
    "Closed-CH 2019-45": "Final",
    "Closed Conditionally": "Final",
    "COND": "Final",  # legacy Kiva abbreviation for closed conditionally
    "CLOS": "Final",
    # Active
    "Issued": "Active",
    "Permit Issued": "Active",
    # In Review
    "In Review": "In Review",
    "Waiting on Applicant": "In Review",
    "Payment Required": "In Review",
    "Ready for Issuance": "In Review",
    "OPEN": "In Review",
    "Awaiting Resubmittals": "In Review",
    "Resubmittal Required": "In Review",
    "Awaiting Plans": "In Review",
    # Inactive
    "Closed-Cancelled": "Inactive",
    "CNCL": "Inactive",
    "VOID": "Inactive",
    "Void": "Inactive",
    "EXP": "Inactive",
    "Expired": "Inactive",
    "Application Expired": "Inactive",
}

_STATUS_MAP_LOWER = {k.lower(): v for k, v in _STATUS_MAP.items()}


def _map_status(data_status: str, tasks: list) -> Optional[str]:
    if not data_status:
        return None

    # Bare "Closed" is ambiguous: plan-mod revisions with Issued - Revised
    # and no certificate behave like Active; certificate / CO closure is Final.
    if data_status.strip().lower() == "closed":
        cert_task = _event_dates(
            tasks,
            {"Certificate Issuance"},
            {"Certificate Issued", "Closed Conditionally"},
        )
        if cert_task:
            return "Final"
        issued = _permit_date_from_accela(tasks)
        if issued is not pd.NaT and not pd.isna(issued):
            return "Active"
        return "Final"

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
    for key in ("Application Date", "Date"):
        dt = _safe_to_datetime(sd.get(key))
        if dt is not pd.NaT and not pd.isna(dt):
            return dt
    intake = _event_dates(
        d.get("tasks") or [],
        {"Application", "Application Submittal"},
        {
            "Complete",
            "Plans Received",
            "Awaiting Plans",
            "Reviews Not Required",
        },
    )
    return min(intake) if intake else pd.NaT


def _permit_date_from_accela(tasks: list):
    dates = _event_dates(
        tasks,
        {"Permit Issuance"},
        {"Issued", "Issued - Revised"},
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


def _final_date_from_accela(d: dict, tasks: list):
    cert = _event_dates(
        tasks,
        {"Certificate Issuance"},
        {"Certificate Issued", "Closed Conditionally"},
    )
    if cert:
        return max(cert)

    completed = _event_dates(tasks, {"Inspections", "Inspection"}, {"Completed"})
    if completed:
        return max(completed)

    fin_insp = _final_inspection_dates(d)
    if fin_insp:
        return max(fin_insp)

    return pd.NaT


def _permit_looks_like_certificate(current_permit, cert_date, issued_date) -> bool:
    """True when PERMIT_DATE matches certificate date, not issuance."""
    if pd.isna(current_permit):
        return False
    if cert_date is pd.NaT or pd.isna(cert_date):
        return False
    if not _dates_equal(current_permit, cert_date):
        return False
    if issued_date is not pd.NaT and not pd.isna(issued_date):
        return not _dates_equal(current_permit, issued_date)
    return True


# ── Per-schema repair ────────────────────────────────────────────────────────

def _repair_accela(row, d: dict, repairs: dict) -> None:
    tasks = d.get("tasks") or []
    raw = _accela_raw_status(d)
    expected = _map_status(raw, tasks)
    issued = _permit_date_from_accela(tasks)
    final_src = _final_date_from_accela(d, tasks)

    # Issued permits stuck in review statuses upgrade to Active.
    if (
        expected == "In Review"
        and issued is not pd.NaT
        and not pd.isna(issued)
        and raw.lower() in {
            "in review",
            "waiting on applicant",
            "payment required",
            "ready for issuance",
            "resubmittal required",
            "awaiting resubmittals",
        }
    ):
        expected = "Active"

    effective = _apply_status(repairs, row["STATUS_NORMALIZED"], expected)

    _apply_date(repairs, row, "FILE_DATE", _file_date_from_accela(d))

    current_permit = row["PERMIT_DATE"]

    if issued is not pd.NaT and not pd.isna(issued):
        if effective in ("Active", "Final", "Inactive"):
            _apply_date(repairs, row, "PERMIT_DATE", issued)
        elif effective == "In Review" and not pd.isna(current_permit):
            # In Review should not keep a permit date.
            _clear_date(repairs, row, "PERMIT_DATE")
    else:
        # No Issued task: clear certificate-sourced PERMIT_DATE (common on DONE).
        if _permit_looks_like_certificate(current_permit, final_src, issued):
            _clear_date(repairs, row, "PERMIT_DATE")
        elif effective == "In Review" and not pd.isna(current_permit):
            _clear_date(repairs, row, "PERMIT_DATE")

    if effective == "Final":
        _apply_date(repairs, row, "FINAL_DATE", final_src)
    else:
        _clear_date(repairs, row, "FINAL_DATE")


def _repair_accela_shell(row, d: dict, repairs: dict) -> None:
    _apply_date(repairs, row, "FILE_DATE", _file_date_from_accela(d))


# ── Main entry point ─────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Martin County permit records using information from the raw DATA JSON.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Martin County".  Must contain
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
        (df["JURISDICTION"] == "Martin County") & (df["STATE"] == "FL")
    ].copy()

    print(f"Martin County records: {len(city):,}\n")
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
            agent_data_path, "martin_county_repaired_sample.parquet"
        )
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote {out_path}")

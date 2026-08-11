"""Data repair for Lee County (FL) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Lee County DATA is an Accela Citizen Access payload. Nearly every row has
``tasks``, ``status``, ``date``, ``search_data``, and ``more_details``.
Legacy converted records often ship empty task event histories
(``tasks_shell``).

Canonical mappings:
  - DATA.status                                              → STATUS_NORMALIZED
  - DATA.date (when date-like) / earliest Application event  → FILE_DATE
  - Earliest Permit Issuance Marked as Issued                → PERMIT_DATE
  - Latest Certificate Issuance Cert of Compliance /
    Occupancy / Partial CC Issued; else Inspections
    Certificate of Use Issued                                → FINAL_DATE

Known issues repaired:
  - STATUS_NORMALIZED derived from STATUS_ORIGINAL lags DATA.status
    (e.g. permit issued while Accela shows Closed-CC Issued) → FIXED.
  - Unmapped Closed-TMP / Resubmitted-In Review / Pending Inspections
    left STATUS_NORMALIZED null → FILLED.
  - Closed-Cert of Use Issued / Closed-PCC Issued mapped to Active
    instead of Final; Closed-Administrative / Closed-Not Effective /
    Closed-Old mapped to Final instead of Inactive → FIXED.
  - PERMIT_DATE frequently copied from the certificate / final date
    rather than Permit Issuance Issued → FIXED to Issued when present.
  - Missing PERMIT_DATE / FINAL_DATE filled from workflow events when
    status is Active / Final as appropriate.

Not repairable / left as-is:
  - ~1,100 Closed-Conversion (and similar) ``tasks_shell`` rows have no
    dated Permit Issuance or Certificate Issuance events → PERMIT_DATE
    and FINAL_DATE stay missing.
  - One legacy row stores a record ID in DATA.date (COM199803838) with
    empty Application events → FILE_DATE stays missing.
"""

from __future__ import annotations

import json
import math
import re
from typing import Optional

import numpy as np
import pandas as pd


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
    """Parse a date value, returning pd.NaT on failure / TBD / record IDs."""
    if val is None or (isinstance(val, str) and not str(val).strip()):
        return pd.NaT
    text = str(val).strip()
    if text.upper() == "TBD":
        return pd.NaT
    # Accela sometimes puts the record number in the date field.
    if re.match(r"^[A-Za-z]", text) and not re.search(r"\d{1,4}[-/]\d{1,2}[-/]\d{1,4}", text):
        if re.search(r"\d", text) and not re.search(r"[A-Za-z]{3,}", text.split()[0] if text.split() else text):
            # e.g. still try pandas on oddly formatted strings
            pass
        elif re.match(r"^[A-Z]{2,}\d", text, re.I):
            return pd.NaT
    try:
        return pd.to_datetime(val)
    except (ValueError, TypeError):
        return pd.NaT


def _dates_equal(a, b) -> bool:
    """Compare two datelike values at calendar-day resolution."""
    da = _safe_to_datetime(a)
    db = _safe_to_datetime(b)
    if da is pd.NaT or db is pd.NaT:
        return False
    return da.normalize() == db.normalize()


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
        yield (t.get("name") or "").strip(), t
        for st in t.get("subtasks") or []:
            if isinstance(st, dict):
                yield (st.get("name") or "").strip(), st


def _has_dated_task_event(tasks: list) -> bool:
    for _, t in _iter_task_nodes(tasks):
        for e in t.get("events") or []:
            if not isinstance(e, dict):
                continue
            _, on_val = _parse_event(e)
            if _safe_to_datetime(on_val) is not pd.NaT:
                return True
    return False


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())
    if "tasks" not in keys:
        return "unknown"
    tasks = data_dict.get("tasks") or []
    has_inspections = "inspections" in keys
    has_fees = "fees_details" in keys
    has_contacts = "contacts" in keys
    has_dated_event = _has_dated_task_event(tasks)

    if has_inspections and has_fees:
        return "tasks_full" if has_dated_event else "tasks_shell"
    if has_contacts and not has_inspections:
        return "tasks_contacts" if has_dated_event else "tasks_contacts_shell"
    if has_dated_event:
        return "tasks_basic"
    return "tasks_shell"


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
            if dt is not pd.NaT:
                dates.append(dt)
    return dates


# ── Status mapping ──────────────────────────────────────────────────────────

# DATA.status → STATUS_NORMALIZED (lookup is case-insensitive)
_STATUS_MAP = {
    # Final
    "Closed-CC Issued": "Final",
    "Closed-CO Issued": "Final",
    "Closed-Cert of Use Issued": "Final",
    "Closed-PCC Issued": "Final",
    "Closed-Completed": "Final",
    "Closed-Complete": "Final",
    "Closed-Conversion": "Final",
    "Closed-Revision Approved": "Final",
    "Closed-Approved": "Final",
    # Active
    "Permit Issued": "Active",
    "Inspections Ongoing": "Active",
    "Pending Inspections": "Active",
    # In Review
    "In Review": "In Review",
    "Waiting on Applicant": "In Review",
    "Ready-Documents Required": "In Review",
    "Documents Uploaded": "In Review",
    "Payment Required": "In Review",
    "Ready": "In Review",
    "Submitted": "In Review",
    "Resubmitted-In Review": "In Review",
    "Application Received": "In Review",
    # Inactive
    "Permit Expired": "Inactive",
    "Closed-Voided": "Inactive",
    "Closed-Withdrawn": "Inactive",
    "Closed-Abandoned": "Inactive",
    "Closed-Administrative": "Inactive",
    "Closed-Not Effective": "Inactive",
    "Closed-Old": "Inactive",
    "Closed-TMP": "Inactive",
}

_STATUS_MAP_LOWER = {k.lower(): v for k, v in _STATUS_MAP.items()}


def _map_status(data_status: Optional[str]) -> Optional[str]:
    if not data_status or not isinstance(data_status, str):
        return None
    key = data_status.strip()
    if not key:
        return None
    return _STATUS_MAP.get(key) or _STATUS_MAP_LOWER.get(key.lower())


_ISSUE_MARKS = {"issued"}
_FINAL_CERT_MARKS = {
    "cert of compliance issued",
    "cert of occupancy issued",
    "partial cc issued",
    "certificate of use issued",
}


def _file_date_from_data(d: dict):
    """Best available application / file date from Accela payload."""
    dt = _safe_to_datetime(d.get("date"))
    if dt is not pd.NaT:
        return dt

    app_dates = _event_dates(
        d.get("tasks") or [],
        {"Application"},
        lambda m: True,
    )
    if app_dates:
        return min(app_dates)
    return pd.NaT


def _permit_date_from_tasks(tasks: list):
    """Earliest Permit Issuance / Issued date."""
    issued = _event_dates(
        tasks,
        {"Permit Issuance"},
        lambda m: (m or "").strip().lower() in _ISSUE_MARKS,
    )
    return min(issued) if issued else pd.NaT


def _final_date_from_data(d: dict):
    """Latest certificate / CO-CC / cert-of-use finalization date."""
    tasks = d.get("tasks") or []
    cert_dates = _event_dates(
        tasks,
        {"Certificate Issuance"},
        lambda m: (m or "").strip().lower() in _FINAL_CERT_MARKS
        or (
            "cert" in (m or "").lower()
            and "issued" in (m or "").lower()
            and "void" not in (m or "").lower()
        ),
    )
    use_dates = _event_dates(
        tasks,
        {"Inspections", "Inspection"},
        lambda m: (m or "").strip().lower() == "certificate of use issued",
    )
    dates = cert_dates + use_dates
    return max(dates) if dates else pd.NaT


# ── Per-record repair logic ─────────────────────────────────────────────────

def _repair_record(row, d: dict, repairs: dict):
    """Populate *repairs* with corrected values for one Lee County record."""
    tasks = d.get("tasks") or []
    data_status = d.get("status")
    if isinstance(data_status, str):
        data_status = data_status.strip() or None
    else:
        data_status = None

    # -- STATUS_NORMALIZED --
    current_status = row["STATUS_NORMALIZED"]
    expected = _map_status(data_status)
    if expected is not None:
        if pd.isna(current_status):
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"
        elif current_status != expected:
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FIXED"

    effective_status = repairs.get("STATUS_NORMALIZED", current_status)

    # -- FILE_DATE --
    file_src = _file_date_from_data(d)
    if file_src is not pd.NaT:
        if pd.isna(row["FILE_DATE"]):
            repairs["FILE_DATE"] = file_src
            repairs["FILE_DATE_FLAG"] = "FILLED"
        elif not _dates_equal(row["FILE_DATE"], file_src):
            repairs["FILE_DATE"] = file_src
            repairs["FILE_DATE_FLAG"] = "FIXED"

    # -- PERMIT_DATE --
    issued = _permit_date_from_tasks(tasks)
    final_src = _final_date_from_data(d)
    current_permit = row["PERMIT_DATE"]

    if issued is not pd.NaT:
        if pd.isna(current_permit):
            if effective_status in ("Active", "Final"):
                repairs["PERMIT_DATE"] = issued
                repairs["PERMIT_DATE_FLAG"] = "FILLED"
        elif not _dates_equal(current_permit, issued):
            repairs["PERMIT_DATE"] = issued
            repairs["PERMIT_DATE_FLAG"] = "FIXED"
    elif (
        not pd.isna(current_permit)
        and final_src is not pd.NaT
        and _dates_equal(current_permit, final_src)
    ):
        # Upstream copied the certificate date into PERMIT_DATE with no
        # Permit Issuance / Issued event available to replace it.
        repairs["PERMIT_DATE"] = pd.NaT
        repairs["PERMIT_DATE_FLAG"] = "FIXED"

    # -- FINAL_DATE --
    current_final = row["FINAL_DATE"]
    if effective_status == "Final":
        if final_src is not pd.NaT:
            if pd.isna(current_final):
                repairs["FINAL_DATE"] = final_src
                repairs["FINAL_DATE_FLAG"] = "FILLED"
            elif not _dates_equal(current_final, final_src):
                repairs["FINAL_DATE"] = final_src
                repairs["FINAL_DATE_FLAG"] = "FIXED"
    elif not pd.isna(current_final):
        # Spurious FINAL_DATE on non-Final rows.
        repairs["FINAL_DATE"] = pd.NaT
        repairs["FINAL_DATE_FLAG"] = "FIXED"


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Lee County permit records using the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Lee County".  Must contain
        columns STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, FINAL_DATE,
        and DATA.

    Returns
    -------
    pd.DataFrame
        Copy of *df* with corrected field values, an INFERRED_SCHEMA column
        naming the DATA JSON sub-schema identified for each record, and new
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
    from dotenv import load_dotenv, find_dotenv

    load_dotenv(find_dotenv())
    MY_DATA_PATH = os.getenv("MY_DATA_PATH")
    filepath = os.path.join(MY_DATA_PATH, "processed_data", "permits_fl_sample.parquet")
    df = pd.read_parquet(filepath)
    lee = df[df["JURISDICTION"] == "Lee County"].copy()

    print(f"Lee County records: {len(lee):,}\n")

    repaired = data_repair(lee)

    print("INFERRED_SCHEMA:")
    for s, c in repaired["INFERRED_SCHEMA"].value_counts(dropna=False).items():
        print(f"  {str(s):24s}: {c:>4,}")
    print()

    for field in ["STATUS_NORMALIZED", "FILE_DATE", "PERMIT_DATE", "FINAL_DATE"]:
        flag_col = f"{field}_FLAG"
        n_filled = (repaired[flag_col] == "FILLED").sum()
        n_fixed = (repaired[flag_col] == "FIXED").sum()
        print(f"{field}:")
        print(f"  FILLED: {n_filled:>4,}   FIXED: {n_fixed:>4,}")

        before_missing = lee[field].isna().sum()
        after_missing = repaired[field].isna().sum()
        print(f"  Missing before: {before_missing:>4,}   Missing after: {after_missing:>4,}")
        print()

    print("STATUS_NORMALIZED distribution:")
    print("  Before:")
    for s, c in lee["STATUS_NORMALIZED"].value_counts(dropna=False).items():
        print(f"    {str(s):15s}: {c:>4,}")
    print("  After:")
    for s, c in repaired["STATUS_NORMALIZED"].value_counts(dropna=False).items():
        print(f"    {str(s):15s}: {c:>4,}")

    print("\nFILE_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FILE_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({n_has / max(len(sub), 1):.1%})")

    print("\nPERMIT_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["PERMIT_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({n_has / max(len(sub), 1):.1%})")

    print("\nFINAL_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FINAL_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({n_has / max(len(sub), 1):.1%})")

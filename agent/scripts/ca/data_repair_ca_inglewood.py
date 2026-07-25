"""Data repair for Inglewood permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

The Inglewood DATA column has two sub-schemas:

  - tasks:  Accela Citizen Access scrape with top-level keys 'tasks',
            'status', 'date', 'record_type', 'search_data', etc.  Task
            event keys have trailing spaces ('Marked as ', ' on '), same
            as Downey.  Covers Solar, Fire, and Pre-Sale record types.

  - flat:   Minimal listing scrape with only 'date', 'address',
            'parcel_no', 'permit_no', 'valuation', 'description'.  No
            status or workflow dates are available, so most flat records
            cannot be repaired from DATA alone.

Known issues repaired (tasks schema):
  - STATUS_NORMALIZED missing for "Report Sent" (→ Final), "Submitted"
    (→ In Review), and blank status (→ In Review).
  - STATUS_NORMALIZED incorrectly set to Final for 5 "Issued" Solar
    permits that still have Inspection TBD (→ Active); their FINAL_DATE
    values do not appear anywhere in DATA and are cleared.
  - PERMIT_DATE missing for Active/Final records that have a
    "Permit Issuance / Issued" task event, or (Pre-Sale Issued) a
    "Review Application / Approved" event, or (Finaled without issuance)
    a "Plans Coordination / Ready to Issue" event.
  - FINAL_DATE missing or stale for "Report Sent" Final records; set to
    the latest "Pre-Sale Report / Sent" event date.
  - Spurious FINAL_DATE on non-Final records (e.g. Submitted) cleared.
"""

import json
import math
from typing import Optional

import pandas as pd
import numpy as np


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
    """Parse a date value, returning pd.NaT on failure."""
    if val is None or (isinstance(val, str) and not val.strip()):
        return pd.NaT
    try:
        return pd.to_datetime(val)
    except (ValueError, TypeError):
        return pd.NaT


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())
    if "tasks" in keys:
        return "tasks"
    if keys <= {"date", "address", "parcel_no", "permit_no", "valuation", "description"} \
            or ({"date", "address"} <= keys and "status" not in keys and "tasks" not in keys):
        return "flat"
    return "unknown"


def _event_field(event: dict, *names: str):
    """Read an event field, tolerating leading/trailing spaces in keys."""
    targets = {n.strip() for n in names}
    for k, v in event.items():
        if k.strip() in targets:
            return v
    return None


def _first_event_date(tasks: list, task_name: str, marked_as: str):
    """Return the date of the first event matching task_name + marked_as."""
    for t in tasks:
        if t.get("name") != task_name:
            continue
        for e in t.get("events") or []:
            if _event_field(e, "Marked as") != marked_as:
                continue
            on_val = _event_field(e, "on")
            if on_val and str(on_val).strip() and str(on_val).strip() != "TBD":
                return _safe_to_datetime(on_val)
    return pd.NaT


def _last_event_date(tasks: list, task_name: str, marked_as: str):
    """Return the date of the latest event matching task_name + marked_as."""
    best = pd.NaT
    for t in tasks:
        if t.get("name") != task_name:
            continue
        for e in t.get("events") or []:
            if _event_field(e, "Marked as") != marked_as:
                continue
            on_val = _event_field(e, "on")
            if on_val and str(on_val).strip() and str(on_val).strip() != "TBD":
                dt = _safe_to_datetime(on_val)
                if dt is not pd.NaT and (best is pd.NaT or dt > best):
                    best = dt
    return best


# ── Status mapping ──────────────────────────────────────────────────────────

_STATUS_MAP = {
    "Finaled": "Final",
    "Report Sent": "Final",
    "Issued": "Active",
    "Expired": "Inactive",
    "Submitted": "In Review",
    "Ready to Issue": "In Review",
    "Plan Review": "In Review",
    "Pending": "In Review",
}


# ── Per-schema repair logic ─────────────────────────────────────────────────

def _repair_tasks(row, d: dict, repairs: dict):
    """Repair a tasks-schema (Accela Citizen Access) record."""
    tasks = d.get("tasks") or []
    data_status = d.get("status")
    if isinstance(data_status, str) and not data_status.strip():
        data_status = None

    # -- STATUS_NORMALIZED --
    current_status = row["STATUS_NORMALIZED"]
    if data_status is None:
        # Lone Fire Permit scrape with empty status and only TBD tasks.
        expected = "In Review"
    else:
        expected = _STATUS_MAP.get(data_status)

    if expected is not None:
        if pd.isna(current_status):
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"
        elif current_status != expected:
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FIXED"

    effective_status = repairs.get("STATUS_NORMALIZED", current_status)

    # -- FILE_DATE --
    # Already populated for all Inglewood sample rows.  For tasks records
    # FILE_DATE always equals DATA.date; leave as-is.

    # -- PERMIT_DATE --
    issued = _first_event_date(tasks, "Permit Issuance", "Issued")
    review_approved = _first_event_date(tasks, "Review Application", "Approved")
    ready_to_issue = _first_event_date(tasks, "Plans Coordination", "Ready to Issue")

    if not pd.isna(row["PERMIT_DATE"]):
        current_pd = _safe_to_datetime(row["PERMIT_DATE"])
        if issued is not pd.NaT and current_pd is not pd.NaT:
            if current_pd.normalize() != issued.normalize():
                repairs["PERMIT_DATE"] = issued
                repairs["PERMIT_DATE_FLAG"] = "FIXED"
    elif effective_status in ("Active", "Final"):
        if issued is not pd.NaT:
            repairs["PERMIT_DATE"] = issued
            repairs["PERMIT_DATE_FLAG"] = "FILLED"
        elif review_approved is not pd.NaT and data_status == "Issued":
            # Pre-Sale "Issued" cases have no Permit Issuance task; the
            # Review Application / Approved event is the issuance proxy
            # (always equals FILE_DATE / DATA.date in the sample).
            repairs["PERMIT_DATE"] = review_approved
            repairs["PERMIT_DATE_FLAG"] = "FILLED"
        elif ready_to_issue is not pd.NaT and data_status == "Finaled":
            # Some Finaled Solar permits omit the Permit Issuance event
            # but retain Plans Coordination / Ready to Issue.
            repairs["PERMIT_DATE"] = ready_to_issue
            repairs["PERMIT_DATE_FLAG"] = "FILLED"

    # -- FINAL_DATE --
    if effective_status == "Final":
        final_date = pd.NaT
        if data_status == "Report Sent":
            final_date = _last_event_date(tasks, "Pre-Sale Report", "Sent")
        if final_date is pd.NaT:
            final_date = _first_event_date(
                tasks, "Inspection", "Final Inspection Complete"
            )
        if final_date is pd.NaT:
            final_date = _last_event_date(tasks, "Inspection", "Completed")

        if final_date is not pd.NaT:
            if pd.isna(row["FINAL_DATE"]):
                repairs["FINAL_DATE"] = final_date
                repairs["FINAL_DATE_FLAG"] = "FILLED"
            else:
                current_fd = _safe_to_datetime(row["FINAL_DATE"])
                if current_fd is pd.NaT or current_fd.normalize() != final_date.normalize():
                    repairs["FINAL_DATE"] = final_date
                    repairs["FINAL_DATE_FLAG"] = "FIXED"
    elif not pd.isna(row["FINAL_DATE"]):
        # Spurious FINAL_DATE on non-Final records (e.g. Issued mislabeled
        # as Final, or Submitted rows with an inspection date copied in).
        repairs["FINAL_DATE"] = pd.NaT
        repairs["FINAL_DATE_FLAG"] = "FIXED"


def _repair_flat(row, d: dict, repairs: dict):
    """Repair a flat-schema record.

    Flat DATA has no status field and no workflow dates.  FILE_DATE is
    already populated.  The handful of flat rows that already have
    STATUS_NORMALIZED / PERMIT_DATE / FINAL_DATE cannot be validated or
    completed from DATA alone, so this is a no-op beyond schema tagging.
    """
    del row, d, repairs  # explicitly unused


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Inglewood permit records using information from the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Inglewood".  Must contain
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

        if schema == "tasks":
            _repair_tasks(row, d, repairs)
        elif schema == "flat":
            _repair_flat(row, d, repairs)

        for key, value in repairs.items():
            out.at[idx, key] = value

    return out


# ── CLI: run standalone to preview repair stats ─────────────────────────────

if __name__ == "__main__":
    import os
    from dotenv import load_dotenv

    load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))
    MY_DATA_PATH = os.getenv("MY_DATA_PATH")
    filepath = os.path.join(MY_DATA_PATH, "processed_data", "permits_la_sample.parquet")
    df = pd.read_parquet(filepath)
    inglewood = df[df["JURISDICTION"] == "Inglewood"].copy()

    print(f"Inglewood records: {len(inglewood):,}\n")

    repaired = data_repair(inglewood)

    print("INFERRED_SCHEMA:")
    for s, c in repaired["INFERRED_SCHEMA"].value_counts(dropna=False).items():
        print(f"  {str(s):20s}: {c:>4,}")
    print()

    for field in ["STATUS_NORMALIZED", "FILE_DATE", "PERMIT_DATE", "FINAL_DATE"]:
        flag_col = f"{field}_FLAG"
        n_filled = (repaired[flag_col] == "FILLED").sum()
        n_fixed = (repaired[flag_col] == "FIXED").sum()
        print(f"{field}:")
        print(f"  FILLED: {n_filled:>4,}   FIXED: {n_fixed:>4,}")

        before_missing = inglewood[field].isna().sum()
        after_missing = repaired[field].isna().sum()
        print(f"  Missing before: {before_missing:>4,}   Missing after: {after_missing:>4,}")
        print()

    print("STATUS_NORMALIZED distribution:")
    print("  Before:")
    for s, c in inglewood["STATUS_NORMALIZED"].value_counts(dropna=False).items():
        print(f"    {str(s):15s}: {c:>4,}")
    print("  After:")
    for s, c in repaired["STATUS_NORMALIZED"].value_counts(dropna=False).items():
        print(f"    {str(s):15s}: {c:>4,}")

    print("\nFINAL_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        if len(sub) == 0:
            continue
        n_has = sub["FINAL_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({n_has/len(sub):.1%})")

    print("\nPERMIT_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        if len(sub) == 0:
            continue
        n_has = sub["PERMIT_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({n_has/len(sub):.1%})")

    print("\nFILE_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        if len(sub) == 0:
            continue
        n_has = sub["FILE_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({n_has/len(sub):.1%})")

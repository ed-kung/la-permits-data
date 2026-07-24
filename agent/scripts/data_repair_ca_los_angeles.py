"""Data repair for Los Angeles (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Los Angeles DATA is a flat LADBS permit-detail payload.  All records share
the same core keys (Current Status, Permit Application Status History,
Permit Issued, Type, …).  Two sub-schemas are distinguished by whether a
real status history is present:

  - ladbs:            Permit Application Status History contains dated
                      workflow events (Submitted, Issued, Permit Finaled, …).
  - ladbs_no_history: History is the placeholder ``[['No Data Available.']]``
                      (or empty).  Only Current Status (and sometimes its
                      trailing date) is available.  Common for Completed /
                      Application Submittal / Ready to Issue rows.

Optional keys ``Issuing Office`` and ``Certificate of Occupancy`` appear
on some rows but do not change repair logic.

Known issues repaired:
  - STATUS_NORMALIZED missing on all ladbs_no_history rows and a few
    history rows (Application Submittal, Completed, Ready to Issue, …).
  - STATUS_NORMALIZED wrong when Current Status lags the latest history
    event (e.g. Active while history ends in Permit Finaled; In Review
    while history ends in Issued; Inactive terminal events ignored when
    Current Status is stale PC Approved).
  - FILE_DATE missing on ~70% of sample rows.  Prefer Submitted; else the
    earliest history date (internet / express permits often start at
    Issued with no Submitted event); else Current Status date for early
    Application Submittal rows.
  - PERMIT_DATE missing on a handful of issued Active/Final rows — fill
    from Permit Issued / first Issued history event.
  - FINAL_DATE missing for Final rows whose terminal event is Permit
    Closed / CofC Issued / CofO Issued / Completed — fill from the last
    final-like history event (or Current Status date when no history).
  - Spurious FINAL_DATE on non-Final rows cleared.

Not repairable from DATA:
  - FILE_DATE for Completed (and similar) ladbs_no_history rows whose only
    timestamp is the completion/status date — that date is not an
    application date.
  - PERMIT_DATE for Final/Active rows that were never issued
    (Permit Issued == "No"), including Completed grading/demolition rows.
"""

import json
import math
import re
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
    if val is None or (isinstance(val, str) and not str(val).strip()):
        return pd.NaT
    try:
        return pd.to_datetime(val)
    except (ValueError, TypeError):
        return pd.NaT


def _as_date(val):
    """Parse to a calendar date (datetime.date), or None on failure."""
    dt = _safe_to_datetime(val)
    if dt is pd.NaT or pd.isna(dt):
        return None
    return dt.date()


def _dates_equal(a, b) -> bool:
    da = _as_date(a)
    db = _as_date(b)
    if da is None or db is None:
        return False
    return da == db


_CURRENT_STATUS_RE = re.compile(
    r"^(.*?)\s+on\s+(\d{1,2}/\d{1,2}/\d{2,4})\s*$",
    re.DOTALL,
)
_PERMIT_ISSUED_RE = re.compile(
    r"Issued on\s+(\d{1,2}/\d{1,2}/\d{2,4})",
    re.IGNORECASE,
)


def _parse_current_status(cs) -> tuple[Optional[str], object]:
    """Return (status_token, status_date) from DATA['Current Status']."""
    if not cs or not isinstance(cs, str):
        return None, pd.NaT
    text = re.sub(r"\s+", " ", cs).strip()
    m = _CURRENT_STATUS_RE.match(text)
    if m:
        return m.group(1).strip(), _safe_to_datetime(m.group(2))
    # Trailing "on" with no usable date (common for Application Submittal)
    text = re.sub(r"\s+on\s*$", "", text).strip()
    return (text or None), pd.NaT


def _history_events(d: dict) -> list[tuple[str, object]]:
    """Return [(event_name, datetime), ...] from status history."""
    hist = d.get("Permit Application Status History") or []
    events = []
    for row in hist:
        if not isinstance(row, list) or len(row) < 2:
            continue
        name = str(row[0]).strip()
        if not name or name == "No Data Available.":
            continue
        events.append((name, _safe_to_datetime(row[1])))
    return events


def _parse_permit_issued(val) -> object:
    """Parse DATA['Permit Issued'] → issuance datetime or NaT."""
    if not val or not isinstance(val, str):
        return pd.NaT
    s = val.strip()
    if s.lower() == "no":
        return pd.NaT
    m = _PERMIT_ISSUED_RE.search(s)
    if m:
        return _safe_to_datetime(m.group(1))
    return pd.NaT


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    if _history_events(data_dict):
        return "ladbs"
    return "ladbs_no_history"


# ── Status mapping ──────────────────────────────────────────────────────────

_FINAL_TOKENS = {
    "Permit Finaled",
    "CofO Issued",
    "CofC Issued",
    "CofO Corrected",
    "Permit Closed",
    "Completed",
}

_ACTIVE_TOKENS = {
    "Issued",
    "CofO in Progress",
    "OK for CofC",
    "Re-Activate Permit",
}

_INACTIVE_TOKENS = {
    "Permit Expired",
    "Permit Expired-Status Void",
    "Permit Finaled-Status Void",
    "CofO Issued-Status Void",
    "Refund Completed",
    "Refund Closed",
    "Refund in Progress",
    "Application Withdrawn",
    "Permit Withdrawn",
    "Permit Revoked",
    "PC Expired",
    "Not Issued",
    "Reactivate - Status Void",
}

# Post-issuance clerical events that must not demote Active/Final status
# when they appear as the chronologically last history row.
_ADMIN_HISTORY_TOKENS = {
    "Building Plans Picked Up",
    "Green Plans Picked Up",
    "Electrical Plans Picked Up",
    "Mechanical Plans Picked Up",
    "Disabled Access Plans Picked Up",
    "Process Cleared",
}

# Early-stage Current Status tokens whose date is a usable FILE_DATE proxy
# when history is absent.
_FILE_DATE_STATUS_TOKENS = {
    "Application Submittal",
    "Application Pending",
    "Submitted",
    "Pending",
}


def _map_status_token(token: Optional[str]) -> Optional[str]:
    if not token:
        return None
    if token in _FINAL_TOKENS:
        return "Final"
    if token in _ACTIVE_TOKENS:
        return "Active"
    if token in _INACTIVE_TOKENS:
        return "Inactive"
    # All other LADBS workflow tokens (PC Approved, Corrections Issued,
    # Ready to Issue, Quality Review Completed, No Progress, …) → In Review
    return "In Review"


def _last_meaningful_history(events: list[tuple[str, object]]):
    """Last history event that carries lifecycle signal (skip plan pickups)."""
    for name, dt in reversed(events):
        if name in _ADMIN_HISTORY_TOKENS:
            continue
        return name, dt
    return None, pd.NaT


def _infer_status(d: dict) -> Optional[str]:
    """Infer STATUS_NORMALIZED from Current Status and history.

    When both Current Status and the last meaningful history event are
    available, prefer the one with the more recent date so stale Current
    Status values (e.g. PC Approved after Application Withdrawn) lose to
    the terminal history event.  Clerical post-issuance events such as
    ``Building Plans Picked Up`` are ignored so they cannot demote an
    Issued / Permit Finaled permit back to In Review.
    """
    token, status_dt = _parse_current_status(d.get("Current Status"))
    events = _history_events(d)
    last_name, last_dt = _last_meaningful_history(events)

    candidates: list[tuple[object, Optional[str]]] = []
    mapped_current = _map_status_token(token)
    if mapped_current is not None:
        candidates.append((status_dt, mapped_current))

    if last_name is not None:
        mapped_hist = _map_status_token(last_name)
        if mapped_hist is not None:
            candidates.append((last_dt, mapped_hist))

    dated = [(dt, st) for dt, st in candidates if dt is not pd.NaT and pd.notna(dt)]
    if dated:
        dated.sort(key=lambda x: x[0])
        return dated[-1][1]

    # No usable dates: prefer last meaningful history, else Current Status
    if last_name is not None:
        return _map_status_token(last_name)
    return mapped_current


def _file_date_from_data(d: dict) -> object:
    """Best available application / submittal date."""
    events = _history_events(d)
    for name, dt in events:
        if name == "Submitted" and dt is not pd.NaT and pd.notna(dt):
            return dt
    # No Submitted event — earliest history date (often Issued for
    # internet / express permits that never recorded a separate submittal).
    earliest = pd.NaT
    for _, dt in events:
        if dt is pd.NaT or pd.isna(dt):
            continue
        if earliest is pd.NaT or pd.isna(earliest) or dt < earliest:
            earliest = dt
    if earliest is not pd.NaT and pd.notna(earliest):
        return earliest

    token, status_dt = _parse_current_status(d.get("Current Status"))
    if token in _FILE_DATE_STATUS_TOKENS and status_dt is not pd.NaT and pd.notna(status_dt):
        return status_dt
    return pd.NaT


def _permit_date_from_data(d: dict) -> object:
    """Issuance date from Permit Issued field or first Issued history event."""
    issued = _parse_permit_issued(d.get("Permit Issued"))
    if issued is not pd.NaT and pd.notna(issued):
        return issued
    for name, dt in _history_events(d):
        if name == "Issued" and dt is not pd.NaT and pd.notna(dt):
            return dt
    return pd.NaT


def _final_date_from_data(d: dict) -> object:
    """Last final-like history event, else Current Status date when Final."""
    final_dt = pd.NaT
    for name, dt in _history_events(d):
        if name in _FINAL_TOKENS and dt is not pd.NaT and pd.notna(dt):
            final_dt = dt
    if final_dt is not pd.NaT and pd.notna(final_dt):
        return final_dt

    token, status_dt = _parse_current_status(d.get("Current Status"))
    if token in _FINAL_TOKENS and status_dt is not pd.NaT and pd.notna(status_dt):
        return status_dt
    return pd.NaT


# ── Per-record repair ───────────────────────────────────────────────────────

def _repair_record(row, d: dict, repairs: dict):
    """Repair one LADBS record (works for both schemas)."""
    # -- STATUS_NORMALIZED --
    current_status = row["STATUS_NORMALIZED"]
    expected = _infer_status(d)
    if expected is not None:
        if pd.isna(current_status):
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"
        elif current_status != expected:
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FIXED"

    effective_status = repairs.get("STATUS_NORMALIZED", current_status)

    # -- FILE_DATE --
    file_from_data = _file_date_from_data(d)
    if pd.isna(row["FILE_DATE"]):
        if file_from_data is not pd.NaT and pd.notna(file_from_data):
            repairs["FILE_DATE"] = file_from_data
            repairs["FILE_DATE_FLAG"] = "FILLED"
    elif file_from_data is not pd.NaT and pd.notna(file_from_data):
        # Prefer Submitted / earliest history when existing value disagrees
        events = _history_events(d)
        has_submitted = any(n == "Submitted" for n, _ in events)
        if has_submitted and not _dates_equal(row["FILE_DATE"], file_from_data):
            repairs["FILE_DATE"] = file_from_data
            repairs["FILE_DATE_FLAG"] = "FIXED"

    # -- PERMIT_DATE --
    permit_from_data = _permit_date_from_data(d)
    if pd.isna(row["PERMIT_DATE"]):
        if (
            effective_status in ("Active", "Final", "Inactive")
            and permit_from_data is not pd.NaT
            and pd.notna(permit_from_data)
        ):
            repairs["PERMIT_DATE"] = permit_from_data
            repairs["PERMIT_DATE_FLAG"] = "FILLED"
    elif permit_from_data is not pd.NaT and pd.notna(permit_from_data):
        if not _dates_equal(row["PERMIT_DATE"], permit_from_data):
            repairs["PERMIT_DATE"] = permit_from_data
            repairs["PERMIT_DATE_FLAG"] = "FIXED"

    # -- FINAL_DATE --
    final_from_data = _final_date_from_data(d)
    if effective_status == "Final":
        if pd.isna(row["FINAL_DATE"]):
            if final_from_data is not pd.NaT and pd.notna(final_from_data):
                repairs["FINAL_DATE"] = final_from_data
                repairs["FINAL_DATE_FLAG"] = "FILLED"
        elif final_from_data is not pd.NaT and pd.notna(final_from_data):
            if not _dates_equal(row["FINAL_DATE"], final_from_data):
                repairs["FINAL_DATE"] = final_from_data
                repairs["FINAL_DATE_FLAG"] = "FIXED"
    elif not pd.isna(row["FINAL_DATE"]):
        # Spurious final date on non-Final records
        repairs["FINAL_DATE"] = pd.NaT
        repairs["FINAL_DATE_FLAG"] = "FIXED"


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Los Angeles permit records using information from the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Los Angeles".  Must contain
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
    filepath = os.path.join(MY_DATA_PATH, "processed_data", "permits_la_sample.parquet")
    df = pd.read_parquet(filepath)
    la = df[(df["JURISDICTION"] == "Los Angeles") & (df["STATE"] == "CA")].copy()

    print(f"Los Angeles records: {len(la):,}\n")

    repaired = data_repair(la)

    print("INFERRED_SCHEMA:")
    for s, c in repaired["INFERRED_SCHEMA"].value_counts(dropna=False).items():
        print(f"  {s}: {c:,}")
    print()

    for field in ["STATUS_NORMALIZED", "FILE_DATE", "PERMIT_DATE", "FINAL_DATE"]:
        flag_col = f"{field}_FLAG"
        n_filled = (repaired[flag_col] == "FILLED").sum()
        n_fixed = (repaired[flag_col] == "FIXED").sum()
        print(f"{field}:")
        print(f"  FILLED: {n_filled:>4,}   FIXED: {n_fixed:>4,}")

        before_missing = la[field].isna().sum()
        after_missing = repaired[field].isna().sum()
        print(f"  Missing before: {before_missing:>4,}   Missing after: {after_missing:>4,}")
        print()

    print("STATUS_NORMALIZED distribution:")
    print("  Before:")
    for s, c in la["STATUS_NORMALIZED"].value_counts(dropna=False).items():
        print(f"    {str(s):15s}: {c:>4,}")
    print("  After:")
    for s, c in repaired["STATUS_NORMALIZED"].value_counts(dropna=False).items():
        print(f"    {str(s):15s}: {c:>4,}")

    print("\nFILE_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FILE_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({n_has / len(sub) if len(sub) else 0:.1%})")

    print("\nPERMIT_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["PERMIT_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({n_has / len(sub) if len(sub) else 0:.1%})")

    print("\nFINAL_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FINAL_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({n_has / len(sub) if len(sub) else 0:.1%})")

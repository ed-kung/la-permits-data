"""Data repair for Hermosa Beach (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Hermosa Beach DATA is an Accela Citizen Access scrape with two schemas:

  - tasks:  Full record with top-level keys ``status``, ``date``,
            ``tasks``, ``search_data``, etc. Workflow dates live in
            ``tasks`` events (e.g. ``Permit Issuance / Issued``,
            ``Inspections / Finaled``, ``Closed / Closed``).
  - search_data_only: Sparse stub with only ``search_data`` (no status
            or workflow events).

Canonical mappings from the tasks schema:
  - DATA.status                         → STATUS_NORMALIZED
  - DATA.date / Application Submittal   → FILE_DATE (already correct)
  - Permit Issuance / Issued            → PERMIT_DATE
      (fallback: Permit Application In Review / Issued;
       OTC proxy: Application Submittal / Approved - No PC Required;
       Approved revisions: Final Building Review / Approved)
  - Inspections / Finaled               → FINAL_DATE
      (fallback: Finaled - C of O, Closed / Closed,
       Certificate of Occupancy / Final CO Issued)

Known issues repaired:
  - 18 rows missing STATUS_NORMALIZED for uncommon Accela statuses
    (Finaled - Complete → Final; Expired Plan → Inactive;
    PREZONE / INQUIRY / CONCURNT → In Review).
  - 2 Final rows whose FINAL_DATE matches Inspections /
    Finaled - C of O but not the later Inspections / Finaled event
    → FIXED to Finaled.
  - 4 Final rows missing FINAL_DATE but with Closed / Closed → FILLED.
  - Spurious FINAL_DATE on non-Final rows (Issued, EXPIRED, Void,
    Ready to Issue) → cleared.
  - Missing PERMIT_DATE on Active/Final filled from Permit Application
    In Review / Issued, OTC Approved - No PC Required, or (Approved
    revisions only) Final Building Review / Approved.

Not repairable / left as-is:
  - FILE_DATE already matches DATA.date for all full-schema rows; none
    missing.
  - ~206 Historical Building Record Finaled stubs have empty ``tasks``
    and no issuance/finaling events → PERMIT_DATE / FINAL_DATE stay
    missing.
  - One search_data_only Solar stub has blank Status and no workflow
    → STATUS_NORMALIZED / PERMIT_DATE / FINAL_DATE stay missing.
  - Active Issued rows with Inspections / Finaled but Accela status
    still Issued keep STATUS_NORMALIZED=Active; FINAL_DATE cleared.
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
    if val is None or (isinstance(val, str) and not val.strip()) or val == "TBD":
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


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())
    if "tasks" in keys and "status" in keys:
        return "tasks"
    if keys == {"search_data"} or (keys <= {"search_data"} and "search_data" in keys):
        return "search_data_only"
    if "search_data" in keys and "tasks" not in keys:
        return "search_data_only"
    return "unknown"


def _first_event_date(tasks: list, task_name: str, marked_as: str) -> pd.Timestamp:
    """Return the date of the first event matching task_name + marked_as."""
    for t in tasks or []:
        if t.get("name") != task_name:
            continue
        for e in t.get("events", []):
            if e.get("Marked as") != marked_as:
                continue
            on_val = e.get("on", "")
            if on_val and on_val != "TBD":
                return _safe_to_datetime(on_val)
        break
    return pd.NaT


def _first_of_events(tasks: list, candidates: list) -> pd.Timestamp:
    """Return the first usable date from an ordered list of (task, marked_as)."""
    for task_name, marked_as in candidates:
        dt = _first_event_date(tasks, task_name, marked_as)
        if dt is not pd.NaT:
            return dt
    return pd.NaT


# ── Status mapping ──────────────────────────────────────────────────────────

# DATA.status → STATUS_NORMALIZED
_STATUS_MAP = {
    # Final
    "Finaled": "Final",
    "Finaled - Complete": "Final",
    # Active
    "Issued": "Active",
    "Approved": "Active",
    "Inspections": "Active",
    # Inactive
    "EXPIRED": "Inactive",
    "Expired Permit": "Inactive",
    "Expired Plan": "Inactive",
    "Void": "Inactive",
    "Withdrawn": "Inactive",
    "Denied": "Inactive",
    # In Review
    "Applied": "In Review",
    "Ready to Issue": "In Review",
    "In Review": "In Review",
    "In Plan Review": "In Review",
    "Pending": "In Review",
    "PENDING": "In Review",
    "PREZONE": "In Review",
    "INQUIRY": "In Review",
    "CONCURNT": "In Review",
}


_FINAL_DATE_CANDIDATES = [
    ("Inspections", "Finaled"),
    ("Inspections", "Finaled - C of O"),
    ("Closed", "Closed"),
    ("Certificate of Occupancy", "Final CO Issued"),
]


def _permit_date_from_tasks(tasks: list, data_status: Optional[str]) -> pd.Timestamp:
    """Issuance / approval date from Accela workflow events."""
    dt = _first_of_events(
        tasks,
        [
            ("Permit Issuance", "Issued"),
            ("Permit Application In Review", "Issued"),
            ("Application Submittal", "Approved - No PC Required"),
        ],
    )
    if dt is not pd.NaT:
        return dt
    # Revision / planning "Approved" records often never hit Permit Issuance;
    # Final Building Review / Approved is the closest approval date.
    if data_status == "Approved":
        return _first_event_date(tasks, "Final Building Review", "Approved")
    return pd.NaT


# ── Per-schema repair logic ─────────────────────────────────────────────────

def _repair_tasks(row, d: dict, repairs: dict):
    """Repair a tasks-schema (Accela Citizen Access) record."""
    tasks = d.get("tasks") or []
    data_status = d.get("status")
    if isinstance(data_status, str):
        data_status = data_status.strip() or None

    # -- STATUS_NORMALIZED --
    current_status = row["STATUS_NORMALIZED"]
    expected = _STATUS_MAP.get(data_status) if data_status else None
    if expected is not None:
        if pd.isna(current_status):
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"
        elif current_status != expected:
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FIXED"

    effective_status = repairs.get("STATUS_NORMALIZED", current_status)

    # -- FILE_DATE --
    # DATA.date is the record open/application date used upstream; already
    # populated and matching for all full-schema sample rows.
    file_src = _safe_to_datetime(d.get("date"))
    if file_src is pd.NaT:
        file_src = _first_event_date(tasks, "Application Submittal", "Applied")
    if file_src is not pd.NaT:
        if pd.isna(row["FILE_DATE"]):
            repairs["FILE_DATE"] = file_src
            repairs["FILE_DATE_FLAG"] = "FILLED"
        elif not _dates_equal(row["FILE_DATE"], file_src):
            repairs["FILE_DATE"] = file_src
            repairs["FILE_DATE_FLAG"] = "FIXED"

    # -- PERMIT_DATE --
    issued = _permit_date_from_tasks(tasks, data_status)
    if not pd.isna(row["PERMIT_DATE"]):
        if issued is not pd.NaT and not _dates_equal(row["PERMIT_DATE"], issued):
            # Only overwrite when the canonical issuance event disagrees.
            primary_issued = _first_event_date(tasks, "Permit Issuance", "Issued")
            if primary_issued is not pd.NaT and not _dates_equal(
                row["PERMIT_DATE"], primary_issued
            ):
                repairs["PERMIT_DATE"] = primary_issued
                repairs["PERMIT_DATE_FLAG"] = "FIXED"
    elif effective_status in ("Active", "Final") and issued is not pd.NaT:
        repairs["PERMIT_DATE"] = issued
        repairs["PERMIT_DATE_FLAG"] = "FILLED"

    # -- FINAL_DATE --
    final = _first_of_events(tasks, _FINAL_DATE_CANDIDATES)
    current_final = row["FINAL_DATE"]

    if effective_status == "Final":
        if final is not pd.NaT:
            if pd.isna(current_final):
                repairs["FINAL_DATE"] = final
                repairs["FINAL_DATE_FLAG"] = "FILLED"
            elif not _dates_equal(current_final, final):
                repairs["FINAL_DATE"] = final
                repairs["FINAL_DATE_FLAG"] = "FIXED"
    elif not pd.isna(current_final):
        # Spurious FINAL_DATE on non-Final rows (Issued still open in Accela,
        # Expired/Void, Ready to Issue with stale finaling events).
        repairs["FINAL_DATE"] = pd.NaT
        repairs["FINAL_DATE_FLAG"] = "FIXED"


def _repair_search_data_only(row, d: dict, repairs: dict):
    """Repair a search_data-only stub (usually no usable status/dates)."""
    sd = d.get("search_data") if isinstance(d.get("search_data"), dict) else {}
    raw_status = (sd.get("Status") or "").strip() or None
    expected = _STATUS_MAP.get(raw_status) if raw_status else None

    current_status = row["STATUS_NORMALIZED"]
    if expected is not None:
        if pd.isna(current_status):
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"
        elif current_status != expected:
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FIXED"

    # FILE_DATE from search_data.Date when missing
    sd_date = _safe_to_datetime(sd.get("Date"))
    if sd_date is not pd.NaT and pd.isna(row["FILE_DATE"]):
        repairs["FILE_DATE"] = sd_date
        repairs["FILE_DATE_FLAG"] = "FILLED"


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Hermosa Beach permit records using information from the raw DATA JSON
    column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Hermosa Beach".  Must contain
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
        if schema == "tasks":
            _repair_tasks(row, d, repairs)
        elif schema == "search_data_only":
            _repair_search_data_only(row, d, repairs)

        for key, value in repairs.items():
            out.at[idx, key] = value

    return out


# ── CLI: run standalone to preview repair stats ─────────────────────────────

if __name__ == "__main__":
    import os
    from dotenv import load_dotenv

    load_dotenv("/Users/ekung/projects/la-permits-data/.env")
    MY_DATA_PATH = os.getenv("MY_DATA_PATH")
    AGENT_DATA_PATH = os.getenv("AGENT_DATA_PATH")
    filepath = os.path.join(MY_DATA_PATH, "processed_data", "permits_la_sample.parquet")
    df = pd.read_parquet(filepath)
    city = df[(df["JURISDICTION"] == "Hermosa Beach") & (df["STATE"] == "CA")].copy()

    print(f"Hermosa Beach records: {len(city):,}\n")

    repaired = data_repair(city)

    if AGENT_DATA_PATH:
        out_path = os.path.join(
            AGENT_DATA_PATH, "processed_data", "permits_ca_hermosa_beach_repaired.parquet"
        )
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
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
        print(f"  Missing before: {before_missing:>4,}   Missing after: {after_missing:>4,}")
        print()

    print("STATUS_NORMALIZED distribution:")
    print("  Before:")
    for s, c in city["STATUS_NORMALIZED"].value_counts(dropna=False).items():
        print(f"    {str(s):15s}: {c:>4,}")
    print("  After:")
    for s, c in repaired["STATUS_NORMALIZED"].value_counts(dropna=False).items():
        print(f"    {str(s):15s}: {c:>4,}")

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
    print(f"  {n_has:>4,} / {len(repaired):>4,} ({n_has/len(repaired):.1%})")

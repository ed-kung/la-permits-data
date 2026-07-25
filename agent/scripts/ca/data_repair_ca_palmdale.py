"""Data repair for Palmdale (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Palmdale DATA is Accela Citizen Access with two sub-schemas:

  - tasks:  full ACA payload with top-level keys ``tasks``, ``date``,
            ``status``, ``search_data``, ``fees_details``, etc.  Status
            lives in DATA.status (often ALL-CAPS Accela codes).  Issuance
            dates live in task ``Issuance`` / ``Issued`` (or
            ``Registered`` for rental registrations).  Most pre-2023 rows
            have empty task event lists (historical migration).

  - search_data_only: listing scrape with only ``search_data``.  Status
            is empty and no workflow dates are available.

Canonical fields:
  - DATA.status                         → STATUS_NORMALIZED
  - DATA.date / search_data.Date        → FILE_DATE
  - Issuance / Issued (fallback:
    Issuance / Registered)              → PERMIT_DATE
  - (no usable finaling event in sample)→ FINAL_DATE

Known issues repaired:
  - STATUS_NORMALIZED missing for unmapped Accela codes (COC*, REGISTRD,
    VERIFIED, INSPCTED, 1st NOT., FORMAL, SCHLED) → FILLED (~188).
  - COMPLIED mapped upstream as In Review → Final; Registered mapped as
    In Review → Active (~40 FIXED).
  - Stale DATA.status ``In Review`` despite Issuance / Issued → Active.
  - PERMIT_DATE filled from Issuance / Issued or Issuance / Registered
    when missing for Active / Final rows with workflow history.

Not repairable / left as-is:
  - FILE_DATE already matches DATA.date (or search_data.Date) for all
    sample rows.
  - ~1,750 tasks rows (mostly pre-2023) have empty task events →
    PERMIT_DATE / FINAL_DATE stay missing.
  - Inspections events are TBD placeholders; no Final / Closed dates →
    FINAL_DATE remains 100% missing in the sample.
  - search_data_only rows (17) have no status or workflow dates.
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
    if val is None or (isinstance(val, str) and not str(val).strip()):
        return pd.NaT
    if str(val).strip() == "TBD":
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
    if "search_data" in keys and "tasks" not in keys:
        return "search_data_only"
    return "unknown"


def _event_field(event: dict, *names: str):
    """Read an event field, tolerating leading/trailing spaces in keys."""
    targets = {n.strip() for n in names}
    for k, v in event.items():
        if k.strip() in targets:
            return v
    return None


def _event_dates(tasks: list, task_name: str, marked_pred) -> list:
    """Return all datetimes for task_name events matching marked_pred(marked)."""
    dates = []
    for t in tasks or []:
        if t.get("name") != task_name:
            continue
        for e in t.get("events") or []:
            if not isinstance(e, dict):
                continue
            marked = _event_field(e, "Marked as")
            marked = (marked or "").strip() if isinstance(marked, str) else marked
            if not marked_pred(marked):
                continue
            on_val = _event_field(e, "on")
            dt = _safe_to_datetime(on_val)
            if dt is not pd.NaT:
                dates.append(dt)
    return dates


def _first_event_date(tasks: list, task_name: str, marked_as: str):
    dates = _event_dates(tasks, task_name, lambda m: m == marked_as)
    return min(dates) if dates else pd.NaT


def _dates_equal(a, b) -> bool:
    da = _safe_to_datetime(a)
    db = _safe_to_datetime(b)
    if da is pd.NaT or db is pd.NaT:
        return False
    return da.normalize() == db.normalize()


# ── Status mapping ──────────────────────────────────────────────────────────
# Keys are uppercase; DATA.status is normalized with .strip().upper() before
# lookup. Mixed-case Accela values (Final, Issued, Open, …) share the same map.

_STATUS_MAP = {
    # Final
    "COFO": "Final",
    "FINAL": "Final",
    "FINALED": "Final",
    "CLOSED": "Final",
    "COMPLIED": "Final",
    # Certificate of Compliance (rental registration cycle complete)
    "COC5": "Final",
    "COC3": "Final",
    "COC-3": "Final",
    "COC1": "Final",
    "COC-5": "Final",
    # Active
    "ISSUED": "Active",
    "APPROVED": "Active",
    "INSPCTED": "Active",
    "INSPECTED": "Active",
    "VERIFIED": "Active",
    "REGISTRD": "Active",
    "REGISTERED": "Active",
    # Inactive
    "EXPIRED": "Inactive",
    "PERMIT EXPIRED": "Inactive",
    "WITHDRWN": "Inactive",
    "WITHDRAWN": "Inactive",
    "CANCELED": "Inactive",
    "CANCELLED": "Inactive",
    # In Review
    "APPLIED": "In Review",
    "PENDING": "In Review",
    "IN REVIEW": "In Review",
    "OPEN": "In Review",  # early-stage applications (submittal / payment)
    "PAID": "In Review",
    "CORRECTIONS REQUIRED": "In Review",
    "ADDITIONAL INFO REQUIRED": "In Review",
    "PLANS APPROVED": "In Review",
    "FEES INVOICED": "In Review",
    "PAYMENT RECEIVED": "In Review",
    "TRANSFER": "In Review",
    "1ST NOT.": "In Review",
    "FORMAL": "In Review",
    "SCHLED": "In Review",
}


def _normalize_status_key(data_status: Optional[str]) -> Optional[str]:
    if not data_status or not isinstance(data_status, str):
        return None
    key = data_status.strip()
    return key.upper() if key else None


def _map_status(data_status: Optional[str]) -> Optional[str]:
    key = _normalize_status_key(data_status)
    if key is None:
        return None
    return _STATUS_MAP.get(key)


def _permit_date_from_tasks(tasks: list):
    """Issuance date: Issuance/Issued, else Issuance/Registered."""
    issued = _event_dates(tasks, "Issuance", lambda m: m == "Issued")
    if issued:
        return min(issued)
    registered = _event_dates(tasks, "Issuance", lambda m: m == "Registered")
    if registered:
        return min(registered)
    return pd.NaT


def _final_date_from_tasks(tasks: list):
    """Completion / sign-off date if Accela ever records one.

    Palmdale sample Inspections events are almost all TBD placeholders, so
    this usually returns NaT. Kept for forward-compatibility if Final /
    Closed events appear in fuller extracts.
    """
    for task_name, marked in (
        ("Inspections", "Final"),
        ("Inspections", "Finaled"),
        ("Inspections", "Final Inspection"),
        ("Inspections", "Final Inspection Complete"),
        ("Closed", "Close"),
        ("Closed", "Closed"),
    ):
        dt = _first_event_date(tasks, task_name, marked)
        if dt is not pd.NaT:
            return dt
    return pd.NaT


# ── Per-schema repair logic ─────────────────────────────────────────────────

def _repair_tasks(row, d: dict, repairs: dict):
    """Repair a tasks-schema Palmdale record."""
    tasks = d.get("tasks") or []
    data_status = d.get("status")
    if isinstance(data_status, str):
        data_status = data_status.strip() or None

    # -- STATUS_NORMALIZED --
    current_status = row["STATUS_NORMALIZED"]
    expected = _map_status(data_status)

    # Stale Accela status: still "In Review" after Issuance / Issued
    issued_dt = _first_event_date(tasks, "Issuance", "Issued")
    if (
        expected == "In Review"
        and issued_dt is not pd.NaT
        and _normalize_status_key(data_status) == "IN REVIEW"
    ):
        expected = "Active"

    if expected is not None:
        if pd.isna(current_status):
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"
        elif current_status != expected:
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FIXED"

    effective_status = repairs.get("STATUS_NORMALIZED", current_status)

    # -- FILE_DATE --
    apply = _safe_to_datetime(d.get("date"))
    if apply is pd.NaT:
        search = d.get("search_data") if isinstance(d.get("search_data"), dict) else {}
        apply = _safe_to_datetime(search.get("Date"))
    if apply is not pd.NaT:
        if pd.isna(row["FILE_DATE"]):
            repairs["FILE_DATE"] = apply
            repairs["FILE_DATE_FLAG"] = "FILLED"
        elif not _dates_equal(row["FILE_DATE"], apply):
            repairs["FILE_DATE"] = apply
            repairs["FILE_DATE_FLAG"] = "FIXED"

    # -- PERMIT_DATE --
    permit = _permit_date_from_tasks(tasks)
    if not pd.isna(row["PERMIT_DATE"]):
        if permit is not pd.NaT and not _dates_equal(row["PERMIT_DATE"], permit):
            # Prefer Issuance/Issued (or Registered) when present and mismatched
            issued_only = _event_dates(tasks, "Issuance", lambda m: m == "Issued")
            if issued_only and not _dates_equal(row["PERMIT_DATE"], min(issued_only)):
                repairs["PERMIT_DATE"] = min(issued_only)
                repairs["PERMIT_DATE_FLAG"] = "FIXED"
    elif effective_status in ("Active", "Final") and permit is not pd.NaT:
        repairs["PERMIT_DATE"] = permit
        repairs["PERMIT_DATE_FLAG"] = "FILLED"

    # -- FINAL_DATE --
    final = _final_date_from_tasks(tasks)
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
        # Spurious FINAL_DATE on non-Final rows
        repairs["FINAL_DATE"] = pd.NaT
        repairs["FINAL_DATE_FLAG"] = "FIXED"


def _repair_search_data_only(row, d: dict, repairs: dict):
    """search_data_only: no Accela status; FILE_DATE may come from Date."""
    search = d.get("search_data") if isinstance(d.get("search_data"), dict) else {}
    apply = _safe_to_datetime(search.get("Date"))
    if apply is not pd.NaT:
        if pd.isna(row["FILE_DATE"]):
            repairs["FILE_DATE"] = apply
            repairs["FILE_DATE_FLAG"] = "FILLED"
        elif not _dates_equal(row["FILE_DATE"], apply):
            repairs["FILE_DATE"] = apply
            repairs["FILE_DATE_FLAG"] = "FIXED"


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Palmdale permit records using information from the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Palmdale".  Must contain
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
    filepath = os.path.join(MY_DATA_PATH, "processed_data", "permits_la_sample.parquet")
    df = pd.read_parquet(filepath)
    city = df[(df["JURISDICTION"] == "Palmdale") & (df["STATE"] == "CA")].copy()

    print(f"Palmdale records: {len(city):,}\n")

    repaired = data_repair(city)

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
    print(f"  {n_has:>4,} / {len(repaired):>4,} ({n_has / len(repaired):.1%})")

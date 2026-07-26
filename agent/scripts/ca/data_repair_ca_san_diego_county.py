"""Data repair for San Diego County (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

San Diego County DATA is an Accela Citizen Access scrape with two key-set
variants (same repair logic):

  - tasks_full:   top-level keys include ``tasks``, ``status``, ``date``,
                  ``search_data``, plus ``contacts``, ``fees_details``,
                  ``inspections``, ``conditions``, etc.
  - tasks_sparse: same core keys but without contacts / fees_details /
                  inspections / related_records / conditions /
                  address_lines (1 Issued stub in the sample).

Canonical mappings:
  - DATA.status                              → STATUS_NORMALIZED
  - DATA.date / search_data['Opened Date']   → FILE_DATE
  - Permit Issuance / Issuance Complete      → PERMIT_DATE
      (fallback: more_details … EXPIRATION['Permit Issue Date'])
  - Under Construction - Inspections / Finaled → FINAL_DATE
      (fallbacks: Pass ``*FINAL*`` inspection Status Date;
       Case Closure / Complete; Complete / Complete;
       Status / Closed)

Known issues repaired:
  - STATUS_NORMALIZED derived from stale STATUS_ORIGINAL disagrees with
    DATA.status on 73 rows (e.g. Completed labeled Active; Closed labeled
    In Review / Active; Issued Expired labeled Active; Request Closed -
    Approved labeled Active) → FIXED.
  - One Recommended row with missing STATUS_NORMALIZED → FILLED as
    In Review.
  - Missing PERMIT_DATE on Active / Final rows that carry Permit Issue
    Date in more_details but no Issuance Complete event → FILLED.
  - Missing FINAL_DATE on Final / remapped-to-Final rows → FILLED from
    Finaled task events, Pass FINAL inspections, Case Closure, etc.
  - One spurious FINAL_DATE on an Active row → cleared (FIXED).

Not repairable / left as-is:
  - FILE_DATE already matches DATA.date for all sample rows.
  - Four rows with blank DATA.status and blank search_data Record Status
    → STATUS_NORMALIZED stays missing.
  - Hundreds of Closed enforcement / citation / planning shells and
    Completed stubs have empty task events and no FINAL inspection →
    FINAL_DATE stays missing.
  - Active / Final rows with neither Issuance Complete nor Permit Issue
    Date → PERMIT_DATE stays missing (common for enforcement / planning
    approvals that never issued a building permit).
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
    if str(val).strip() == "TBD":
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
        if {"contacts", "fees_details", "inspections"} & keys:
            return "tasks_full"
        return "tasks_sparse"
    if "search_data" in keys and "tasks" not in keys:
        return "search_data_only"
    return "unknown"


def _event_field(event: dict, *names: str):
    """Read an event field, tolerating spaces / trailing colons in keys."""
    targets = {n.strip().rstrip(":") for n in names}
    for k, v in event.items():
        if isinstance(k, str) and k.strip().rstrip(":") in targets:
            return v
    return None


def _event_dates(tasks: list, task_name: str, status_pred) -> list:
    """Return datetimes for task_name events matching status_pred(status)."""
    dates = []
    for t in tasks or []:
        if not isinstance(t, dict) or t.get("name") != task_name:
            continue
        for e in t.get("events") or []:
            if not isinstance(e, dict):
                continue
            status = _event_field(e, "Status")
            status = (status or "").strip() if isinstance(status, str) else status
            if not status_pred(status):
                continue
            on_val = _event_field(e, "on")
            dt = _safe_to_datetime(on_val)
            if dt is not pd.NaT:
                dates.append(dt)
    return dates


def _walk_find(obj, key: str):
    """Depth-first search for the first non-empty value of *key*."""
    if isinstance(obj, dict):
        if key in obj and obj[key] not in (None, "", []):
            return obj[key]
        for v in obj.values():
            found = _walk_find(v, key)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = _walk_find(item, key)
            if found is not None:
                return found
    return None


# ── Status mapping ──────────────────────────────────────────────────────────

# DATA.status (Title Case, as scraped) → STATUS_NORMALIZED
_STATUS_MAP = {
    # Final — completed / closed / recorded terminals
    "Completed": "Final",
    "Closed": "Final",
    "Kiva Legacy Closed": "Final",
    "Legacy Closed": "Final",
    "Kiva Legacy": "Final",
    "RECORDED": "Final",
    "Authorized": "Final",
    "Request Closed - Approved": "Final",
    # Active — issued / approved / open enforcement
    "Issued": "Active",
    "Issued About to Expire": "Active",
    "Active": "Active",
    "DIR Approved": "Active",
    "ZA Approved": "Active",
    "PC Approved": "Active",
    "Approved": "Active",
    "In Violation": "Active",
    "Sent to Revenue & Recovery": "Active",
    # Inactive — expired / withdrawn / denied
    "Issued Expired": "Inactive",
    "Issued Invalid Expired": "Inactive",
    "Expired": "Inactive",
    "Expired Permits-Stop INSP": "Inactive",
    "PC Expired": "Inactive",
    "PC Invalid Expired": "Inactive",
    "Withdrawn": "Inactive",
    "Cancelled": "Inactive",
    "Canceled": "Inactive",
    "DIR Denied": "Inactive",
    "Request Closed - Denied": "Inactive",
    # In Review — open / intake / conversion / unpaid citation
    "Open": "In Review",
    "In Review": "In Review",
    "Backfile Conversion": "In Review",
    "Paid": "In Review",
    "Under Investigation": "In Review",
    "Out to Applicant": "In Review",
    "Recommended": "In Review",
}


def _map_status(data_status: Optional[str]) -> Optional[str]:
    if not data_status or not isinstance(data_status, str):
        return None
    key = data_status.strip()
    return _STATUS_MAP.get(key) if key else None


def _data_status(d: dict) -> Optional[str]:
    status = d.get("status")
    if isinstance(status, str) and status.strip():
        return status.strip()
    sd = d.get("search_data") if isinstance(d.get("search_data"), dict) else {}
    rs = sd.get("Record Status")
    if isinstance(rs, str) and rs.strip():
        return rs.strip()
    return None


def _permit_date_from_tasks(tasks: list):
    """Earliest Permit Issuance / Issuance Complete date."""
    dates = _event_dates(tasks, "Permit Issuance", lambda s: s == "Issuance Complete")
    return min(dates) if dates else pd.NaT


def _permit_issue_date_from_details(d: dict):
    """Permit Issue Date under more_details Application Information / EXPIRATION."""
    md = d.get("more_details") if isinstance(d.get("more_details"), dict) else {}
    ai = md.get("Application Information")
    if isinstance(ai, dict):
        exp = ai.get("EXPIRATION")
        if isinstance(exp, dict) and exp.get("Permit Issue Date"):
            return _safe_to_datetime(exp.get("Permit Issue Date"))
    # Rare alternate nesting
    found = _walk_find(md, "Permit Issue Date")
    return _safe_to_datetime(found)


def _final_date_from_tasks(tasks: list):
    """Latest Under Construction - Inspections / Finaled."""
    finals = _event_dates(
        tasks, "Under Construction - Inspections", lambda s: s == "Finaled"
    )
    return max(finals) if finals else pd.NaT


def _final_date_from_inspections(d: dict):
    """Latest Pass FINAL inspection Status Date (not Last Update Date).

    Last Update Date is often a 2012-11-19 Accela migration stamp and must
    not be used as the completion date.
    """
    best = pd.NaT
    for insp in d.get("inspections") or []:
        if not isinstance(insp, dict):
            continue
        title = str(insp.get("Title") or "")
        status = str(insp.get("Status") or "").strip()
        if status != "Pass":
            continue
        if not re.search(r"\bFINAL\b", title, re.IGNORECASE):
            continue
        dt = _safe_to_datetime(insp.get("Status Date"))
        if dt is not pd.NaT and (best is pd.NaT or dt > best):
            best = dt
    return best


def _final_date_fallbacks(tasks: list):
    """Case Closure / Complete, then Complete / Complete, then Status / Closed."""
    for task_name, pred in (
        ("Case Closure", lambda s: s == "Complete"),
        ("Complete", lambda s: s == "Complete"),
        ("Status", lambda s: s == "Closed"),
    ):
        dates = _event_dates(tasks, task_name, pred)
        if dates:
            return max(dates)
    return pd.NaT


# ── Per-record repair logic ─────────────────────────────────────────────────

def _repair_record(row, d: dict, repairs: dict):
    """Populate *repairs* with corrected values for a San Diego County record."""
    tasks = d.get("tasks") or []
    raw_status = _data_status(d)
    expected = _map_status(raw_status)

    # -- STATUS_NORMALIZED --
    current_status = row["STATUS_NORMALIZED"]
    if expected is not None:
        if pd.isna(current_status):
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"
        elif current_status != expected:
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FIXED"

    effective_status = repairs.get("STATUS_NORMALIZED", current_status)

    # -- FILE_DATE (application / opened) --
    file_src = _safe_to_datetime(d.get("date"))
    if file_src is pd.NaT:
        sd = d.get("search_data") if isinstance(d.get("search_data"), dict) else {}
        file_src = _safe_to_datetime(sd.get("Opened Date"))
    if file_src is not pd.NaT:
        if pd.isna(row["FILE_DATE"]):
            repairs["FILE_DATE"] = file_src
            repairs["FILE_DATE_FLAG"] = "FILLED"
        elif not _dates_equal(row["FILE_DATE"], file_src):
            repairs["FILE_DATE"] = file_src
            repairs["FILE_DATE_FLAG"] = "FIXED"

    # -- PERMIT_DATE (issuance) --
    issued_task = _permit_date_from_tasks(tasks)
    issued_detail = _permit_issue_date_from_details(d)
    issued = issued_task if issued_task is not pd.NaT else issued_detail

    if issued_task is not pd.NaT:
        # Issuance Complete is canonical when present.
        if pd.isna(row["PERMIT_DATE"]):
            if effective_status in ("Active", "Final"):
                repairs["PERMIT_DATE"] = issued_task
                repairs["PERMIT_DATE_FLAG"] = "FILLED"
        elif not _dates_equal(row["PERMIT_DATE"], issued_task):
            repairs["PERMIT_DATE"] = issued_task
            repairs["PERMIT_DATE_FLAG"] = "FIXED"
    elif issued_detail is not pd.NaT:
        if pd.isna(row["PERMIT_DATE"]) and effective_status in ("Active", "Final"):
            repairs["PERMIT_DATE"] = issued_detail
            repairs["PERMIT_DATE_FLAG"] = "FILLED"
        # Do not FIXED from Permit Issue Date alone — it can disagree with a
        # correct existing PERMIT_DATE by a day or more on a few rows.

    # -- FINAL_DATE (finaled / closed / complete) --
    final = _final_date_from_tasks(tasks)
    if final is pd.NaT:
        final = _final_date_from_inspections(d)
    if final is pd.NaT:
        final = _final_date_fallbacks(tasks)

    current_final = row["FINAL_DATE"]
    if effective_status == "Final":
        if final is not pd.NaT:
            if pd.isna(current_final):
                repairs["FINAL_DATE"] = final
                repairs["FINAL_DATE_FLAG"] = "FILLED"
            elif not _dates_equal(current_final, final):
                # Only overwrite from the canonical Finaled task when it
                # disagrees; inspection Status Date can lag/lead Finaled.
                task_final = _final_date_from_tasks(tasks)
                if task_final is not pd.NaT and not _dates_equal(current_final, task_final):
                    repairs["FINAL_DATE"] = task_final
                    repairs["FINAL_DATE_FLAG"] = "FIXED"
    elif not pd.isna(current_final):
        repairs["FINAL_DATE"] = pd.NaT
        repairs["FINAL_DATE_FLAG"] = "FIXED"


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    San Diego County permit records using information from the raw DATA
    JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "San Diego County".  Must
        contain columns STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE,
        FINAL_DATE, and DATA.

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

    # Normalize date columns so FILLED/FIXED Timestamps do not mix with
    # datetime.date objects already present in the sample parquet.
    for col in ("FILE_DATE", "PERMIT_DATE", "FINAL_DATE"):
        out[col] = pd.to_datetime(out[col], errors="coerce")

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
    from collections import Counter
    from dotenv import load_dotenv

    load_dotenv("/Users/ekung/projects/la-permits-data/.env")
    MY_DATA_PATH = os.getenv("MY_DATA_PATH")
    AGENT_DATA_PATH = os.getenv("AGENT_DATA_PATH")
    filepath = os.path.join(MY_DATA_PATH, "processed_data", "permits_ca_sample.parquet")
    df = pd.read_parquet(filepath)
    city = df[
        (df["JURISDICTION"] == "San Diego County") & (df["STATE"] == "CA")
    ].copy()

    print(f"San Diego County records: {len(city):,}\n")

    repaired = data_repair(city)

    if AGENT_DATA_PATH:
        out_path = os.path.join(
            AGENT_DATA_PATH, "san_diego_county_repaired_sample.parquet"
        )
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

    print("\nSTATUS_NORMALIZED change summary (DATA.status → before → after):")
    change_counts: Counter = Counter()
    for idx in repaired.index:
        flag = repaired.at[idx, "STATUS_NORMALIZED_FLAG"]
        if flag not in ("FILLED", "FIXED"):
            continue
        d = _safe_parse(city.at[idx, "DATA"])
        cs = _data_status(d) if d else None
        before = city.at[idx, "STATUS_NORMALIZED"]
        after = repaired.at[idx, "STATUS_NORMALIZED"]
        change_counts[(flag, cs, str(before), after)] += 1
    for (flag, cs, before, after), n in sorted(change_counts.items(), key=lambda x: -x[1]):
        print(f"  {flag:6s} n={n:>3}  {cs!r:30s} {before:15s} → {after}")

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

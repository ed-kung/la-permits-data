"""Data repair for Redlands (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Redlands DATA is a CityView / Civic Access task-workflow scrape. Every
sample row shares the same top-level keys (CASE_STATUS, CASE_TYPE1,
Tasks, address, …). Content tags further distinguish issuance / final
workflow marks (INFERRED_SCHEMA):

  - cityview_issued_finaled: Permit Issued|Issue Permit ISSUED + final mark
  - cityview_issued:         issuance mark, no final mark
  - cityview_finaled_only:   final mark, no issuance
  - cityview_submittal_no_issue: submittal task(s), no issuance/final
  - cityview_other_tasks:    other dated tasks only
  - cityview_empty_tasks:    no usable tasks
  - cityview_rental_*:       Q-Rental / RENTAL* CASE_STATUS variants of
                             the above content tags

Canonical mappings:
  - DATA.CASE_STATUS (+ rare STATUS_ORIGINAL lag fixes) → STATUS_NORMALIZED
  - earliest Bldg Plan Submittal / Plans Submitted /
    Plan Submittal TASK_AVAIL (fallback earliest TASK_AVAIL) → FILE_DATE
  - earliest Permit Issued|Issue Permit with RESULT_CODE=ISSUED
    ACTUAL_END (fallback TASK_AVAIL)                     → PERMIT_DATE
  - latest successful final/close ACTUAL_END
    (Building - Final FINALED, Fire - Final FINALED,
     Print Rental/CO CLOSED, Sign Off / Plans Approved /
     Issue Permit and Close, etc.)                       → FINAL_DATE

Known issues repaired:
  - Null STATUS for RENTAL*, MYLARRCVD, APPROVEDC, CLOSEDR, FEECALC
    → FILLED from CASE_STATUS map.
  - FINALED / EXPIRED / WITHDRAWN / APPROVED rows whose upstream
    STATUS_NORMALIZED lagged (Active/In Review) → FIXED.
  - In Review CASE_STATUS with Permit Issued|Issue Permit ISSUED →
    upgraded to Active; Active/ISSUED with a strict final/close mark →
    Final.
  - FILE_DATE missing on ~39% of rows → FILLED from submittal /
    earliest task availability; near-miss stamps (≤90d from submittal)
    → FIXED.
  - PERMIT_DATE stamped from Permit Issued TASK_AVAIL instead of
    ACTUAL_END → FIXED; missing Active/Final/Inactive issuance → FILLED.
  - Spurious PERMIT_DATE on In Review without ISSUED → cleared.
  - FINAL_DATE stamped from Building-Final TASK_AVAIL (incl. NOTREADY /
    CORRECTIO / CONDITION) instead of FINALED ACTUAL_END → FIXED;
    Final missing FINAL → FILLED; spurious FINAL on non-Final → cleared.

Not repairable / left as-is:
  - A handful of Final shells (plan revisions / encroachment / fireworks)
    with CASE_STATUS FINALED/CLOSED but no successful final/close
    ACTUAL_END → FINAL_DATE stays missing.
  - Active / Final without Permit Issued|Issue Permit ISSUED
    (APPROVED plan-check shells) → PERMIT_DATE stays missing.
  - ~50 rows with empty / undated Tasks → FILE_DATE stays missing.
"""

from __future__ import annotations

import json
import math
from typing import Optional

import numpy as np
import pandas as pd


_MIN_YEAR = 1990
_MAX_YEAR = 2035

_SUBMITTAL_DESCS = {
    "Bldg Plan Submittal",
    "Plans Submitted",
    "Plan Submittal",
    "Request Submitted",
}

_ISSUE_DESCS = {"Permit Issued", "Issue Permit"}

# Priority 1–4 final/close task patterns: (task_desc_set or None, result_set)
# None desc set means match by RESULT / keyword heuristics in extractor.
_FINAL_PRIORITY = [
    # 1. Building final finaled
    ({"Building - Final", "Building - Final for Commercial"}, {"FINALED"}),
    # 2. Other department finals / building final closed
    ({"Fire - Final", "Building - Final"}, {"FINALED", "CLOSED"}),
    # 3. Explicit close / CO / rental / plans-approved finaled
    (
        {
            "Print Certificate of Occupancy",
            "Print Rental Permit",
            "Sign Off to Close Permit",
            "Send Approval Letter/Close Permit",
            "Issue Permit and Close",
            "Plans Approved",
            "Permit Closed",
            "Certificate of Compliance Recorded",
            "Building - Plans Approved",
            "Notify Client and Close Permit",
        },
        {"CLOSED", "APPROVEDC", "APPROVED", "FINALED", "YES", "YES-CLOSE"},
    ),
    # 4. Occupancy approved / work-order complete
    (
        {"Inspection - Occupancy", "Work Order Completed"},
        {"APPROVED", "YES-COMPLE", "COMPLETED"},
    ),
]


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
    """Parse a date value, returning pd.NaT on failure / Null / bad year."""
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return pd.NaT
    if isinstance(val, dict):
        return pd.NaT
    if isinstance(val, str):
        s = val.strip()
        if not s or s.upper() in {"NULL", "NONE", "TBD", "N/A", "NA"}:
            return pd.NaT
    try:
        dt = pd.to_datetime(val, errors="coerce")
    except (ValueError, TypeError):
        return pd.NaT
    if dt is pd.NaT or pd.isna(dt):
        return pd.NaT
    # Normalize to tz-naive Timestamp (avoid date/datetime mix for parquet).
    dt = pd.Timestamp(dt)
    if getattr(dt, "tzinfo", None) is not None:
        dt = dt.tz_convert("UTC").tz_localize(None)
    year = int(dt.year)
    if year < _MIN_YEAR or year > _MAX_YEAR:
        return pd.NaT
    return dt


def _dates_equal(a, b) -> bool:
    da = _safe_to_datetime(a)
    db = _safe_to_datetime(b)
    if da is pd.NaT or db is pd.NaT or pd.isna(da) or pd.isna(db):
        return False
    return da.normalize() == db.normalize()


def _tasks(d: dict) -> list:
    raw = d.get("Tasks") or []
    if not isinstance(raw, list):
        return []
    return [t for t in raw if isinstance(t, dict)]


def _task_dt(t: dict, prefer_actual: bool = True):
    """Best date on a task. Prefer ACTUAL_END when prefer_actual."""
    order = (
        ("ACTUAL_END", "TASK_AVAIL", "TARGET_END")
        if prefer_actual
        else ("TASK_AVAIL", "ACTUAL_END", "TARGET_END")
    )
    for key in order:
        dt = _safe_to_datetime(t.get(key))
        if dt is not pd.NaT:
            return dt
    return pd.NaT


def _result_code(t: dict) -> str:
    rc = t.get("RESULT_CODE")
    if rc is None:
        return ""
    return str(rc).strip().upper()


# ── Status mapping ───────────────────────────────────────────────────────────

_STATUS_MAP = {
    "FINALED": "Final",
    "CLOSED": "Final",
    "COMPLETE": "Final",
    "CLOSEDR": "Final",
    "APPROVEDC": "Final",
    "RENTALPASS": "Final",
    "ISSUED": "Active",
    "APPROVED": "Active",
    "EXPIRED": "Inactive",
    "CANCELED": "Inactive",
    "REMOVED": "Inactive",
    "DENIED": "Inactive",
    "WITHDRAWN": "Inactive",
    "SUBMITTED": "In Review",
    "PLAN CHECK": "In Review",
    "WAITING": "In Review",
    "EXTENDED": "In Review",
    "RESOLVED": "In Review",
    "FEECALC": "In Review",
    "MYLARRCVD": "In Review",
    "RENTALPAY": "In Review",
    "RENTALPAID": "In Review",
}


def _expected_status(d: dict) -> Optional[str]:
    cs = d.get("CASE_STATUS")
    if cs is None:
        return None
    mapped = _STATUS_MAP.get(str(cs).strip().upper())
    if mapped is None:
        return None
    # Workflow upgrades: CASE_STATUS can lag behind task events.
    if mapped == "In Review":
        if _has_final_mark(d):
            return "Final"
        if _has_issued(d):
            return "Active"
    if mapped == "Active" and _has_final_mark(d):
        # e.g. ISSUED CASE_STATUS but Building-Final already FINALED
        return "Final"
    return mapped


# ── Date extractors ──────────────────────────────────────────────────────────

def _preferred_file_date(d: dict):
    """Earliest submittal TASK_AVAIL; fallback earliest any TASK_AVAIL."""
    tasks = _tasks(d)
    sub_dates = []
    for t in tasks:
        td = t.get("TASK_DESC") or ""
        if td in _SUBMITTAL_DESCS:
            dt = _task_dt(t, prefer_actual=False)  # AVAIL first for filing
            if dt is not pd.NaT:
                sub_dates.append(dt)
    if sub_dates:
        return min(sub_dates)

    any_avail = []
    for t in tasks:
        dt = _safe_to_datetime(t.get("TASK_AVAIL"))
        if dt is not pd.NaT:
            any_avail.append(dt)
    if any_avail:
        return min(any_avail)
    return pd.NaT


def _preferred_permit_date(d: dict):
    """Earliest Permit Issued / Issue Permit with RESULT_CODE=ISSUED."""
    dates = []
    for t in _tasks(d):
        td = t.get("TASK_DESC") or ""
        if td not in _ISSUE_DESCS:
            continue
        if _result_code(t) != "ISSUED":
            continue
        dt = _task_dt(t, prefer_actual=True)
        if dt is not pd.NaT:
            dates.append(dt)
    return min(dates) if dates else pd.NaT


def _has_issued(d: dict) -> bool:
    return _preferred_permit_date(d) is not pd.NaT


def _preferred_final_date(
    d: dict,
    allow_encroachment_fallback: bool = True,
    max_priority: int = 4,
):
    """Latest successful final/close ACTUAL_END by priority bucket.

    ``max_priority`` limits which ``_FINAL_PRIORITY`` buckets are used
    (1-based). Status upgrades should pass ``max_priority=3`` so that
    Inspection - Occupancy APPROVED alone does not promote SUBMITTED
    business-license shells to Final.
    """
    tasks = _tasks(d)
    for pri, (desc_set, result_set) in enumerate(_FINAL_PRIORITY, start=1):
        if pri > max_priority:
            break
        dates = []
        for t in tasks:
            td = t.get("TASK_DESC") or ""
            if td not in desc_set:
                continue
            if _result_code(t) not in result_set:
                continue
            # Require ACTUAL_END for finals (AVAIL is often schedule-only).
            dt = _safe_to_datetime(t.get("ACTUAL_END"))
            if dt is not pd.NaT:
                dates.append(dt)
        if dates:
            return max(dates)

    if allow_encroachment_fallback:
        # Encroachment PASS- inspection ACTUAL_END when that is the only
        # close signal (common for FINALED encroachment OTC shells).
        enc = []
        for t in tasks:
            if (t.get("TASK_DESC") or "") != "Encroachment Permit Inspection":
                continue
            if _result_code(t) not in {"PASS-", "COMPLETED", "PASS"}:
                continue
            dt = _safe_to_datetime(t.get("ACTUAL_END"))
            if dt is not pd.NaT:
                enc.append(dt)
        if enc:
            return max(enc)

    # Fallback: any task whose desc suggests close and result is CLOSED /
    # FINALED / YES-CLOSE, or any YES-CLOSE result (recordation close).
    generic = []
    for t in tasks:
        td = (t.get("TASK_DESC") or "").lower()
        rc = _result_code(t)
        if rc == "YES-CLOSE":
            dt = _safe_to_datetime(t.get("ACTUAL_END"))
            if dt is not pd.NaT:
                generic.append(dt)
            continue
        if rc not in {"CLOSED", "FINALED", "APPROVEDC"}:
            continue
        if not any(k in td for k in ("close", "final", "certificate", "approved", "record")):
            continue
        dt = _safe_to_datetime(t.get("ACTUAL_END"))
        if dt is not pd.NaT:
            generic.append(dt)
    if generic:
        return max(generic)
    return pd.NaT


def _has_final_mark(d: dict) -> bool:
    """Strict final mark for status upgrades (no occupancy/encroachment-only)."""
    return (
        _preferred_final_date(
            d, allow_encroachment_fallback=False, max_priority=3
        )
        is not pd.NaT
    )


# ── Schema classification ────────────────────────────────────────────────────

def _classify_schema(d: Optional[dict]) -> str:
    if d is None:
        return "missing"

    cs = str(d.get("CASE_STATUS") or "").upper()
    ctype = str(d.get("CASE_TYPE1") or "")
    is_rental = cs.startswith("RENTAL") or ctype.startswith("Q-Rental")

    tasks = _tasks(d)
    has_iss = _has_issued(d)
    has_fin = _has_final_mark(d)
    has_sub = any((t.get("TASK_DESC") or "") in _SUBMITTAL_DESCS for t in tasks)
    has_dated = any(_task_dt(t) is not pd.NaT for t in tasks)

    if has_iss and has_fin:
        tag = "issued_finaled"
    elif has_iss:
        tag = "issued"
    elif has_fin:
        tag = "finaled_only"
    elif has_sub:
        tag = "submittal_no_issue"
    elif has_dated or tasks:
        tag = "other_tasks"
    else:
        tag = "empty_tasks"

    prefix = "cityview_rental" if is_rental else "cityview"
    return f"{prefix}_{tag}"


# ── Per-record repair ────────────────────────────────────────────────────────

def _repair_record(row, d: dict, repairs: dict) -> None:
    # -- STATUS_NORMALIZED --
    current_status = row["STATUS_NORMALIZED"]
    expected = _expected_status(d)
    if expected is not None:
        if pd.isna(current_status):
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"
        elif current_status != expected:
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FIXED"

    effective_status = repairs.get("STATUS_NORMALIZED", current_status)

    # -- FILE_DATE --
    file_src = _preferred_file_date(d)
    if file_src is not pd.NaT:
        if pd.isna(row["FILE_DATE"]):
            repairs["FILE_DATE"] = file_src
            repairs["FILE_DATE_FLAG"] = "FILLED"
        elif not _dates_equal(row["FILE_DATE"], file_src):
            cur = _safe_to_datetime(row["FILE_DATE"])
            # Only overwrite when the existing stamp is near the submittal
            # task (same filing episode). Large gaps often mean an older
            # parent application date vs a later resubmittal / extension.
            if cur is not pd.NaT and abs((file_src.normalize() - cur.normalize()).days) <= 90:
                repairs["FILE_DATE"] = file_src
                repairs["FILE_DATE_FLAG"] = "FIXED"

    # -- PERMIT_DATE --
    permit_src = _preferred_permit_date(d)
    current_permit = row["PERMIT_DATE"]

    if effective_status in ("Active", "Final", "Inactive"):
        if permit_src is not pd.NaT:
            if pd.isna(current_permit):
                repairs["PERMIT_DATE"] = permit_src
                repairs["PERMIT_DATE_FLAG"] = "FILLED"
            elif not _dates_equal(current_permit, permit_src):
                repairs["PERMIT_DATE"] = permit_src
                repairs["PERMIT_DATE_FLAG"] = "FIXED"
        elif (
            not pd.isna(current_permit)
            and effective_status == "Active"
            and str(d.get("CASE_STATUS") or "").upper() == "APPROVED"
        ):
            # APPROVED shells sometimes carry a fee/plan-check stamp as
            # PERMIT_DATE with no ISSUED task — clear the spurious stamp.
            repairs["PERMIT_DATE"] = pd.NaT
            repairs["PERMIT_DATE_FLAG"] = "FIXED"
    elif effective_status == "In Review":
        if not pd.isna(current_permit):
            if permit_src is pd.NaT:
                repairs["PERMIT_DATE"] = pd.NaT
                repairs["PERMIT_DATE_FLAG"] = "FIXED"
            elif not _dates_equal(current_permit, permit_src):
                repairs["PERMIT_DATE"] = permit_src
                repairs["PERMIT_DATE_FLAG"] = "FIXED"

    # -- FINAL_DATE --
    final_src = _preferred_final_date(d)
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
            # Existing FINAL has no successful final/close ACTUAL_END behind
            # it (often Building-Final TASK_AVAIL for NOTREADY/CORRECTIO).
            # Keep only if it still matches a preferred source; otherwise
            # leave as-is when we have no replacement (avoid wiping a date
            # we cannot improve). Prefer clearing when source is absent and
            # current looks like a schedule-only AVAIL of an incomplete final.
            incomplete_avail = False
            for t in _tasks(d):
                td = t.get("TASK_DESC") or ""
                rc = _result_code(t)
                if td in {"Building - Final", "Building - Final for Commercial"} and rc in {
                    "NOTREADY",
                    "CORRECTIO",
                    "CONDITION",
                    "NULL",
                    "",
                }:
                    if _dates_equal(current_final, t.get("TASK_AVAIL")):
                        incomplete_avail = True
                        break
            if incomplete_avail:
                repairs["FINAL_DATE"] = pd.NaT
                repairs["FINAL_DATE_FLAG"] = "FIXED"
    elif not pd.isna(current_final):
        repairs["FINAL_DATE"] = pd.NaT
        repairs["FINAL_DATE_FLAG"] = "FIXED"


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Redlands permit records using information from the raw DATA JSON.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Redlands".  Must contain
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

    # Homogenize date columns (sample often stores bare datetime.date).
    for col in ("FILE_DATE", "PERMIT_DATE", "FINAL_DATE"):
        if col in out.columns:
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

    for col in ("FILE_DATE", "PERMIT_DATE", "FINAL_DATE"):
        out[col] = pd.to_datetime(out[col], errors="coerce")

    return out


# ── CLI: run standalone to preview repair stats ─────────────────────────────

if __name__ == "__main__":
    import os
    from pathlib import Path
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[3] / ".env")
    MY_DATA_PATH = os.getenv("MY_DATA_PATH")
    AGENT_DATA_PATH = os.getenv("AGENT_DATA_PATH")
    filepath = os.path.join(MY_DATA_PATH, "processed_data", "permits_ca_sample.parquet")
    df = pd.read_parquet(filepath)
    city = df[(df["JURISDICTION"] == "Redlands") & (df["STATE"] == "CA")].copy()

    print(f"Redlands records: {len(city):,}\n")

    repaired = data_repair(city)

    if AGENT_DATA_PATH:
        out_dir = Path(AGENT_DATA_PATH) / "repaired"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "permits_ca_redlands_repaired.parquet"
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

    print("\nSTATUS_NORMALIZED_FLAG breakdown:")
    print(repaired["STATUS_NORMALIZED_FLAG"].value_counts(dropna=False).to_string())

    print("\nSTATUS transitions (where flagged):")
    flagged = repaired[repaired["STATUS_NORMALIZED_FLAG"].notna()].copy()
    flagged["before"] = city.loc[flagged.index, "STATUS_NORMALIZED"]
    print(
        flagged.groupby(
            [flagged["before"].fillna("(null)"), "STATUS_NORMALIZED", "STATUS_NORMALIZED_FLAG"]
        )
        .size()
        .rename("n")
        .reset_index()
        .to_string(index=False)
    )

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

    print("\nChronology checks (after repair):")
    f = pd.to_datetime(repaired["FILE_DATE"], errors="coerce")
    p = pd.to_datetime(repaired["PERMIT_DATE"], errors="coerce")
    fin = pd.to_datetime(repaired["FINAL_DATE"], errors="coerce")
    inv_fp = f.notna() & p.notna() & (p.dt.normalize() < f.dt.normalize())
    inv_pf = p.notna() & fin.notna() & (fin.dt.normalize() < p.dt.normalize())
    print(f"  PERMIT < FILE: {inv_fp.sum()}")
    print(f"  FINAL < PERMIT: {inv_pf.sum()}")

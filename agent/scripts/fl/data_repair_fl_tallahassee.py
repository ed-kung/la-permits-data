"""Data repair for Tallahassee (FL) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Tallahassee DATA is a City of Tallahassee / EnerGov-style case payload
with top-level keys ``Fees``, ``Tasks``, ``People``, ``Street``,
``Comments``, ``Location``, ``Payments``, ``Workflow``, ``Case Group``,
``Case Number``, ``Case Status``, ``Date Issued``, and optionally
``Case Type`` / ``Case Type Description`` / ``Project Name``.

Content variants (INFERRED_SCHEMA) are keyed by Case Group family and
which date evidence is present:

  - tlh_{family}_issued_finalinsp: Date Issued + FINAL AP inspection
  - tlh_{family}_issued:           Date Issued present
  - tlh_{family}_tasks:            completed Tasks / Workflow dates only
  - tlh_{family}_shell:            no usable dates
  - missing / unknown

Families: building, code, land_use, admin, fire, other.

Canonical mappings:
  - Case Status                         → STATUS_NORMALIZED
  - earliest Task Date Completed
    else earliest Workflow Assigned
    Date (fill only)                    → FILE_DATE
  - Date Issued else earliest ISSUE /
    OP_ISSUED task                      → PERMIT_DATE
  - last FINAL AP inspection else
    COMPLETE/COFOCOMP/CLOSED task else
    last passed final-ish inspection
    else last completed task (Final)    → FINAL_DATE

Known issues repaired:
  - ~107 unmapped Case Status values left STATUS_NORMALIZED null
    (OP ISSUED, ELIGIBLE, NOC HOLD, INVOICED2, CERTOFOCC, CE notices,
    COMP-FINE / MOW-FINE / CM-FINE, etc.) → FILLED.
  - COMPLIED code-enforcement rows labeled In Review → FIXED to Final.
  - COMPLETE / CERTOFOCC rows still labeled Active → FIXED to Final.
  - VOID / CANCELLED / EXPIRED / OP ISSUED mislabels → FIXED.
  - PERMIT_DATE that does not match Date Issued (inspection dates
    copied in) → FIXED to Date Issued.
  - Final rows missing FINAL_DATE filled from FINAL AP / complete /
    closed task milestones.
  - Non-Final rows incorrectly carrying FINAL_DATE are cleared.

Not repairable from DATA:
  - ~66 FILE_DATE shells with empty Tasks/Workflow and blank dates.
  - Many Final / Active rows (esp. CLOSED / COMPLIED code cases) have
    no Date Issued and no ISSUE task → PERMIT_DATE stays missing.
  - Some Final shells still lack any completion / inspection stamp
    → FINAL_DATE stays missing.
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
    r"final|certificate|cofo|certofocc|\bco\b|\bcc\b",
    re.I,
)
_PASS_RESULTS = {
    "FINAL AP",
    "AP",
    "AP_",
    "PA",
    "PA_",
    "APPROVED",
    "PASS",
    "PASSED",
    "COMPLETE",
    "COMPLETED",
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
    """Parse a date value, returning pd.NaT on failure or implausible year."""
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


def _case_family(d: dict) -> str:
    cg = (d.get("Case Group") or "").strip().lower()
    if "code enforcement" in cg:
        return "code"
    if "building" in cg:
        return "building"
    if "land use" in cg:
        return "land_use"
    if "administration" in cg:
        return "admin"
    if "fire" in cg:
        return "fire"
    return "other"


def _has_final_ap(d: dict) -> bool:
    for tsk in d.get("Tasks") or []:
        if not isinstance(tsk, dict):
            continue
        if (tsk.get("Task Result") or "").strip().upper() != "FINAL AP":
            continue
        if _safe_to_datetime(tsk.get("Date Completed")) is not pd.NaT:
            return True
    return False


def _has_completed_task_or_wf(d: dict) -> bool:
    for tsk in d.get("Tasks") or []:
        if isinstance(tsk, dict) and _safe_to_datetime(tsk.get("Date Completed")) is not pd.NaT:
            return True
    for w in d.get("Workflow") or []:
        if isinstance(w, dict) and _safe_to_datetime(w.get("Assigned Date")) is not pd.NaT:
            return True
    return False


def _classify_schema(d: Optional[dict]) -> str:
    if d is None:
        return "missing"
    if not isinstance(d, dict):
        return "unknown"
    if "Case Status" not in d and "Case Number" not in d:
        return "unknown"

    family = _case_family(d)
    issued = _safe_to_datetime(d.get("Date Issued"))
    has_issued = issued is not pd.NaT and not pd.isna(issued)

    if has_issued and _has_final_ap(d):
        return f"tlh_{family}_issued_finalinsp"
    if has_issued:
        return f"tlh_{family}_issued"
    if _has_completed_task_or_wf(d):
        return f"tlh_{family}_tasks"
    return f"tlh_{family}_shell"


# ── Status mapping ───────────────────────────────────────────────────────────

_STATUS_MAP = {
    # Final / closed / complied / certificate
    "COMPLETE": "Final",
    "CLOSED": "Final",
    "COMPLIED": "Final",
    "CERTOFOCC": "Final",
    "COMP-FINE": "Final",
    "MOW-FINE": "Final",
    "CM-FINE": "Final",
    # Active / issued
    "ISSUED": "Active",
    "APPROVED": "Active",
    "OP ISSUED": "Active",
    "NOC HOLD": "Active",
    "CONSTR": "Active",
    # In review / open enforcement / pre-issuance
    "PENDING": "In Review",
    "PLANCHECK": "In Review",
    "ELIGIBLE": "In Review",
    "INVOICED2": "In Review",
    "OP PENDING": "In Review",
    "REFERRED": "In Review",
    "CITY": "In Review",
    "VCN": "In Review",
    "NOTICE1": "In Review",
    "NOTICE2": "In Review",
    "NOV": "In Review",
    "CM-HEAR": "In Review",
    "ORDERS": "In Review",
    "SWO": "In Review",
    "LEGAL": "In Review",
    # Inactive
    "VOID": "Inactive",
    "EXPIRED": "Inactive",
    "WITHDRAWN": "Inactive",
    "CANCELLED": "Inactive",
    "DENIED": "Inactive",
}


def _raw_status(d: dict) -> str:
    return (d.get("Case Status") or "").strip().upper()


def _expected_status(d: dict) -> Optional[str]:
    return _STATUS_MAP.get(_raw_status(d))


# ── Date extractors ──────────────────────────────────────────────────────────

def _earliest_task_date(d: dict):
    dates = []
    for tsk in d.get("Tasks") or []:
        if not isinstance(tsk, dict):
            continue
        dt = _safe_to_datetime(tsk.get("Date Completed"))
        if dt is not pd.NaT and not pd.isna(dt):
            dates.append(dt)
    return min(dates) if dates else pd.NaT


def _earliest_workflow_date(d: dict):
    dates = []
    for w in d.get("Workflow") or []:
        if not isinstance(w, dict):
            continue
        dt = _safe_to_datetime(w.get("Assigned Date"))
        if dt is not pd.NaT and not pd.isna(dt):
            dates.append(dt)
    return min(dates) if dates else pd.NaT


def _earliest_issue_task(d: dict):
    """Earliest permit-issuance workflow task (ISSUE / OP_ISSUED)."""
    dates = []
    for tsk in d.get("Tasks") or []:
        if not isinstance(tsk, dict):
            continue
        code = (tsk.get("Task Code") or "").strip().upper()
        res = (tsk.get("Task Result") or "").strip().upper()
        if code == "ISSUE" and res == "ISSUE":
            dt = _safe_to_datetime(tsk.get("Date Completed"))
        elif code == "OP_ISSUED" and res in {"OP ISSUED", "ISSUE", "OP_ISSUED"}:
            dt = _safe_to_datetime(tsk.get("Date Completed"))
        else:
            continue
        if dt is not pd.NaT and not pd.isna(dt):
            dates.append(dt)
    return min(dates) if dates else pd.NaT


def _last_final_ap(d: dict):
    dates = []
    for tsk in d.get("Tasks") or []:
        if not isinstance(tsk, dict):
            continue
        if (tsk.get("Task Result") or "").strip().upper() != "FINAL AP":
            continue
        dt = _safe_to_datetime(tsk.get("Date Completed"))
        if dt is not pd.NaT and not pd.isna(dt):
            dates.append(dt)
    return max(dates) if dates else pd.NaT


def _last_passed_finalish_inspection(d: dict):
    dates = []
    for tsk in d.get("Tasks") or []:
        if not isinstance(tsk, dict):
            continue
        if (tsk.get("Task Type") or "").strip().upper() != "INSPECTION":
            continue
        res = (tsk.get("Task Result") or "").strip().upper()
        if res not in _PASS_RESULTS:
            continue
        desc = str(tsk.get("Task Desc.") or "")
        code = str(tsk.get("Task Code") or "")
        is_finalish = bool(_FINAL_INSP_RE.search(desc)) or (
            code.isdigit() and code.startswith("9")
        )
        if not is_finalish:
            continue
        dt = _safe_to_datetime(tsk.get("Date Completed"))
        if dt is not pd.NaT and not pd.isna(dt):
            dates.append(dt)
    return max(dates) if dates else pd.NaT


def _complete_or_closed_task(d: dict):
    dates = []
    for tsk in d.get("Tasks") or []:
        if not isinstance(tsk, dict):
            continue
        code = (tsk.get("Task Code") or "").strip().upper()
        res = (tsk.get("Task Result") or "").strip().upper()
        if code in {"COMPLETE", "COFOCOMP"} and res in {
            "COMPLETE_", "COMPLETE", "COFO", "CERTOFOCC",
        }:
            dt = _safe_to_datetime(tsk.get("Date Completed"))
        elif code in {"CLOSED", "BI_CLOSED"} and res in {"CLOSED", "COMPLETE_", "COMPLETE"}:
            dt = _safe_to_datetime(tsk.get("Date Completed"))
        else:
            continue
        if dt is not pd.NaT and not pd.isna(dt):
            dates.append(dt)
    return max(dates) if dates else pd.NaT


def _last_completed_task(d: dict):
    dates = []
    for tsk in d.get("Tasks") or []:
        if not isinstance(tsk, dict):
            continue
        dt = _safe_to_datetime(tsk.get("Date Completed"))
        if dt is not pd.NaT and not pd.isna(dt):
            dates.append(dt)
    return max(dates) if dates else pd.NaT


def _permit_date_candidate(d: dict):
    issued = _safe_to_datetime(d.get("Date Issued"))
    if issued is not pd.NaT and not pd.isna(issued):
        return issued
    return _earliest_issue_task(d)


def _final_date_candidate(d: dict):
    for getter in (
        _last_final_ap,
        _complete_or_closed_task,
        _last_passed_finalish_inspection,
        _last_completed_task,
    ):
        cand = getter(d)
        if cand is not pd.NaT and not pd.isna(cand):
            return cand
    return pd.NaT


# ── Per-record repair ────────────────────────────────────────────────────────

def _apply_date(repairs: dict, row, field: str, candidate, *, allow_fill: bool = True,
                allow_fix: bool = True) -> None:
    cand = _safe_to_datetime(candidate)
    if cand is pd.NaT or pd.isna(cand):
        return
    current = row[field]
    if pd.isna(current):
        if allow_fill:
            repairs[field] = cand
            repairs[f"{field}_FLAG"] = "FILLED"
    elif allow_fix and not _dates_equal(current, cand):
        repairs[field] = cand
        repairs[f"{field}_FLAG"] = "FIXED"


def _clear_date(repairs: dict, row, field: str) -> None:
    current = repairs.get(field, row[field])
    if pd.isna(current):
        return
    repairs[field] = pd.NaT
    repairs[f"{field}_FLAG"] = "FIXED"


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

    # -- FILE_DATE ← earliest task else earliest workflow (fill only) --
    # Upstream FILE_DATE often post-dates the first automated task; that
    # applied date is not stored separately in DATA, so do not overwrite.
    if pd.isna(row["FILE_DATE"]):
        file_cand = _earliest_task_date(d)
        if file_cand is pd.NaT or pd.isna(file_cand):
            file_cand = _earliest_workflow_date(d)
        _apply_date(repairs, row, "FILE_DATE", file_cand, allow_fix=False)

    # -- PERMIT_DATE ← Date Issued else ISSUE / OP_ISSUED task --
    permit_cand = _permit_date_candidate(d)
    if permit_cand is not pd.NaT and not pd.isna(permit_cand):
        _apply_date(repairs, row, "PERMIT_DATE", permit_cand)
    elif effective_status == "In Review" and not pd.isna(row["PERMIT_DATE"]):
        # No issuance evidence for an In Review row → clear spurious date.
        _clear_date(repairs, row, "PERMIT_DATE")

    # -- FINAL_DATE --
    if effective_status == "Final":
        _apply_date(repairs, row, "FINAL_DATE", _final_date_candidate(d))
    else:
        _clear_date(repairs, row, "FINAL_DATE")


# ── Main entry point ─────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Tallahassee permit records using information from the raw DATA JSON.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Tallahassee". Must contain
        columns STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, FINAL_DATE,
        and DATA.

    Returns
    -------
    pd.DataFrame
        Copy of *df* with corrected field values, an INFERRED_SCHEMA
        column naming the DATA JSON sub-schema identified for each
        record, and flag columns: STATUS_NORMALIZED_FLAG, FILE_DATE_FLAG,
        PERMIT_DATE_FLAG, FINAL_DATE_FLAG. Flag values are "FILLED"
        (was missing, now populated) or "FIXED" (had an incorrect value,
        now corrected).
    """
    out = df.copy()

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
        if d is None or schema in {"missing", "unknown"}:
            continue

        repairs: dict = {}
        _repair_record(row, d, repairs)
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
    filepath = os.path.join(my_data_path, "processed_data", "permits_fl_sample.parquet")
    df = pd.read_parquet(filepath)
    city = df[
        (df["JURISDICTION"] == "Tallahassee") & (df["STATE"] == "FL")
    ].copy()

    print(f"Tallahassee records: {len(city):,}\n")
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
        print(f"  Missing before: {before_missing:>4,}   Missing after: {after_missing:>4,}")
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

    both = repaired[repaired["PERMIT_DATE"].notna() & repaired["FINAL_DATE"].notna()]
    n_inv = (
        both["PERMIT_DATE"].dt.normalize() > both["FINAL_DATE"].dt.normalize()
    ).sum()
    print(f"\nPERMIT_DATE > FINAL_DATE inversions after repair: {n_inv}")

    fd = repaired["FILE_DATE"]
    pd_ = repaired["PERMIT_DATE"]
    both_fp = repaired[fd.notna() & pd_.notna()]
    n_fp_inv = (
        both_fp["FILE_DATE"].dt.normalize() > both_fp["PERMIT_DATE"].dt.normalize()
    ).sum()
    print(f"FILE_DATE > PERMIT_DATE inversions after repair: {n_fp_inv}")

    still_null = repaired[repaired["STATUS_NORMALIZED"].isna()]
    print(f"\nRemaining null STATUS_NORMALIZED: {len(still_null):,}")
    if len(still_null):
        print(still_null["INFERRED_SCHEMA"].value_counts().to_string())

    # Sanity vs portal sources
    n_issue_mismatch = 0
    n_issue = 0
    n_file_filled_ok = 0
    n_final_mm = 0
    for idx in repaired.index:
        d = _safe_parse(repaired.at[idx, "DATA"]) or {}
        issued = _safe_to_datetime(d.get("Date Issued"))
        if issued is not pd.NaT and not pd.isna(issued):
            n_issue += 1
            if not _dates_equal(repaired.at[idx, "PERMIT_DATE"], issued):
                n_issue_mismatch += 1
        if repaired.at[idx, "STATUS_NORMALIZED"] == "Final":
            final_cand = _final_date_candidate(d)
            final_val = repaired.at[idx, "FINAL_DATE"]
            if (
                final_cand is not pd.NaT and not pd.isna(final_cand)
                and not pd.isna(final_val)
                and not _dates_equal(final_val, final_cand)
            ):
                n_final_mm += 1

    print(
        f"PERMIT_DATE != Date Issued (when Date Issued present): "
        f"{n_issue_mismatch} (of {n_issue})"
    )
    print(f"Final FINAL_DATE != candidate (when both present): {n_final_mm}")

    active_final = repaired["STATUS_NORMALIZED"].isin(["Active", "Final"])
    final = repaired["STATUS_NORMALIZED"] == "Final"
    print(f"\nAny missing FILE_DATE: {repaired['FILE_DATE'].isna().sum()}")
    print(
        f"Active/Final missing PERMIT_DATE: "
        f"{(active_final & repaired['PERMIT_DATE'].isna()).sum()}"
    )
    print(f"Final missing FINAL_DATE: {(final & repaired['FINAL_DATE'].isna()).sum()}")

    if agent_data_path:
        out_dir = Path(agent_data_path) / "repaired"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "permits_fl_tallahassee_repaired.parquet"
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote repaired sample → {out_path}")

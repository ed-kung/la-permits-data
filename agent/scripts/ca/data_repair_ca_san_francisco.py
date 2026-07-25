"""Data repair for San Francisco (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

San Francisco DATA is a DBI permit-portal scrape. All rows have
`processing_status` (list of {date, stage, comments}). Two sub-schemas:

  - with_detail:  also has agents / inspections / addenda_details
                  (processing_status ordered chronologically)
  - header_only:  status + address/description only
                  (processing_status ordered reverse-chronologically)

Canonical mappings (by calendar date, not array position):
  - chronologically latest processing_status.stage → STATUS_NORMALIZED
      (COMPLETE wins over later Auto-expire EXPIRED; hard cancels win)
  - FILED / FILING / TRIAGE (else earliest stage date) → FILE_DATE
  - earliest ISSUED (else APPROVED)                   → PERMIT_DATE
  - latest COMPLETE (else final inspection approved)  → FINAL_DATE

Known issues repaired:
  - STATUS_ORIGINAL / STATUS_NORMALIZED used the last array element,
    which is the *earliest* stage on header_only rows → ~518 status
    FIXES (COMPLETE→Final, EXPIRED→Inactive, ISSUED→Active, etc.)
    plus 5 triage NaNs → FILLED as In Review.
  - Missing FILE_DATE on header_only rows with no FILED stage → FILLED
    from ISSUED (or earliest available stage) as application proxy.
  - Missing FINAL_DATE on Final (incl. status-corrected) rows with
    COMPLETE → FILLED; spurious FINAL_DATE on non-Final → cleared.
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
    try:
        return pd.to_datetime(val)
    except (ValueError, TypeError):
        return pd.NaT


def _dates_equal(a, b) -> bool:
    da = _safe_to_datetime(a)
    db = _safe_to_datetime(b)
    if da is pd.NaT or db is pd.NaT:
        return False
    return da.normalize() == db.normalize()


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())
    if "processing_status" not in keys:
        return "unknown"
    if keys & {"agents", "inspections", "addenda_details", "special_inspections"}:
        return "with_detail"
    return "header_only"


# ── Stage → status mapping ───────────────────────────────────────────────────

# Tie-break priority when multiple stages share the same calendar date.
_STAGE_PRIORITY = {
    "REVOKED": 100,
    "CANCELLED": 99,
    "CANCELED": 99,
    "WITHDRAWN": 98,
    "DISAPPROVED": 97,
    "EXPIRED": 96,
    "SUSPEND": 95,
    "SUSPENDED": 95,
    "COMPLETE": 80,
    "ISSUED": 60,
    "ISSUING": 55,
    "REINSTATED": 50,
    "APPROVED": 40,
    "PLANCHECK": 30,
    "FILED": 20,
    "FILING": 10,
    "TRIAGE": 5,
}

_STAGE_STATUS = {
    "COMPLETE": "Final",
    "ISSUED": "Active",
    "ISSUING": "Active",
    "REINSTATED": "Active",
    "APPROVED": "Active",
    "FILED": "In Review",
    "FILING": "In Review",
    "TRIAGE": "In Review",
    "PLANCHECK": "In Review",
    "CANCELLED": "Inactive",
    "CANCELED": "Inactive",
    "EXPIRED": "Inactive",
    "WITHDRAWN": "Inactive",
    "REVOKED": "Inactive",
    "DISAPPROVED": "Inactive",
    "SUSPEND": "Inactive",
    "SUSPENDED": "Inactive",
}

_HARD_CANCEL = {
    "CANCELLED",
    "CANCELED",
    "WITHDRAWN",
    "REVOKED",
    "DISAPPROVED",
}


def _iter_stages(data_dict: dict):
    """Yield (STAGE_UPPER, Timestamp|NaT, comments) from processing_status."""
    for s in data_dict.get("processing_status") or []:
        if not isinstance(s, dict):
            continue
        stage = (s.get("stage") or "").strip().upper()
        if not stage:
            continue
        yield stage, _safe_to_datetime(s.get("date")), s.get("comments") or ""


def _chrono_latest_stage(stages) -> Optional[str]:
    dated = [(st, dt) for st, dt, _ in stages if dt is not pd.NaT]
    if not dated:
        # Fall back to last non-empty stage label if undated.
        labels = [st for st, _, _ in stages]
        return labels[-1] if labels else None
    max_dt = max(dt for _, dt in dated)
    cands = [st for st, dt in dated if dt == max_dt]
    return max(cands, key=lambda s: _STAGE_PRIORITY.get(s, 0))


def _expected_status(data_dict: dict) -> Optional[str]:
    """Derive STATUS_NORMALIZED from processing_status by calendar date.

    Array order differs by schema (chrono vs reverse), so status must be
    based on dates. COMPLETE beats a later Auto-expire EXPIRED (common
    DBI artifact after final inspection). Hard cancels always win when
    they are the chronologically latest stage.
    """
    stages = list(_iter_stages(data_dict))
    if not stages:
        return None

    latest = _chrono_latest_stage(stages)
    if latest is None:
        return None

    has_complete = any(st == "COMPLETE" for st, dt, _ in stages if dt is not pd.NaT)

    if latest in _HARD_CANCEL:
        return "Inactive"
    if has_complete:
        return "Final"
    return _STAGE_STATUS.get(latest)


def _stage_dates(data_dict: dict, stage_names) -> list:
    names = {s.upper() for s in stage_names}
    out = []
    for st, dt, _ in _iter_stages(data_dict):
        if st in names and dt is not pd.NaT:
            out.append(dt)
    return out


def _earliest_stage_date(data_dict: dict) -> pd.Timestamp:
    dates = [dt for _, dt, _ in _iter_stages(data_dict) if dt is not pd.NaT]
    return min(dates) if dates else pd.NaT


def _final_inspection_date(data_dict: dict) -> pd.Timestamp:
    """Latest final-inspection approval date from inspections list."""
    dates = []
    for insp in data_dict.get("inspections") or []:
        if not isinstance(insp, dict):
            continue
        blob = " ".join(
            str(insp.get(k) or "")
            for k in ("Inspection Status", "Inspection Description")
        ).upper()
        if "FINAL" not in blob:
            continue
        if not any(tok in blob for tok in ("APPRV", "APPROV", "PASS")):
            continue
        dt = _safe_to_datetime(insp.get("Activity Date"))
        if dt is not pd.NaT:
            dates.append(dt)
    return max(dates) if dates else pd.NaT


def _set_status(repairs: dict, current, expected: str):
    if expected is None:
        return
    if pd.isna(current):
        repairs["STATUS_NORMALIZED"] = expected
        repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"
    elif current != expected:
        repairs["STATUS_NORMALIZED"] = expected
        repairs["STATUS_NORMALIZED_FLAG"] = "FIXED"


def _set_date(repairs: dict, field: str, current, new_val, *, allow_fix: bool = True):
    """Set date field with FILLED/FIXED flag. Clears use FIXED when current present."""
    if new_val is pd.NaT or new_val is None:
        return
    if pd.isna(current):
        repairs[field] = new_val
        repairs[f"{field}_FLAG"] = "FILLED"
    elif allow_fix and not _dates_equal(current, new_val):
        repairs[field] = new_val
        repairs[f"{field}_FLAG"] = "FIXED"


def _clear_date(repairs: dict, field: str, current):
    if pd.isna(current):
        return
    repairs[field] = pd.NaT
    repairs[f"{field}_FLAG"] = "FIXED"


# ── Per-record repair ────────────────────────────────────────────────────────

def _repair_record(row, d: dict, repairs: dict):
    current_status = row["STATUS_NORMALIZED"]
    expected = _expected_status(d)
    _set_status(repairs, current_status, expected)
    effective_status = repairs.get("STATUS_NORMALIZED", current_status)

    # -- FILE_DATE: FILED > FILING > TRIAGE > earliest stage date ----------
    file_candidates = _stage_dates(d, ("FILED",))
    if not file_candidates:
        file_candidates = _stage_dates(d, ("FILING",))
    if not file_candidates:
        file_candidates = _stage_dates(d, ("TRIAGE",))
    canonical_file = min(file_candidates) if file_candidates else _earliest_stage_date(d)
    _set_date(repairs, "FILE_DATE", row["FILE_DATE"], canonical_file)

    # -- PERMIT_DATE: earliest ISSUED, else APPROVED (Active/Final only) --
    issued = _stage_dates(d, ("ISSUED", "ISSUING"))
    approved = _stage_dates(d, ("APPROVED",))
    canonical_permit = min(issued) if issued else (min(approved) if approved else pd.NaT)

    if effective_status in ("Active", "Final"):
        _set_date(repairs, "PERMIT_DATE", row["PERMIT_DATE"], canonical_permit)
    # Leave PERMIT_DATE on Inactive (was issued then expired/cancelled).
    # Clear spurious PERMIT_DATE on true In Review (never issued).
    elif effective_status == "In Review" and pd.notna(row["PERMIT_DATE"]):
        if not issued:
            _clear_date(repairs, "PERMIT_DATE", row["PERMIT_DATE"])

    # -- FINAL_DATE: latest COMPLETE, else final inspection ----------------
    complete = _stage_dates(d, ("COMPLETE",))
    canonical_final = max(complete) if complete else _final_inspection_date(d)

    if effective_status == "Final":
        _set_date(repairs, "FINAL_DATE", row["FINAL_DATE"], canonical_final)
    else:
        _clear_date(repairs, "FINAL_DATE", row["FINAL_DATE"])


# ── Main entry point ─────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    San Francisco permit records using information from the raw DATA JSON.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "San Francisco". Must contain
        columns STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, FINAL_DATE, and DATA.

    Returns
    -------
    pd.DataFrame
        Copy of *df* with corrected field values, an INFERRED_SCHEMA column,
        and flag columns STATUS_NORMALIZED_FLAG, FILE_DATE_FLAG,
        PERMIT_DATE_FLAG, FINAL_DATE_FLAG ("FILLED" or "FIXED").
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


# ── CLI: run standalone to preview repair stats ──────────────────────────────

if __name__ == "__main__":
    import os
    from dotenv import load_dotenv

    load_dotenv("/Users/ekung/projects/la-permits-data/.env")
    MY_DATA_PATH = os.getenv("MY_DATA_PATH")
    filepath = os.path.join(MY_DATA_PATH, "processed_data", "permits_ca_sample.parquet")
    df = pd.read_parquet(filepath)
    sf = df[(df["JURISDICTION"] == "San Francisco") & (df["STATE"] == "CA")].copy()

    print(f"San Francisco records: {len(sf):,}\n")

    repaired = data_repair(sf)

    print("INFERRED_SCHEMA:")
    print(repaired["INFERRED_SCHEMA"].value_counts(dropna=False).to_string())
    print()

    for field in ["STATUS_NORMALIZED", "FILE_DATE", "PERMIT_DATE", "FINAL_DATE"]:
        flag_col = f"{field}_FLAG"
        n_filled = (repaired[flag_col] == "FILLED").sum()
        n_fixed = (repaired[flag_col] == "FIXED").sum()
        print(f"{field}:")
        print(f"  FILLED: {n_filled:>4,}   FIXED: {n_fixed:>4,}")
        before_missing = sf[field].isna().sum()
        after_missing = repaired[field].isna().sum()
        print(f"  Missing before: {before_missing:>4,}   Missing after: {after_missing:>4,}")
        print()

    print("STATUS_NORMALIZED distribution:")
    print("  Before:")
    for s, c in sf["STATUS_NORMALIZED"].value_counts(dropna=False).items():
        print(f"    {str(s):15s}: {c:>4,}")
    print("  After:")
    for s, c in repaired["STATUS_NORMALIZED"].value_counts(dropna=False).items():
        print(f"    {str(s):15s}: {c:>4,}")

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

    print("\nFILE_DATE coverage after repair:")
    print(f"  populated: {repaired['FILE_DATE'].notna().sum()} / {len(repaired)}")

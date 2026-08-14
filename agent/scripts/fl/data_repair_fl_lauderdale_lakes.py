"""Data repair for Lauderdale Lakes (FL) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Lauderdale Lakes DATA is a uniform city-portal payload with top-level
keys app, fees, permit, init_info, permit_list, and inspection_list.
Content variants (INFERRED_SCHEMA) split by whether ``permit`` carries
a parseable Issued Date and whether ``inspection_list`` has dated rows:

  - city_app_issued_insp
  - city_app_issued
  - city_app_permit_no_issued
  - city_app_app_only   (empty permit object)

Unlike Nassau County's 5-column inspection rows, Lauderdale Lakes uses
6-column rows: [type, party, date, result, fee, due].

Canonical fields:

  - app.Status (+ Permit Status / Issued Date /
    permit_list ISSUED|COMPLETED)         → STATUS_NORMALIZED
  - app.Application Received Date         → FILE_DATE
  - permit.Issued Date                    → PERMIT_DATE
  - latest PASS* inspection date
    (prefer FINAL* types; floor at Issue) → FINAL_DATE

Known issues repaired:
  - STATUS_NORMALIZED null on 1,975/2,000 rows despite clear
    COMPLETE / ACTIVE / WITHDRAWN / EXPIRED / ENTERED IN ERROR
    labels → FILLED (only WITHDRAWN / VOID was already Inactive).
  - FINAL_DATE never ingested → FILLED from PASS inspections for
    Final rows.
  - ACTIVE / PENDING|READY TO ISSUE shells that already carry an
    Issued Date (or ISSUED permit_list row) → Active, keeping
    PERMIT_DATE.

Not repairable from DATA:
  - FILE_DATE already matches Application Received Date for every
    sample row.
  - PERMIT_DATE already matches Issued Date whenever present; many
    Complete / Active shells only show FEE / ISSUED on permit_list
    with a blank Issued Date → PERMIT_DATE stays missing.
  - Final rows with no dated PASS inspections → FINAL_DATE stays
    missing.
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
    r"final|fnl|close\s*out|closeout|certificate|occupancy|\bco\b|\bcc\b",
    re.IGNORECASE,
)

_PASS_RESULTS = {
    "pass",
    "passed",
    "pass partial",
    "approved",
    "complete",
    "completed",
    "in compliance",
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
    """Parse a date value, returning pd.NaT on failure / out-of-range."""
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


def _present(dt) -> bool:
    return dt is not pd.NaT and not pd.isna(dt)


def _apply_status(repairs: dict, current, expected: Optional[str]) -> Optional[str]:
    """Apply expected STATUS_NORMALIZED; return effective status."""
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
    """Fill or fix *field* from *candidate* datetime (pd.NaT = no candidate)."""
    cand = _safe_to_datetime(candidate)
    if not _present(cand):
        return

    current = row[field]
    if pd.isna(current):
        repairs[field] = cand
        repairs[f"{field}_FLAG"] = "FILLED"
    elif not _dates_equal(current, cand):
        repairs[field] = cand
        repairs[f"{field}_FLAG"] = "FIXED"


def _clear_date(repairs: dict, row, field: str) -> None:
    """Clear a spurious date value."""
    current = repairs.get(field, row[field])
    if pd.isna(current):
        return
    repairs[field] = pd.NaT
    repairs[f"{field}_FLAG"] = "FIXED"


def _parse_insp_row(row) -> tuple[Optional[str], object, Optional[str]]:
    """Return (type, date, result) for a Lauderdale Lakes inspection row.

    Layout: [type, party, date, result, fee, due]. Falls back to scanning
    for a parseable date / PASS-like token when column count differs.
    """
    if not isinstance(row, list) or not row:
        return None, pd.NaT, None

    if len(row) >= 4:
        typ = str(row[0] or "").strip() or None
        dt = _safe_to_datetime(row[2])
        result = str(row[3] or "").strip() or None
        if _present(dt):
            return typ, dt, result

    typ = str(row[0] or "").strip() or None
    dt = pd.NaT
    result = None
    for cell in row[1:]:
        text = str(cell or "").strip()
        if not text:
            continue
        if result is None and (
            text.lower() in _PASS_RESULTS
            or text.upper().startswith("PASS")
            or text.upper() in {"FAIL", "CANCEL", "NOT REQUIRED"}
        ):
            result = text
            continue
        cand = _safe_to_datetime(text)
        if _present(cand) and not _present(dt):
            dt = cand
    return typ, dt, result


def _has_insp_date(d: dict) -> bool:
    for row in d.get("inspection_list") or []:
        _, dt, _ = _parse_insp_row(row)
        if _present(dt):
            return True
    return False


def _permit_list_statuses(d: dict) -> set[str]:
    out = set()
    for row in d.get("permit_list") or []:
        if isinstance(row, list) and len(row) >= 2:
            status = str(row[1] or "").strip().upper()
            if status:
                out.add(status)
    return out


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())
    if "app" not in keys:
        return "unknown"

    permit = data_dict.get("permit")
    has_permit = isinstance(permit, dict) and bool(permit)
    issued = (
        _safe_to_datetime(permit.get("Issued Date")) if has_permit else pd.NaT
    )
    has_issued = _present(issued)
    has_insp = _has_insp_date(data_dict)

    if has_permit and has_issued and has_insp:
        return "city_app_issued_insp"
    if has_permit and has_issued:
        return "city_app_issued"
    if has_permit:
        return "city_app_permit_no_issued"
    return "city_app_app_only"


# ── Status mapping ───────────────────────────────────────────────────────────

_APP_STATUS_MAP = {
    "COMPLETE / CLOSED": "Final",
    "COMPLETE / READY TO CLOSE": "Final",
    "COMPLETE / VOID": "Inactive",
    "COMPLETE / WITHDRAWN": "Inactive",
    "ACTIVE / ISSUED": "Active",
    "ACTIVE / READY TO CLOSE": "Active",
    "ACTIVE / PENDING": "In Review",
    "ACTIVE / READY TO ISSUE": "In Review",
    "ACTIVE / CLOSED": "Inactive",
    "ACTIVE / WITHDRAWN": "Inactive",
    "ACTIVE / EXPIRED": "Inactive",
    "EXPIRED / CLOSED": "Inactive",
    "EXPIRED / EXPIRED": "Inactive",
    "WITHDRAWN / CLOSED": "Inactive",
    "WITHDRAWN / VOID": "Inactive",
    "WITHDRAWN / WITHDRAWN": "Inactive",
    "WITHDRAWN / ISSUED": "Inactive",
    "WITHDRAWN / PENDING": "Inactive",
    "ENTERED IN ERROR / CLOSED": "Inactive",
}

_INACTIVE_APP_LEFT = {
    "ENTERED IN ERROR",
    "WITHDRAWN",
    "DENIED",
    "EXPIRED",
}

_INACTIVE_APP_RIGHT = {
    "VOID",
    "WITHDRAWN",
    "EXPIRED",
    "DENIED",
}

_INACTIVE_PERMIT = {"DENIED", "WITHDRAWN", "VOIDED", "VOID", "REVOKED"}


def _expected_status(
    app_status: Optional[str],
    permit_status: Optional[str],
    issued,
    list_statuses: set[str],
) -> Optional[str]:
    app_key = (app_status or "").strip().upper()
    ps = (permit_status or "").strip().upper()
    has_issued = _present(_safe_to_datetime(issued))
    has_list_issued = "ISSUED" in list_statuses
    has_list_completed = "COMPLETED" in list_statuses

    left = app_key.split("/", 1)[0].strip() if app_key else ""
    right = app_key.split("/", 1)[1].strip() if "/" in app_key else ""

    # Terminal app labels beat permit COMPLETED (e.g. COMPLETE / VOID).
    if left in _INACTIVE_APP_LEFT or right in _INACTIVE_APP_RIGHT:
        return "Inactive"
    if ps in _INACTIVE_PERMIT:
        return "Inactive"

    if ps == "COMPLETED" or (left == "COMPLETE" and has_list_completed):
        return "Final"
    if left == "COMPLETE":
        return "Final"

    base = _APP_STATUS_MAP.get(app_key)
    if base is None:
        if left == "ACTIVE":
            if right in {"PENDING", "READY TO ISSUE"}:
                base = "In Review"
            elif right in {"ISSUED", "READY TO CLOSE"}:
                base = "Active"
            elif right == "CLOSED":
                base = "Inactive"
            else:
                base = "Active"
        elif left == "COMPLETE":
            base = "Final"
        else:
            base = None

    if base is None:
        if has_issued or ps == "ISSUED" or has_list_issued:
            return "Active"
        if right == "READY TO CLOSE":
            return "Active"
        if ps == "REVIEWING" or right in {"PENDING", "READY TO ISSUE"}:
            return "In Review"
        return None

    # Unissued review shells vs issued active work.
    if base in ("Active", "In Review"):
        if ps == "ISSUED" or has_issued or has_list_issued:
            return "Active"
        if ps == "COMPLETED" or has_list_completed:
            return "Final"
        # Ready-to-close means work is done pending closeout — keep Active
        # even when Issued Date is blank / Permit Status is still REVIEWING.
        if right == "READY TO CLOSE":
            return "Active"
        if ps == "REVIEWING" or right in {"PENDING", "READY TO ISSUE"}:
            return "In Review"
        if base == "Active" and not has_issued and not ps and not list_statuses:
            return "In Review"

    return base


def _latest_pass_date(inspection_list, final_only: bool = False):
    """Latest inspection date with a PASS-like result."""
    dates = []
    for row in inspection_list or []:
        typ, dt, result = _parse_insp_row(row)
        if not _present(dt):
            continue
        res = (result or "").strip().lower()
        if not (res in _PASS_RESULTS or res.startswith("pass")):
            continue
        if final_only and not _FINAL_INSP_RE.search(typ or ""):
            continue
        dates.append(dt)
    return max(dates) if dates else pd.NaT


def _final_date_candidate(d: dict, issued_dt):
    """Prefer FINAL* PASS dates; else any PASS; floor at Issued Date."""
    final_src = _latest_pass_date(d.get("inspection_list"), final_only=True)
    if not _present(final_src):
        final_src = _latest_pass_date(d.get("inspection_list"), final_only=False)
    if _present(final_src) and _present(issued_dt):
        final_src = max(
            pd.Timestamp(final_src).normalize(),
            pd.Timestamp(issued_dt).normalize(),
        )
    return final_src


# ── Per-record repair ────────────────────────────────────────────────────────

def _repair_record(row, d: dict, repairs: dict) -> None:
    app = d.get("app") if isinstance(d.get("app"), dict) else {}
    permit = d.get("permit") if isinstance(d.get("permit"), dict) else {}

    app_status = app.get("Status") or ""
    permit_status = permit.get("Permit Status")
    issued = permit.get("Issued Date")
    issued_dt = _safe_to_datetime(issued)
    list_statuses = _permit_list_statuses(d)

    expected = _expected_status(
        app_status, permit_status, issued, list_statuses
    )
    effective = _apply_status(repairs, row["STATUS_NORMALIZED"], expected)

    # -- FILE_DATE ← Application Received Date --
    _apply_date(repairs, row, "FILE_DATE", app.get("Application Received Date"))

    # -- PERMIT_DATE ← Issued Date --
    if effective in ("Active", "Final", "Inactive"):
        if _present(issued_dt):
            _apply_date(repairs, row, "PERMIT_DATE", issued_dt)
    elif effective == "In Review":
        _clear_date(repairs, row, "PERMIT_DATE")

    # -- FINAL_DATE ← PASS inspections; Final only --
    if effective == "Final":
        _apply_date(
            repairs, row, "FINAL_DATE", _final_date_candidate(d, issued_dt)
        )
    else:
        _clear_date(repairs, row, "FINAL_DATE")


# ── Main entry point ─────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Lauderdale Lakes permit records using information from the raw DATA JSON.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Lauderdale Lakes".  Must
        contain columns STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE,
        FINAL_DATE, and DATA.

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
        if d is None or schema in ("missing", "unknown"):
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

    repo_root = Path(__file__).resolve().parents[3]
    load_dotenv(repo_root / ".env")
    my_data_path = os.getenv("MY_DATA_PATH")
    agent_data_path = os.getenv("AGENT_DATA_PATH")
    filepath = os.path.join(
        my_data_path, "processed_data", "permits_fl_sample.parquet"
    )
    df = pd.read_parquet(filepath)
    city = df[
        (df["JURISDICTION"] == "Lauderdale Lakes") & (df["STATE"] == "FL")
    ].copy()

    print(f"Lauderdale Lakes records: {len(city):,}\n")
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
        })
        .groupby(["before", "after"], dropna=False)
        .size()
        .reset_index(name="n")
    )
    changed = transitions[
        transitions["before"].astype(str) != transitions["after"].astype(str)
    ]
    print(changed.sort_values("n", ascending=False).to_string(index=False))

    print("\napp.Status → STATUS_NORMALIZED (after):")
    app_status = city["DATA"].map(
        lambda x: (_safe_parse(x) or {}).get("app", {}).get("Status")
        if isinstance((_safe_parse(x) or {}).get("app"), dict)
        else None
    )
    cross = (
        pd.DataFrame({
            "app": app_status,
            "norm": repaired["STATUS_NORMALIZED"],
        })
        .groupby(["app", "norm"], dropna=False)
        .size()
        .reset_index(name="n")
        .sort_values("n", ascending=False)
    )
    print(cross.to_string(index=False))

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

    file_permit = repaired[
        repaired["FILE_DATE"].notna() & repaired["PERMIT_DATE"].notna()
    ]
    n_fp = (
        file_permit["FILE_DATE"].dt.normalize()
        > file_permit["PERMIT_DATE"].dt.normalize()
    ).sum()
    print(f"FILE_DATE > PERMIT_DATE inversions after repair: {n_fp}")

    final_miss = repaired[
        (repaired["STATUS_NORMALIZED"] == "Final") & repaired["FINAL_DATE"].isna()
    ]
    print(f"Final still missing FINAL_DATE: {len(final_miss)}")

    af_miss = repaired[
        repaired["STATUS_NORMALIZED"].isin(["Active", "Final"])
        & repaired["PERMIT_DATE"].isna()
    ]
    print(f"Active/Final still missing PERMIT_DATE: {len(af_miss)}")

    status_null = repaired["STATUS_NORMALIZED"].isna().sum()
    print(f"STATUS_NORMALIZED still null: {status_null}")

    if agent_data_path:
        out_path = os.path.join(
            agent_data_path, "lauderdale_lakes_repaired_sample.parquet"
        )
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote repaired sample → {out_path}")

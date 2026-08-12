"""Data repair for Boynton Beach (FL) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Boynton Beach DATA is a City portal payload (Process Type / Project/Case
/ Status / Fees / Reviews / Inspections) with three sub-schemas in this
sample:

  - permit_single: top-level Permit object (often with project_no)
  - permits_list:  top-level Permits array (no singular Permit)
  - case_only:     neither Permit nor Permits (case / application shell)

The only explicit timestamps in DATA are nested ``Updated On`` fields.

Canonical mappings:
  - Permit.Status / Permits[].Status, with top-level Status
    (Completed outweighs Issued for instant/affidavit cases;
    Finaled wins; Abandoned/Withdrawn/etc. → Inactive)
                                                 → STATUS_NORMALIZED
  - Earliest Fees Updated On (else earliest Reviews;
    else earliest Permit/Inspections Updated On) → FILE_DATE
  - Issued Permit/Permits Updated On             → PERMIT_DATE
  - Latest Approved final-ish / affidavit
    inspection; else Finaled Permit Updated On;
    else latest Approved inspection              → FINAL_DATE

Known issues repaired:
  - STATUS_NORMALIZED null whenever STATUS_ORIGINAL was blank but
    top-level Status / Permit status is present → FILLED.
  - Completed + Issued instant/affidavit rows incorrectly left
    Active → FIXED to Final.
  - Review Cycle Approved left Active → FIXED to In Review.
  - Top-level Permit Issued with Permit.Status Required
    (portal lag, no Issued timestamp) → FIXED/FILLED as In Review.
  - Abandoned with stray Active → FIXED to Inactive.
  - FILE_DATE often ingested as a mid-stream review Updated On
    while earlier Fees timestamps exist → FIXED to fee minimum.
  - PERMIT_DATE / FINAL_DATE entirely missing in the sample →
    FILLED from Issued / final inspection (or Finaled) timestamps.

Not repairable from DATA:
  - Case shells with no Fees/Reviews/Inspections/Permit dates
    (~578 rows) → FILE_DATE stays missing.
  - Finaled permits never expose an Issued timestamp → PERMIT_DATE
    stays missing for most Final rows.
  - Completed case_only shells with empty Inspections → FINAL_DATE
    stays missing.
"""

from __future__ import annotations

import json
import math
import re
from typing import Optional

import numpy as np
import pandas as pd


_MIN_YEAR = 1990
_MAX_YEAR = 2035

_FINAL_INSP_RE = re.compile(
    r"final|fnl|closeout|certificate|\btco\b|affidavit",
    re.I,
)


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
    """Parse a date value, returning pd.NaT on failure / sentinels."""
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
    da = _safe_to_datetime(a)
    db = _safe_to_datetime(b)
    if da is pd.NaT or db is pd.NaT or pd.isna(da) or pd.isna(db):
        return False
    return pd.Timestamp(da).normalize() == pd.Timestamp(db).normalize()


def _apply_status(repairs: dict, current, expected: Optional[str]) -> Optional[str]:
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
    cand = _safe_to_datetime(candidate)
    if cand is pd.NaT or pd.isna(cand):
        return

    current = row[field]
    if pd.isna(current):
        repairs[field] = cand
        repairs[f"{field}_FLAG"] = "FILLED"
    elif not _dates_equal(current, cand):
        repairs[field] = cand
        repairs[f"{field}_FLAG"] = "FIXED"


def _apply_file_date(repairs: dict, row, candidate, *, prefer_earlier: bool) -> None:
    """Fill / fix FILE_DATE.

    When *prefer_earlier* is True (fee / review sources), only overwrite an
    existing value if the candidate is strictly earlier — preserving rare
    upstream application dates that pre-date fee Updated On stamps.
    """
    cand = _safe_to_datetime(candidate)
    if cand is pd.NaT or pd.isna(cand):
        return

    current = row["FILE_DATE"]
    if pd.isna(current):
        repairs["FILE_DATE"] = cand
        repairs["FILE_DATE_FLAG"] = "FILLED"
        return

    if _dates_equal(current, cand):
        return

    if prefer_earlier:
        cur_dt = _safe_to_datetime(current)
        if cur_dt is not pd.NaT and not pd.isna(cur_dt):
            if pd.Timestamp(cur_dt).normalize() < pd.Timestamp(cand).normalize():
                return

    repairs["FILE_DATE"] = cand
    repairs["FILE_DATE_FLAG"] = "FIXED"


def _clear_date(repairs: dict, row, field: str) -> None:
    current = repairs.get(field, row[field])
    if pd.isna(current):
        return
    repairs[field] = pd.NaT
    repairs[f"{field}_FLAG"] = "FIXED"


# ── Schema / extractors ──────────────────────────────────────────────────────

def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    if not isinstance(data_dict, dict):
        return "unknown"
    if isinstance(data_dict.get("Permit"), dict):
        return "permit_single"
    if "Permits" in data_dict:
        return "permits_list"
    if "Status" in data_dict and "Process Type" in data_dict:
        return "case_only"
    return "unknown"


def _permit_objs(d: dict) -> list:
    out = []
    if isinstance(d.get("Permit"), dict):
        out.append(d["Permit"])
    for p in d.get("Permits") or []:
        if isinstance(p, dict):
            out.append(p)
    return out


def _section_dates(d: dict, section: str) -> list:
    items = d.get(section) or []
    if not isinstance(items, list):
        return []
    dates = []
    for it in items:
        if not isinstance(it, dict):
            continue
        dt = _safe_to_datetime(it.get("Updated On"))
        if dt is not pd.NaT and not pd.isna(dt):
            dates.append(dt)
    return dates


def _permit_dates(d: dict, statuses=None) -> list:
    dates = []
    for p in _permit_objs(d):
        if statuses is not None and p.get("Status") not in statuses:
            continue
        dt = _safe_to_datetime(p.get("Updated On"))
        if dt is not pd.NaT and not pd.isna(dt):
            dates.append(dt)
    return dates


# ── Status mapping ───────────────────────────────────────────────────────────

_TOP_STATUS_MAP = {
    "Completed": "Final",
    "Completed - Archived": "Final",
    "Permit Issued": "Active",
    "Permit In Progress": "Active",
    "In Progress": "In Review",
    "Submission in Progress": "In Review",
    "Review Cycle Disapproved": "In Review",
    "Review Cycle Approved": "In Review",
    "Ready for Approval": "In Review",
    "Fees Pending": "In Review",
    "Waiting For Intake": "In Review",
    "Abandoned": "Inactive",
    "Withdrawn": "Inactive",
    "Intake Rejected": "Inactive",
    "Permit Expired": "Inactive",
}

_INACTIVE_TOP = {
    "Abandoned",
    "Withdrawn",
    "Intake Rejected",
    "Permit Expired",
}


def _expected_status(d: dict) -> Optional[str]:
    top = d.get("Status")
    statuses = [p.get("Status") for p in _permit_objs(d)]
    has_finaled = any(s in ("Finaled", "Finaled - Archived") for s in statuses)
    has_issued = any(s == "Issued" for s in statuses)
    has_dead = any(s in ("Expired", "Voided") for s in statuses)
    has_required = any(s == "Required" for s in statuses)

    if has_finaled:
        return "Final"

    # Case-level Completed outweighs permit still showing Issued
    # (instant / affidavit permits often never flip to Finaled).
    if top in ("Completed", "Completed - Archived"):
        if has_dead and not has_issued:
            return "Inactive"
        return "Final"

    if top in _INACTIVE_TOP:
        return "Inactive"

    if has_dead and not has_issued:
        return "Inactive"

    # Issued permit object is authoritative. Top-level "Permit Issued"
    # with Permit.Status still Required is portal lag → In Review.
    if has_issued:
        return "Active"
    if has_required:
        return "In Review"
    if top == "Permit Issued":
        return "Active"

    return _TOP_STATUS_MAP.get(top)


# ── Per-record repair ────────────────────────────────────────────────────────

def _repair_record(row, d: dict, repairs: dict) -> None:
    expected = _expected_status(d)
    effective = _apply_status(repairs, row["STATUS_NORMALIZED"], expected)

    # -- FILE_DATE --
    fee_dates = _section_dates(d, "Fees")
    review_dates = _section_dates(d, "Reviews")
    if fee_dates:
        _apply_file_date(repairs, row, min(fee_dates), prefer_earlier=True)
    elif review_dates:
        _apply_file_date(repairs, row, min(review_dates), prefer_earlier=True)
    else:
        other = _permit_dates(d) + _section_dates(d, "Inspections")
        if other and pd.isna(row["FILE_DATE"]):
            # Weak signal — only fill gaps, never overwrite.
            _apply_file_date(repairs, row, min(other), prefer_earlier=False)

    # -- PERMIT_DATE (Active / Final only; Issued timestamps) --
    issued_dates = _permit_dates(d, statuses={"Issued"})
    if effective in ("Active", "Final"):
        if issued_dates:
            _apply_date(repairs, row, "PERMIT_DATE", min(issued_dates))
    else:
        # Spurious issuance dates on non-issued statuses (none in sample,
        # but keep the invariant).
        if not pd.isna(row["PERMIT_DATE"]):
            _clear_date(repairs, row, "PERMIT_DATE")

    # -- FINAL_DATE (Final only) --
    final_insp = []
    any_approved = []
    for it in d.get("Inspections") or []:
        if not isinstance(it, dict):
            continue
        if it.get("Status") != "Approved":
            continue
        dt = _safe_to_datetime(it.get("Updated On"))
        if dt is pd.NaT or pd.isna(dt):
            continue
        any_approved.append(dt)
        rt = it.get("Record Type") or ""
        if _FINAL_INSP_RE.search(rt):
            final_insp.append(dt)

    finaled_dates = _permit_dates(d, statuses={"Finaled", "Finaled - Archived"})

    if effective == "Final":
        if final_insp:
            _apply_date(repairs, row, "FINAL_DATE", max(final_insp))
        elif finaled_dates:
            _apply_date(repairs, row, "FINAL_DATE", max(finaled_dates))
        elif any_approved:
            _apply_date(repairs, row, "FINAL_DATE", max(any_approved))
    else:
        if not pd.isna(row["FINAL_DATE"]):
            _clear_date(repairs, row, "FINAL_DATE")


# ── Public API ───────────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED / FILE_DATE / PERMIT_DATE / FINAL_DATE.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Boynton Beach". Must contain
        columns STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, FINAL_DATE,
        and DATA.

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
        if d is None:
            continue

        repairs: dict = {}
        if schema in {"permit_single", "permits_list", "case_only"}:
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
    filepath = os.path.join(
        my_data_path, "processed_data", "permits_fl_sample.parquet"
    )
    df = pd.read_parquet(filepath)
    city = df[
        (df["JURISDICTION"] == "Boynton Beach") & (df["STATE"] == "FL")
    ].copy()

    print(f"Boynton Beach records: {len(city):,}\n")
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

    if agent_data_path:
        out_path = os.path.join(
            agent_data_path, "boynton_beach_repaired_sample.parquet"
        )
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote repaired sample → {out_path}")

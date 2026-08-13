"""Data repair for Islamorada (FL) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Islamorada DATA is an EnerGov / Civic platform community-development
payload with top-level ``Summary`` plus ``Inspections``, and usually
``Locations``, ``Contacts``, ``Reviews``, plus either ``Permits``
(list) or ``Permit Info`` (dict). A minority of rows also carry
``project_id`` and/or ``Submittals``. Variants (INFERRED_SCHEMA):

  - energov_permits_project_*: Permits list + project_id
  - energov_permits_*:         Permits list, no project_id
  - energov_permit_info_*:     Permit Info dict
  - energov_*:                 Summary shell without Permits/Permit Info
  - Content suffixes:          _issued_finaled / _issued / _finaled /
                               _app_date / _minimal
  - missing / unknown

Canonical mappings:
  - Summary["Application Status"] with Issued Date /
    Date Finalled overrides                   → STATUS_NORMALIZED
  - Summary["Application Date"]               → FILE_DATE
  - Summary["Issued Date"]                    → PERMIT_DATE
  - Summary["Date Finalled"], else latest
    approved Final* inspection DateCompleted  → FINAL_DATE

Known issues repaired:
  - Voided/Cancelled, Withdrawn/Abandoned, Assigned in Error, In BPAS,
    Allocated, Returned for Correction (and a few other unmapped
    statuses) left STATUS_NORMALIZED null → FILLED.
  - Stale STATUS_ORIGINAL (e.g. issued / in plan check / expired) when
    Summary.Application Status has already advanced to Closed / Issued
    → FIXED (Active/In Review/Inactive → Final or Active).
  - FINAL_DATE missing on every sample row despite Date Finalled on
    ~1,247 rows → FILLED; additional Closed rows recover FINAL_DATE
    from approved Final* inspections.
  - PERMIT_DATE missing on Issued / Closed rows that carry Issued Date
    (often because STATUS_ORIGINAL was still In Review) → FILLED after
    status correction; spurious PERMIT_DATE on In Review cleared.

Not repairable from DATA:
  - ~440 Closed / Final rows with blank Summary["Issued Date"]
    → PERMIT_DATE stays missing (common on legacy shells).
  - ~100 Closed / Final rows with neither Date Finalled nor an
    approved Final* inspection → FINAL_DATE stays missing.
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

_FINAL_INSP_RE = re.compile(r"final|\bco\b|\bcc\b|\bcoc\b", re.IGNORECASE)

_PASS_OUTCOME = {
    "approved",
    "passed",
    "pass",
    "complete",
    "completed",
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
    """Parse a date value, returning pd.NaT on failure / sentinel / OOR year."""
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return pd.NaT
    if isinstance(val, dict):
        return pd.NaT
    if isinstance(val, str):
        s = val.strip().replace("\xa0", " ")
        if not s or s.lower() in {"none", "null", "n/a", "na", "nan", "tbd"}:
            return pd.NaT
        if s.startswith("0001-01-01") or s.startswith("1900-01-01"):
            return pd.NaT
    try:
        dt = pd.to_datetime(val, utc=True, errors="coerce")
    except (ValueError, TypeError, OverflowError):
        return pd.NaT
    if pd.isna(dt):
        return pd.NaT
    year = int(dt.year)
    if year < _MIN_YEAR or year > _MAX_YEAR:
        return pd.NaT
    return dt.tz_convert("UTC").tz_localize(None)


def _present(dt) -> bool:
    return dt is not pd.NaT and not pd.isna(dt)


def _dates_equal(a, b) -> bool:
    """Compare two datelike values at calendar-day resolution."""
    da = _safe_to_datetime(a)
    db = _safe_to_datetime(b)
    if not _present(da) or not _present(db):
        return False
    return pd.Timestamp(da).normalize() == pd.Timestamp(db).normalize()


def _normalize_text(raw) -> Optional[str]:
    if raw is None or (isinstance(raw, float) and math.isnan(raw)):
        return None
    s = re.sub(r"\s+", " ", str(raw).replace("\xa0", " ")).strip()
    return s or None


def _summary(d: dict) -> dict:
    s = d.get("Summary")
    return s if isinstance(s, dict) else {}


def _app_status(d: dict) -> Optional[str]:
    return _normalize_text(_summary(d).get("Application Status"))


def _app_date(d: dict):
    return _safe_to_datetime(_summary(d).get("Application Date"))


def _issued_date(d: dict):
    return _safe_to_datetime(_summary(d).get("Issued Date"))


def _finaled_date_from_summary(d: dict):
    """Islamorada uses 'Date Finalled' (double-L); accept Westlake spelling too."""
    s = _summary(d)
    dt = _safe_to_datetime(s.get("Date Finalled"))
    if _present(dt):
        return dt
    return _safe_to_datetime(s.get("Date Finaled"))


def _final_from_inspections(d: dict):
    """Latest approved Final*/CO inspection DateCompleted."""
    insp = d.get("Inspections")
    if not isinstance(insp, list):
        return pd.NaT
    dates = []
    for item in insp:
        if not isinstance(item, dict):
            continue
        activity = str(item.get("Activity") or item.get("Inspection Type") or "")
        if not _FINAL_INSP_RE.search(activity):
            continue
        outcome = str(item.get("Outcome") or item.get("Status") or "").strip().lower()
        if outcome not in _PASS_OUTCOME:
            continue
        dt = _safe_to_datetime(item.get("DateCompleted") or item.get("Date"))
        if _present(dt):
            dates.append(dt)
    return max(dates) if dates else pd.NaT


def _finaled_date(d: dict):
    dt = _finaled_date_from_summary(d)
    if _present(dt):
        return dt
    return _final_from_inspections(d)


# ── Status mapping ───────────────────────────────────────────────────────────

# Direct Application Status → STATUS_NORMALIZED (before date overrides).
_STATUS_MAP = {
    "Finalled": "Final",
    "Finaled": "Final",
    "Closed": "Final",
    "Issued": "Active",
    "Permit(s) Issued": "Active",
    "Pending": "In Review",
    "In Plan Check": "In Review",
    "Ready for Issuance": "In Review",
    "Returned for Correction": "In Review",
    "Incomplete": "In Review",
    "Waiting for Payment": "In Review",
    "In BPAS": "In Review",
    "Allocated": "In Review",
    "On Hold": "In Review",
    "In Progress": "In Review",
    "Withdrawn": "Inactive",
    "Withdrawn/Abandoned": "Inactive",
    "Expired": "Inactive",
    "Canceled": "Inactive",
    "Cancelled": "Inactive",
    "Voided/Cancelled": "Inactive",
    "Abandoned": "Inactive",
    "Denied": "Inactive",
    "Assigned in Error": "Inactive",
}

_INACTIVE = {
    "Withdrawn",
    "Withdrawn/Abandoned",
    "Expired",
    "Canceled",
    "Cancelled",
    "Voided/Cancelled",
    "Abandoned",
    "Denied",
    "Assigned in Error",
}


def _expected_status(d: dict) -> Optional[str]:
    """Derive STATUS_NORMALIZED from Application Status with date overrides.

    Priority:
      1. Terminal inactive Application Status → Inactive
      2. Date Finalled present, or Finalled/Closed status → Final
      3. Issued Date present, or Issued status → Active
      4. Otherwise map Application Status.
    """
    status = _app_status(d)
    finaled = _finaled_date_from_summary(d)
    issued = _issued_date(d)

    if status in _INACTIVE:
        return "Inactive"

    if _present(finaled) or status in {"Finalled", "Finaled", "Closed"}:
        return "Final"

    if _present(issued) or status in {"Permit(s) Issued", "Issued"}:
        return "Active"

    if status is not None:
        mapped = _STATUS_MAP.get(status)
        if mapped is not None:
            return mapped
        # Case-insensitive fallback for odd casing.
        for key, val in _STATUS_MAP.items():
            if key.lower() == status.lower():
                return val
        return "In Review"

    if _present(_final_from_inspections(d)):
        return "Final"
    return None


# ── Schema classification ────────────────────────────────────────────────────

def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())
    if "Summary" not in keys:
        return "unknown"

    if "Permits" in keys and "project_id" in keys:
        base = "energov_permits_project"
    elif "Permits" in keys:
        base = "energov_permits"
    elif "Permit Info" in keys:
        base = "energov_permit_info"
    else:
        base = "energov"

    has_app = _present(_app_date(data_dict))
    has_issued = _present(_issued_date(data_dict))
    has_finaled = _present(_finaled_date_from_summary(data_dict))

    if has_issued and has_finaled:
        return f"{base}_issued_finaled"
    if has_issued:
        return f"{base}_issued"
    if has_finaled:
        return f"{base}_finaled"
    if has_app:
        return f"{base}_app_date"
    return f"{base}_minimal"


# ── Per-record repair logic ─────────────────────────────────────────────────

def _repair_record(row, d: dict, repairs: dict) -> None:
    """Populate *repairs* with corrected values for a single record."""
    current_status = row["STATUS_NORMALIZED"]
    expected = _expected_status(d)

    # -- STATUS_NORMALIZED --
    if expected is not None:
        if pd.isna(current_status):
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"
        elif current_status != expected:
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FIXED"

    effective_status = repairs.get("STATUS_NORMALIZED", current_status)

    app = _app_date(d)
    issued = _issued_date(d)
    finaled = _finaled_date(d)

    # -- FILE_DATE (application / Summary["Application Date"]) --
    if _present(app):
        if pd.isna(row["FILE_DATE"]):
            repairs["FILE_DATE"] = app
            repairs["FILE_DATE_FLAG"] = "FILLED"
        elif not _dates_equal(row["FILE_DATE"], app):
            repairs["FILE_DATE"] = app
            repairs["FILE_DATE_FLAG"] = "FIXED"

    # -- PERMIT_DATE (issuance / Summary["Issued Date"]) --
    current_permit = row["PERMIT_DATE"]
    if effective_status in ("Active", "Final"):
        if _present(issued):
            if pd.isna(current_permit):
                repairs["PERMIT_DATE"] = issued
                repairs["PERMIT_DATE_FLAG"] = "FILLED"
            elif not _dates_equal(current_permit, issued):
                repairs["PERMIT_DATE"] = issued
                repairs["PERMIT_DATE_FLAG"] = "FIXED"
    elif effective_status == "Inactive":
        # Keep / fill issuance when present (Expired etc. were issued);
        # clear only unsupported stamps.
        if _present(issued):
            if pd.isna(current_permit):
                repairs["PERMIT_DATE"] = issued
                repairs["PERMIT_DATE_FLAG"] = "FILLED"
            elif not _dates_equal(current_permit, issued):
                repairs["PERMIT_DATE"] = issued
                repairs["PERMIT_DATE_FLAG"] = "FIXED"
        elif not pd.isna(current_permit):
            repairs["PERMIT_DATE"] = pd.NaT
            repairs["PERMIT_DATE_FLAG"] = "FIXED"
    elif not pd.isna(current_permit):
        # Spurious issuance stamp on In Review.
        repairs["PERMIT_DATE"] = pd.NaT
        repairs["PERMIT_DATE_FLAG"] = "FIXED"

    # -- FINAL_DATE (Date Finalled / Final* inspection) --
    current_final = row["FINAL_DATE"]
    if effective_status == "Final":
        if _present(finaled):
            if pd.isna(current_final) or not _present(_safe_to_datetime(current_final)):
                repairs["FINAL_DATE"] = finaled
                repairs["FINAL_DATE_FLAG"] = (
                    "FILLED" if pd.isna(current_final) else "FIXED"
                )
            elif not _dates_equal(current_final, finaled):
                repairs["FINAL_DATE"] = finaled
                repairs["FINAL_DATE_FLAG"] = "FIXED"
        elif not pd.isna(current_final) and not _present(
            _safe_to_datetime(current_final)
        ):
            repairs["FINAL_DATE"] = pd.NaT
            repairs["FINAL_DATE_FLAG"] = "FIXED"
    elif not pd.isna(current_final):
        repairs["FINAL_DATE"] = pd.NaT
        repairs["FINAL_DATE_FLAG"] = "FIXED"


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Islamorada (FL) permit records using information from the raw DATA JSON.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Islamorada". Must contain
        columns STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, FINAL_DATE,
        and DATA.

    Returns
    -------
    pd.DataFrame
        Copy of *df* with corrected field values, an INFERRED_SCHEMA column
        naming the DATA JSON sub-schema identified for each record, and new
        flag columns: STATUS_NORMALIZED_FLAG, FILE_DATE_FLAG,
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
    from collections import Counter
    from pathlib import Path

    from dotenv import load_dotenv

    repo_root = Path(__file__).resolve().parents[3]
    load_dotenv(repo_root / ".env")
    MY_DATA_PATH = os.getenv("MY_DATA_PATH")
    AGENT_DATA_PATH = os.getenv("AGENT_DATA_PATH")
    filepath = os.path.join(
        MY_DATA_PATH, "processed_data", "permits_fl_sample.parquet"
    )
    df = pd.read_parquet(filepath)
    city = df[
        (df["JURISDICTION"] == "Islamorada") & (df["STATE"] == "FL")
    ].copy()

    print(f"Islamorada records: {len(city):,}\n")

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
        print(
            f"  Missing before: {before_missing:>4,}   "
            f"Missing after: {after_missing:>4,}"
        )
        if field != "STATUS_NORMALIZED":
            before_bad = 0
            for v in city[field].dropna():
                dt = pd.to_datetime(v, errors="coerce")
                if pd.isna(dt) or dt.year < _MIN_YEAR or dt.year > _MAX_YEAR:
                    before_bad += 1
            print(f"  Sentinel/OOR before: {before_bad:>4,}")
        print()

    print("STATUS_NORMALIZED distribution:")
    print("  Before:")
    for s, c in city["STATUS_NORMALIZED"].value_counts(dropna=False).items():
        print(f"    {str(s):15s}: {c:>4,}")
    print("  After:")
    for s, c in repaired["STATUS_NORMALIZED"].value_counts(dropna=False).items():
        print(f"    {str(s):15s}: {c:>4,}")

    print("\nSTATUS_NORMALIZED changes (before → after):")
    changed = city["STATUS_NORMALIZED"].fillna("__NA__") != repaired[
        "STATUS_NORMALIZED"
    ].fillna("__NA__")
    if changed.any():
        tmp = pd.DataFrame(
            {
                "before": city.loc[changed, "STATUS_NORMALIZED"].fillna("__NA__"),
                "after": repaired.loc[changed, "STATUS_NORMALIZED"].fillna("__NA__"),
            }
        )
        print(tmp.value_counts().to_string())
    else:
        print("  (none)")

    print("\nDATA.Application Status → STATUS_NORMALIZED (after):")
    status_from_data = repaired["DATA"].map(
        lambda x: _app_status(_safe_parse(x) or {}) or "__EMPTY__"
    )
    ct = (
        pd.DataFrame({
            "DATA_STATUS": status_from_data,
            "STATUS_NORMALIZED": repaired["STATUS_NORMALIZED"],
        })
        .groupby(["DATA_STATUS", "STATUS_NORMALIZED"], dropna=False)
        .size()
        .reset_index(name="n")
        .sort_values("n", ascending=False)
    )
    print(ct.to_string(index=False))

    print("\nFINAL_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FINAL_DATE"].notna().sum()
        pct = n_has / len(sub) if len(sub) else 0.0
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({pct:.1%})")

    print("\nPERMIT_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["PERMIT_DATE"].notna().sum()
        pct = n_has / len(sub) if len(sub) else 0.0
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({pct:.1%})")

    print("\nFILE_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FILE_DATE"].notna().sum()
        pct = n_has / len(sub) if len(sub) else 0.0
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({pct:.1%})")

    final_miss = repaired[
        (repaired["STATUS_NORMALIZED"] == "Final") & repaired["FINAL_DATE"].isna()
    ]
    print(f"\nFinal still missing FINAL_DATE: {len(final_miss)}")
    if len(final_miss):
        ps_counts = Counter()
        for idx in final_miss.index:
            d = _safe_parse(repaired.at[idx, "DATA"])
            if d is None:
                continue
            raw = (_app_status(d) or "").strip() or "__EMPTY__"
            ps_counts[raw] += 1
        print("  by Application Status:", dict(ps_counts))

    status_null = repaired["STATUS_NORMALIZED"].isna().sum()
    print(f"\nSTATUS_NORMALIZED still null: {status_null}")

    af_miss = repaired[
        repaired["STATUS_NORMALIZED"].isin(["Active", "Final"])
        & repaired["PERMIT_DATE"].isna()
    ]
    print(f"Active/Final still missing PERMIT_DATE: {len(af_miss)}")
    if len(af_miss):
        ps_counts = Counter()
        for idx in af_miss.index:
            d = _safe_parse(repaired.at[idx, "DATA"])
            if d is None:
                continue
            raw = (_app_status(d) or "").strip() or "__EMPTY__"
            ps_counts[raw] += 1
        print("  by Application Status:", dict(ps_counts))

    file_gt_permit = 0
    permit_gt_final = 0
    file_gt_final = 0
    for idx in repaired.index:
        f = repaired.at[idx, "FILE_DATE"]
        p = repaired.at[idx, "PERMIT_DATE"]
        fin = repaired.at[idx, "FINAL_DATE"]
        if (
            pd.notna(f)
            and pd.notna(p)
            and pd.Timestamp(f).normalize() > pd.Timestamp(p).normalize()
        ):
            file_gt_permit += 1
        if (
            pd.notna(p)
            and pd.notna(fin)
            and pd.Timestamp(p).normalize() > pd.Timestamp(fin).normalize()
        ):
            permit_gt_final += 1
        if (
            pd.notna(f)
            and pd.notna(fin)
            and pd.Timestamp(f).normalize() > pd.Timestamp(fin).normalize()
        ):
            file_gt_final += 1
    print(f"\nFILE_DATE > PERMIT_DATE: {file_gt_permit}")
    print(f"PERMIT_DATE > FINAL_DATE: {permit_gt_final}")
    print(f"FILE_DATE > FINAL_DATE: {file_gt_final}")

    for field in ["FILE_DATE", "PERMIT_DATE", "FINAL_DATE"]:
        n_sent = 0
        for v in repaired[field].dropna():
            dt = pd.to_datetime(v, errors="coerce")
            if pd.notna(dt) and (dt.year < _MIN_YEAR or dt.year > _MAX_YEAR):
                n_sent += 1
        print(f"{field} sentinel remaining: {n_sent}")

    if AGENT_DATA_PATH:
        out_dir = os.path.join(AGENT_DATA_PATH, "repaired")
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(
            out_dir, "permits_fl_islamorada_repaired.parquet"
        )
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote repaired sample → {out_path}")

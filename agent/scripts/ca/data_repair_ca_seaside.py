"""Data repair for Seaside (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Seaside DATA is a SmartGov community portal payload with top-level keys
``Department``, ``My Project``, ``Permit Type``, ``Build Status``,
``Permit Number``, ``Permit Details``, contacts/fees/inspections arrays,
and optionally ``Parcel Number`` / ``ProjectDescription``. Variants:

  - smartgov_full:       core keys + ProjectDescription (+ Parcel Number)
  - smartgov_no_desc:    core keys + Parcel Number (no ProjectDescription)
  - smartgov_minimal:    core keys without Parcel Number / ProjectDescription
  - empty_shell:         empty My Project {}, null Build Status /
                         Permit Type / Department

Canonical fields:
  - DATA["Build Status"] (+ My Project date overrides)
                                  → STATUS_NORMALIZED
  - My Project.Submitted (fallback Created) → FILE_DATE
  - My Project.Issued (fallback Approved) → PERMIT_DATE
  - My Project.Closed (fallback latest passed/completed Final
    inspection)                   → FINAL_DATE

Known issues repaired:
  - 1,332 null STATUS_NORMALIZED: Pending Initial Application Review
    never mapped (149); null Build Status scrapes inferred from Closed /
    Issued / Submitted|Approved dates (~1,177); empty shells stay null.
  - Stale In Review on Technically Completed / Ready To Issue / Open
    rows that already carry Issued or Closed → FIXED to Active / Final.
  - FILE_DATE already matches Submitted when present; empty shells with
    no dates stay missing (5).
  - PERMIT_DATE FILLED on Active/Final from Issued (else Approved);
    spurious PERMIT_DATE on In Review without Issued cleared.
  - FINAL_DATE FILLED on Final from Closed or Final inspection;
    Finaled shells with blank Closed use inspection fallback; junk
    FINAL_DATE on non-Final cleared.

Not repairable / left as-is:
  - 14 empty_shell rows (5 fully blank; 9 with upstream dates only and
    no DATA to verify).
  - Finaled (2) with blank Closed and no usable Final inspection →
    FINAL_DATE stays missing.
  - Closed / Final shells with neither Issued nor Approved →
    PERMIT_DATE stays missing.
  - Technically Completed without Issued/Closed stays In Review.
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

_BLANK_DATE_STRINGS = {
    "",
    "-",
    "--",
    " - -",
    "None",
    "null",
    "n/a",
    "N/A",
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
        return json.loads(data)
    return data


def _is_blank_date(val) -> bool:
    if val is None:
        return True
    if isinstance(val, float) and math.isnan(val):
        return True
    s = str(val).strip()
    if s in _BLANK_DATE_STRINGS:
        return True
    # SmartGov placeholder: " - -", "- -", "-"
    if re.fullmatch(r"[\s\-]*", s):
        return True
    return False


def _safe_to_datetime(val):
    """Parse a date value as UTC, returning pd.NaT on failure or sentinel."""
    if _is_blank_date(val):
        return pd.NaT
    try:
        dt = pd.to_datetime(val, utc=True, errors="coerce")
    except (ValueError, TypeError):
        return pd.NaT
    if dt is pd.NaT or pd.isna(dt):
        return pd.NaT
    year = int(dt.year)
    if year < _MIN_YEAR or year > _MAX_YEAR:
        return pd.NaT
    return dt


def _my_project(d: dict) -> dict:
    mp = d.get("My Project")
    return mp if isinstance(mp, dict) else {}


def _normalize_build_status(raw) -> Optional[str]:
    if raw is None or (isinstance(raw, float) and math.isnan(raw)):
        return None
    s = re.sub(r"\s+", " ", str(raw).replace("\xa0", " ")).strip()
    if not s or s.lower() == "none":
        return None
    if s.lower().startswith("expired"):
        return "Expired"
    return s


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())
    if "My Project" not in keys:
        return "unknown"

    mp = _my_project(data_dict)
    bs = _normalize_build_status(data_dict.get("Build Status"))
    has_any_date = any(
        not _is_blank_date(mp.get(k))
        for k in ("Submitted", "Created", "Approved", "Issued", "Closed")
    )
    has_type = bool(data_dict.get("Permit Type"))
    has_dept = bool(data_dict.get("Department"))
    if not has_any_date and bs is None and not has_type and not has_dept and not mp:
        return "empty_shell"

    if "ProjectDescription" in keys:
        return "smartgov_full"
    if data_dict.get("Parcel Number") is not None:
        return "smartgov_no_desc"
    return "smartgov_minimal"


# ── Status mapping ──────────────────────────────────────────────────────────

# Normalized Build Status → STATUS_NORMALIZED (before date overrides)
_STATUS_MAP = {
    # Final
    "Closed": "Final",
    "Finaled": "Final",
    # Active
    "Approved": "Active",
    "Issued": "Active",
    # Inactive
    "Expired": "Inactive",
    # In Review — application / plan check / pre-issuance / incomplete
    "Open": "In Review",
    "Pending": "In Review",
    "Pending Initial Application Review": "In Review",
    "Ready To Issue": "In Review",
    "Technically Completed": "In Review",
    "Under Review": "In Review",
}


def _mp_date(d: dict, key: str):
    return _safe_to_datetime(_my_project(d).get(key))


def _status_from_dates(d: dict) -> Optional[str]:
    """Infer STATUS_NORMALIZED from My Project date availability."""
    if _mp_date(d, "Closed") is not pd.NaT:
        return "Final"
    if _mp_date(d, "Issued") is not pd.NaT:
        return "Active"
    # Approved without Issued is plan approval, not issuance.
    if (
        _mp_date(d, "Submitted") is not pd.NaT
        or _mp_date(d, "Created") is not pd.NaT
        or _mp_date(d, "Approved") is not pd.NaT
    ):
        return "In Review"
    return None


def _expected_status(d: dict) -> Optional[str]:
    """Derive STATUS_NORMALIZED from Build Status with date overrides.

    Sticky Inactive for Expired. Explicit Closed / Finaled → Final.
    Otherwise Closed date → Final, Issued date → Active (overrides
    review-pipeline labels). Null Build Status falls back to date
    inference; Approved-only without Issued stays In Review.
    """
    bs = _normalize_build_status(d.get("Build Status"))
    closed = _mp_date(d, "Closed")
    issued = _mp_date(d, "Issued")

    if bs == "Expired":
        return "Inactive"

    if bs in ("Closed", "Finaled"):
        return "Final"

    if closed is not pd.NaT:
        return "Final"

    if issued is not pd.NaT:
        # Issued stamp promotes review-pipeline labels to Active.
        mapped = _STATUS_MAP.get(bs) if bs is not None else None
        if mapped == "Inactive":
            return "Inactive"
        return "Active"

    mapped = _STATUS_MAP.get(bs) if bs is not None else None
    if mapped is not None:
        return mapped

    if bs is None:
        return _status_from_dates(d)

    return None


def _dates_equal(a, b) -> bool:
    """Compare two datelike values at calendar-day resolution (UTC)."""
    da = _safe_to_datetime(a)
    db = _safe_to_datetime(b)
    if da is pd.NaT or db is pd.NaT:
        return False
    return da.date() == db.date()


def _file_date_from_data(d: dict):
    submitted = _mp_date(d, "Submitted")
    if submitted is not pd.NaT:
        return submitted
    return _mp_date(d, "Created")


def _permit_date_from_data(d: dict):
    issued = _mp_date(d, "Issued")
    if issued is not pd.NaT:
        return issued
    return _mp_date(d, "Approved")


def _final_inspection_date(d: dict):
    """Latest passed/completed/approved inspection whose name contains Final."""
    inspections = d.get("Permit Inspections") or []
    dates = []
    for insp in inspections:
        if not isinstance(insp, dict):
            continue
        status = str(insp.get("Status") or "").strip().lower()
        name = str(insp.get("Inspection") or "")
        if status not in ("passed", "approved", "completed"):
            continue
        if not re.search(r"\bfinal\b", name, re.IGNORECASE):
            continue
        dt = _safe_to_datetime(insp.get("Date"))
        if dt is not pd.NaT:
            dates.append(dt)
    if not dates:
        return pd.NaT
    return max(dates)


def _final_date_from_data(d: dict):
    closed = _mp_date(d, "Closed")
    if closed is not pd.NaT:
        return closed
    return _final_inspection_date(d)


# ── Per-record repair logic ─────────────────────────────────────────────────

def _repair_record(row, d: dict, repairs: dict):
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

    # -- FILE_DATE (application / Submitted) --
    file_src = _file_date_from_data(d)
    if file_src is not pd.NaT:
        if pd.isna(row["FILE_DATE"]):
            repairs["FILE_DATE"] = file_src
            repairs["FILE_DATE_FLAG"] = "FILLED"
        elif not _dates_equal(row["FILE_DATE"], file_src):
            repairs["FILE_DATE"] = file_src
            repairs["FILE_DATE_FLAG"] = "FIXED"

    # -- PERMIT_DATE (issuance / Issued, else Approved) --
    permit_src = _permit_date_from_data(d)
    current_permit = row["PERMIT_DATE"]
    issued = _mp_date(d, "Issued")

    if not pd.isna(current_permit):
        if issued is not pd.NaT and not _dates_equal(current_permit, issued):
            repairs["PERMIT_DATE"] = issued
            repairs["PERMIT_DATE_FLAG"] = "FIXED"
        elif (
            effective_status == "In Review"
            and issued is pd.NaT
        ):
            # Spurious permit stamp on a still-in-review record.
            repairs["PERMIT_DATE"] = pd.NaT
            repairs["PERMIT_DATE_FLAG"] = "FIXED"
    elif effective_status in ("Active", "Final") and permit_src is not pd.NaT:
        repairs["PERMIT_DATE"] = permit_src
        repairs["PERMIT_DATE_FLAG"] = "FILLED"

    # -- FINAL_DATE (completion / Closed, else Final inspection) --
    final_src = _final_date_from_data(d)
    closed = _mp_date(d, "Closed")
    current_final = row["FINAL_DATE"]

    if effective_status == "Final":
        if final_src is not pd.NaT:
            if pd.isna(current_final):
                repairs["FINAL_DATE"] = final_src
                repairs["FINAL_DATE_FLAG"] = "FILLED"
            elif closed is not pd.NaT and not _dates_equal(current_final, closed):
                repairs["FINAL_DATE"] = closed
                repairs["FINAL_DATE_FLAG"] = "FIXED"
    elif not pd.isna(current_final):
        repairs["FINAL_DATE"] = pd.NaT
        repairs["FINAL_DATE_FLAG"] = "FIXED"


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Seaside (CA) permit records using information from the raw DATA JSON.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Seaside". Must contain
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
        if col in out.columns:
            out[col] = pd.to_datetime(out[col], utc=True, errors="coerce")

    return out


# ── CLI: run standalone to preview repair stats ─────────────────────────────

if __name__ == "__main__":
    import os
    from pathlib import Path

    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[3] / ".env")
    MY_DATA_PATH = os.getenv("MY_DATA_PATH")
    AGENT_DATA_PATH = os.getenv("AGENT_DATA_PATH")
    filepath = os.path.join(
        MY_DATA_PATH, "processed_data", "permits_ca_sample.parquet"
    )
    df = pd.read_parquet(filepath)
    city = df[(df["JURISDICTION"] == "Seaside") & (df["STATE"] == "CA")].copy()

    print(f"Seaside records: {len(city):,}\n")

    repaired = data_repair(city)

    if AGENT_DATA_PATH:
        out_dir = Path(AGENT_DATA_PATH) / "repaired"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "permits_ca_seaside_repaired.parquet"
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

    print("\nStatus transitions (before → after):")
    mask = repaired["STATUS_NORMALIZED_FLAG"].notna()
    if mask.any():
        transitions = (
            pd.DataFrame({
                "before": city.loc[mask, "STATUS_NORMALIZED"].fillna("nan").astype(str),
                "after": repaired.loc[mask, "STATUS_NORMALIZED"].fillna("nan").astype(str),
            })
            .value_counts()
            .reset_index(name="n")
        )
        for _, trow in transitions.iterrows():
            print(f"  {trow['before']:15s} → {trow['after']:15s}: {trow['n']:>4,}")
    else:
        print("  (none)")

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

    fd = pd.to_datetime(repaired["FILE_DATE"], utc=True, errors="coerce")
    pd_ = pd.to_datetime(repaired["PERMIT_DATE"], utc=True, errors="coerce")
    ff = pd.to_datetime(repaired["FINAL_DATE"], utc=True, errors="coerce")
    both_fp = fd.notna() & pd_.notna()
    both_pf = pd_.notna() & ff.notna()
    print("\nChronology inversions:")
    print(f"  FILE > PERMIT: {(both_fp & (fd.dt.normalize() > pd_.dt.normalize())).sum()}")
    print(f"  PERMIT > FINAL: {(both_pf & (pd_.dt.normalize() > ff.dt.normalize())).sum()}")

    print("\nRemaining ideal-coverage gaps:")
    active_final = repaired["STATUS_NORMALIZED"].isin(["Active", "Final"])
    final = repaired["STATUS_NORMALIZED"] == "Final"
    print(
        f"  Active/Final missing PERMIT_DATE: "
        f"{(active_final & repaired['PERMIT_DATE'].isna()).sum()}"
    )
    print(
        f"  Final missing FINAL_DATE: "
        f"{(final & repaired['FINAL_DATE'].isna()).sum()}"
    )
    print(f"  Any missing FILE_DATE: {repaired['FILE_DATE'].isna().sum()}")
    print(f"  Any missing STATUS_NORMALIZED: {repaired['STATUS_NORMALIZED'].isna().sum()}")

    from collections import Counter

    print("\nActive/Final still missing PERMIT_DATE (by Build Status):")
    gap = Counter()
    for idx in repaired.index:
        if repaired.at[idx, "STATUS_NORMALIZED"] not in ("Active", "Final"):
            continue
        if pd.notna(repaired.at[idx, "PERMIT_DATE"]):
            continue
        d = _safe_parse(city.at[idx, "DATA"])
        gap[_normalize_build_status((d or {}).get("Build Status"))] += 1
    for k, v in gap.most_common():
        print(f"  {k}: {v}")

    print("\nFinal still missing FINAL_DATE (by Build Status):")
    gap = Counter()
    for idx in repaired.index:
        if repaired.at[idx, "STATUS_NORMALIZED"] != "Final":
            continue
        if pd.notna(repaired.at[idx, "FINAL_DATE"]):
            continue
        d = _safe_parse(city.at[idx, "DATA"])
        gap[_normalize_build_status((d or {}).get("Build Status"))] += 1
    for k, v in gap.most_common():
        print(f"  {k}: {v}")

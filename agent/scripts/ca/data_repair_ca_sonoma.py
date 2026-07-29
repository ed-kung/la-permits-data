"""Data repair for Sonoma (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Sonoma DATA is a CitizenServe / OpenGov-style payload with top-level keys
``main``, ``extra``, and ``location``. Content variants
(INFERRED_SCHEMA) are classified by record-type family:

  - citizenserve_lsbp:            Limited Scope Building Permit
                                  (ASI 26607 status + 26608 date)
  - citizenserve_building:        Building / Express Building permits
                                  (named Status + ASI 26854 date)
  - citizenserve_encroachment:    Encroachment (ASI 26940 + 26941)
  - citizenserve_design_change:   Design Change & Deferred Submittal
                                  (named Status + ASI 26895)
  - citizenserve_fire:            Fire Permit (ASI 26800 + 26801)
  - citizenserve_solar:           SolarAPP+ forms
  - citizenserve_planning:        Uniform / zone / sign / planning apps
  - citizenserve_plaza_event:     plaza / vendor / temporary use / garage
  - citizenserve_home_occ:        Home Occupation Permit
  - citizenserve_other:           remaining named forms
  - empty_extra / unknown / missing

Canonical mappings:
  - main.status (0/1/2/-1), with Inactive overrides from form
    Withdrawn / Expired / Application Expired, and Final overrides from
    encroachment Completed → STATUS_NORMALIZED
  - main.dateSubmitted (else dateCreated) → FILE_DATE
  - Issued status-date pairs (ASI / named Status) → PERMIT_DATE
  - encroachment Completed date / Decision Date (when Final) → FINAL_DATE

Known issues repaired:
  - STATUS_NORMALIZED was derived from STATUS_ORIGINAL (active / draft /
    complete / stopped), which can lag the live numeric main.status.
    Sample mismatches (status=2 still Active, status=1 still Final,
    status=-1 still Active, status=2 still Inactive) → FIXED to the
    code map, then form Inactive / Completed overrides.
  - FILE_DATE was taken from main.dateCreated. When dateSubmitted falls
    on a later calendar day → FIXED to the submittal date.
  - PERMIT_DATE / FINAL_DATE universally missing; fill from Issued
    companion dates and Completed / Decision Date stamps when present.

Not repairable from DATA:
  - Most Express / Go-Live / SolarAPP+ / planning / plaza shells have no
    issuance or finaling timestamp. Form Status dates for review states
    (1st Review, Out for Corrections, In Review, Approved) are status-
    change stamps, not issuance. expirationDate and lastUpdatedDate are
    not safe proxies. Approved without Issued is treated as plan
    approval, not PERMIT_DATE.
"""

from __future__ import annotations

import json
import math
from datetime import date, datetime
from typing import Optional

import numpy as np
import pandas as pd


_MIN_YEAR = 1900
_MAX_YEAR = 2035

# Form-level labels that force Inactive (even when main.status lags).
_INACTIVE_FORM_LABELS = {
    "Withdrawn",
    "Expired",
    "Application Expired",
    "Canceled",
    "Cancelled",
    "Denied",
    "Void",
    "Voided",
}

# Form-level labels that force Final (encroachment completion).
_FINAL_FORM_LABELS = {
    "Completed",
    "Finaled",
    "Final",
    "Closed",
    "Complete",
}

# ASI / named status values that indicate permit issuance.
_ISSUED_LABELS = {"Issued"}

# (status_asi_id, date_asi_id) pairs used when the status companion is Issued.
_ASI_ISSUED_PAIRS = (
    ("26607", "26608"),  # Limited Scope Building Permit
    ("26800", "26801"),  # Fire Permit
    ("26940", "26941"),  # Encroachment Permit
)

# recordTypeName fragment → date ASI used with named extra['Status']==Issued
_NAMED_STATUS_ISSUED_DATE = (
    ("building permit", "26854"),
    ("design change", "26895"),
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
        return json.loads(data)
    return data


def _safe_to_datetime(val):
    """Parse a date value, returning pd.NaT on failure or implausible year."""
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return pd.NaT
    if isinstance(val, dict):
        return pd.NaT
    if isinstance(val, str):
        s = val.strip()
        if not s or s.upper() in {"TBD", "NULL", "NONE", "N/A", "NA"}:
            return pd.NaT
    try:
        dt = pd.to_datetime(val, errors="coerce")
    except (ValueError, TypeError):
        return pd.NaT
    if pd.isna(dt):
        return pd.NaT
    year = int(dt.year)
    if year < _MIN_YEAR or year > _MAX_YEAR:
        return pd.NaT
    if getattr(dt, "tzinfo", None) is not None:
        dt = dt.tz_convert("UTC").tz_localize(None)
    return dt


def _utc_date(val) -> Optional[date]:
    """Parse a timestamp and return its UTC calendar date."""
    if val is None or (isinstance(val, str) and not str(val).strip()):
        return None
    try:
        ts = pd.to_datetime(val, utc=True, errors="coerce")
    except (ValueError, TypeError):
        return None
    if pd.isna(ts):
        return None
    year = int(ts.year)
    if year < _MIN_YEAR or year > _MAX_YEAR:
        return None
    return ts.date()


def _as_date(val) -> Optional[date]:
    """Normalize a FILE_DATE-like value to datetime.date."""
    if _is_missing(val):
        return None
    if isinstance(val, date) and not isinstance(val, datetime):
        return val
    dt = _safe_to_datetime(val)
    if dt is pd.NaT or pd.isna(dt):
        return None
    if getattr(dt, "tzinfo", None) is not None:
        dt = dt.tz_convert("UTC") if hasattr(dt, "tz_convert") else dt
        return dt.date()
    return dt.date()


def _main(d: dict) -> dict:
    main = d.get("main")
    return main if isinstance(main, dict) else {}


def _extra(d: dict) -> dict:
    extra = d.get("extra")
    return extra if isinstance(extra, dict) else {}


def _form_status_labels(extra: dict) -> list[str]:
    """Collect non-empty workflow status strings from named + ASI fields."""
    out = []
    for key in ("Status", "26607", "26940", "26800"):
        raw = extra.get(key)
        if raw is None:
            continue
        s = str(raw).strip()
        if s:
            out.append(s)
    return out


# ── Schema classification ───────────────────────────────────────────────────

def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    if not isinstance(data_dict, dict) or "main" not in data_dict:
        return "unknown"

    extra = _extra(data_dict)
    if not extra:
        return "empty_extra"

    main = _main(data_dict)
    rt = (main.get("recordTypeName") or "").strip().lower()

    if "limited scope" in rt:
        return "citizenserve_lsbp"
    if "encroach" in rt:
        return "citizenserve_encroachment"
    if "design change" in rt or "deferred submittal" in rt:
        return "citizenserve_design_change"
    if "fire permit" in rt:
        return "citizenserve_fire"
    if "solar" in rt:
        return "citizenserve_solar"
    if "building permit" in rt or "express building" in rt:
        return "citizenserve_building"
    if "home occupation" in rt:
        return "citizenserve_home_occ"
    if any(
        frag in rt
        for frag in (
            "plaza",
            "vendor",
            "garage sale",
            "temporary use",
            "special event",
            "banner",
            "tuesday night",
            "depot park",
            "sidewalk seating",
            "wine tasting",
        )
    ):
        return "citizenserve_plaza_event"
    if any(
        frag in rt
        for frag in (
            "uniform",
            "planning",
            "zone clearance",
            "sign review",
            "tree removal",
            "historic",
            "wireless",
            "housing development",
            "improvement plan",
            "address",
        )
    ):
        return "citizenserve_planning"

    return "citizenserve_other"


# ── Status / date derivation ────────────────────────────────────────────────

# main.status (int) → STATUS_NORMALIZED
_STATUS_CODE_MAP = {
    0: "In Review",  # draft
    1: "Active",     # active
    2: "Final",      # complete
    -1: "Inactive",  # stopped
}


def _derive_status(main: dict, extra: dict) -> Optional[str]:
    """Map CitizenServe portal lifecycle code to STATUS_NORMALIZED.

    Prefer live ``main.status`` over lagged STATUS_ORIGINAL. Inactive
    form labels (Withdrawn / Expired / Application Expired) are sticky.
    Encroachment ``Completed`` (and similar) promotes to Final.
    """
    status = main.get("status")
    if status is None:
        mapped = None
    else:
        try:
            mapped = _STATUS_CODE_MAP.get(int(status))
        except (TypeError, ValueError):
            mapped = None

    labels = _form_status_labels(extra)
    if any(label in _INACTIVE_FORM_LABELS for label in labels):
        return "Inactive"
    if any(label in _FINAL_FORM_LABELS for label in labels):
        return "Final"

    return mapped


def _preferred_file_date(main: dict) -> Optional[date]:
    """Application/submittal date: dateSubmitted, else dateCreated."""
    submitted = _utc_date(main.get("dateSubmitted"))
    if submitted is not None:
        return submitted
    return _utc_date(main.get("dateCreated"))


def _permit_date_from_extra(main: dict, extra: dict):
    """Issuance stamp: ASI/named Status must be Issued (not review/Approved)."""
    for status_key, date_key in _ASI_ISSUED_PAIRS:
        if str(extra.get(status_key) or "").strip() in _ISSUED_LABELS:
            dt = _safe_to_datetime(extra.get(date_key))
            if dt is not pd.NaT and not pd.isna(dt):
                return dt

    named = str(extra.get("Status") or "").strip()
    if named in _ISSUED_LABELS:
        rt = (main.get("recordTypeName") or "").strip().lower()
        for frag, date_key in _NAMED_STATUS_ISSUED_DATE:
            if frag in rt:
                dt = _safe_to_datetime(extra.get(date_key))
                if dt is not pd.NaT and not pd.isna(dt):
                    return dt

    return pd.NaT


def _final_date_from_extra(extra: dict, effective_status):
    """Completion / decision stamp when effective status is Final."""
    if effective_status != "Final":
        return pd.NaT

    # Encroachment completion date (ASI 26940=Completed → 26941).
    if str(extra.get("26940") or "").strip() in _FINAL_FORM_LABELS:
        dt = _safe_to_datetime(extra.get("26941"))
        if dt is not pd.NaT and not pd.isna(dt):
            return dt

    dt = _safe_to_datetime(extra.get("Decision Date"))
    if dt is not pd.NaT and not pd.isna(dt):
        return dt

    return pd.NaT


def _dates_equal(a, b) -> bool:
    da = _safe_to_datetime(a)
    db = _safe_to_datetime(b)
    if da is pd.NaT or db is pd.NaT or pd.isna(da) or pd.isna(db):
        return False
    return da.normalize() == db.normalize()


# ── Per-record repair logic ─────────────────────────────────────────────────

def _repair_record(row, d: dict, repairs: dict):
    """Populate *repairs* with corrected values for a single Sonoma record."""
    main = _main(d)
    extra = _extra(d)

    # -- STATUS_NORMALIZED --
    current_status = row["STATUS_NORMALIZED"]
    expected = _derive_status(main, extra)
    if expected is not None:
        if pd.isna(current_status):
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"
        elif current_status != expected:
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FIXED"

    effective_status = repairs.get("STATUS_NORMALIZED", current_status)

    # -- FILE_DATE --
    preferred = _preferred_file_date(main)
    current_fd = _as_date(row["FILE_DATE"])
    if preferred is not None:
        if current_fd is None:
            repairs["FILE_DATE"] = pd.Timestamp(preferred)
            repairs["FILE_DATE_FLAG"] = "FILLED"
        elif current_fd != preferred:
            repairs["FILE_DATE"] = pd.Timestamp(preferred)
            repairs["FILE_DATE_FLAG"] = "FIXED"

    # -- PERMIT_DATE --
    permit_dt = _permit_date_from_extra(main, extra)
    current_permit = row["PERMIT_DATE"]

    if not pd.isna(current_permit):
        if permit_dt is not pd.NaT and not pd.isna(permit_dt):
            if not _dates_equal(current_permit, permit_dt):
                repairs["PERMIT_DATE"] = permit_dt
                repairs["PERMIT_DATE_FLAG"] = "FIXED"
        elif effective_status == "In Review":
            repairs["PERMIT_DATE"] = pd.NaT
            repairs["PERMIT_DATE_FLAG"] = "FIXED"
    elif effective_status in ("Active", "Final"):
        if permit_dt is not pd.NaT and not pd.isna(permit_dt):
            repairs["PERMIT_DATE"] = permit_dt
            repairs["PERMIT_DATE_FLAG"] = "FILLED"

    # -- FINAL_DATE --
    final_dt = _final_date_from_extra(extra, effective_status)
    current_final = row["FINAL_DATE"]

    if effective_status == "Final":
        if final_dt is not pd.NaT and not pd.isna(final_dt):
            if pd.isna(current_final):
                repairs["FINAL_DATE"] = final_dt
                repairs["FINAL_DATE_FLAG"] = "FILLED"
            elif not _dates_equal(current_final, final_dt):
                repairs["FINAL_DATE"] = final_dt
                repairs["FINAL_DATE_FLAG"] = "FIXED"
    elif not pd.isna(current_final):
        repairs["FINAL_DATE"] = pd.NaT
        repairs["FINAL_DATE_FLAG"] = "FIXED"


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Sonoma permit records using information from the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Sonoma".  Must contain
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
    city = df[(df["JURISDICTION"] == "Sonoma") & (df["STATE"] == "CA")].copy()

    print(f"Sonoma records: {len(city):,}\n")

    repaired = data_repair(city)

    if AGENT_DATA_PATH:
        out_dir = Path(AGENT_DATA_PATH) / "repaired"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "permits_ca_sonoma_repaired.parquet"
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

    from collections import Counter

    print("\nActive/Final still missing PERMIT_DATE (by recordTypeName):")
    gap = Counter()
    for idx in repaired.index:
        if repaired.at[idx, "STATUS_NORMALIZED"] not in ("Active", "Final"):
            continue
        if pd.notna(repaired.at[idx, "PERMIT_DATE"]):
            continue
        d = _safe_parse(city.at[idx, "DATA"])
        main = _main(d or {})
        gap[main.get("recordTypeName")] += 1
    for k, v in gap.most_common(15):
        print(f"  {k}: {v}")

    print("\nFinal still missing FINAL_DATE (by recordTypeName):")
    gap = Counter()
    for idx in repaired.index:
        if repaired.at[idx, "STATUS_NORMALIZED"] != "Final":
            continue
        if pd.notna(repaired.at[idx, "FINAL_DATE"]):
            continue
        d = _safe_parse(city.at[idx, "DATA"])
        main = _main(d or {})
        gap[main.get("recordTypeName")] += 1
    for k, v in gap.most_common(15):
        print(f"  {k}: {v}")

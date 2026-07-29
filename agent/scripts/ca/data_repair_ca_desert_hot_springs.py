"""Data repair for Desert Hot Springs (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Desert Hot Springs DATA is a CitizenServe / OpenGov-style payload with
top-level keys ``main``, ``extra``, and ``location``. Content variants
(INFERRED_SCHEMA):

  - citizenserve_code_compliance: Code Compliance Case / Archive forms
  - citizenserve_code_closed:     CE form with Compliance Date and/or
                                  Case Closed
  - citizenserve_building:        Building / solar / Old Building forms
  - citizenserve_cannabis:        Cannabis ID / facility / regulatory
  - citizenserve_business:        Business license applications
  - citizenserve_planning:        Planning / CUP / zoning / variance
  - citizenserve_encroachment:    Encroachment / utility / engineering
  - citizenserve_temporary:       Garage sale / special event / wide load
  - citizenserve_vacation_rental: Vacation rental forms
  - citizenserve_form_other:      Other named/numeric form fields
  - citizenserve_empty_extra:     empty extra dict
  - unknown / missing

Canonical mappings:
  - main.status (0/1/2/-1) → STATUS_NORMALIZED
  - main.dateSubmitted (else dateCreated) → FILE_DATE
  - (none reliable) → PERMIT_DATE
  - extra['Compliance Date'] when effective status is Final → FINAL_DATE

Known issues repaired:
  - FILE_DATE was taken from main.dateCreated. When dateSubmitted falls
    on a later calendar day → FIXED to the submittal date.
  - FINAL_DATE universally missing; fill from Compliance Date on Final
    code-enforcement rows when present.

Not repairable from DATA:
  - No Date Issued / Date Finaled / Permit Status fields (unlike Buena
    Park). Numeric ASI-like dates (e.g. 12678) are license / workers-
    comp expirations, not issuance. Event Start/End, Garage Sale dates,
    Permit Start Date, and lastUpdatedDate are not safe proxies for
    approval or finaling.
  - STATUS_NORMALIZED already matches main.status 1:1 on the sample
    (draft/active/complete/stopped ↔ In Review/Active/Final/Inactive).
  - Form field 20656 Active/Inactive on CE Archive rows describes the
    violation state, not the portal lifecycle — do not override Final.
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
    if val is None or (isinstance(val, str) and not val.strip()):
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


# ── Schema classification ───────────────────────────────────────────────────

def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys()) if isinstance(data_dict, dict) else set()
    if not {"main", "extra", "location"}.issubset(keys):
        if "main" in keys:
            return "main_only"
        return "unknown"

    main = _main(data_dict)
    extra = _extra(data_dict)
    if not extra:
        return "citizenserve_empty_extra"

    rt = (main.get("recordTypeName") or "").strip()
    rt_l = rt.lower()

    has_compliance = _safe_to_datetime(extra.get("Compliance Date")) is not pd.NaT
    case_closed = str(extra.get("Case Closed") or "").strip().lower() == "true"
    if has_compliance or case_closed:
        return "citizenserve_code_closed"

    if "code compliance" in rt_l:
        return "citizenserve_code_compliance"

    if (
        "cannabis" in rt_l
        or "background disclosure" in rt_l
        or "massage" in rt_l
    ):
        return "citizenserve_cannabis"

    if "business license" in rt_l:
        return "citizenserve_business"

    if (
        "building permit" in rt_l
        or "old building" in rt_l
        or "solar" in rt_l
        or "vacant building" in rt_l
    ):
        return "citizenserve_building"

    if (
        "encroach" in rt_l
        or "engineering" in rt_l
        or "utility" in rt_l
        or rt_l.startswith("mswd")
        or "wide load" in rt_l
        or "transportation" in rt_l
    ):
        return "citizenserve_encroachment"

    if "vacation rental" in rt_l:
        return "citizenserve_vacation_rental"

    if (
        "garage sale" in rt_l
        or "special event" in rt_l
        or "temporary use" in rt_l
        or "film permit" in rt_l
        or "facility use" in rt_l
    ):
        return "citizenserve_temporary"

    if (
        "planning" in rt_l
        or "conditional use" in rt_l
        or "cup" in rt_l
        or "zoning" in rt_l
        or "variance" in rt_l
        or "lot line" in rt_l
        or "tentative" in rt_l
        or "development" in rt_l
        or "design review" in rt_l
        or "sign review" in rt_l
        or "home occupation" in rt_l
        or "environmental" in rt_l
    ):
        return "citizenserve_planning"

    return "citizenserve_form_other"


# ── Status mapping ──────────────────────────────────────────────────────────

# main.status (int) → STATUS_NORMALIZED
_STATUS_CODE_MAP = {
    0: "In Review",  # draft
    1: "Active",     # active
    2: "Final",      # complete
    -1: "Inactive",  # stopped
}


def _derive_status(main: dict) -> Optional[str]:
    """Map CitizenServe portal lifecycle code to STATUS_NORMALIZED.

    Desert Hot Springs has no Accela-style extra Status / Date Issued /
    Date Finaled fields to refine against. Form labels such as extra
    field 20656 (Active/Inactive on CE Archive) describe violation state,
    not the portal record lifecycle.
    """
    status = main.get("status")
    if status is None:
        return None
    try:
        code = int(status)
    except (TypeError, ValueError):
        return None
    return _STATUS_CODE_MAP.get(code)


def _preferred_file_date(main: dict) -> Optional[date]:
    """Application/submittal date: dateSubmitted, else dateCreated."""
    submitted = _utc_date(main.get("dateSubmitted"))
    if submitted is not None:
        return submitted
    return _utc_date(main.get("dateCreated"))


def _final_date_from_extra(extra: dict, effective_status):
    """Compliance / close-out date for Final code-enforcement rows."""
    if effective_status != "Final":
        return pd.NaT
    return _safe_to_datetime(extra.get("Compliance Date"))


# ── Per-record repair logic ─────────────────────────────────────────────────

def _repair_record(row, d: dict, repairs: dict):
    """Populate *repairs* with corrected values for a single DHS record."""
    main = _main(d)
    extra = _extra(d)

    # -- STATUS_NORMALIZED --
    current_status = row["STATUS_NORMALIZED"]
    expected = _derive_status(main)
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
    # No reliable issuance/approval timestamp in DATA; leave as-is.

    # -- FINAL_DATE --
    final_dt = _final_date_from_extra(extra, effective_status)
    if final_dt is not pd.NaT and not pd.isna(final_dt):
        if pd.isna(row["FINAL_DATE"]):
            repairs["FINAL_DATE"] = final_dt
            repairs["FINAL_DATE_FLAG"] = "FILLED"
        else:
            cur_final = _safe_to_datetime(row["FINAL_DATE"])
            if (
                cur_final is pd.NaT
                or pd.isna(cur_final)
                or cur_final.normalize() != final_dt.normalize()
            ):
                repairs["FINAL_DATE"] = final_dt
                repairs["FINAL_DATE_FLAG"] = "FIXED"
    elif (
        effective_status != "Final"
        and not pd.isna(row["FINAL_DATE"])
    ):
        repairs["FINAL_DATE"] = pd.NaT
        repairs["FINAL_DATE_FLAG"] = "FIXED"


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Desert Hot Springs permit records using information from the raw DATA
    JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Desert Hot Springs".  Must
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
    from pathlib import Path

    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[3] / ".env")
    MY_DATA_PATH = os.getenv("MY_DATA_PATH")
    AGENT_DATA_PATH = os.getenv("AGENT_DATA_PATH")
    filepath = os.path.join(
        MY_DATA_PATH, "processed_data", "permits_ca_sample.parquet"
    )
    df = pd.read_parquet(filepath)
    city = df[
        (df["JURISDICTION"] == "Desert Hot Springs") & (df["STATE"] == "CA")
    ].copy()

    print(f"Desert Hot Springs records: {len(city):,}\n")

    repaired = data_repair(city)

    if AGENT_DATA_PATH:
        out_dir = Path(AGENT_DATA_PATH) / "repaired"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "permits_ca_desert_hot_springs_repaired.parquet"
        for col in ["FILE_DATE", "PERMIT_DATE", "FINAL_DATE"]:
            repaired[col] = pd.to_datetime(repaired[col], errors="coerce")
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

    print("\nSTATUS transitions (where flagged):")
    flagged = repaired[repaired["STATUS_NORMALIZED_FLAG"].notna()].copy()
    if len(flagged):
        flagged["before"] = city.loc[flagged.index, "STATUS_NORMALIZED"]
        print(
            flagged.groupby(
                [
                    flagged["before"].fillna("(null)"),
                    "STATUS_NORMALIZED",
                    "STATUS_NORMALIZED_FLAG",
                ]
            )
            .size()
            .rename("n")
            .reset_index()
            .to_string(index=False)
        )
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

    print("\nChronology checks (after repair):")
    f = pd.to_datetime(repaired["FILE_DATE"], errors="coerce")
    p = pd.to_datetime(repaired["PERMIT_DATE"], errors="coerce")
    fin = pd.to_datetime(repaired["FINAL_DATE"], errors="coerce")
    inv_fp = f.notna() & p.notna() & (p.dt.normalize() < f.dt.normalize())
    inv_pf = p.notna() & fin.notna() & (fin.dt.normalize() < p.dt.normalize())
    inv_ff = f.notna() & fin.notna() & (fin.dt.normalize() < f.dt.normalize())
    print(f"  PERMIT < FILE: {inv_fp.sum()}")
    print(f"  FINAL < PERMIT: {inv_pf.sum()}")
    print(f"  FINAL < FILE: {inv_ff.sum()}")

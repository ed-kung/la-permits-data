"""Data repair for Tehama County (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Tehama County DATA is a CitizenServe / OpenGov-style payload with
top-level keys ``main``, ``extra``, and ``location``. Content variants
(INFERRED_SCHEMA):

  - citizenserve_legacy_building_v1: Building Permit v1 + ASI 16681 status
  - citizenserve_legacy_reroof:      Residential Re-Roofing + ASI 16701
  - citizenserve_legacy_mh:          Manufactured Home + ASI 16691
  - citizenserve_legacy_ag_exempt:   Agricultural Building Exemption + 16711
  - citizenserve_code_closed:        Code Enforcement with close date 17056
  - citizenserve_code:               Code Enforcement without close date
  - citizenserve_modern_building:    Building Permit / solar / electrical /
                                     re-roof / HVAC / demo modern forms
  - citizenserve_plot_plan:          PPA / plot-plan shells
  - citizenserve_marijuana:          Marijuana Enforcement Case
  - citizenserve_planning:           merger / lot line / use permit
  - citizenserve_form_other:         other named/numeric form fields
  - citizenserve_empty_extra:        empty extra dict
  - unknown / missing

Canonical mappings:
  - main.status (0/1/2/-1), overridden by legacy ASI status strings
    (16681 / 16701 / 16691 / 16711 / 17062) → STATUS_NORMALIZED
  - dateSubmitted (else dateCreated) → FILE_DATE
  - no reliable issuance timestamp in DATA → PERMIT_DATE unchanged
  - Code Enforcement ASI 17056 when effective status is Final
                                                      → FINAL_DATE

Known issues repaired:
  - STATUS_NORMALIZED mirrored coarse main.status / STATUS_ORIGINAL only.
    Legacy building / MH / reroof / ag / CE ASI labels contradict that:
    EXPIRED / CANCELLED / VOID left as Final → FIXED to Inactive;
    ACTIVE / APPROVED / AVTIVE left as Final → FIXED to Active;
    FINALED left as Active → FIXED to Final;
    PEND ISSUE left as Active/Final/Inactive → FIXED to In Review;
    CE ACTIVE left as Final → FIXED to Active.
  - FILE_DATE taken from dateCreated. When dateSubmitted falls on a
    different calendar day (late online submit, or bulk 2020-08-21
    migration shells whose submitted/ASI date is the historical
    application day) → FIXED to dateSubmitted.
  - PERMIT_DATE / FINAL_DATE universally missing; fill FINAL_DATE from
    CE close date 17056 when status is Final.

Not repairable from DATA:
  - No Date Issued / Permit Issuance Date (or equivalent) on modern or
    legacy building forms → PERMIT_DATE stays missing for Active/Final.
  - Legacy FINALED building / reroof / MH / ag rows have no finaling
    timestamp → FINAL_DATE stays missing.
  - Modern building / plot-plan / planning / marijuana forms lack
    issuance and finaling timestamps.
"""

from __future__ import annotations

import json
import math
from datetime import date, datetime
from typing import Optional

import numpy as np
import pandas as pd


_MIN_YEAR = 1950
_MAX_YEAR = 2035
_SENTINEL_YEAR = 1900

# Legacy Accela-style ASI status field IDs by migrated record family.
_ASI_STATUS_KEYS = ("16681", "16701", "16691", "16711", "17062")

# Legacy application / open-date ASI field IDs (redundant with dateSubmitted).
_ASI_FILE_KEYS = ("16674", "16694", "16684", "16704", "17058")


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
        if not s or s.upper() in {"TBD", "NULL", "NONE", "N/A", "NA", "#N/A", "VOID", "VOIDED"}:
            return pd.NaT
    try:
        dt = pd.to_datetime(val, errors="coerce")
    except (ValueError, TypeError):
        return pd.NaT
    if pd.isna(dt):
        return pd.NaT
    year = int(dt.year)
    if year == _SENTINEL_YEAR:
        return pd.NaT
    if year < _MIN_YEAR or year > _MAX_YEAR:
        return pd.NaT
    if getattr(dt, "tzinfo", None) is not None:
        dt = dt.tz_convert("UTC").tz_localize(None)
    return dt


def _utc_date(val) -> Optional[date]:
    """Parse a timestamp and return its UTC calendar date (reject sentinels)."""
    if val is None or (isinstance(val, str) and not val.strip()):
        return None
    try:
        ts = pd.to_datetime(val, utc=True, errors="coerce")
    except (ValueError, TypeError):
        return None
    if pd.isna(ts):
        return None
    year = int(ts.year)
    if year == _SENTINEL_YEAR:
        return None
    if year < _MIN_YEAR or year > _MAX_YEAR:
        return None
    return ts.date()


def _as_date(val) -> Optional[date]:
    """Normalize a FILE_DATE-like value to datetime.date (None if sentinel)."""
    if _is_missing(val):
        return None
    if isinstance(val, date) and not isinstance(val, datetime):
        if val.year == _SENTINEL_YEAR:
            return None
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

    if extra.get("16681") is not None or rt == "Building Permit v1":
        return "citizenserve_legacy_building_v1"
    if (
        extra.get("16701") is not None
        or rt == "Residential Re-Roofing Supplemental Application"
    ):
        return "citizenserve_legacy_reroof"
    if extra.get("16691") is not None or rt == "Manufactured Home Building Permit":
        return "citizenserve_legacy_mh"
    if (
        extra.get("16711") is not None
        or rt == "Agricultural Building Exemption Permit"
    ):
        return "citizenserve_legacy_ag_exempt"

    if (
        extra.get("17062") is not None
        or "code enforcement" in rt_l
    ):
        if _safe_to_datetime(extra.get("17056")) is not pd.NaT:
            return "citizenserve_code_closed"
        return "citizenserve_code"

    if "marijuana" in rt_l:
        return "citizenserve_marijuana"

    if (
        rt == "Building Permit"
        or "solar" in rt_l
        or "electrical" in rt_l
        or rt_l in {"re-roof", "hvac", "mechanical"}
        or "demo" in rt_l
    ):
        return "citizenserve_modern_building"

    if "Use" in extra or "Zoning" in extra or rt_l.startswith("plot"):
        return "citizenserve_plot_plan"

    if (
        "planning" in rt_l
        or "merger" in rt_l
        or "lot line" in rt_l
        or "use permit" in rt_l
        or "administrative use" in rt_l
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

# Legacy ASI status string → STATUS_NORMALIZED
_ASI_STATUS_MAP = {
    "FINALED": "Final",
    "CLOSED": "Final",
    "RENEWED": "Final",
    "ACTIVE": "Active",
    "AVTIVE": "Active",  # typo in source
    "APPROVED": "Active",
    "EXPIRED": "Inactive",
    "CANCELLED": "Inactive",
    "CANCELED": "Inactive",
    "VOID": "Inactive",
    "PEND ISSUE": "In Review",
}


def _asi_status_raw(extra: dict) -> Optional[str]:
    for key in _ASI_STATUS_KEYS:
        val = extra.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip().upper()
    return None


def _status_from_main(main: dict) -> Optional[str]:
    status = main.get("status")
    if status is None:
        return None
    try:
        code = int(status)
    except (TypeError, ValueError):
        return None
    return _STATUS_CODE_MAP.get(code)


def _derive_status(main: dict, extra: dict) -> Optional[str]:
    """Prefer legacy ASI lifecycle labels over coarse main.status codes."""
    asi = _asi_status_raw(extra)
    if asi is not None:
        mapped = _ASI_STATUS_MAP.get(asi)
        if mapped is not None:
            return mapped
    return _status_from_main(main)


def _preferred_file_date(main: dict, extra: dict) -> Optional[date]:
    """Application/submittal date: dateSubmitted, else dateCreated, else ASI."""
    submitted = _utc_date(main.get("dateSubmitted"))
    if submitted is not None:
        return submitted
    created = _utc_date(main.get("dateCreated"))
    if created is not None:
        return created
    for key in _ASI_FILE_KEYS:
        dt = _safe_to_datetime(extra.get(key))
        if dt is not pd.NaT and not pd.isna(dt):
            return dt.date()
    return None


def _final_date_from_extra(extra: dict, effective_status):
    """Code-enforcement close date (ASI 17056) when status is Final."""
    if effective_status != "Final":
        return pd.NaT
    return _safe_to_datetime(extra.get("17056"))


# ── Per-record repair logic ─────────────────────────────────────────────────

def _repair_record(row, d: dict, repairs: dict):
    """Populate *repairs* with corrected values for a single Tehama record."""
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
    preferred = _preferred_file_date(main, extra)
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
    Tehama County permit records using information from the raw DATA JSON
    column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Tehama County".  Must
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
    from dotenv import load_dotenv

    load_dotenv("/Users/ekung/projects/la-permits-data/.env")
    MY_DATA_PATH = os.getenv("MY_DATA_PATH")
    filepath = os.path.join(MY_DATA_PATH, "processed_data", "permits_ca_sample.parquet")
    df = pd.read_parquet(filepath)
    tehama = df[(df["JURISDICTION"] == "Tehama County") & (df["STATE"] == "CA")].copy()

    print(f"Tehama County records: {len(tehama):,}\n")

    repaired = data_repair(tehama)

    print("INFERRED_SCHEMA:")
    print(repaired["INFERRED_SCHEMA"].value_counts(dropna=False).to_string())
    print()

    for field in ["STATUS_NORMALIZED", "FILE_DATE", "PERMIT_DATE", "FINAL_DATE"]:
        flag_col = f"{field}_FLAG"
        n_filled = (repaired[flag_col] == "FILLED").sum()
        n_fixed = (repaired[flag_col] == "FIXED").sum()
        print(f"{field}:")
        print(f"  FILLED: {n_filled:>4,}   FIXED: {n_fixed:>4,}")

        before_missing = tehama[field].isna().sum()
        after_missing = repaired[field].isna().sum()
        print(f"  Missing before: {before_missing:>4,}   Missing after: {after_missing:>4,}")
        print()

    print("STATUS_NORMALIZED distribution:")
    print("  Before:")
    for s, c in tehama["STATUS_NORMALIZED"].value_counts(dropna=False).items():
        print(f"    {str(s):15s}: {c:>4,}")
    print("  After:")
    for s, c in repaired["STATUS_NORMALIZED"].value_counts(dropna=False).items():
        print(f"    {str(s):15s}: {c:>4,}")

    print("\nStatus transitions (before → after):")
    both = pd.DataFrame({
        "before": tehama["STATUS_NORMALIZED"].values,
        "after": repaired["STATUS_NORMALIZED"].values,
    })
    changed = both[both["before"].astype(str) != both["after"].astype(str)]
    if len(changed) == 0:
        print("  (none)")
    else:
        print(changed.groupby(["before", "after"], dropna=False).size().to_string())

    print("\nPost-repair completeness by status:")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        subset = repaired[repaired["STATUS_NORMALIZED"] == status]
        n = len(subset)
        if n == 0:
            continue
        file_pct = 100 * subset["FILE_DATE"].notna().mean()
        permit_pct = 100 * subset["PERMIT_DATE"].notna().mean()
        final_pct = 100 * subset["FINAL_DATE"].notna().mean()
        print(
            f"  {status:10s} n={n:>4,}  "
            f"FILE={file_pct:5.1f}%  PERMIT={permit_pct:5.1f}%  FINAL={final_pct:5.1f}%"
        )

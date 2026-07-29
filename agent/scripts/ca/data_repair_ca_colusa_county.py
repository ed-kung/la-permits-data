"""Data repair for Colusa County (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Colusa County DATA is a CitizenServe / OpenGov-style payload with
top-level keys ``main``, ``extra``, and ``location``. Content variants
(INFERRED_SCHEMA):

  - citizenserve_building_finaled: Final Inspection Date present
  - citizenserve_building_issued:  Permit Issuance Date present
  - citizenserve_building_legacy:  numeric ASI dates 24954 / 24958
  - citizenserve_well:             Water Well Application forms
  - citizenserve_planning:         Universal Planning Application
  - citizenserve_eh_facility:      Environmental Health facility permits
  - citizenserve_code:             Code Compliance Complaint forms
  - citizenserve_employee_daily:   Employee Daily Template
  - citizenserve_form_other:       other named/numeric form fields
  - citizenserve_empty_extra:      empty extra dict
  - unknown / missing

Canonical mappings:
  - main.status (0/1/2/-1), upgraded by final-inspection evidence
                                                      → STATUS_NORMALIZED
  - dateSubmitted (else dateCreated), else earliest legacy ASI /
    form application date; reject 1900-01-01 sentinel → FILE_DATE
  - Permit Issuance Date / 24958 / Date Approved /
    Permit Active Date / Approval Date (/ 24954 fallback)
                                                      → PERMIT_DATE
  - Final Inspection Date / Date of Final Inspection / 24981
    when effective status is Final                    → FINAL_DATE

Known issues repaired:
  - FILE_DATE taken from dateCreated; when dateSubmitted is a later
    calendar day → FIXED to submittal date.
  - Legacy building ASI 24954 (application) earlier than system
    created/submitted (= 24958 issuance) → FIXED FILE to 24954.
  - Missing FILE on historical building shells → FILLED from 24954.
  - Sentinel FILE_DATE 1900-01-01 on EH facility permits → FIXED from
    Permit Active Date / 25007.
  - PERMIT_DATE / FINAL_DATE universally missing; fill from named and
    numeric issuance / final-inspection fields when present.
  - Active rows with Final Inspection Date / Date of Final Inspection
    → FIXED to Final.
  - VOID shell with null main.status → FILLED as Inactive.
  - Stale planning ``Approval Date`` values that predate FILE_DATE are
    not used for PERMIT_DATE.

Not repairable from DATA:
  - Most modern building shells lack Permit Issuance Date /
    Final Inspection Date → PERMIT_DATE / FINAL_DATE stay missing.
  - Employee Daily / planning / many EH forms have no issuance or
    finaling timestamps.
  - A handful of empty building shells have no application/issue dates.
  - Primary Status (CLEAR) is a bond/contractor flag, not lifecycle.
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


def _is_void_shell(main: dict, extra: dict) -> bool:
    """True when the record is an explicit VOID placeholder."""
    for key in ("streetName", "fullAddress"):
        val = main.get(key)
        if isinstance(val, str) and val.strip().upper() in {"VOID", "VOIDED"}:
            return True
    voidish = 0
    n = 0
    for val in extra.values():
        if not isinstance(val, str) or not val.strip():
            continue
        n += 1
        if val.strip().upper() in {"VOID", "VOIDED"}:
            voidish += 1
    return n > 0 and voidish >= max(3, n - 1)


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

    rt = (main.get("recordTypeName") or "").strip().lower()

    if _safe_to_datetime(extra.get("Final Inspection Date")) is not pd.NaT:
        return "citizenserve_building_finaled"
    if _safe_to_datetime(extra.get("Permit Issuance Date")) is not pd.NaT:
        return "citizenserve_building_issued"
    if (
        _safe_to_datetime(extra.get("24954")) is not pd.NaT
        or _safe_to_datetime(extra.get("24958")) is not pd.NaT
    ):
        return "citizenserve_building_legacy"

    if "water well" in rt:
        return "citizenserve_well"
    if "planning" in rt:
        return "citizenserve_planning"
    if "environmental health general facility" in rt:
        return "citizenserve_eh_facility"
    if "code compliance" in rt:
        return "citizenserve_code"
    if "employee daily" in rt:
        return "citizenserve_employee_daily"

    return "citizenserve_form_other"


# ── Status mapping ──────────────────────────────────────────────────────────

# main.status (int) → STATUS_NORMALIZED
_STATUS_CODE_MAP = {
    0: "In Review",  # draft
    1: "Active",     # active
    2: "Final",      # complete
    -1: "Inactive",  # stopped
}


def _status_from_main(main: dict) -> Optional[str]:
    status = main.get("status")
    if status is None:
        return None
    try:
        code = int(status)
    except (TypeError, ValueError):
        return None
    return _STATUS_CODE_MAP.get(code)


def _has_final_inspection(extra: dict) -> bool:
    return (
        _safe_to_datetime(extra.get("Final Inspection Date")) is not pd.NaT
        or _safe_to_datetime(extra.get("Date of Final Inspection")) is not pd.NaT
    )


def _derive_status(main: dict, extra: dict) -> Optional[str]:
    """Map CitizenServe lifecycle code, with final-inspection / VOID upgrades."""
    if _is_void_shell(main, extra) and main.get("status") is None:
        return "Inactive"

    base = _status_from_main(main)
    if base == "Inactive":
        return "Inactive"
    if _has_final_inspection(extra) and base in ("Active", "In Review", "Final", None):
        return "Final"
    return base


# ── Date extractors ─────────────────────────────────────────────────────────

def _legacy_applied(extra: dict):
    """Legacy building application date (ASI 24954)."""
    return _safe_to_datetime(extra.get("24954"))


def _legacy_issued(extra: dict):
    """Legacy building issuance date (ASI 24958)."""
    return _safe_to_datetime(extra.get("24958"))


def _preferred_file_date(main: dict, extra: dict) -> Optional[date]:
    """Application/submittal date.

    Prefer dateSubmitted, else dateCreated. When legacy ASI 24954 is earlier
    than the system stamp (often equal to issuance 24958), use 24954.
    Fall back to form-specific application dates when main dates are absent
    or sentinel (1900-01-01).
    """
    submitted = _utc_date(main.get("dateSubmitted"))
    created = _utc_date(main.get("dateCreated"))
    system = submitted or created

    applied = _legacy_applied(extra)
    if applied is not pd.NaT and not pd.isna(applied):
        applied_d = applied.date()
        if system is None or applied_d <= system:
            # Prefer earlier paper/ASI application over system entry/issue stamp.
            if system is None or applied_d < system:
                return applied_d
            return system

    if submitted is not None:
        return submitted
    if created is not None:
        return created

    # Form-specific application / received dates (no system stamp).
    for key in (
        "25014",  # planning application date
        "25044",  # water well application date
        "25032",  # sewage application date
        "24984",  # code compliance received date
        "Permit Active Date",  # EH facility: prefer over period-start 25007
        "25007",  # EH facility period start
        "24960",  # legacy building alternate stamp (≈ issuance/file)
        "Date:",  # signed application date on some EH/sewage forms
    ):
        dt = _safe_to_datetime(extra.get(key))
        if dt is not pd.NaT and not pd.isna(dt):
            return dt.date()
    return None


def _permit_date_from_extra(extra: dict, effective_status, file_date: Optional[date] = None) -> pd.Timestamp:
    """Issuance / approval date from named fields and legacy ASI.

    Skips candidates that fall before FILE_DATE (e.g. stale planning
    ``Approval Date`` values from prior actions).
    """
    candidates = []

    for key in (
        "Permit Issuance Date",
        "24958",
        "Date Approved",
        "Permit Active Date",
        "25007",
        "24960",
    ):
        dt = _safe_to_datetime(extra.get(key))
        if dt is not pd.NaT and not pd.isna(dt):
            candidates.append(dt)

    # Single legacy date on Active/Final historical shells: best available
    # issuance/file stamp when no separate issue field exists.
    if effective_status in ("Active", "Final") and not candidates:
        applied = _legacy_applied(extra)
        if applied is not pd.NaT and not pd.isna(applied):
            candidates.append(applied)

    for dt in candidates:
        if file_date is not None and dt.date() < file_date:
            continue
        return dt
    return pd.NaT


def _final_date_from_extra(extra: dict, effective_status) -> pd.Timestamp:
    """Final inspection / close-out date when status is Final."""
    if effective_status != "Final":
        return pd.NaT

    for key in (
        "Final Inspection Date",
        "Date of Final Inspection",
        "24981",  # code compliance resolution / close date
    ):
        dt = _safe_to_datetime(extra.get(key))
        if dt is not pd.NaT and not pd.isna(dt):
            return dt
    return pd.NaT


# ── Per-record repair logic ─────────────────────────────────────────────────

def _repair_record(row, d: dict, repairs: dict):
    """Populate *repairs* with corrected values for a single Colusa County record."""
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
    # Treat sentinel 1900-01-01 stored in the row as incorrect (not missing).
    sentinel_file = False
    raw_fd = row["FILE_DATE"]
    if not _is_missing(raw_fd):
        try:
            raw_year = pd.to_datetime(raw_fd, errors="coerce")
            if not pd.isna(raw_year) and int(raw_year.year) == _SENTINEL_YEAR:
                sentinel_file = True
                current_fd = None
        except (ValueError, TypeError, AttributeError):
            pass

    if preferred is not None:
        if current_fd is None:
            repairs["FILE_DATE"] = pd.Timestamp(preferred)
            repairs["FILE_DATE_FLAG"] = "FIXED" if sentinel_file else "FILLED"
        elif current_fd != preferred:
            repairs["FILE_DATE"] = pd.Timestamp(preferred)
            repairs["FILE_DATE_FLAG"] = "FIXED"

    effective_file = preferred
    if effective_file is None:
        effective_file = current_fd

    # -- PERMIT_DATE --
    permit_dt = _permit_date_from_extra(extra, effective_status, effective_file)
    if permit_dt is not pd.NaT and not pd.isna(permit_dt):
        if pd.isna(row["PERMIT_DATE"]):
            repairs["PERMIT_DATE"] = permit_dt
            repairs["PERMIT_DATE_FLAG"] = "FILLED"
        else:
            cur_pd = _safe_to_datetime(row["PERMIT_DATE"])
            if (
                cur_pd is pd.NaT
                or pd.isna(cur_pd)
                or cur_pd.normalize() != permit_dt.normalize()
            ):
                repairs["PERMIT_DATE"] = permit_dt
                repairs["PERMIT_DATE_FLAG"] = "FIXED"

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
    Colusa County permit records using information from the raw DATA JSON
    column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Colusa County".  Must
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
        (df["JURISDICTION"] == "Colusa County") & (df["STATE"] == "CA")
    ].copy()

    print(f"Colusa County records: {len(city):,}\n")

    repaired = data_repair(city)

    if AGENT_DATA_PATH:
        out_dir = Path(AGENT_DATA_PATH) / "repaired"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "permits_ca_colusa_county_repaired.parquet"
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
        # Count sentinel 1900 as missing for FILE before stats
        if field == "FILE_DATE":
            before_fd = pd.to_datetime(city[field], errors="coerce")
            before_missing = int(
                before_fd.isna().sum()
                + ((before_fd.dt.year == 1900).fillna(False)).sum()
            )
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

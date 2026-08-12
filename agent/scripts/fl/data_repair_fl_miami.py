"""Data repair for Miami (FL) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Miami DATA is a City of Miami open-data / ArcGIS attribute payload with
``BuildingPermitStatusDescription``, ``FirstSubmissionDate``,
``PlanCreatedDate``, ``PlanAcceptedDate``, ``IssuedDate``,
``Statusdate``, ``Certificatedate``, and ``BuildingFinalLastInspDate``.
Three near-identical key-set variants appear in the sample
(``miami_arcgis_appnum``, ``miami_arcgis_bom_x``, ``miami_arcgis_xy``).

Canonical mappings:
  - DATA.BuildingPermitStatusDescription          → STATUS_NORMALIZED
  - FirstSubmissionDate; else PlanAcceptedDate;
    else PlanCreatedDate                          → FILE_DATE
  - IssuedDate                                    → PERMIT_DATE
  - Statusdate when status is Final (fallback
    BuildingFinalLastInspDate / Certificatedate)  → FINAL_DATE

Known issues repaired:
  - FILE_DATE missing on ~78% of rows because FirstSubmissionDate is
    blank (empty string) on newer exports; filled from PlanAcceptedDate
    (preferred; usually equals FirstSubmission when both exist) or
    PlanCreatedDate.

Already correct in the Florida sample (no flag churn expected):
  - STATUS_NORMALIZED matches BuildingPermitStatusDescription for all
    Active / Final / Hold / Expired / Revoked values.
  - PERMIT_DATE already equals IssuedDate on every row.
  - FINAL_DATE already equals Statusdate on every Final row and is
    absent on non-Final rows.
"""

from __future__ import annotations

import json
import math
from typing import Optional

import numpy as np
import pandas as pd


_MIN_YEAR = 1980
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
        if s.startswith("0001-01-01"):
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


# ── Status mapping ───────────────────────────────────────────────────────────

_STATUS_MAP = {
    "Active": "Active",
    "Final": "Final",
    "Hold": "In Review",
    "Expired": "Inactive",
    "Revoked": "Inactive",
}

_STATUS_MAP_LOWER = {k.lower(): v for k, v in _STATUS_MAP.items()}


def _raw_status(d: dict) -> str:
    status = d.get("BuildingPermitStatusDescription")
    if isinstance(status, str) and status.strip():
        return status.strip()
    return ""


def _map_status(data_status: str) -> Optional[str]:
    if not data_status:
        return None
    return _STATUS_MAP.get(data_status) or _STATUS_MAP_LOWER.get(data_status.lower())


def _is_permit_final_flag(d: dict) -> bool:
    val = d.get("IsPermitFinal")
    if isinstance(val, bool):
        return val
    if val is None:
        return False
    return str(val).strip().lower() in {"yes", "true", "1", "y"}


# ── Date extractors ──────────────────────────────────────────────────────────

def _file_date_from_data(d: dict):
    """Application / submittal date.

    Prefer FirstSubmissionDate (canonical when populated). When blank —
    common on newer Miami exports — fall back to PlanAcceptedDate
    (matches FirstSubmission on ~92% of dual-populated rows), then
    PlanCreatedDate (plan/application record creation).
    """
    for key in ("FirstSubmissionDate", "PlanAcceptedDate", "PlanCreatedDate"):
        dt = _safe_to_datetime(d.get(key))
        if dt is not pd.NaT and not pd.isna(dt):
            return dt
    return pd.NaT


def _permit_date_from_data(d: dict):
    return _safe_to_datetime(d.get("IssuedDate"))


def _final_date_from_data(d: dict):
    """Finalization / sign-off date for Final permits.

    Statusdate is the agency stamp when the permit became Final ("All
    Inspections are finalized") and matches existing FINAL_DATE for every
    Final row in the sample. Fall back to last building-final inspection
    or certificate date only if Statusdate is absent.
    """
    for key in ("Statusdate", "BuildingFinalLastInspDate", "Certificatedate"):
        dt = _safe_to_datetime(d.get(key))
        if dt is not pd.NaT and not pd.isna(dt):
            return dt
    return pd.NaT


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    if not isinstance(data_dict, dict):
        return "unknown"

    keys = set(data_dict.keys())
    if "BuildingPermitStatusDescription" not in keys or "IssuedDate" not in keys:
        return "unknown"

    if "ApplicationNumber" in keys:
        base = "miami_arcgis_appnum"
    elif "\ufeffX" in keys:
        base = "miami_arcgis_bom_x"
    elif "X" in keys or "Y" in keys:
        base = "miami_arcgis_xy"
    else:
        base = "miami_arcgis"

    file_dt = _file_date_from_data(data_dict)
    issued_dt = _permit_date_from_data(data_dict)
    has_file = file_dt is not pd.NaT and not pd.isna(file_dt)
    has_issued = issued_dt is not pd.NaT and not pd.isna(issued_dt)
    # "finaled" = agency Final status or explicit final flag / certificate
    raw = _raw_status(data_dict)
    mapped = _map_status(raw)
    has_final_signal = (
        mapped == "Final"
        or _is_permit_final_flag(data_dict)
        or (
            _safe_to_datetime(data_dict.get("Certificatedate")) is not pd.NaT
            and not pd.isna(_safe_to_datetime(data_dict.get("Certificatedate")))
        )
    )

    if has_issued and has_final_signal:
        return f"{base}_issued_finaled"
    if has_issued:
        return f"{base}_issued"
    if has_final_signal:
        return f"{base}_finaled"
    if has_file:
        return f"{base}_applied"
    return f"{base}_status_only"


# ── Per-record repair ────────────────────────────────────────────────────────

def _apply_date(repairs: dict, row, field: str, candidate, *, allow_fill: bool = True) -> None:
    cand = _safe_to_datetime(candidate)
    if cand is pd.NaT or pd.isna(cand):
        return
    current = row[field]
    if pd.isna(current):
        if allow_fill:
            repairs[field] = cand
            repairs[f"{field}_FLAG"] = "FILLED"
    elif not _dates_equal(current, cand):
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
    expected = _map_status(_raw_status(d))
    if expected is not None:
        if pd.isna(current_status):
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"
        elif current_status != expected:
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FIXED"

    effective_status = repairs.get("STATUS_NORMALIZED", current_status)

    # -- FILE_DATE --
    _apply_date(repairs, row, "FILE_DATE", _file_date_from_data(d))

    # -- PERMIT_DATE --
    issued = _permit_date_from_data(d)
    current_permit = row["PERMIT_DATE"]
    if issued is not pd.NaT and not pd.isna(issued):
        if pd.isna(current_permit):
            # Ideal: Active/Final; also keep for Hold (issued then held).
            if effective_status in ("Active", "Final", "In Review", "Inactive"):
                repairs["PERMIT_DATE"] = issued
                repairs["PERMIT_DATE_FLAG"] = "FILLED"
        elif not _dates_equal(current_permit, issued):
            repairs["PERMIT_DATE"] = issued
            repairs["PERMIT_DATE_FLAG"] = "FIXED"

    # -- FINAL_DATE --
    final_src = _final_date_from_data(d)
    if effective_status == "Final":
        _apply_date(repairs, row, "FINAL_DATE", final_src)
    else:
        _clear_date(repairs, row, "FINAL_DATE")


# ── Main entry point ─────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Miami permit records using information from the raw DATA JSON.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Miami".  Must contain
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
        (df["JURISDICTION"] == "Miami") & (df["STATE"] == "FL")
    ].copy()

    print(f"Miami records: {len(city):,}\n")
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

    print("\nFILE_DATE coverage by status (after):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FILE_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({(n_has/len(sub) if len(sub) else 0):.1%})")

    print("\nPERMIT_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["PERMIT_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({(n_has/len(sub) if len(sub) else 0):.1%})")

    print("\nFINAL_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FINAL_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({(n_has/len(sub) if len(sub) else 0):.1%})")

    # Consistency checks
    violations = 0
    for idx in repaired.index:
        row = repaired.loc[idx]
        d = _safe_parse(row["DATA"])
        if d is None:
            continue
        expected = _map_status(_raw_status(d))
        if expected is not None and row["STATUS_NORMALIZED"] != expected:
            violations += 1
        file_src = _file_date_from_data(d)
        if not (
            (pd.isna(row["FILE_DATE"]) and (file_src is pd.NaT or pd.isna(file_src)))
            or _dates_equal(row["FILE_DATE"], file_src)
        ):
            violations += 1
        issued = _permit_date_from_data(d)
        if issued is not pd.NaT and not pd.isna(issued):
            if pd.isna(row["PERMIT_DATE"]) or not _dates_equal(row["PERMIT_DATE"], issued):
                violations += 1
        if row["STATUS_NORMALIZED"] == "Final":
            final_src = _final_date_from_data(d)
            if final_src is not pd.NaT and not pd.isna(final_src):
                if pd.isna(row["FINAL_DATE"]) or not _dates_equal(row["FINAL_DATE"], final_src):
                    violations += 1
        else:
            if pd.notna(row["FINAL_DATE"]):
                violations += 1
    print(f"\nConsistency violations: {violations}")

    # FILE_DATE fill source breakdown
    fill_src = {"FirstSubmissionDate": 0, "PlanAcceptedDate": 0, "PlanCreatedDate": 0}
    for idx in repaired.index:
        if repaired.at[idx, "FILE_DATE_FLAG"] != "FILLED":
            continue
        d = _safe_parse(repaired.at[idx, "DATA"])
        fs = _safe_to_datetime(d.get("FirstSubmissionDate"))
        pa = _safe_to_datetime(d.get("PlanAcceptedDate"))
        pc = _safe_to_datetime(d.get("PlanCreatedDate"))
        fd = repaired.at[idx, "FILE_DATE"]
        if _dates_equal(fd, fs):
            fill_src["FirstSubmissionDate"] += 1
        elif _dates_equal(fd, pa):
            fill_src["PlanAcceptedDate"] += 1
        elif _dates_equal(fd, pc):
            fill_src["PlanCreatedDate"] += 1
    print("\nFILE_DATE FILLED sources:", fill_src)

    if agent_data_path:
        out_path = os.path.join(agent_data_path, "miami_repaired_sample.parquet")
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote repaired sample → {out_path}")

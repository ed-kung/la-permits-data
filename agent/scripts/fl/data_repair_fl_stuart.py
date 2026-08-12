"""Data repair for Stuart (FL) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Stuart DATA has two top-level shapes:

  1. CitizenServe / SmartGov (``main`` / ``extra`` / ``location``) —
     ~1,866 rows, almost all HIST migrations.
  2. Legacy permit extract (``permit_info``, ``inspection_info``, …) —
     135 rows from an older permitting system.

CitizenServe content variants (INFERRED_SCHEMA):

  - citizenserve_historical_building
  - citizenserve_building
  - citizenserve_btr
  - citizenserve_code
  - citizenserve_contractor
  - citizenserve_false_alarm
  - citizenserve_fire
  - citizenserve_draft
  - citizenserve_other

Legacy variant:

  - legacy_permit_info

Canonical mappings (CitizenServe):
  - main.status (0/1/2/-1)              → STATUS_NORMALIZED
  - APPLICATION DATE / ASI apply keys /
    main.dateCreated
    (NOT dateSubmitted — often equals
    ISSUED DATE on HIST rows)           → FILE_DATE
  - ISSUED DATE / ASI issue keys
    (building + BTR only)               → PERMIT_DATE
  - CO ISSUED DATE / ASI CO keys;
    CE resolution ASI when Final        → FINAL_DATE

Canonical mappings (legacy_permit_info):
  - permit_info.Status                  → STATUS_NORMALIZED
  - Application Date                    → FILE_DATE
  - Issued Date                         → PERMIT_DATE
  - C.O. Issued, else Passed final
    inspection                          → FINAL_DATE

Known issues repaired:
  - CitizenServe PERMIT_DATE / FINAL_DATE are almost universally
    missing upstream; filled from named HIST fields and unlabeled
    ASI extras when present.
  - Legacy Open rows were normalized to In Review despite having an
    Issued Date → FIXED to Active (Open means an open/active permit).
  - Legacy Final rows missing C.O. Issued can often take FINAL_DATE
    from a Passed/Approved ``*FINAL*`` inspection.

Not repairable from DATA:
  - ~62 False Alarm + ~8 Contractor Registration rows have null
    dateCreated/dateSubmitted and no apply ASI → FILE_DATE stays
    missing.
  - Fire Safety / most False Alarm rows have no issuance or
    completion timestamp in ``extra``.
  - Business Tax / Contractor Registration lack a reliable
    completion / CO field → FINAL_DATE stays missing.
  - Contractor Registration later ASI dates behave like renewals /
    expirations, not original issuance → PERMIT_DATE left alone.
"""

from __future__ import annotations

import json
import math
import re
from datetime import date, datetime
from typing import Optional

import numpy as np
import pandas as pd


_MIN_YEAR = 1980
_MAX_YEAR = 2035

_FINAL_INSP_RE = re.compile(r"final|\bco\b|certificate", re.IGNORECASE)
_INSP_PASS = {"p", "a", "passed", "approved", "pass"}

# Named + unlabeled ASI keys observed in Stuart CitizenServe extras.
_APPLY_KEYS = (
    "APPLICATION DATE",
    "16952",  # Building Permit apply
    "17387",  # Historical Building Permit apply (numeric sibling)
    "17633",  # Business Tax Receipt apply
    "16832",  # BTR - New Application apply
    "17092",  # Code Enforcement notice/apply
    "17575",  # Historical Code Enforcement apply
    "16942",  # False Alarm apply (subset)
    "16899",  # Contractor Registration apply
    "17684",  # Contractor Registration apply (sibling form)
)

_ISSUE_KEYS = (
    "ISSUED DATE",
    "16953",  # Building Permit issue
    "17414",  # Historical Building Permit issue
    "17631",  # Business Tax Receipt issue
    "16830",  # BTR - New Application issue
)

_FINAL_KEYS = (
    "CO ISSUED DATE",
    "16955",  # Building Permit CO / final
    "17403",  # Historical Building Permit CO / final
)

# Code Enforcement "resolution / close" ASI keys (Final only).
_CE_RESOLUTION_KEYS = (
    "17093",
    "17596",
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
    """Parse a date value, returning pd.NaT on failure / sentinel / OOR."""
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
        if s.startswith("0001-01-01") or "Jan  1 1900" in s or s.startswith("1900-01-01"):
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


def _as_date(val) -> Optional[date]:
    if _is_missing(val):
        return None
    if isinstance(val, date) and not isinstance(val, datetime):
        return val
    dt = _safe_to_datetime(val)
    if dt is pd.NaT or pd.isna(dt):
        return None
    return pd.Timestamp(dt).date()


def _dates_equal(a, b) -> bool:
    da, db = _as_date(a), _as_date(b)
    if da is None or db is None:
        return False
    return da == db


def _first_date(mapping: dict, keys: tuple[str, ...]):
    for key in keys:
        dt = _safe_to_datetime(mapping.get(key))
        if dt is not pd.NaT and not pd.isna(dt):
            return dt
    return pd.NaT


def _main(d: dict) -> dict:
    main = d.get("main")
    return main if isinstance(main, dict) else {}


def _extra(d: dict) -> dict:
    extra = d.get("extra")
    return extra if isinstance(extra, dict) else {}


def _permit_info(d: dict) -> dict:
    pi = d.get("permit_info")
    return pi if isinstance(pi, dict) else {}


# ── Schema classification ───────────────────────────────────────────────────

def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())

    if "permit_info" in keys and "main" not in keys:
        return "legacy_permit_info"

    if not {"main", "extra", "location"}.issubset(keys):
        if "main" in keys:
            return "main_only"
        return "unknown"

    main = _main(data_dict)
    rtype = (main.get("recordTypeName") or "").strip()
    rtype_l = rtype.lower()

    try:
        status_code = int(main.get("status"))
    except (TypeError, ValueError):
        status_code = None
    if status_code == 0:
        return "citizenserve_draft"

    if rtype == "Historical Building Permit":
        return "citizenserve_historical_building"
    if "building permit" in rtype_l:
        return "citizenserve_building"
    if "business tax" in rtype_l:
        return "citizenserve_btr"
    if "code enforcement" in rtype_l:
        return "citizenserve_code"
    if "contractor registration" in rtype_l:
        return "citizenserve_contractor"
    if "false alarm" in rtype_l:
        return "citizenserve_false_alarm"
    if "fire" in rtype_l:
        return "citizenserve_fire"
    return "citizenserve_other"


# ── Status mapping ──────────────────────────────────────────────────────────

_STATUS_CODE_MAP = {
    0: "In Review",  # draft
    1: "Active",
    2: "Final",      # complete
    -1: "Inactive",  # stopped
}

_LEGACY_STATUS_MAP = {
    "Closed": "Final",
    "Open": "Active",       # open/active permit (was wrongly In Review)
    "Expired": "Inactive",
    "Void": "Inactive",
}


def _derive_status_citizenserve(main: dict) -> Optional[str]:
    status = main.get("status")
    if status is None:
        return None
    try:
        return _STATUS_CODE_MAP.get(int(status))
    except (TypeError, ValueError):
        return None


def _derive_status_legacy(pi: dict) -> Optional[str]:
    raw = (pi.get("Status") or "").strip()
    if not raw:
        return None
    if raw in _LEGACY_STATUS_MAP:
        return _LEGACY_STATUS_MAP[raw]
    for key, val in _LEGACY_STATUS_MAP.items():
        if key.lower() == raw.lower():
            return val
    return None


def _apply_status(repairs: dict, current, expected: Optional[str]):
    if expected is None:
        return None if pd.isna(current) else current
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
        return
    if not _dates_equal(current, cand):
        repairs[field] = cand
        repairs[f"{field}_FLAG"] = "FIXED"


def _clear_date(repairs: dict, row, field: str) -> None:
    current = repairs.get(field, row[field])
    if pd.isna(current):
        return
    repairs[field] = pd.NaT
    repairs[f"{field}_FLAG"] = "FIXED"


# ── Date extractors ─────────────────────────────────────────────────────────

def _file_date_citizenserve(main: dict, extra: dict):
    """Prefer explicit apply ASI / APPLICATION DATE, else dateCreated.

    ``dateSubmitted`` is intentionally ignored: on Stuart HIST building
    rows it frequently equals ISSUED DATE rather than the application
    day, and FILE_DATE already tracks dateCreated / APPLICATION DATE.
    """
    apply = _first_date(extra, _APPLY_KEYS)
    if apply is not pd.NaT and not pd.isna(apply):
        return apply
    created = _safe_to_datetime(main.get("dateCreated"))
    if created is not pd.NaT and not pd.isna(created):
        return created
    return pd.NaT


def _permit_date_citizenserve(extra: dict, schema: str):
    """Issuance date for building / BTR forms only."""
    if schema not in {
        "citizenserve_historical_building",
        "citizenserve_building",
        "citizenserve_btr",
    }:
        return pd.NaT
    return _first_date(extra, _ISSUE_KEYS)


def _final_date_citizenserve(extra: dict, schema: str, effective_status, file_dt):
    if effective_status != "Final":
        return pd.NaT

    final = _first_date(extra, _FINAL_KEYS)
    if final is not pd.NaT and not pd.isna(final):
        return final

    if schema == "citizenserve_code":
        resolution = _first_date(extra, _CE_RESOLUTION_KEYS)
        if resolution is pd.NaT or pd.isna(resolution):
            return pd.NaT
        # Prefer resolution dates on/after the file/notice day.
        file_day = _as_date(file_dt)
        res_day = _as_date(resolution)
        if file_day is None or res_day is None or res_day >= file_day:
            return resolution
    return pd.NaT


def _final_inspection_date_legacy(d: dict):
    """Latest Passed/Approved inspection whose TYPE looks final."""
    inspections = d.get("inspection_info")
    if not isinstance(inspections, list):
        return pd.NaT
    candidates = []
    for insp in inspections:
        if not isinstance(insp, dict):
            continue
        res = str(insp.get("RES") or "").strip().lower().rstrip(".")
        if res not in _INSP_PASS:
            continue
        typ = str(insp.get("TYPE") or "")
        if not _FINAL_INSP_RE.search(typ):
            continue
        dt = _safe_to_datetime(insp.get("INSP DATE"))
        if dt is not pd.NaT and not pd.isna(dt):
            candidates.append(dt)
    return max(candidates) if candidates else pd.NaT


# ── Per-record repair ───────────────────────────────────────────────────────

def _repair_citizenserve(row, d: dict, schema: str, repairs: dict) -> None:
    main = _main(d)
    extra = _extra(d)

    expected = _derive_status_citizenserve(main)
    effective = _apply_status(repairs, row["STATUS_NORMALIZED"], expected)

    file_dt = _file_date_citizenserve(main, extra)
    if file_dt is not pd.NaT and not pd.isna(file_dt):
        _apply_date(repairs, row, "FILE_DATE", file_dt)

    issue = _permit_date_citizenserve(extra, schema)
    if issue is not pd.NaT and not pd.isna(issue):
        if effective in ("Active", "Final", "Inactive"):
            _apply_date(repairs, row, "PERMIT_DATE", issue)
        elif effective == "In Review":
            _clear_date(repairs, row, "PERMIT_DATE")
    elif effective == "In Review":
        _clear_date(repairs, row, "PERMIT_DATE")

    final = _final_date_citizenserve(extra, schema, effective, file_dt)
    if effective == "Final":
        if final is not pd.NaT and not pd.isna(final):
            _apply_date(repairs, row, "FINAL_DATE", final)
    else:
        _clear_date(repairs, row, "FINAL_DATE")


def _repair_legacy(row, d: dict, repairs: dict) -> None:
    pi = _permit_info(d)

    expected = _derive_status_legacy(pi)
    effective = _apply_status(repairs, row["STATUS_NORMALIZED"], expected)

    app = _safe_to_datetime(pi.get("Application Date"))
    if app is not pd.NaT and not pd.isna(app):
        _apply_date(repairs, row, "FILE_DATE", app)

    issued = _safe_to_datetime(pi.get("Issued Date"))
    if issued is not pd.NaT and not pd.isna(issued):
        if effective in ("Active", "Final", "Inactive"):
            _apply_date(repairs, row, "PERMIT_DATE", issued)
        elif effective == "In Review":
            _clear_date(repairs, row, "PERMIT_DATE")
    elif effective == "In Review":
        _clear_date(repairs, row, "PERMIT_DATE")

    co = _safe_to_datetime(pi.get("C.O. Issued"))
    if (co is pd.NaT or pd.isna(co)) and effective == "Final":
        co = _final_inspection_date_legacy(d)

    if effective == "Final":
        if co is not pd.NaT and not pd.isna(co):
            _apply_date(repairs, row, "FINAL_DATE", co)
    else:
        _clear_date(repairs, row, "FINAL_DATE")


def _repair_record(row, d: dict, schema: str, repairs: dict) -> None:
    if schema == "legacy_permit_info":
        _repair_legacy(row, d, repairs)
    elif schema.startswith("citizenserve") or schema == "main_only":
        _repair_citizenserve(row, d, schema, repairs)


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Stuart permit records using the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Stuart".  Must contain
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

    for col in ("FILE_DATE", "PERMIT_DATE", "FINAL_DATE"):
        out[col] = pd.to_datetime(out[col], errors="coerce", utc=True).dt.tz_localize(None)
        out[col] = out[col].astype(object)

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
        _repair_record(row, d, schema, repairs)
        for key, value in repairs.items():
            out.at[idx, key] = value

    for col in ("FILE_DATE", "PERMIT_DATE", "FINAL_DATE"):
        out[col] = pd.to_datetime(out[col], errors="coerce", utc=True).dt.tz_localize(None)

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
    filepath = os.path.join(my_data_path, "processed_data", "permits_fl_sample.parquet")
    df = pd.read_parquet(filepath)
    city = df[(df["JURISDICTION"] == "Stuart") & (df["STATE"] == "FL")].copy()

    print(f"Stuart records: {len(city):,}\n")

    repaired = data_repair(city)

    print("INFERRED_SCHEMA:")
    for s, c in repaired["INFERRED_SCHEMA"].value_counts(dropna=False).items():
        print(f"  {str(s):40s}: {c:>4,}")
    print()

    for field in ["STATUS_NORMALIZED", "FILE_DATE", "PERMIT_DATE", "FINAL_DATE"]:
        flag_col = f"{field}_FLAG"
        n_filled = (repaired[flag_col] == "FILLED").sum()
        n_fixed = (repaired[flag_col] == "FIXED").sum()
        print(f"{field}:")
        print(f"  FILLED: {n_filled:>4,}   FIXED: {n_fixed:>4,}")
        before_missing = city[field].isna().sum()
        after_missing = repaired[field].isna().sum()
        print(f"  Missing before: {before_missing:>4,}   Missing after: {after_missing:>4,}")
        print()

    print("STATUS_NORMALIZED distribution:")
    print("  Before:")
    for s, c in city["STATUS_NORMALIZED"].value_counts(dropna=False).items():
        print(f"    {str(s):15s}: {c:>4,}")
    print("  After:")
    for s, c in repaired["STATUS_NORMALIZED"].value_counts(dropna=False).items():
        print(f"    {str(s):15s}: {c:>4,}")

    print("\nCoverage by STATUS_NORMALIZED (after):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        if len(sub) == 0:
            continue
        for field in ["FILE_DATE", "PERMIT_DATE", "FINAL_DATE"]:
            n_has = sub[field].notna().sum()
            print(
                f"  {status:12s} {field:12s}: "
                f"{n_has:>4,} / {len(sub):>4,} ({n_has / len(sub):.1%})"
            )

    print("\nFlags by INFERRED_SCHEMA (PERMIT_DATE_FLAG / FINAL_DATE_FLAG):")
    for schema, sub in repaired.groupby("INFERRED_SCHEMA"):
        n_pf = (sub["PERMIT_DATE_FLAG"] == "FILLED").sum()
        n_px = (sub["PERMIT_DATE_FLAG"] == "FIXED").sum()
        n_ff = (sub["FINAL_DATE_FLAG"] == "FILLED").sum()
        n_fx = (sub["FINAL_DATE_FLAG"] == "FIXED").sum()
        n_sf = (sub["STATUS_NORMALIZED_FLAG"] == "FIXED").sum()
        if n_pf or n_px or n_ff or n_fx or n_sf:
            print(
                f"  {schema:40s} "
                f"status_fix={n_sf:>3} "
                f"permit F/X={n_pf:>4}/{n_px:>3} "
                f"final F/X={n_ff:>4}/{n_fx:>3}"
            )

    if agent_data_path:
        out_path = os.path.join(agent_data_path, "stuart_repaired_sample.parquet")
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote repaired sample → {out_path}")

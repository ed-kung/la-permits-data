"""Data repair for Cocoa Beach (FL) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED"
or "FIXED" annotations for every value that was changed.

Cocoa Beach DATA is a CitizenServe / SmartGov-style payload with
top-level keys ``main``, ``extra``, and ``location``. Content variants
(INFERRED_SCHEMA):

  - citizenserve_draft:              unsubmitted drafts (main.status == 0)
  - citizenserve_building:           BLDG / ROW building permits
  - citizenserve_btr:                business tax receipt applications
  - citizenserve_legacy_citations:   Legacy Civil Citations (LCC-* HIST)
  - citizenserve_citations:          modern Civil Citations / CB CITATIONS
  - citizenserve_code:               DS / CBPD / Code Enforcement
  - citizenserve_reclaimed:          WR Reclaimed Water Inspection Report
  - citizenserve_vacation_rental:    vacation rental registrations
  - citizenserve_other:              garage sale, P&Z, events, tests, …
  - unknown / missing

Canonical mappings:
  - main.status (0/1/2/-1), with Voided
    legacy citation override → Inactive     → STATUS_NORMALIZED
  - Legacy CitDate (HIST citations); else
    main.dateSubmitted; else
    main.dateCreated                        → FILE_DATE
  - extra['DATE ISSUED'] / CitDate
    (Active/Final citations only)           → PERMIT_DATE
  - Closing date / Date of Compliance /
    Abatement Date (code, Final); else
    extra['Date:'] (reclaimed, Final); else
    End Date / End of Garage Sale (Final)   → FINAL_DATE

Known issues repaired:
  - Five rows with STATUS_ORIGINAL=active / STATUS_NORMALIZED=Active
    while main.status==2 (complete) → FIXED to Final.
  - Twelve Legacy Civil Citations with Status Desc=Voided still
    labeled Final via main.status==2 → FIXED to Inactive.
  - FILE_DATE missing on 3 rows that have dateSubmitted → FILLED.
  - FILE_DATE often equals dateCreated when dateSubmitted falls on a
    later calendar day → FIXED to submittal date.
  - Legacy Civil Citations FILE_DATE is the 2025 CitizenServe import
    day; CitDate is the historical citation date → FIXED.
  - PERMIT_DATE / FINAL_DATE are universally missing upstream; a
    subset can be filled from citation issue dates, CE closing /
    compliance dates, reclaimed-water inspection dates, and sparse
    event end dates.

Not repairable from DATA:
  - Modern BLDG / BTR / vacation-rental Active and Final rows have no
    issuance or CO / final timestamp in ``extra`` (expirationDate and
    lastUpdatedDate are not safe proxies).
  - Legacy citation Final rows have CitDate (used as PERMIT_DATE) but
    no payment / close timestamp for FINAL_DATE.
"""

from __future__ import annotations

import json
import math
from datetime import date, datetime
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
    """Parse a date value, returning pd.NaT on failure or implausible year."""
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


def _as_date(val) -> Optional[date]:
    """Normalize a datelike value to datetime.date."""
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
    rtype = (main.get("recordTypeName") or "").strip()
    rtype_l = rtype.lower()

    # Legacy citations keep their form schema even when main.status==0
    # (unsubmitted shells) so CitDate can still correct FILE_DATE.
    if rtype == "Legacy Civil Citations":
        return "citizenserve_legacy_citations"

    try:
        status_code = int(main.get("status"))
    except (TypeError, ValueError):
        status_code = None
    if status_code == 0:
        return "citizenserve_draft"

    if "citation" in rtype_l:
        return "citizenserve_citations"
    if "reclaimed water" in rtype_l:
        return "citizenserve_reclaimed"
    if "code enforcement" in rtype_l or rtype_l.startswith("ds code"):
        return "citizenserve_code"
    if "business tax" in rtype_l or rtype_l.startswith("btr"):
        return "citizenserve_btr"
    if "vacation rental" in rtype_l:
        return "citizenserve_vacation_rental"
    if "building permit" in rtype_l or "right of way" in rtype_l:
        return "citizenserve_building"

    return "citizenserve_other"


# ── Status mapping ──────────────────────────────────────────────────────────

_STATUS_CODE_MAP = {
    0: "In Review",  # draft
    1: "Active",     # active
    2: "Final",      # complete
    -1: "Inactive",  # stopped
}


def _derive_status(main: dict, extra: dict, schema: str) -> Optional[str]:
    status = main.get("status")
    if status is None:
        return None
    try:
        code = int(status)
    except (TypeError, ValueError):
        return None
    expected = _STATUS_CODE_MAP.get(code)

    # Legacy citation form status can refine Voided completes.
    if schema == "citizenserve_legacy_citations":
        desc = str(extra.get("Status Desc") or "").strip().lower()
        code_letter = str(extra.get("Status") or "").strip().upper()
        if desc == "voided" or code_letter == "V":
            return "Inactive"

    return expected


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

def _file_date_from_data(main: dict, extra: dict, schema: str):
    """Best application / citation / submittal date available in DATA."""
    if schema == "citizenserve_legacy_citations":
        cit = _safe_to_datetime(extra.get("CitDate"))
        if cit is not pd.NaT and not pd.isna(cit):
            return cit
        entered = _safe_to_datetime(extra.get("Entered On"))
        if entered is not pd.NaT and not pd.isna(entered):
            return entered

    submitted = _safe_to_datetime(main.get("dateSubmitted"))
    if submitted is not pd.NaT and not pd.isna(submitted):
        return submitted

    created = _safe_to_datetime(main.get("dateCreated"))
    if created is not pd.NaT and not pd.isna(created):
        return created

    return pd.NaT


def _permit_date_from_data(extra: dict, schema: str):
    """Issuance / citation date when present."""
    if schema == "citizenserve_citations":
        return _first_date(extra, ("DATE ISSUED", "Date Issued"))
    if schema == "citizenserve_legacy_citations":
        return _safe_to_datetime(extra.get("CitDate"))
    # Modern CE sometimes carries DATE ISSUED on citation-like forms.
    if schema == "citizenserve_code":
        return _first_date(extra, ("DATE ISSUED", "Date Issued"))
    return pd.NaT


def _final_date_from_data(extra: dict, schema: str, effective_status):
    """Completion / close / inspection date when status is Final."""
    if effective_status != "Final":
        return pd.NaT

    if schema == "citizenserve_code":
        closing = _first_date(
            extra,
            (
                "Closing date",
                "Date of Compliance",
                "Abatement Date",
                "Corrective Action Date",
            ),
        )
        if closing is not pd.NaT and not pd.isna(closing):
            return closing

    if schema == "citizenserve_reclaimed":
        insp = _safe_to_datetime(extra.get("Date:"))
        if insp is not pd.NaT and not pd.isna(insp):
            return insp

    if schema in {"citizenserve_building", "citizenserve_other"}:
        end = _first_date(
            extra,
            (
                "End Date",
                "End of Garage Sale : ",
                "Event End Date",
            ),
        )
        if end is not pd.NaT and not pd.isna(end):
            return end

    return pd.NaT


# ── Per-record repair logic ─────────────────────────────────────────────────

def _repair_record(row, d: dict, schema: str, repairs: dict) -> None:
    main = _main(d)
    extra = _extra(d)

    expected = _derive_status(main, extra, schema)
    effective = _apply_status(repairs, row["STATUS_NORMALIZED"], expected)

    file_dt = _file_date_from_data(main, extra, schema)
    if file_dt is not pd.NaT and not pd.isna(file_dt):
        _apply_date(repairs, row, "FILE_DATE", file_dt)

    issue = _permit_date_from_data(extra, schema)
    if issue is not pd.NaT and not pd.isna(issue):
        if effective in ("Active", "Final", "Inactive"):
            _apply_date(repairs, row, "PERMIT_DATE", issue)
        elif effective == "In Review":
            _clear_date(repairs, row, "PERMIT_DATE")
    elif effective == "In Review":
        _clear_date(repairs, row, "PERMIT_DATE")

    final = _final_date_from_data(extra, schema, effective)
    if effective == "Final":
        if final is not pd.NaT and not pd.isna(final):
            _apply_date(repairs, row, "FINAL_DATE", final)
    else:
        _clear_date(repairs, row, "FINAL_DATE")


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Cocoa Beach permit records using information from the raw DATA JSON.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Cocoa Beach".  Must contain
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
        _repair_record(row, d, schema, repairs)

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
    filepath = os.path.join(my_data_path, "processed_data", "permits_fl_sample.parquet")
    df = pd.read_parquet(filepath)
    city = df[(df["JURISDICTION"] == "Cocoa Beach") & (df["STATE"] == "FL")].copy()

    print(f"Cocoa Beach records: {len(city):,}\n")

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

    print("\nFILE_DATE_FLAG by INFERRED_SCHEMA:")
    ct = pd.crosstab(
        repaired["INFERRED_SCHEMA"],
        repaired["FILE_DATE_FLAG"].fillna("(none)"),
    )
    print(ct.to_string())

    if agent_data_path:
        out_path = os.path.join(agent_data_path, "cocoa_beach_repaired_sample.parquet")
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote repaired sample → {out_path}")

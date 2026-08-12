"""Data repair for Leon County (FL) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Leon County DATA is a Tallahassee/Leon shared permitting portal payload
with top-level keys Detail / Contacts / Inspections, optionally
Subtrades and/or a Date inspection index:

  - Detail.Current Status  → STATUS_NORMALIZED
  - Detail.Applied Date    → FILE_DATE
  - Detail.Status Date     → PERMIT_DATE (Active only) or
                             FINAL_DATE (Final only);
                             literal "Unavailable" means missing
  - Passed final-ish
    Inspections[].Date     → FINAL_DATE fallback when Status Date
                             is Unavailable

Known issues repaired:
  - 91 rows with unmapped Current Status (CERTOFOCC, NOC HOLD,
    INVOICED2, FINAL INSPECTION COMPLETED, …) → STATUS_NORMALIZED
    FILLED.
  - 59 COMPLIED code-enforcement rows labeled In Review → FIXED to
    Final (case closed / complied).
  - 3 CONDITIONAL LUCC rows labeled Final → FIXED to In Review.
  - Upstream copied Status Date into BOTH PERMIT_DATE and FINAL_DATE
    whenever Status Date was parseable. That makes FINAL_DATE wrong
    for non-Final rows and PERMIT_DATE wrong for Final / Inactive /
    In Review (no separate issue-date field exists in DATA).
  - 45 FINALED rows with Status Date "Unavailable" → FINAL_DATE
    FILLED from latest Approved/Y final inspection.

Not repairable from DATA:
  - FILE_DATE already matches Applied Date for every sample row.
  - No Issue / Issued date key exists anywhere in DATA, so Final
    PERMIT_DATE cannot be reconstructed; spurious Status Date copies
    are cleared instead.
  - 74 Final rows with Status Date Unavailable and no passed final
    inspection keep a missing FINAL_DATE (legacy Not Approved-only
    inspection histories, or closed code-compliance cases with no
    inspections).
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

_FINAL_INSP_RE = re.compile(
    r"final|certificate of (completion|occupancy)|\bcofo\b|certofocc|"
    r"closeout|permit final",
    re.IGNORECASE,
)
_PASS_OK = {"Approved", "Y"}

# Detail.Current Status (case-normalized) → STATUS_NORMALIZED
_STATUS_MAP = {
    # Final
    "COMPLETE": "Final",
    "CLOSED": "Final",
    "FINALED": "Final",
    "CERTIFICATE OF COMPLETION": "Final",
    "CERTIFICATE OF COMPLETION REDA": "Final",
    "CERTIFICATE OF OCCUPANCY": "Final",
    "CERTOFOCC": "Final",
    "COFO": "Final",
    "FINAL INSPECTION COMPLETED": "Final",
    "COMPLIED": "Final",
    # Active
    "ISSUED": "Active",
    "APPROVED": "Active",
    "RENEWED": "Active",
    "ROW_ISSUED": "Active",
    "ISSUED REDACTED": "Active",
    "APPROVED NOTIFY": "Active",
    "APPROVED NOTIFIED": "Active",
    "NOC HOLD": "Active",
    "CITYWRKS": "Active",
    # In Review
    "PENDING": "In Review",
    "PLANCHECK": "In Review",
    "PLANCK": "In Review",
    "PLANS REVIEW": "In Review",
    "PLAN REVIEW": "In Review",
    "OPEN": "In Review",
    "REFERRED": "In Review",
    "HOLD": "In Review",
    "CITY": "In Review",
    "REGISTERED": "In Review",
    "PAID": "In Review",
    "INVOICED": "In Review",
    "INVOICED2": "In Review",
    "ELIGIBLE": "In Review",
    "CLIENT RESUBMITTAL REQUIRED": "In Review",
    "CLIENT SUBMITTAL REQUIRED": "In Review",
    "DOCUMENTS RECEIVED": "In Review",
    "CLIENT - DEF. NOTICE ISSUED": "In Review",
    "CLIENT CONDITIONAL APPROVAL": "In Review",
    "CONDITIONAL APPROVAL": "In Review",
    "CONDITIONAL": "In Review",
    "NEW PERMIT(S) CREATED": "In Review",
    "NOTICE2": "In Review",
    "NOV": "In Review",
    "NOTICE OF VIOLATION": "In Review",
    # Inactive
    "EXPIRED": "Inactive",
    "VOID": "Inactive",
    "INVALID": "Inactive",
    "CANCELLED": "Inactive",
    "WITHDRAWN": "Inactive",
    "CEB FINDING": "Inactive",
    "CEB LIEN": "Inactive",
    "CODE ENFORCEMENT BOARD FINDING": "Inactive",
    "MOW-FINE": "Inactive",
    "ORDERS": "Inactive",
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
    """Parse a date value, returning pd.NaT on failure / blanks / OOR."""
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return pd.NaT
    if isinstance(val, dict):
        return pd.NaT
    if isinstance(val, str):
        s = val.strip()
        if not s or s.upper() in {
            "TBD", "NULL", "NONE", "N/A", "NA", "NAN",
            "UNAVAILABLE", "00/00/0000", "0/0/0000",
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
    return dt


def _dates_equal(a, b) -> bool:
    """Compare two datelike values at calendar-day resolution."""
    if pd.isna(a) or pd.isna(b):
        return False
    return pd.Timestamp(a).normalize() == pd.Timestamp(b).normalize()


def _detail(d: dict) -> dict:
    detail = d.get("Detail")
    return detail if isinstance(detail, dict) else {}


def _current_status(d: dict) -> Optional[str]:
    raw = _detail(d).get("Current Status")
    if raw is None:
        return None
    s = str(raw).strip()
    return s if s else None


def _map_status(raw: Optional[str]) -> Optional[str]:
    if raw is None:
        return None
    return _STATUS_MAP.get(raw.strip().upper())


def _applied_date(d: dict):
    return _safe_to_datetime(_detail(d).get("Applied Date"))


def _status_date(d: dict):
    return _safe_to_datetime(_detail(d).get("Status Date"))


def _inspection_final_date(d: dict):
    """Latest Approved/Y final-ish inspection date (skip NOC)."""
    best = pd.NaT
    for ins in d.get("Inspections") or []:
        if not isinstance(ins, dict):
            continue
        if ins.get("Inspection Status") not in _PASS_OK:
            continue
        desc = str(ins.get("Description") or "")
        if "notice of commencement" in desc.lower():
            continue
        if not _FINAL_INSP_RE.search(desc):
            continue
        dt = _safe_to_datetime(ins.get("Date"))
        if dt is pd.NaT:
            continue
        if best is pd.NaT or dt > best:
            best = dt
    return best


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    if not isinstance(data_dict, dict) or "Detail" not in data_dict:
        return "unknown"

    parts = ["tlhportal"]
    if "Subtrades" in data_dict:
        parts.append("subtrades")
    elif "Date" in data_dict:
        parts.append("dateidx")

    ninsp = len(data_dict.get("Inspections") or [])
    parts.append("insp" if ninsp else "noinsp")

    applied = _applied_date(data_dict)
    status_dt = _status_date(data_dict)
    if applied is not pd.NaT and status_dt is not pd.NaT:
        parts.append("applied_status")
    elif applied is not pd.NaT:
        parts.append("applied")
    elif status_dt is not pd.NaT:
        parts.append("status")
    else:
        parts.append("nodates")
    return "_".join(parts)


def _apply_status(repairs: dict, current, expected: Optional[str]) -> Optional[str]:
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
    current = repairs.get(field, row[field])
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


# ── Per-record repair ────────────────────────────────────────────────────────

def _repair_record(row, d: dict, repairs: dict) -> None:
    raw = _current_status(d)
    expected = _map_status(raw)
    effective_status = _apply_status(repairs, row["STATUS_NORMALIZED"], expected)

    applied = _applied_date(d)
    status_dt = _status_date(d)
    final_insp = _inspection_final_date(d)

    # -- FILE_DATE ← Applied Date --
    _apply_date(repairs, row, "FILE_DATE", applied)

    # -- PERMIT_DATE --
    # DATA has no Issue/Issued field. Status Date is the date of the
    # *current* status transition, so it is only a reasonable issuance
    # proxy while the record is Active (Issued / Approved / NOC Hold / …).
    if effective_status == "Active":
        if status_dt is not pd.NaT:
            _apply_date(repairs, row, "PERMIT_DATE", status_dt)
    else:
        # Spurious upstream copy of Status Date (or Applied Date) into
        # PERMIT_DATE for Final / In Review / Inactive.
        current_permit = repairs.get("PERMIT_DATE", row["PERMIT_DATE"])
        if not pd.isna(current_permit):
            if status_dt is not pd.NaT and _dates_equal(current_permit, status_dt):
                _clear_date(repairs, row, "PERMIT_DATE")
            elif applied is not pd.NaT and _dates_equal(current_permit, applied):
                _clear_date(repairs, row, "PERMIT_DATE")
            elif effective_status in ("In Review", "Inactive"):
                _clear_date(repairs, row, "PERMIT_DATE")
            elif effective_status == "Final":
                # Final with a PERMIT_DATE that isn't Status/Applied —
                # still no issuance source; leave only if it differs
                # from FINAL candidate below (none observed in sample).
                pass

    # -- FINAL_DATE --
    if effective_status == "Final":
        final_cand = status_dt if status_dt is not pd.NaT else final_insp
        if final_cand is not pd.NaT:
            _apply_date(repairs, row, "FINAL_DATE", final_cand)
    else:
        _clear_date(repairs, row, "FINAL_DATE")


# ── Main entry point ─────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Leon County (FL) permit records using the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Leon County".  Must contain
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

    for col in ("FILE_DATE", "PERMIT_DATE", "FINAL_DATE"):
        out[col] = pd.to_datetime(out[col], errors="coerce", utc=True).dt.tz_localize(None)

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
        if isinstance(d.get("Detail"), dict):
            _repair_record(row, d, repairs)

        for key, value in repairs.items():
            out.at[idx, key] = value

    for col in ("FILE_DATE", "PERMIT_DATE", "FINAL_DATE"):
        out[col] = pd.to_datetime(out[col], errors="coerce", utc=True).dt.tz_localize(None)

    return out


# ── CLI: run standalone to preview repair stats ──────────────────────────────

if __name__ == "__main__":
    import os
    from collections import Counter
    from pathlib import Path

    from dotenv import load_dotenv

    repo_root = Path(__file__).resolve().parents[3]
    load_dotenv(repo_root / ".env")
    my_data_path = os.getenv("MY_DATA_PATH")
    agent_data_path = os.getenv("AGENT_DATA_PATH")
    filepath = os.path.join(my_data_path, "processed_data", "permits_fl_sample.parquet")
    df = pd.read_parquet(filepath)
    city = df[df["JURISDICTION"] == "Leon County"].copy()

    print(f"Leon County records: {len(city):,}\n")
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

    print("\nSTATUS_NORMALIZED_FLAG breakdown:")
    for flag in ["FILLED", "FIXED"]:
        sub = repaired[repaired["STATUS_NORMALIZED_FLAG"] == flag]
        print(f"  {flag} ({len(sub)}):")
        labels = Counter()
        for idx in sub.index:
            d = _safe_parse(city.loc[idx, "DATA"])
            label = _current_status(d) if d else None
            labels[
                (
                    label,
                    city.loc[idx, "STATUS_NORMALIZED"],
                    repaired.loc[idx, "STATUS_NORMALIZED"],
                )
            ] += 1
        for (label, before, after), n in labels.most_common():
            print(f"    {n:>4}  {label!r:40s}  {before} → {after}")

    print("\nIdeal date coverage after repair:")
    for sn in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == sn]
        n = len(sub)
        if n == 0:
            continue
        file_ok = sub["FILE_DATE"].notna().sum()
        permit_ok = sub["PERMIT_DATE"].notna().sum()
        final_ok = sub["FINAL_DATE"].notna().sum()
        print(
            f"  {sn:10s} n={n:>4}  FILE={file_ok}/{n}  "
            f"PERMIT={permit_ok}/{n}  FINAL={final_ok}/{n}"
        )

    if agent_data_path:
        out_path = os.path.join(agent_data_path, "leon_county_repaired_sample.parquet")
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote {out_path}")

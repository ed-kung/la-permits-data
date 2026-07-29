"""Data repair for Pismo Beach (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Pismo Beach DATA is a flat open-data / tabular export with keys Status,
``Address ``, ``Permit #``, Permit Type, Sub Type, optional Issue Date,
and optional Work Description. Issue Date / Work Description presence
and column-shift corruption define the sub-schemas:

  - tabular_spaced:            Address  + Permit # + Issue Date + WD
  - tabular_spaced_no_wd:      Address  + Permit # + Issue Date
  - tabular_spaced_no_issue:   Address  + Permit # (no Issue Date)
  - tabular_shifted:           Status not a lifecycle label; real status
                               lives in Sub Type and/or Status holds a
                               date (column misalignment)

Canonical mappings:
  - Status (fallback: Sub Type on shifted rows) → STATUS_NORMALIZED
  - Issue Date (fallback: date-like Status / Sub Type on shifted rows)
                                                      → PERMIT_DATE
  - No application or finaling timestamp exists in DATA

Known issues repaired:
  - Unmapped Admin Approval / Construction Permit / PC Approval /
    CC Approval left STATUS_NORMALIZED null → FILLED Active.
  - Revision Approved mapped to In Review despite approval (and usually
    a parseable Issue Date) → FIXED to Active when issued; stays
    In Review when no issuance stamp.
  - Estimate incorrectly mapped to Final → FIXED to In Review.
  - Column-shifted rows with lifecycle label in Sub Type (Closed /
    Issued) and date in Status → FILLED status + PERMIT_DATE.
    Sub Type ``Other`` is a planning subtype, not the Inactive
    ``Status=Other`` label, so it is not used as a status fallback.
  - Missing PERMIT_DATE on Active/Final when Issue Date (or shifted
    Status date) is a valid calendar date → FILLED.

Not repairable / left as-is:
  - FILE_DATE is missing on every row; DATA has no apply/submit date.
    Issue Date is issuance, not filing — not used as FILE_DATE.
  - FINAL_DATE is missing on every row; Closed / Finaled imply Final
    but no completion / signoff timestamp exists in DATA.
  - ~586 rows store Work Description text in Issue Date (WD key often
    absent) — not a date; PERMIT_DATE stays missing unless Status
    carries a recoverable date on a shifted Active/Final row.
  - ~143 Eng Migrated rows with date-as-Status and Sub Type
    ``Eng Migrated`` (not a lifecycle label) have no recoverable
    status; left null.
  - A handful of description-as-Status shells (dedication text, daily
    transpo descriptions, etc.) have no lifecycle label.
"""

from __future__ import annotations

import json
import math
import re
from typing import Optional

import numpy as np
import pandas as pd


_MIN_YEAR = 1970
_MAX_YEAR = 2035

_DATE_ONLY_RE = re.compile(r"^\d{1,2}/\d{1,2}/\d{2,4}$")

# DATA Status (and Sub Type on shifted rows) → STATUS_NORMALIZED
_STATUS_MAP = {
    # Final
    "Closed": "Final",
    "Finaled": "Final",
    # Active — issued / approved
    "Issued": "Active",
    "Admin Approval": "Active",
    "Construction Permit": "Active",
    "PC Approval": "Active",
    "CC Approval": "Active",
    "Revision Approved": "Active",
    # In Review
    "Under Review": "In Review",
    "Online Application Received": "In Review",
    "Application": "In Review",
    "Pending": "In Review",
    "Estimate": "In Review",
    # Inactive
    "Expired": "Inactive",
    "Withdrawn": "Inactive",
    "Void": "Inactive",
    "Denied": "Inactive",
    "Other": "Inactive",
}

_CANONICAL_STATUSES = set(_STATUS_MAP.keys())

# Sub Type may carry the real lifecycle label on column-shifted rows, but
# some Sub Type values collide with status names while meaning a record
# subtype (notably ``Other`` = planning "Other"). Only these labels are
# trusted when read from Sub Type.
_SHIFTED_SUBTYPE_STATUSES = {
    "Closed",
    "Finaled",
    "Issued",
    "Admin Approval",
    "Construction Permit",
    "PC Approval",
    "CC Approval",
    "Revision Approved",
    "Under Review",
    "Online Application Received",
    "Application",
    "Pending",
    "Estimate",
    "Expired",
    "Withdrawn",
    "Void",
    "Denied",
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


def _safe_to_datetime(val):
    """Parse a date value, returning pd.NaT on failure or implausible year."""
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return pd.NaT
    if isinstance(val, str):
        s = val.strip()
        if not s or s.upper() in {"TBD", "NULL", "NONE", "N/A", "NA"}:
            return pd.NaT
        # Reject free-text that happens to parse (e.g. "January 2005").
        if not _DATE_ONLY_RE.match(s) and not re.match(
            r"^\d{4}-\d{2}-\d{2}", s
        ):
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
    return dt


def _is_date_only(val) -> bool:
    return isinstance(val, str) and bool(_DATE_ONLY_RE.match(val.strip()))


def _dates_equal(a, b) -> bool:
    da = _safe_to_datetime(a)
    db = _safe_to_datetime(b)
    if da is pd.NaT or db is pd.NaT or pd.isna(da) or pd.isna(db):
        return False
    return da.normalize() == db.normalize()


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())
    if not (
        ("Address" in keys or "Address " in keys)
        and ("Permit#" in keys or "Permit #" in keys)
    ):
        return "unknown"

    status = data_dict.get("Status")
    sub = data_dict.get("Sub Type")
    shifted = (
        (status not in _CANONICAL_STATUSES)
        and (
            sub in _SHIFTED_SUBTYPE_STATUSES
            or _is_date_only(status)
            or _is_date_only(sub)
        )
    )
    if shifted:
        return "tabular_shifted"

    spaced = "Address " in keys or "Permit #" in keys
    has_issue = "Issue Date" in keys
    has_wd = "Work Description" in keys
    base = "tabular_spaced" if spaced else "tabular_compact"
    if has_issue and has_wd:
        return base
    if has_issue:
        return f"{base}_no_wd"
    return f"{base}_no_issue"


def _resolve_status_label(d: dict) -> Optional[str]:
    """Return the lifecycle label from Status, or Sub Type if shifted."""
    status = d.get("Status")
    if isinstance(status, str):
        status = status.strip()
    else:
        status = None

    if status in _CANONICAL_STATUSES:
        return status

    sub = d.get("Sub Type")
    if isinstance(sub, str):
        sub = sub.strip()
        # Do not treat subtype categories like ``Other`` as lifecycle labels.
        if sub in _SHIFTED_SUBTYPE_STATUSES:
            return sub

    return None


def _issue_date_from_data(d: dict):
    """Best issuance date: Issue Date, else date-like Status / Sub Type."""
    issue = _safe_to_datetime(d.get("Issue Date"))
    if issue is not pd.NaT and not pd.isna(issue):
        return issue

    status = d.get("Status")
    if _is_date_only(status):
        # Column misalignment: Status holds the issue stamp.
        return _safe_to_datetime(status)

    sub = d.get("Sub Type")
    if _is_date_only(sub):
        # Rare shift: Sub Type holds the date (description in Status).
        return _safe_to_datetime(sub)

    return pd.NaT


def _expected_status(d: dict, issue_dt) -> Optional[str]:
    """Map DATA status label to STATUS_NORMALIZED.

    Revision Approved without an issuance stamp stays In Review (plan
    approval only); with a parseable Issue Date / shifted date → Active.
    """
    label = _resolve_status_label(d)
    if label is None:
        return None
    if label == "Revision Approved":
        if issue_dt is not pd.NaT and not pd.isna(issue_dt):
            return "Active"
        return "In Review"
    return _STATUS_MAP.get(label)


def _set_status(repairs: dict, row, expected: str) -> None:
    current = row["STATUS_NORMALIZED"]
    if pd.isna(current):
        repairs["STATUS_NORMALIZED"] = expected
        repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"
    elif current != expected:
        repairs["STATUS_NORMALIZED"] = expected
        repairs["STATUS_NORMALIZED_FLAG"] = "FIXED"


def _fill_date(repairs: dict, row, field: str, value) -> None:
    if pd.isna(row[field]):
        repairs[field] = value
        repairs[f"{field}_FLAG"] = "FILLED"
    elif not _dates_equal(row[field], value):
        repairs[field] = value
        repairs[f"{field}_FLAG"] = "FIXED"


# ── Per-record repair ────────────────────────────────────────────────────────

def _repair_record(row, d: dict, repairs: dict) -> None:
    issue_dt = _issue_date_from_data(d)
    expected = _expected_status(d, issue_dt)
    if expected is not None:
        _set_status(repairs, row, expected)

    effective = repairs.get("STATUS_NORMALIZED", row["STATUS_NORMALIZED"])

    # FILE_DATE: no apply/submit field in Pismo Beach DATA — leave missing.

    # PERMIT_DATE: Issue Date (or shifted Status/Sub Type date) is issuance.
    if (
        effective in ("Active", "Final")
        and issue_dt is not pd.NaT
        and not pd.isna(issue_dt)
    ):
        _fill_date(repairs, row, "PERMIT_DATE", issue_dt)

    # FINAL_DATE: no finaling / completion / signoff field in DATA.


# ── Main entry point ─────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Pismo Beach permit records using information from the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Pismo Beach". Must contain
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
        if schema != "unknown":
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

    load_dotenv(Path(__file__).resolve().parents[3] / ".env")
    MY_DATA_PATH = os.getenv("MY_DATA_PATH")
    AGENT_DATA_PATH = os.getenv("AGENT_DATA_PATH")
    filepath = os.path.join(
        MY_DATA_PATH, "processed_data", "permits_ca_sample.parquet"
    )
    df = pd.read_parquet(filepath)
    city = df[
        (df["JURISDICTION"] == "Pismo Beach") & (df["STATE"] == "CA")
    ].copy()

    print(f"Pismo Beach records: {len(city):,}\n")

    repaired = data_repair(city)

    print("INFERRED_SCHEMA:")
    print(repaired["INFERRED_SCHEMA"].value_counts(dropna=False).to_string())
    print()

    for field in ["STATUS_NORMALIZED", "FILE_DATE", "PERMIT_DATE", "FINAL_DATE"]:
        flag_col = f"{field}_FLAG"
        n_filled = int((repaired[flag_col] == "FILLED").sum())
        n_fixed = int((repaired[flag_col] == "FIXED").sum())
        before_missing = int(city[field].isna().sum())
        after_missing = int(repaired[field].isna().sum())
        print(f"{field}:")
        print(f"  FILLED: {n_filled:>4,}   FIXED: {n_fixed:>4,}")
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

    print("\nStatus transitions (where changed):")
    changed = repaired["STATUS_NORMALIZED_FLAG"].notna()
    if changed.any():
        trans = (
            pd.DataFrame({
                "before": city.loc[changed, "STATUS_NORMALIZED"].fillna("__NA__"),
                "after": repaired.loc[changed, "STATUS_NORMALIZED"].fillna("__NA__"),
                "data_status": [
                    (_safe_parse(city.loc[i, "DATA"]) or {}).get("Status")
                    for i in city.loc[changed].index
                ],
            })
            .value_counts()
            .reset_index(name="n")
        )
        print(trans.to_string(index=False))

    print("\nPERMIT_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = int(sub["PERMIT_DATE"].notna().sum())
        n = len(sub)
        pct = n_has / n if n else 0.0
        print(f"  {status:15s}: {n_has:>4,} / {n:>4,} ({pct:.1%})")

    print("\nFINAL_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = int(sub["FINAL_DATE"].notna().sum())
        n = len(sub)
        pct = n_has / n if n else 0.0
        print(f"  {status:15s}: {n_has:>4,} / {n:>4,} ({pct:.1%})")

    print("\nFILE_DATE coverage (after repair):")
    n_has = int(repaired["FILE_DATE"].notna().sum())
    print(f"  {n_has:>4,} / {len(repaired):>4,} ({n_has / len(repaired):.1%})")

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

    if AGENT_DATA_PATH:
        out_dir = os.path.join(AGENT_DATA_PATH, "repaired")
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(
            out_dir, "permits_ca_pismo_beach_repaired.parquet"
        )
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote {out_path}")

"""Data repair for Broward County (FL) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Broward County DATA is a POSSE / Accela-style master-permit portal
payload. Nearly all rows share the nested key set (Permit, Permit
Application, Permit Information, Permits, Plan Reviews, Holds, Parcel
Information, …); a few also expose Fee Information; one sample row is
Permit-only.

Canonical fields:

  - Permit.Status                         → STATUS_NORMALIZED
  - Permit Information.ApplicationDate
    (fallback earliest Plan Reviews
     Plans Submitted)                     → FILE_DATE
  - Permit.Issue Date                     → PERMIT_DATE
    (never a real date in this sample —
     blank or the placeholder
     ``mmm dd, yyyy``)
  - no true completion / finaled stamp
    in DATA; ExpirationDate was
    incorrectly loaded into FINAL_DATE    → FINAL_DATE cleared

Key-set variants (INFERRED_SCHEMA prefixes):
  - posse:          standard nested sections
  - posse_fees:     + Fee Information
  - posse_permit:   Permit key only

Content suffixes reflect which usable dates are present
(``_applied_expired``, ``_applied``, ``_status_only``).

Known issues repaired:
  - 8 missing STATUS_NORMALIZED filled from Permit.Status
    (All/Primary Permits Issued → Active; Plans Check → In Review;
    All Permits Expired → Inactive; All Permits Finaled → Final).
  - FINAL_DATE on 617 rows equals Permit Information.ExpirationDate
    (and nowhere else in DATA has a completion stamp) → FIXED cleared
    for every status, including Final and Inactive.

Not repairable from DATA:
  - PERMIT_DATE is missing on all 2,000 rows; Issue Date is never a
    parseable date.
  - FINAL_DATE has no real source after clearing ExpirationDate
    misloads → remains missing for Final rows.
  - 17 FILE_DATE gaps (mostly Cancelled / New / Permit-only) have
    empty ApplicationDate and no Plans Submitted → stay missing.
"""

from __future__ import annotations

import json
import math
from typing import Optional

import numpy as np
import pandas as pd


_MIN_YEAR = 1980
_MAX_YEAR = 2035

# Permit.Status → STATUS_NORMALIZED
_STATUS_MAP = {
    "Complete": "Final",
    "All Permits Finaled": "Final",
    "All Permits Issued": "Active",
    "Primary Permit Issued": "Active",
    "New": "In Review",
    "Plans Check": "In Review",
    "Reviews Complete": "In Review",
    "Cancelled": "Inactive",
    "All Permits Expired": "Inactive",
    "Primary Permit Expired": "Inactive",
    "Null and Void": "Inactive",
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
        # Broward Issue Date placeholder text, not a real date.
        if s.lower() in {"mmm dd, yyyy", "mm/dd/yyyy", "yyyy-mm-dd"}:
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


def _section(d: dict, name: str) -> dict:
    val = d.get(name)
    return val if isinstance(val, dict) else {}


def _permit_status(d: dict) -> Optional[str]:
    status = _section(d, "Permit").get("Status")
    if status is None:
        return None
    s = str(status).strip()
    return s or None


def _application_date(d: dict):
    app = _safe_to_datetime(_section(d, "Permit Information").get("ApplicationDate"))
    if app is not pd.NaT and not pd.isna(app):
        return app
    # Plans Submitted always equals ApplicationDate when both present;
    # use earliest as a fallback when ApplicationDate is blank.
    reviews = d.get("Plan Reviews")
    if not isinstance(reviews, list):
        return pd.NaT
    candidates = []
    for item in reviews:
        if not isinstance(item, dict):
            continue
        dt = _safe_to_datetime(item.get("Plans Submitted"))
        if dt is not pd.NaT and not pd.isna(dt):
            candidates.append(dt)
    return min(candidates) if candidates else pd.NaT


def _issue_date(d: dict):
    return _safe_to_datetime(_section(d, "Permit").get("Issue Date"))


def _expiration_date(d: dict):
    return _safe_to_datetime(_section(d, "Permit Information").get("ExpirationDate"))


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"

    keys = set(data_dict.keys())
    if "Fee Information" in keys and "Permit" in keys:
        base = "posse_fees"
    elif "Permit" in keys and "Permit Information" in keys:
        base = "posse"
    elif "Permit" in keys:
        base = "posse_permit"
    else:
        return "unknown"

    app = _application_date(data_dict)
    exp = _expiration_date(data_dict)
    issue = _issue_date(data_dict)

    has_app = app is not pd.NaT and not pd.isna(app)
    has_exp = exp is not pd.NaT and not pd.isna(exp)
    has_issue = issue is not pd.NaT and not pd.isna(issue)

    if has_issue and has_exp:
        return f"{base}_issued_expired"
    if has_issue and has_app:
        return f"{base}_issued"
    if has_app and has_exp:
        return f"{base}_applied_expired"
    if has_app:
        return f"{base}_applied"
    if has_exp:
        return f"{base}_expired"
    return f"{base}_status_only"


def _expected_status(status: Optional[str]) -> Optional[str]:
    if status is None:
        return None
    if status in _STATUS_MAP:
        return _STATUS_MAP[status]
    for key, val in _STATUS_MAP.items():
        if key.lower() == status.lower():
            return val
    return None


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


# ── Per-record repair ────────────────────────────────────────────────────────

def _repair_record(row, d: dict, repairs: dict) -> None:
    expected = _expected_status(_permit_status(d))
    effective_status = _apply_status(repairs, row["STATUS_NORMALIZED"], expected)

    # -- FILE_DATE ← ApplicationDate (else Plans Submitted) --
    file_cand = _application_date(d)
    if file_cand is not pd.NaT and not pd.isna(file_cand):
        _apply_date(repairs, row, "FILE_DATE", file_cand)

    # -- PERMIT_DATE ← Issue Date (unavailable in this sample) --
    issue = _issue_date(d)
    if issue is not pd.NaT and not pd.isna(issue):
        if effective_status in ("Active", "Final", "Inactive"):
            _apply_date(repairs, row, "PERMIT_DATE", issue)
        elif effective_status == "In Review":
            _clear_date(repairs, row, "PERMIT_DATE")
    elif effective_status == "In Review":
        _clear_date(repairs, row, "PERMIT_DATE")

    # -- FINAL_DATE --
    # DATA has no completion / finaled / CO date. Every populated
    # FINAL_DATE in the sample equals ExpirationDate, which is a
    # permit-expiry stamp, not a finalization date. Clear it.
    exp = _expiration_date(d)
    current_final = row["FINAL_DATE"]
    if not pd.isna(current_final):
        if exp is not pd.NaT and not pd.isna(exp) and _dates_equal(current_final, exp):
            _clear_date(repairs, row, "FINAL_DATE")
        elif effective_status != "Final":
            # Non-Final rows should not carry a FINAL_DATE.
            _clear_date(repairs, row, "FINAL_DATE")
        else:
            # Final row with a FINAL_DATE that is not ExpirationDate and
            # has no other DATA source — leave as-is (none observed).
            pass


# ── Main entry point ─────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Broward County permit records using the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Broward County".  Must
        contain columns STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE,
        FINAL_DATE, and DATA.

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
        _repair_record(row, d, repairs)
        for key, value in repairs.items():
            out.at[idx, key] = value

    for col in ("FILE_DATE", "PERMIT_DATE", "FINAL_DATE"):
        out[col] = pd.to_datetime(out[col], errors="coerce", utc=True).dt.tz_localize(None)

    return out


# ── CLI: run standalone to preview repair stats ─────────────────────────────

if __name__ == "__main__":
    import os

    from dotenv import load_dotenv

    load_dotenv("/Users/ekung/projects/la-permits-data/.env")
    MY_DATA_PATH = os.getenv("MY_DATA_PATH")
    filepath = os.path.join(MY_DATA_PATH, "processed_data", "permits_fl_sample.parquet")
    df = pd.read_parquet(filepath)
    city = df[df["JURISDICTION"] == "Broward County"].copy()

    print(f"Broward County records: {len(city):,}\n")

    repaired = data_repair(city)

    print("INFERRED_SCHEMA:")
    for s, c in repaired["INFERRED_SCHEMA"].value_counts(dropna=False).items():
        print(f"  {str(s):35s}: {c:>4,}")
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

    print("\nSTATUS fills/fixes detail:")
    changed = repaired[repaired["STATUS_NORMALIZED_FLAG"].notna()][
        ["STATUS_ORIGINAL", "STATUS_NORMALIZED"]
    ].copy()
    changed["BEFORE"] = city.loc[changed.index, "STATUS_NORMALIZED"]
    print(changed.groupby(["BEFORE", "STATUS_NORMALIZED", "STATUS_ORIGINAL"]).size())

    print("\nFILE_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FILE_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({(n_has / len(sub) if len(sub) else 0):.1%})")

    print("\nPERMIT_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["PERMIT_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({(n_has / len(sub) if len(sub) else 0):.1%})")

    print("\nFINAL_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FINAL_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({(n_has / len(sub) if len(sub) else 0):.1%})")

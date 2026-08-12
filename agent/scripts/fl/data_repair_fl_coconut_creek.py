"""Data repair for Coconut Creek (FL) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Coconut Creek DATA is a municipal permit-portal payload with a nested
``Permit`` object plus optional ``Fee`` / ``Inspection`` / ``Review`` /
``Contractor`` / ``Parcel Info`` / ``Payment`` blocks. Canonical fields:

  - Permit.Status (+ Issued Date for Open)  → STATUS_NORMALIZED
  - Permit['Applied Date']                  → FILE_DATE
  - Permit['Issued Date']                   → PERMIT_DATE
  - Permit['C.O. Issued'], else latest
    Passed (Status=P) final-ish inspection  → FINAL_DATE

Key-set variants (INFERRED_SCHEMA prefixes):
  - portal_fee_insp: Fee + Inspection present
  - portal_fee:      Fee present, no Inspection
  - portal_insp:     Inspection present, no Fee
  - portal_basic:    neither Fee nor Inspection

Content suffixes further split by which canonical dates are populated
(``_issued_finaled``, ``_issued``, ``_finaled``, ``_applied``,
``_status_only``).

Known issues repaired:
  - Open permits with an Issued Date were normalized to In Review
    (STATUS_ORIGINAL ``open``) → FIXED to Active (76 rows).
  - Final (Closed) rows missing C.O. Issued can often take FINAL_DATE
    from a Passed ``*FINAL*`` / CO / certificate inspection (72 rows).
  - Spurious FINAL_DATE on Inactive (Void) cleared — C.O. Issued there
    is not a valid completion date for a voided permit (1 row).

Not repairable from DATA:
  - FILE_DATE already matches Applied Date for every sample row.
  - 7 Final rows (G-FEES / T-REMOVAL) have blank Issued Date →
    PERMIT_DATE stays missing.
  - ~620 Final (Closed) rows have neither C.O. Issued nor a Passed
    final-ish inspection → FINAL_DATE stays missing.
  - Open rows without Issued Date remain In Review with no
    PERMIT_DATE (correctly missing).
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
    r"final|fnl|closeout|certificate|\bc\.?o\.?\b|\bcc\b|\bcoc\b",
    re.IGNORECASE,
)

_INSP_PASS = {"P", "A", "PASSED", "APPROVED", "PASS"}


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


def _dates_equal(a, b) -> bool:
    """Compare two datelike values at calendar-day resolution."""
    da = _safe_to_datetime(a)
    db = _safe_to_datetime(b)
    if da is pd.NaT or db is pd.NaT or pd.isna(da) or pd.isna(db):
        return False
    return pd.Timestamp(da).normalize() == pd.Timestamp(db).normalize()


def _permit(d: dict) -> dict:
    p = d.get("Permit")
    return p if isinstance(p, dict) else {}


# ── Schema classification ────────────────────────────────────────────────────

def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())
    if "Permit" not in keys:
        return "unknown"

    has_fee = "Fee" in keys
    has_insp = "Inspection" in keys
    if has_fee and has_insp:
        base = "portal_fee_insp"
    elif has_fee:
        base = "portal_fee"
    elif has_insp:
        base = "portal_insp"
    else:
        base = "portal_basic"

    p = _permit(data_dict)
    applied = _safe_to_datetime(p.get("Applied Date"))
    issued = _safe_to_datetime(p.get("Issued Date"))
    final = _safe_to_datetime(p.get("C.O. Issued"))
    has_apply = applied is not pd.NaT and not pd.isna(applied)
    has_issue = issued is not pd.NaT and not pd.isna(issued)
    has_final = final is not pd.NaT and not pd.isna(final)

    if has_issue and has_final:
        return f"{base}_issued_finaled"
    if has_issue:
        return f"{base}_issued"
    if has_final:
        return f"{base}_finaled"
    if has_apply:
        return f"{base}_applied"
    return f"{base}_status_only"


# ── Status mapping ───────────────────────────────────────────────────────────

def _expected_status(d: dict) -> Optional[str]:
    """Derive STATUS_NORMALIZED from Permit.Status (+ Issued Date for Open).

    Open + Issued Date → Active (issued but not yet closed).
    Open without Issued Date → In Review (still pre-issuance).
    Closed → Final; Void / Expired / Reject → Inactive.
    """
    p = _permit(d)
    raw = (p.get("Status") or "").strip()
    if not raw:
        return None

    key = raw.lower()
    if key == "closed":
        return "Final"
    if key == "open":
        issued = _safe_to_datetime(p.get("Issued Date"))
        if issued is not pd.NaT and not pd.isna(issued):
            return "Active"
        return "In Review"
    if key in {"void", "expired", "reject"}:
        return "Inactive"
    return None


def _final_inspection_date(d: dict):
    """Latest Passed inspection whose Type looks final / CO / certificate."""
    inspections = d.get("Inspection")
    if isinstance(inspections, dict):
        inspections = [inspections]
    if not isinstance(inspections, list):
        return pd.NaT

    candidates = []
    for insp in inspections:
        if not isinstance(insp, dict):
            continue
        status = str(insp.get("Status") or "").strip().upper()
        if status not in _INSP_PASS:
            continue
        typ = str(insp.get("Type") or "")
        if not _FINAL_INSP_RE.search(typ):
            continue
        dt = _safe_to_datetime(insp.get("Insp Date"))
        if dt is not pd.NaT and not pd.isna(dt):
            candidates.append(dt)
    return max(candidates) if candidates else pd.NaT


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
    p = _permit(d)

    expected = _expected_status(d)
    effective_status = _apply_status(repairs, row["STATUS_NORMALIZED"], expected)

    apply = _safe_to_datetime(p.get("Applied Date"))
    issue = _safe_to_datetime(p.get("Issued Date"))
    final = _safe_to_datetime(p.get("C.O. Issued"))

    # FILE_DATE ← Applied Date
    if apply is not pd.NaT and not pd.isna(apply):
        _apply_date(repairs, row, "FILE_DATE", apply)

    # PERMIT_DATE ← Issued Date for issued / completed / expired statuses.
    # Clear on In Review (pre-issuance Open rows should not carry a date).
    if issue is not pd.NaT and not pd.isna(issue):
        if effective_status in ("Active", "Final", "Inactive"):
            _apply_date(repairs, row, "PERMIT_DATE", issue)
        elif effective_status == "In Review":
            _clear_date(repairs, row, "PERMIT_DATE")
    elif effective_status == "In Review":
        _clear_date(repairs, row, "PERMIT_DATE")

    # FINAL_DATE ← C.O. Issued, else Passed final-ish inspection.
    if (final is pd.NaT or pd.isna(final)) and effective_status == "Final":
        final = _final_inspection_date(d)

    if effective_status == "Final":
        if final is not pd.NaT and not pd.isna(final):
            _apply_date(repairs, row, "FINAL_DATE", final)
    else:
        _clear_date(repairs, row, "FINAL_DATE")


# ── Main entry point ─────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Coconut Creek permit records using the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Coconut Creek".  Must contain
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

    load_dotenv()
    path = os.path.join(
        os.environ["MY_DATA_PATH"],
        "processed_data",
        "permits_fl_sample.parquet",
    )
    raw = pd.read_parquet(path)
    subset = raw[
        (raw["JURISDICTION"] == "Coconut Creek") & (raw["STATE"] == "FL")
    ].copy()
    print(f"Loaded {len(subset)} Coconut Creek rows")

    repaired = data_repair(subset)

    print("\nINFERRED_SCHEMA counts:")
    print(repaired["INFERRED_SCHEMA"].value_counts().to_string())

    print("\nSTATUS_NORMALIZED before → after:")
    print("BEFORE:")
    print(subset["STATUS_NORMALIZED"].value_counts(dropna=False).to_string())
    print("AFTER:")
    print(repaired["STATUS_NORMALIZED"].value_counts(dropna=False).to_string())

    for field in ["STATUS_NORMALIZED", "FILE_DATE", "PERMIT_DATE", "FINAL_DATE"]:
        flag_col = f"{field}_FLAG"
        n_filled = (repaired[flag_col] == "FILLED").sum()
        n_fixed = (repaired[flag_col] == "FIXED").sum()
        print(f"{field}: FILLED={n_filled}, FIXED={n_fixed}")

    print("\nMissing dates by status (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        print(
            f"  {status:12s} n={len(sub):4d}  "
            f"FILE missing={sub['FILE_DATE'].isna().sum():4d}  "
            f"PERMIT missing={sub['PERMIT_DATE'].isna().sum():4d}  "
            f"FINAL missing={sub['FINAL_DATE'].isna().sum():4d}"
        )

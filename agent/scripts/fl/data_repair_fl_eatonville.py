"""Data repair for Eatonville (FL) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Eatonville DATA is a municipal portal payload (CitizenServe-style form
fields) with top-level keys such as ``Status:``, ``Permit #:``,
``Issue Date``, ``Permit Details``, ``Inspections``, and ``Reviews``.
Top-level ``Issue Date`` is always null in the sample; the usable issue
stamp lives under ``Permit Details["Issue Date:"]``. ``Reviews`` is
always empty. There is no application / submittal date field anywhere
in DATA.

Canonical fields:

  - DATA["Status:"] (with Issue-date upgrade from
    In Review → Active; empty status inferred from
    Issue Date / passed Final* inspections)
      → STATUS_NORMALIZED
  - (none available in DATA)              → FILE_DATE
  - Permit Details["Issue Date:"]         → PERMIT_DATE
  - Latest passed Final* inspection date  → FINAL_DATE

Key-set variants (INFERRED_SCHEMA prefixes):
  - portal_full:     valuation form + contractor license + WC cert keys
  - portal_partial:  valuation form present, missing some contractor docs
  - portal_minimal:  core permit keys only (no valuation form)

Content suffixes further split by which canonical dates are recoverable
(``_issued_finaled``, ``_issued``, ``_finaled``, ``_applied``).

Known issues repaired:
  - Null STATUS_NORMALIZED when ``Status:`` is blank → FILLED from
    Issue Date (Active), passed Final* inspection (Final), else
    In Review.
  - STATUS_ORIGINAL-driven mislabel: Issued row kept as Final because
    STATUS_ORIGINAL was ``closed`` → FIXED to Active.
  - Pre-issuance statuses (Processing / More Information Needed) that
    already carry Permit Details Issue Date upgraded In Review → Active.
  - FINAL_DATE missing on Closed / inferred-Final rows that have a
    passed (or blank-status dated) Final* inspection → FILLED.
  - Spurious PERMIT_DATE on remaining In Review rows cleared (none
    expected after Issue-date upgrades).

Not repairable from DATA:
  - FILE_DATE is null for every sample row and DATA has no application /
    received / submittal date field → remains 100% missing.
  - Many Closed / Approved / empty-status shells lack Issue Date →
    PERMIT_DATE stays missing on those Active/Final rows.
  - Most Closed shells have empty Inspections → FINAL_DATE stays missing.
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
    r"final|fnl|certificate|\bco\b|\bcc\b|\bcoc\b|\bcofc\b",
    re.IGNORECASE,
)

_PASS_STATUS = {
    "passed",
    "pass",
    "approved",
    "complete",
    "completed",
}

_STATUS_MAP = {
    "Closed": "Final",
    "Issued": "Active",
    "Approved": "Active",
    "Processing": "In Review",
    "More Information Needed": "In Review",
    "Online Application Received": "In Review",
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
    """Parse a date value, returning pd.NaT on failure / sentinel / OOR."""
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return pd.NaT
    if isinstance(val, dict):
        return pd.NaT
    if isinstance(val, str):
        s = val.strip().replace("\xa0", " ")
        if not s or s.upper() in {
            "TBD", "NULL", "NONE", "N/A", "NA", "NAN",
            "00/00/0000", "0/0/0000",
        }:
            return pd.NaT
        if s.startswith("0001-01-01") or s.startswith("1900-01-01"):
            return pd.NaT
        # "Scheduled for MM/DD/YYYY ..." is not a completed event date.
        if s.lower().startswith("scheduled"):
            return pd.NaT
        # Strip trailing portal chrome ("View Comments", whitespace).
        m = re.search(r"(\d{1,2}/\d{1,2}/\d{2,4})", s)
        if m:
            s = m.group(1)
    try:
        dt = pd.to_datetime(val if not isinstance(val, str) else s, errors="coerce")
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


def _present(dt) -> bool:
    return dt is not pd.NaT and not pd.isna(dt)


def _dates_equal(a, b) -> bool:
    da = _safe_to_datetime(a)
    db = _safe_to_datetime(b)
    if not _present(da) or not _present(db):
        return False
    return pd.Timestamp(da).normalize() == pd.Timestamp(db).normalize()


def _nonempty_str(val) -> Optional[str]:
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return None
    s = str(val).strip()
    return s or None


def _raw_status(d: dict) -> Optional[str]:
    return _nonempty_str(d.get("Status:"))


def _permit_details(d: dict) -> dict:
    det = d.get("Permit Details")
    return det if isinstance(det, dict) else {}


def _issue_date(d: dict):
    """Permit Details Issue Date (top-level Issue Date is always null)."""
    det = _permit_details(d)
    dt = _safe_to_datetime(det.get("Issue Date:"))
    if _present(dt):
        return dt
    return _safe_to_datetime(d.get("Issue Date"))


def _insp_status_token(status: Optional[str]) -> str:
    if not status:
        return ""
    # "Passed\r\n\t\t\t    View Comments" → "passed"
    token = re.split(r"[\r\n]", str(status), maxsplit=1)[0]
    token = re.sub(r"view comments", "", token, flags=re.IGNORECASE)
    return token.strip().lower()


def _inspection_is_passed_final(item: dict) -> bool:
    if not isinstance(item, dict):
        return False
    itype = str(item.get("Inspection Type") or "")
    if not _FINAL_INSP_RE.search(itype):
        return False
    token = _insp_status_token(item.get("Status"))
    date_raw = str(item.get("Date") or "")
    if date_raw.lower().startswith("scheduled"):
        return False
    if token in _PASS_STATUS:
        return _present(_safe_to_datetime(item.get("Date")))
    # Blank status with a real calendar date on a Final* type is treated
    # as a completed final (common on Closed Eatonville shells).
    if token == "":
        return _present(_safe_to_datetime(item.get("Date")))
    return False


def _final_from_inspections(d: dict):
    insp = d.get("Inspections")
    if not isinstance(insp, list):
        return pd.NaT
    dates = []
    for item in insp:
        if _inspection_is_passed_final(item):
            dt = _safe_to_datetime(item.get("Date"))
            if _present(dt):
                dates.append(dt)
    return max(dates) if dates else pd.NaT


def _has_passed_final(d: dict) -> bool:
    return _present(_final_from_inspections(d))


# ── Schema classification ────────────────────────────────────────────────────

def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())
    if "Status:" not in keys or "Permit Details" not in keys:
        return "unknown"

    has_valuation = "Valuation of Work (Estimated Cost)" in keys
    has_lic = "Contractor's License" in keys
    has_wc = (
        "Workman's Compensation Insurance Coverage or State Exemption Certificate"
        in keys
    )
    if has_valuation and has_lic and has_wc:
        base = "portal_full"
    elif has_valuation:
        base = "portal_partial"
    else:
        base = "portal_minimal"

    has_issue = _present(_issue_date(data_dict))
    has_final = _has_passed_final(data_dict)
    if has_issue and has_final:
        return f"{base}_issued_finaled"
    if has_issue:
        return f"{base}_issued"
    if has_final:
        return f"{base}_finaled"
    return f"{base}_applied"


# ── Status mapping ───────────────────────────────────────────────────────────

def _expected_status(d: dict) -> Optional[str]:
    """Map portal Status: → STATUS_NORMALIZED, with Issue / final inference."""
    raw = _raw_status(d)
    has_issue = _present(_issue_date(d))
    has_final = _has_passed_final(d)

    if raw is None:
        if has_final:
            return "Final"
        if has_issue:
            return "Active"
        return "In Review"

    mapped = _STATUS_MAP.get(raw)
    if mapped is None:
        # Case-insensitive fallback.
        for key, val in _STATUS_MAP.items():
            if key.lower() == raw.lower():
                mapped = val
                break
    if mapped is None:
        if has_final:
            return "Final"
        if has_issue:
            return "Active"
        return "In Review"

    # Issued-event upgrade: pre-issuance shells that already carry an
    # Issue Date are Active (portal Status: often lags).
    if mapped == "In Review" and has_issue:
        return "Active"
    return mapped


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
    if not _present(cand):
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
    expected = _expected_status(d)
    effective_status = _apply_status(repairs, row["STATUS_NORMALIZED"], expected)

    issue = _issue_date(d)
    final = _final_from_inspections(d)

    # FILE_DATE — no application/submittal field exists in Eatonville DATA.
    # Intentionally left unchanged.

    # PERMIT_DATE ← Permit Details Issue Date for issued lifecycles.
    if effective_status == "In Review":
        _clear_date(repairs, row, "PERMIT_DATE")
    elif _present(issue) and effective_status in ("Active", "Final", "Inactive"):
        _apply_date(repairs, row, "PERMIT_DATE", issue)

    # FINAL_DATE ← passed Final* inspection for Final only.
    if effective_status == "Final":
        if _present(final):
            _apply_date(repairs, row, "FINAL_DATE", final)
    else:
        _clear_date(repairs, row, "FINAL_DATE")


# ── Main entry point ─────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Eatonville permit records using the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Eatonville".  Must contain
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
        out[col] = pd.to_datetime(out[col], errors="coerce")

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
        if d is None or schema in ("missing", "unknown"):
            continue

        repairs: dict = {}
        _repair_record(row, d, repairs)

        for key, value in repairs.items():
            out.at[idx, key] = value

    for col in ("FILE_DATE", "PERMIT_DATE", "FINAL_DATE"):
        out[col] = pd.to_datetime(out[col], errors="coerce")

    return out


# ── CLI: run standalone to preview repair stats ─────────────────────────────

if __name__ == "__main__":
    import os
    from collections import Counter

    from dotenv import load_dotenv

    load_dotenv("/Users/ekung/projects/la-permits-data/.env")
    MY_DATA_PATH = os.getenv("MY_DATA_PATH")
    filepath = os.path.join(
        MY_DATA_PATH, "processed_data", "permits_fl_sample.parquet"
    )
    df = pd.read_parquet(filepath)
    city = df[df["JURISDICTION"] == "Eatonville"].copy()

    print(f"Eatonville records: {len(city):,}\n")

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

    print("\nSTATUS_NORMALIZED changes (before → after):")
    changed = city["STATUS_NORMALIZED"].fillna("__NA__") != repaired[
        "STATUS_NORMALIZED"
    ].fillna("__NA__")
    if changed.any():
        tmp = pd.DataFrame(
            {
                "before": city.loc[changed, "STATUS_NORMALIZED"].fillna("__NA__"),
                "after": repaired.loc[changed, "STATUS_NORMALIZED"].fillna("__NA__"),
            }
        )
        print(tmp.value_counts().to_string())
    else:
        print("  (none)")

    print("\nFINAL_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FINAL_DATE"].notna().sum()
        pct = n_has / len(sub) if len(sub) else 0.0
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({pct:.1%})")

    print("\nPERMIT_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["PERMIT_DATE"].notna().sum()
        pct = n_has / len(sub) if len(sub) else 0.0
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({pct:.1%})")

    print("\nFILE_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FILE_DATE"].notna().sum()
        pct = n_has / len(sub) if len(sub) else 0.0
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({pct:.1%})")

    final_miss = repaired[
        (repaired["STATUS_NORMALIZED"] == "Final") & repaired["FINAL_DATE"].isna()
    ]
    print(f"\nFinal still missing FINAL_DATE: {len(final_miss)}")
    if len(final_miss):
        ps_counts = Counter()
        for idx in final_miss.index:
            d = _safe_parse(repaired.at[idx, "DATA"])
            if d is None:
                continue
            raw = (_raw_status(d) or "").strip() or "__EMPTY__"
            ps_counts[raw] += 1
        print("  by Status:", dict(ps_counts))

    status_null = repaired["STATUS_NORMALIZED"].isna().sum()
    print(f"\nSTATUS_NORMALIZED still null: {status_null}")

    af_miss = repaired[
        repaired["STATUS_NORMALIZED"].isin(["Active", "Final"])
        & repaired["PERMIT_DATE"].isna()
    ]
    print(f"Active/Final still missing PERMIT_DATE: {len(af_miss)}")
    if len(af_miss):
        ps_counts = Counter()
        for idx in af_miss.index:
            d = _safe_parse(repaired.at[idx, "DATA"])
            if d is None:
                continue
            raw = (_raw_status(d) or "").strip() or "__EMPTY__"
            ps_counts[raw] += 1
        print("  by Status:", dict(ps_counts))

    # Date-order sanity
    file_gt_permit = 0
    permit_gt_final = 0
    for idx in repaired.index:
        f = repaired.at[idx, "FILE_DATE"]
        p = repaired.at[idx, "PERMIT_DATE"]
        fin = repaired.at[idx, "FINAL_DATE"]
        if (
            pd.notna(f)
            and pd.notna(p)
            and pd.Timestamp(f).normalize() > pd.Timestamp(p).normalize()
        ):
            file_gt_permit += 1
        if (
            pd.notna(p)
            and pd.notna(fin)
            and pd.Timestamp(p).normalize() > pd.Timestamp(fin).normalize()
        ):
            permit_gt_final += 1
    print(f"\nFILE_DATE > PERMIT_DATE: {file_gt_permit}")
    print(f"PERMIT_DATE > FINAL_DATE: {permit_gt_final}")

    # PERMIT_DATE agreement with Issue Date
    mismatch = 0
    for idx in repaired.index:
        d = _safe_parse(repaired.at[idx, "DATA"])
        if d is None:
            continue
        issue = _issue_date(d)
        p = repaired.at[idx, "PERMIT_DATE"]
        if _present(issue) and pd.notna(p) and not _dates_equal(p, issue):
            mismatch += 1
    print(f"PERMIT_DATE ≠ Issue Date (when both present): {mismatch}")

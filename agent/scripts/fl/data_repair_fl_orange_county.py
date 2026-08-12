"""Data repair for Orange County (FL) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Orange County DATA shares one top-level key set (PERMIT INFORMATION,
PROCESSES AND REPORTS, etc.) but varies by payload richness and by the
shape of PROCESSES AND REPORTS:

  - permit_info_dict_pr:   full PERMIT INFORMATION + dict-shaped processes
                           (Finalize Permit / Inspection History / Issuance)
  - permit_info_list_pr:   full PERMIT INFORMATION + list-shaped processes
                           (flat PROCESS / STATUS / END DT rows)
  - permit_info_empty_pr:  full PERMIT INFORMATION + empty processes dict
  - permit_info_shell:     PERMIT INFORMATION contains only PERMIT#

Canonical mappings (full schemas):
  - PERMIT INFORMATION.STATUS              → STATUS_NORMALIZED
  - PERMIT INFORMATION['APPLY DATE']       → FILE_DATE
  - PERMIT INFORMATION['ISSUE DATE']       → PERMIT_DATE
  - Finalize Permit Certificate of
    Completion / Cert. of Occupancy END
    DATE, else latest Passed/History final
    inspection (not Final Issuance Review) → FINAL_DATE

Known issues repaired:
  - STATUS_NORMALIZED null on Internet Incomplete / Pending W/Comments /
    Internet Pending / Final Plan Prep / Masterfile / Final Issuance
    Review rows → FILLED as In Review.
  - FINAL_DATE on list_pr Final rows was incorrectly set to
    Final Issuance Review END DT (often equal to PERMIT_DATE) → FIXED
    to the latest Passed final inspection, or cleared when no true
    final exists.
  - FINAL_DATE missing on many dict_pr Complete/Final rows that have
    Certificate of Completion or Passed final inspections → FILLED.
  - FINAL_DATE present on non-Final rows (same Final Issuance Review
    leak) → cleared (FIXED).

Not repairable / left as-is:
  - 64 permit_info_shell rows have no STATUS / APPLY / ISSUE dates in
    DATA → STATUS_NORMALIZED and FILE_DATE stay missing.
  - FILE_DATE / PERMIT_DATE already match APPLY / ISSUE DATE whenever
    those sources exist (0 date corrections on those fields).
  - Some Final rows have empty process history and no finalize /
    final-inspection stamp → FINAL_DATE stays missing.
"""

from __future__ import annotations

import json
import math
import re
from typing import Optional

import numpy as np
import pandas as pd


# Plausible calendar-year range for permit dates in this jurisdiction.
_MIN_YEAR = 1990
_MAX_YEAR = 2035

# Final inspection / completion process names (exclude issuance / plan prep).
_FINAL_INSP_RE = re.compile(
    r"final|fnl|certificate of completion|cert\.?\s*of\s*occupancy|"
    r"certificate of occupancy",
    re.I,
)
_FINAL_INSP_EXCLUDE_RE = re.compile(
    r"final issuance|final plan|final power|pre power|tco\b|tug\b|intake",
    re.I,
)
_FINAL_INSPECTION_OK = ("passed", "approved", "complete", "completed", "history", "closed")


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
    """Parse a date value as UTC, returning pd.NaT on failure or implausible year."""
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return pd.NaT
    if isinstance(val, str) and not str(val).strip():
        return pd.NaT
    if not isinstance(val, str) and pd.isna(val):
        return pd.NaT
    text = str(val).strip()
    if text.upper() in ("TBD", "NONE", "N/A", "NA", "NULL", "NAN", "00/00/0000", "0/0/0000"):
        return pd.NaT
    try:
        dt = pd.to_datetime(val, utc=True, errors="coerce")
    except (ValueError, TypeError, OverflowError):
        return pd.NaT
    if dt is pd.NaT or pd.isna(dt):
        return pd.NaT
    year = int(dt.year)
    if year < _MIN_YEAR or year > _MAX_YEAR:
        return pd.NaT
    return dt


def _dates_equal(a, b) -> bool:
    """Compare two datelike values at calendar-day resolution (UTC)."""
    da = _safe_to_datetime(a)
    db = _safe_to_datetime(b)
    if da is pd.NaT or db is pd.NaT:
        return False
    return da.date() == db.date()


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    pi = data_dict.get("PERMIT INFORMATION")
    if not isinstance(pi, dict) or not pi:
        return "unknown"
    if set(pi.keys()) == {"PERMIT#"} or "STATUS" not in pi:
        return "permit_info_shell"
    pr = data_dict.get("PROCESSES AND REPORTS")
    if isinstance(pr, list):
        return "permit_info_list_pr"
    if isinstance(pr, dict):
        if pr:
            return "permit_info_dict_pr"
        return "permit_info_empty_pr"
    return "permit_info_full"


# ── Status mapping ──────────────────────────────────────────────────────────

_STATUS_MAP = {
    "Complete": "Final",
    "Issued": "Active",
    "Expired": "Inactive",
    "Application Expired": "Inactive",
    "Cancelled": "Inactive",
    "Review": "In Review",
    "New": "In Review",
    "Ready to Issue": "In Review",
    "Replaced": "In Review",
    "Stop Work": "In Review",
    "Internet Incomplete": "In Review",
    "Pending W/Comments": "In Review",
    "Internet Pending": "In Review",
    "Final Plan Prep": "In Review",
    "Masterfile": "In Review",
    "Final Issuance Review": "In Review",
}


def _permit_status(d: dict) -> Optional[str]:
    pi = d.get("PERMIT INFORMATION") if isinstance(d.get("PERMIT INFORMATION"), dict) else {}
    status = pi.get("STATUS")
    if status is None:
        return None
    status = str(status).strip()
    return status or None


def _map_status(label: Optional[str]) -> Optional[str]:
    if not label:
        return None
    if label in _STATUS_MAP:
        return _STATUS_MAP[label]
    # Case / whitespace tolerance
    upper = re.sub(r"\s+", " ", label).strip().upper()
    for key, mapped in _STATUS_MAP.items():
        if key.upper() == upper:
            return mapped
    return None


def _is_final_process(proc: str) -> bool:
    if not proc:
        return False
    if _FINAL_INSP_EXCLUDE_RE.search(proc):
        return False
    return bool(_FINAL_INSP_RE.search(proc))


def _status_ok(status: str) -> bool:
    s = (status or "").strip().lower()
    if not s:
        return False
    if "fail" in s or s == "partial" or "carryover" in s:
        return False
    return any(tok == s or tok in s for tok in _FINAL_INSPECTION_OK)


def _best_date_from_keys(item: dict, keys: tuple[str, ...]):
    best = pd.NaT
    for key in keys:
        dt = _safe_to_datetime(item.get(key))
        if dt is pd.NaT:
            continue
        if best is pd.NaT or dt > best:
            best = dt
    return best


def _finalize_certificate_date(d: dict):
    """Latest Complete Certificate of Completion / Cert. of Occupancy END DATE."""
    pr = d.get("PROCESSES AND REPORTS")
    if not isinstance(pr, dict):
        return pd.NaT
    rows = pr.get("Finalize Permit")
    if not isinstance(rows, list):
        return pd.NaT
    best = pd.NaT
    for item in rows:
        if not isinstance(item, dict):
            continue
        proc = str(item.get("PROCESS") or "")
        status = str(item.get("STATUS") or "")
        if not _status_ok(status):
            continue
        pl = proc.lower()
        if any(x in pl for x in ("tco", "pre power", "final power", "intake", "tug")):
            continue
        if not (
            "certificate" in pl
            or "cert." in pl
            or "occupancy" in pl
            or "completion" in pl
        ):
            continue
        dt = _best_date_from_keys(item, ("END DATE", "DATE", "START DATE"))
        if dt is pd.NaT:
            continue
        if best is pd.NaT or dt > best:
            best = dt
    return best


def _final_inspection_date_dict(d: dict):
    """Latest Passed/History final inspection under dict-shaped processes."""
    pr = d.get("PROCESSES AND REPORTS")
    if not isinstance(pr, dict):
        return pd.NaT
    best = pd.NaT
    for section in ("Inspection History", "Scheduled Inspections"):
        rows = pr.get(section)
        if not isinstance(rows, list):
            continue
        for item in rows:
            if not isinstance(item, dict):
                continue
            proc = str(item.get("PROCESS") or "")
            if not _is_final_process(proc):
                continue
            result = str(item.get("RESULT") or item.get("STATUS") or "")
            if not _status_ok(result):
                continue
            dt = _best_date_from_keys(
                item, ("END DATE", "DATE", "SCHED DATE", "START DATE")
            )
            if dt is pd.NaT:
                continue
            if best is pd.NaT or dt > best:
                best = dt
    return best


def _final_inspection_date_list(d: dict):
    """Latest Passed/History final inspection under list-shaped processes."""
    pr = d.get("PROCESSES AND REPORTS")
    if not isinstance(pr, list):
        return pd.NaT
    best = pd.NaT
    for item in pr:
        if not isinstance(item, dict):
            continue
        proc = str(item.get("PROCESS") or "")
        if not _is_final_process(proc):
            continue
        status = str(item.get("STATUS") or "")
        if not _status_ok(status):
            continue
        dt = _best_date_from_keys(item, ("END DT", "SCHEDULE DT", "START DT"))
        if dt is pd.NaT:
            continue
        if best is pd.NaT or dt > best:
            best = dt
    return best


def _compute_final_date(d: dict, schema: str):
    """Prefer finalize certificate stamp; else latest true final inspection."""
    cert = _finalize_certificate_date(d)
    if cert is not pd.NaT:
        return cert
    if schema == "permit_info_list_pr":
        return _final_inspection_date_list(d)
    return _final_inspection_date_dict(d)


def _set_status(repairs: dict, current_status, expected: Optional[str]) -> None:
    if expected is None:
        return
    if pd.isna(current_status):
        repairs["STATUS_NORMALIZED"] = expected
        repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"
    elif current_status != expected:
        repairs["STATUS_NORMALIZED"] = expected
        repairs["STATUS_NORMALIZED_FLAG"] = "FIXED"


def _set_date_from_source(repairs: dict, field: str, current, source, fill_ok: bool) -> None:
    """Overwrite *field* from *source* when missing (if fill_ok) or mismatched."""
    if source is pd.NaT:
        return
    flag = f"{field}_FLAG"
    if pd.isna(current):
        if fill_ok:
            repairs[field] = source
            repairs[flag] = "FILLED"
    elif not _dates_equal(current, source):
        repairs[field] = source
        repairs[flag] = "FIXED"


def _clear_date(repairs: dict, field: str, current) -> None:
    if pd.isna(current):
        return
    repairs[field] = pd.NaT
    repairs[f"{field}_FLAG"] = "FIXED"


# ── Per-schema repair logic ─────────────────────────────────────────────────

def _repair_full(row, d: dict, schema: str, repairs: dict) -> None:
    current_status = row["STATUS_NORMALIZED"]
    raw_status = _permit_status(d)
    expected = _map_status(raw_status)
    _set_status(repairs, current_status, expected)
    effective_status = repairs.get("STATUS_NORMALIZED", current_status)

    pi = d.get("PERMIT INFORMATION") if isinstance(d.get("PERMIT INFORMATION"), dict) else {}
    apply = _safe_to_datetime(pi.get("APPLY DATE"))
    _set_date_from_source(repairs, "FILE_DATE", row["FILE_DATE"], apply, fill_ok=True)

    issue = _safe_to_datetime(pi.get("ISSUE DATE"))
    if not pd.isna(row["PERMIT_DATE"]):
        if issue is not pd.NaT and not _dates_equal(row["PERMIT_DATE"], issue):
            repairs["PERMIT_DATE"] = issue
            repairs["PERMIT_DATE_FLAG"] = "FIXED"
    elif effective_status in ("Active", "Final") and issue is not pd.NaT:
        repairs["PERMIT_DATE"] = issue
        repairs["PERMIT_DATE_FLAG"] = "FILLED"

    final = _compute_final_date(d, schema)
    current_final = row["FINAL_DATE"]
    if effective_status == "Final":
        if final is not pd.NaT:
            _set_date_from_source(repairs, "FINAL_DATE", current_final, final, fill_ok=True)
        else:
            # Clear incorrect Final Issuance Review dates when no true final exists.
            _clear_date(repairs, "FINAL_DATE", current_final)
    else:
        _clear_date(repairs, "FINAL_DATE", current_final)


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Orange County permit records using the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Orange County".  Must contain
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
        if d is None or schema == "permit_info_shell":
            continue

        repairs: dict = {}
        if schema.startswith("permit_info"):
            _repair_full(row, d, schema, repairs)

        for key, value in repairs.items():
            out.at[idx, key] = value

    for col in ("FILE_DATE", "PERMIT_DATE", "FINAL_DATE"):
        out[col] = pd.to_datetime(out[col], errors="coerce", utc=True).dt.tz_localize(None)

    return out


# ── CLI: run standalone to preview repair stats ─────────────────────────────

if __name__ == "__main__":
    import os
    from collections import Counter

    from dotenv import load_dotenv

    load_dotenv("/Users/ekung/projects/la-permits-data/.env")
    MY_DATA_PATH = os.getenv("MY_DATA_PATH")
    AGENT_DATA_PATH = os.getenv("AGENT_DATA_PATH")
    filepath = os.path.join(MY_DATA_PATH, "processed_data", "permits_fl_sample.parquet")
    df = pd.read_parquet(filepath)
    city = df[df["JURISDICTION"] == "Orange County"].copy()

    print(f"Orange County records: {len(city):,}\n")

    repaired = data_repair(city)

    print("INFERRED_SCHEMA:")
    for s, c in repaired["INFERRED_SCHEMA"].value_counts(dropna=False).items():
        print(f"  {str(s):25s}: {c:>4,}")
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

    print("\nSTATUS_NORMALIZED_FLAG by schema / label:")
    for flag in ["FILLED", "FIXED"]:
        sub = repaired[repaired["STATUS_NORMALIZED_FLAG"] == flag]
        print(f"  {flag} ({len(sub)}):")
        labels = []
        for idx in sub.index:
            d = _safe_parse(city.loc[idx, "DATA"])
            schema = repaired.loc[idx, "INFERRED_SCHEMA"]
            label = _permit_status(d) if d else None
            labels.append(
                (
                    schema,
                    label,
                    city.loc[idx, "STATUS_NORMALIZED"],
                    repaired.loc[idx, "STATUS_NORMALIZED"],
                )
            )
        for (schema, label, before, after), n in Counter(labels).most_common(30):
            print(f"    [{schema}] {label!r}: {before!r} → {after!r}  x{n}")

    print("\nFILE_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FILE_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({n_has / max(len(sub), 1):.1%})")

    print("\nPERMIT_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["PERMIT_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({n_has / max(len(sub), 1):.1%})")

    print("\nFINAL_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FINAL_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({n_has / max(len(sub), 1):.1%})")

    # Chronology sanity
    r = repaired.copy()
    for c in ("FILE_DATE", "PERMIT_DATE", "FINAL_DATE"):
        r[c] = pd.to_datetime(r[c], errors="coerce")
    print("\nChronology after repair:")
    print(
        "  PERMIT < FILE:",
        (
            r.PERMIT_DATE.notna()
            & r.FILE_DATE.notna()
            & (r.PERMIT_DATE.dt.normalize() < r.FILE_DATE.dt.normalize())
        ).sum(),
    )
    print(
        "  FINAL < PERMIT:",
        (
            r.FINAL_DATE.notna()
            & r.PERMIT_DATE.notna()
            & (r.FINAL_DATE.dt.normalize() < r.PERMIT_DATE.dt.normalize())
        ).sum(),
    )
    print(
        "  FINAL on non-Final:",
        ((r.STATUS_NORMALIZED != "Final") & r.FINAL_DATE.notna()).sum(),
    )

    print("\nFINAL_DATE_FLAG breakdown:")
    print(repaired["FINAL_DATE_FLAG"].value_counts(dropna=False))

    if AGENT_DATA_PATH:
        out_path = os.path.join(AGENT_DATA_PATH, "orange_county_repaired_sample.parquet")
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote {out_path}")

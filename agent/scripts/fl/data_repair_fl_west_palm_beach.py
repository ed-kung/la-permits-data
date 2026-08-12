"""Data repair for West Palm Beach (FL) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

West Palm Beach DATA has two portal families in this sample:

  - energov_*:  Tyler EnerGov-style payload with ``entity``, ``details``,
                ``fees``, ``contacts``, ``processing_status`` (inspections),
                and sometimes ``reviews`` / ``holds`` / ``attachments`` /
                ``more_info``.
  - legacy_*:   older city portal with ``permit_info``, ``inspection_info``,
                ``plan_info``, etc.

Content variants (INFERRED_SCHEMA) further split by which dates are set:

  - energov_issued_finaled / energov_issued / energov_finaled /
    energov_applied / energov_status_only
  - legacy_issued_finaled / legacy_issued / legacy_finaled /
    legacy_applied / legacy_status_only
  - missing / unknown

Canonical mappings:
  EnerGov
    - entity.CaseStatus / details.PermitStatus
      + FinalDate / FinalizeDate → Final          → STATUS_NORMALIZED
    - entity.ApplyDate (details fallback)         → FILE_DATE
    - entity.IssueDate (details fallback)         → PERMIT_DATE
    - FinalDate / FinalizeDate; else latest
      Passed final-ish processing_status; else
      latest Passed inspection (Final only;
      inspection fallbacks must not predate
      IssueDate)                                  → FINAL_DATE

  Legacy
    - permit_info.Status
      + C.O. Issued → Final
      + Open + Issued Date → Active               → STATUS_NORMALIZED
    - permit_info.Application Date                → FILE_DATE
    - permit_info.Issued Date                     → PERMIT_DATE
    - C.O. Issued; else latest RES=P final-ish
      inspection; else latest RES=P inspection    → FINAL_DATE

Known issues repaired:
  - 8 EnerGov rows with CaseStatus in
    {Requires Resubmit for Prescreen / ROW Permits,
     Plan Rev Fees Pd} had null STATUS_NORMALIZED
    → FILLED as In Review.
  - 2 Issued rows carry FinalDate while
    STATUS_NORMALIZED=Active → FIXED to Final;
    FINAL_DATE then FILLED from FinalDate.
  - 7 legacy Open rows with Issued Date were
    normalized as In Review → FIXED to Active.
  - 6 In Review rows have IssueDate but null
    PERMIT_DATE → FILLED.
  - Many Final rows lack FinalDate / C.O. Issued
    but have passed final (or other) inspections
    → FINAL_DATE FILLED from inspections.

Not repairable from DATA:
  - FILE_DATE already matches ApplyDate /
    Application Date for every sample row.
  - ~86 Active/Final rows have blank IssueDate /
    Issued Date → PERMIT_DATE stays missing.
  - Some Final rows have empty inspection history
    and no FinalDate / C.O. Issued → FINAL_DATE
    stays missing.
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
    r"final|fnl|cert(?:ificate)?\s*of\s*(?:occupancy|completion)|"
    r"\bc\.?o\.?\b|\bc o\b|\bcc\b",
    re.I,
)
_ENTITY_PASS_OK = ("passed", "approved", "complete", "completed")


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
    if isinstance(val, dict):
        return pd.NaT
    if isinstance(val, str) and not str(val).strip():
        return pd.NaT
    if not isinstance(val, str) and pd.isna(val):
        return pd.NaT
    text = str(val).strip()
    if text.upper() in {
        "TBD", "NONE", "N/A", "NA", "NULL", "NAN",
        "00/00/0000", "0/0/0000",
    }:
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


def _is_legacy(d: dict) -> bool:
    return isinstance(d.get("permit_info"), dict)


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    if not isinstance(data_dict, dict):
        return "unknown"

    if _is_legacy(data_dict):
        pi = data_dict.get("permit_info") or {}
        applied = _safe_to_datetime(pi.get("Application Date"))
        issued = _safe_to_datetime(pi.get("Issued Date"))
        finaled = _safe_to_datetime(pi.get("C.O. Issued"))
        status = str(pi.get("Status") or "").strip()
        has_issued = issued is not pd.NaT
        has_finaled = finaled is not pd.NaT
        has_applied = applied is not pd.NaT
        if has_issued and has_finaled:
            return "legacy_issued_finaled"
        if has_issued:
            return "legacy_issued"
        if has_finaled:
            return "legacy_finaled"
        if has_applied:
            return "legacy_applied"
        if status:
            return "legacy_status_only"
        return "legacy_shell"

    if not {"entity", "details"}.issubset(data_dict.keys()):
        return "unknown"

    entity = data_dict.get("entity") if isinstance(data_dict.get("entity"), dict) else {}
    details = data_dict.get("details") if isinstance(data_dict.get("details"), dict) else {}
    applied = _safe_to_datetime(entity.get("ApplyDate") or details.get("ApplyDate"))
    issued = _safe_to_datetime(entity.get("IssueDate") or details.get("IssueDate"))
    finaled = _safe_to_datetime(entity.get("FinalDate") or details.get("FinalizeDate"))
    status = str(entity.get("CaseStatus") or details.get("PermitStatus") or "").strip()
    has_issued = issued is not pd.NaT
    has_finaled = finaled is not pd.NaT
    has_applied = applied is not pd.NaT
    if has_issued and has_finaled:
        return "energov_issued_finaled"
    if has_issued:
        return "energov_issued"
    if has_finaled:
        return "energov_finaled"
    if has_applied:
        return "energov_applied"
    if status:
        return "energov_status_only"
    return "energov_shell"


# ── Status mapping ───────────────────────────────────────────────────────────

# EnerGov CaseStatus (as stored in DATA) → STATUS_NORMALIZED
_ENTITY_STATUS_MAP = {
    "Complete": "Final",
    "Closed": "Final",
    "Issued": "Active",
    "Approved": "Active",
    "Open": "In Review",  # overridden to Active when IssueDate present
    "Expired": "Inactive",
    "Void": "Inactive",
    "Canceled": "Inactive",
    "Cancelled": "Inactive",
    "Revoked": "Inactive",
    "Withdrawn": "Inactive",
    "Denied": "Inactive",
    "Submitted - Online": "In Review",
    "Submitted": "In Review",
    "Fees Due": "In Review",
    "In Review": "In Review",
    "Requires Resubmit": "In Review",
    "Requires Resubmit for Prescreen": "In Review",
    "Requires Resubmit for ROW Permits": "In Review",
    "Plan Rev Fees Pd": "In Review",
    "On Hold": "In Review",
}

# Legacy permit_info.Status → STATUS_NORMALIZED
_LEGACY_STATUS_MAP = {
    "Closed": "Final",
    "Complete": "Final",
    "Open": "In Review",  # overridden to Active when Issued Date present
    "Issued": "Active",
    "Approved": "Active",
    "Expired": "Inactive",
    "Void": "Inactive",
    "Canceled": "Inactive",
    "Cancelled": "Inactive",
    "Revoked": "Inactive",
}


def _case_status(d: dict) -> Optional[str]:
    entity = d.get("entity") if isinstance(d.get("entity"), dict) else {}
    details = d.get("details") if isinstance(d.get("details"), dict) else {}
    status = entity.get("CaseStatus") or details.get("PermitStatus")
    if status is None:
        return None
    text = str(status).strip()
    return text or None


def _map_status_label(label: Optional[str], mapping: dict) -> Optional[str]:
    if not label:
        return None
    if label in mapping:
        return mapping[label]
    upper = re.sub(r"\s+", " ", label).strip().upper()
    for key, mapped in mapping.items():
        if key.upper() == upper:
            return mapped
    return None


def _entity_date(d: dict, entity_key: str, *detail_keys: str):
    entity = d.get("entity") if isinstance(d.get("entity"), dict) else {}
    dt = _safe_to_datetime(entity.get(entity_key))
    if dt is not pd.NaT:
        return dt
    details = d.get("details") if isinstance(d.get("details"), dict) else {}
    for key in detail_keys:
        dt = _safe_to_datetime(details.get(key))
        if dt is not pd.NaT:
            return dt
    return pd.NaT


def _inspection_dates_entity(d: dict, final_only: bool):
    """Latest Passed inspection date from processing_status."""
    ps = d.get("processing_status")
    if not isinstance(ps, list):
        return pd.NaT
    best = pd.NaT
    for item in ps:
        if not isinstance(item, dict):
            continue
        desc = str(item.get("description") or "")
        status = str(item.get("status") or "").strip().lower()
        if "partial" in status:
            continue
        if not any(tok in status for tok in _ENTITY_PASS_OK):
            continue
        if final_only and not _FINAL_INSP_RE.search(desc):
            continue
        dt = _safe_to_datetime(item.get("scheduled_date"))
        if dt is pd.NaT:
            dt = _safe_to_datetime(item.get("requested_date"))
        if dt is pd.NaT:
            continue
        if best is pd.NaT or dt > best:
            best = dt
    return best


def _inspection_dates_legacy(d: dict, final_only: bool):
    """Latest RES=P inspection date from inspection_info."""
    rows = d.get("inspection_info")
    if not isinstance(rows, list):
        return pd.NaT
    best = pd.NaT
    for item in rows:
        if not isinstance(item, dict):
            continue
        if str(item.get("RES") or "").strip().upper() != "P":
            continue
        typ = str(item.get("TYPE") or "")
        if final_only and not _FINAL_INSP_RE.search(typ):
            continue
        dt = _safe_to_datetime(item.get("INSP DATE"))
        if dt is pd.NaT:
            continue
        if best is pd.NaT or dt > best:
            best = dt
    return best


def _pick_final_candidate(stamp, issue, final_insp, any_pass):
    """Prefer agency final stamp, then final insp, then any passed insp."""
    if stamp is not pd.NaT:
        return stamp
    for cand in (final_insp, any_pass):
        if cand is pd.NaT:
            continue
        if issue is pd.NaT or cand.date() >= issue.date():
            return cand
    return pd.NaT


def _set_status(repairs: dict, current_status, expected: Optional[str]) -> None:
    if expected is None:
        return
    if pd.isna(current_status):
        repairs["STATUS_NORMALIZED"] = expected
        repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"
    elif current_status != expected:
        repairs["STATUS_NORMALIZED"] = expected
        repairs["STATUS_NORMALIZED_FLAG"] = "FIXED"


def _set_date_from_source(repairs: dict, field: str, current, source, fill_ok: bool = True) -> None:
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


def _clear_date(repairs: dict, row, field: str) -> None:
    current = repairs.get(field, row[field])
    if pd.isna(current):
        return
    repairs[field] = pd.NaT
    repairs[f"{field}_FLAG"] = "FIXED"


# ── Per-schema repair logic ─────────────────────────────────────────────────

def _repair_entity(row, d: dict, repairs: dict) -> None:
    current_status = row["STATUS_NORMALIZED"]
    raw = _case_status(d)
    expected = _map_status_label(raw, _ENTITY_STATUS_MAP)

    issue = _entity_date(d, "IssueDate", "IssueDate")
    final_stamp = _entity_date(d, "FinalDate", "FinalizeDate")

    # Issued / Approved with a final stamp → Final (portal status lag).
    if final_stamp is not pd.NaT:
        expected = "Final"
    # Open + issued is an active permit (rare on EnerGov; kept for symmetry).
    elif raw and raw.strip().lower() == "open" and issue is not pd.NaT:
        expected = "Active"

    _set_status(repairs, current_status, expected)
    effective_status = repairs.get("STATUS_NORMALIZED", current_status)

    apply = _entity_date(d, "ApplyDate", "ApplyDate")
    _set_date_from_source(repairs, "FILE_DATE", row["FILE_DATE"], apply)

    if issue is not pd.NaT:
        _set_date_from_source(repairs, "PERMIT_DATE", row["PERMIT_DATE"], issue)

    final_insp = _inspection_dates_entity(d, final_only=True)
    any_pass = _inspection_dates_entity(d, final_only=False)
    final = _pick_final_candidate(final_stamp, issue, final_insp, any_pass)

    if effective_status == "Final":
        _set_date_from_source(repairs, "FINAL_DATE", row["FINAL_DATE"], final)
    else:
        _clear_date(repairs, row, "FINAL_DATE")


def _repair_legacy(row, d: dict, repairs: dict) -> None:
    pi = d.get("permit_info") if isinstance(d.get("permit_info"), dict) else {}
    current_status = row["STATUS_NORMALIZED"]
    raw = str(pi.get("Status") or "").strip() or None
    expected = _map_status_label(raw, _LEGACY_STATUS_MAP)

    issue = _safe_to_datetime(pi.get("Issued Date"))
    final_stamp = _safe_to_datetime(pi.get("C.O. Issued"))

    if final_stamp is not pd.NaT:
        expected = "Final"
    elif raw and raw.strip().lower() == "open" and issue is not pd.NaT:
        expected = "Active"

    _set_status(repairs, current_status, expected)
    effective_status = repairs.get("STATUS_NORMALIZED", current_status)

    apply = _safe_to_datetime(pi.get("Application Date"))
    _set_date_from_source(repairs, "FILE_DATE", row["FILE_DATE"], apply)

    if issue is not pd.NaT:
        _set_date_from_source(repairs, "PERMIT_DATE", row["PERMIT_DATE"], issue)

    final_insp = _inspection_dates_legacy(d, final_only=True)
    any_pass = _inspection_dates_legacy(d, final_only=False)
    final = _pick_final_candidate(final_stamp, issue, final_insp, any_pass)

    if effective_status == "Final":
        _set_date_from_source(repairs, "FINAL_DATE", row["FINAL_DATE"], final)
    else:
        _clear_date(repairs, row, "FINAL_DATE")


# ── Main entry point ─────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    West Palm Beach permit records using the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "West Palm Beach".  Must
        contain columns STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE,
        FINAL_DATE, and DATA.

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
        if _is_legacy(d):
            _repair_legacy(row, d, repairs)
        elif {"entity", "details"}.issubset(d.keys()):
            _repair_entity(row, d, repairs)

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
    city = df[df["JURISDICTION"] == "West Palm Beach"].copy()

    print(f"West Palm Beach records: {len(city):,}\n")
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
        labels = []
        for idx in sub.index:
            d = _safe_parse(city.loc[idx, "DATA"])
            if d and _is_legacy(d):
                label = (d.get("permit_info") or {}).get("Status")
            else:
                label = _case_status(d) if d else None
            labels.append(
                (
                    repaired.loc[idx, "INFERRED_SCHEMA"],
                    label,
                    city.loc[idx, "STATUS_NORMALIZED"],
                    repaired.loc[idx, "STATUS_NORMALIZED"],
                )
            )
        for (schema, label, before, after), n in Counter(labels).most_common(20):
            print(f"    [{schema}] {label!r}: {before!r} → {after!r}  x{n}")

    print("\nFILE_DATE coverage by status (after):")
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

    r = repaired.copy()
    for c in ("FILE_DATE", "PERMIT_DATE", "FINAL_DATE"):
        r[c] = pd.to_datetime(r[c], errors="coerce")
    print("\nChronology after repair:")
    print(
        "  PERMIT < FILE:",
        (r.PERMIT_DATE.notna() & r.FILE_DATE.notna()
         & (r.PERMIT_DATE.dt.normalize() < r.FILE_DATE.dt.normalize())).sum(),
    )
    print(
        "  FINAL < PERMIT:",
        (r.FINAL_DATE.notna() & r.PERMIT_DATE.notna()
         & (r.FINAL_DATE.dt.normalize() < r.PERMIT_DATE.dt.normalize())).sum(),
    )
    print(
        "  FINAL on non-Final:",
        ((r.STATUS_NORMALIZED != "Final") & r.FINAL_DATE.notna()).sum(),
    )

    if agent_data_path:
        out_path = os.path.join(agent_data_path, "west_palm_beach_repaired_sample.parquet")
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote {out_path}")

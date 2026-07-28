"""Data repair for Manteca (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Manteca DATA has two primary agency scrapes plus a thin search stub:

  - permit_portal: legacy Logos / citizen portal with top-level keys
    ``Permit Summary``, ``Payment Summary``, ``Inspections``, etc.
  - accela_tasks: Accela Civic Access rows with dated workflow events
    under ``tasks``
  - accela_shell: Accela rows whose task shells have no dated events
    (mostly ``Completed`` / expired migrations)
  - search_only: only ``search_data`` (temporary / incomplete records)

Canonical mappings:

  permit_portal
    - Permit Summary.StatusValue          → STATUS_NORMALIZED (+ embedded date)
    - StatusValue Created / Pending date  → FILE_DATE
    - StatusValue Issued date; else PaidValue → PERMIT_DATE (Active/Final)
    - StatusValue Completed date          → FINAL_DATE

  accela_*
    - DATA.status                         → STATUS_NORMALIZED
    - DATA.date / search_data['Date']     → FILE_DATE
    - Permit Issuance / Issued events     → PERMIT_DATE
    - Inspection Completed|Finaled /
      CO Issued events                    → FINAL_DATE

Known issues repaired:
  - Portal: ~10 StatusValue/STATUS_NORMALIZED mismatches (Completed→Active,
    Issued→In Review) → FIXED; missing Completed FINAL_DATE → FILLED.
  - Portal: nearly all FILE_DATE gaps on Created/Pending → FILLED from
    StatusValue; Issued/Completed lack an application date in DATA.
  - Portal: Active/Final missing PERMIT_DATE → FILLED from Issued date or
    PaidValue (payment typically at issuance).
  - Accela: Fees Received / Pending Applicant null status → FILLED In Review.
  - Accela: Active/Final missing PERMIT_DATE / Final missing FINAL_DATE
    when Issued / completion task events exist → FILLED.
  - Spurious FINAL_DATE on Active Accela rows → cleared (FIXED).

Not repairable / left as-is:
  - Portal Issued/Completed FILE_DATE: no application/submittal date in DATA.
  - Accela Completed shells (empty tasks): no issuance or finaling events
    → PERMIT_DATE / FINAL_DATE stay missing.
  - search_only TMP rows: empty Status; FILE_DATE already present.
"""

from __future__ import annotations

import json
import math
import re
from typing import Optional

import numpy as np
import pandas as pd


_MIN_YEAR = 1990
_MAX_YEAR = 2035

_SV_DATE_RE = re.compile(
    r"(?P<label>Permit Completed|Permit Issued|Permit Created|"
    r"Application Created|Pending Payment|Pending Review)"
    r".*?\b(?P<date>\d{1,2}/\d{1,2}/\d{2,4})\b",
    re.IGNORECASE,
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
        return json.loads(data)
    return data


def _safe_to_datetime(val):
    """Parse a date value, returning pd.NaT on failure or implausible year."""
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return pd.NaT
    if isinstance(val, str):
        s = val.strip()
        if not s or s.upper() == "TBD" or s.lower() == "not paid":
            return pd.NaT
    try:
        dt = pd.to_datetime(val)
    except (ValueError, TypeError):
        return pd.NaT
    if dt is pd.NaT or pd.isna(dt):
        return pd.NaT
    if getattr(dt, "tzinfo", None) is not None:
        dt = dt.tz_convert("UTC").tz_localize(None)
    year = int(dt.year)
    if year < _MIN_YEAR or year > _MAX_YEAR:
        return pd.NaT
    return dt


def _dates_equal(a, b) -> bool:
    da = _safe_to_datetime(a)
    db = _safe_to_datetime(b)
    if da is pd.NaT or db is pd.NaT:
        return False
    return da.normalize() == db.normalize()


def _event_field(event: dict, *names: str):
    targets = {n.strip() for n in names}
    for k, v in event.items():
        if isinstance(k, str) and k.strip() in targets:
            return v
    return None


def _iter_tasks(tasks: list):
    for t in tasks or []:
        if not isinstance(t, dict):
            continue
        yield t
        for st in t.get("subtasks") or []:
            if isinstance(st, dict):
                yield st


def _has_dated_events(d: dict) -> bool:
    for t in _iter_tasks(d.get("tasks") or []):
        for e in t.get("events") or []:
            if not isinstance(e, dict):
                continue
            if _safe_to_datetime(_event_field(e, "on")) is not pd.NaT:
                return True
    return False


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())
    if "Permit Summary" in keys:
        return "permit_portal"
    if "status" in keys and "tasks" in keys:
        return "accela_tasks" if _has_dated_events(data_dict) else "accela_shell"
    if keys <= {"search_data"} or keys == {"search_data"}:
        return "search_only"
    if "search_data" in keys and len(keys) <= 2:
        return "search_only"
    return "unknown"


def _set_status(repairs: dict, row, expected: str):
    current = row["STATUS_NORMALIZED"]
    if pd.isna(current):
        repairs["STATUS_NORMALIZED"] = expected
        repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"
    elif current != expected:
        repairs["STATUS_NORMALIZED"] = expected
        repairs["STATUS_NORMALIZED_FLAG"] = "FIXED"


def _fill_date(repairs: dict, row, field: str, value):
    if value is pd.NaT or pd.isna(value):
        return
    if pd.isna(row[field]):
        repairs[field] = value
        repairs[f"{field}_FLAG"] = "FILLED"


def _fix_date(repairs: dict, row, field: str, value):
    if value is pd.NaT or pd.isna(value):
        return
    current = row[field]
    if pd.isna(current):
        repairs[field] = value
        repairs[f"{field}_FLAG"] = "FILLED"
    elif not _dates_equal(current, value):
        repairs[field] = value
        repairs[f"{field}_FLAG"] = "FIXED"


def _clear_date(repairs: dict, row, field: str):
    if not pd.isna(row[field]):
        repairs[field] = pd.NaT
        repairs[f"{field}_FLAG"] = "FIXED"


# ── permit_portal ────────────────────────────────────────────────────────────

def _parse_status_value(sv: str):
    """Return (kind, embedded_date) from Permit Summary.StatusValue."""
    if not sv or not isinstance(sv, str):
        return None, pd.NaT
    text = sv.strip()
    low = text.lower()

    kind = None
    if "completed" in low:
        kind = "completed"
    elif "issued" in low:
        kind = "issued"
    elif "pending" in low:
        kind = "pending"
    elif "created" in low:
        kind = "created"

    m = _SV_DATE_RE.search(text)
    if m:
        dt = _safe_to_datetime(m.group("date"))
        return kind, dt

    # Fallback: any MM/DD/YYYY in the string
    m2 = re.search(r"(\d{1,2}/\d{1,2}/\d{2,4})", text)
    dt = _safe_to_datetime(m2.group(1)) if m2 else pd.NaT
    return kind, dt


def _portal_expected_status(kind: Optional[str]) -> Optional[str]:
    return {
        "completed": "Final",
        "issued": "Active",
        "pending": "In Review",
        "created": "In Review",
    }.get(kind)


def _repair_permit_portal(row, d: dict, repairs: dict):
    summary = d.get("Permit Summary") or {}
    payment = d.get("Payment Summary") or {}
    sv = summary.get("StatusValue") or ""
    kind, sv_dt = _parse_status_value(sv)
    paid_dt = _safe_to_datetime(payment.get("PaidValue"))

    expected = _portal_expected_status(kind)
    if expected is not None:
        _set_status(repairs, row, expected)

    effective = repairs.get("STATUS_NORMALIZED", row["STATUS_NORMALIZED"])

    # FILE_DATE: application / created / pending-as-of date only.
    # Issued / Completed StatusValue dates are not filing dates.
    if kind in ("created", "pending") and sv_dt is not pd.NaT:
        if pd.isna(row["FILE_DATE"]):
            _fill_date(repairs, row, "FILE_DATE", sv_dt)
        elif not _dates_equal(row["FILE_DATE"], sv_dt):
            _fix_date(repairs, row, "FILE_DATE", sv_dt)

    # PERMIT_DATE for Active / Final
    if effective in ("Active", "Final"):
        permit_src = pd.NaT
        if kind == "issued" and sv_dt is not pd.NaT:
            permit_src = sv_dt
        elif paid_dt is not pd.NaT:
            # PaidValue is the best issuance proxy when StatusValue is Completed.
            final_ref = sv_dt if kind == "completed" else _safe_to_datetime(
                row["FINAL_DATE"]
            )
            if final_ref is pd.NaT or paid_dt.normalize() <= final_ref.normalize():
                permit_src = paid_dt
        if permit_src is not pd.NaT:
            if pd.isna(row["PERMIT_DATE"]):
                _fill_date(repairs, row, "PERMIT_DATE", permit_src)
            elif kind == "issued" and not _dates_equal(row["PERMIT_DATE"], permit_src):
                _fix_date(repairs, row, "PERMIT_DATE", permit_src)

    # FINAL_DATE for Final / Completed
    if kind == "completed" and sv_dt is not pd.NaT:
        if effective != "Final":
            # StatusValue already forced Final above; use effective after set.
            pass
        if repairs.get("STATUS_NORMALIZED", row["STATUS_NORMALIZED"]) == "Final":
            if pd.isna(row["FINAL_DATE"]):
                _fill_date(repairs, row, "FINAL_DATE", sv_dt)
            elif not _dates_equal(row["FINAL_DATE"], sv_dt):
                _fix_date(repairs, row, "FINAL_DATE", sv_dt)

    # Clear FINAL_DATE on non-Final portal rows
    eff = repairs.get("STATUS_NORMALIZED", row["STATUS_NORMALIZED"])
    if eff != "Final":
        _clear_date(repairs, row, "FINAL_DATE")


# ── Accela ───────────────────────────────────────────────────────────────────

_ACCELA_STATUS_MAP = {
    "Completed": "Final",
    "Closed": "Final",
    "Closed - Completed": "Final",
    "Closed - Complete": "Final",
    "Issued": "Active",
    "Received": "In Review",
    "In Review": "In Review",
    "Revisions Approved": "In Review",
    "Ready to Issue": "In Review",
    "Fees Received": "In Review",
    "Pending Applicant": "In Review",
    "Permit Expired": "Inactive",
    "Closed - Withdrawn": "Inactive",
    "Closed - Denied": "Inactive",
}

_COMPLETION_MARKS = {
    "Finaled",
    "Completed",
    "Completed - CO Not Required",
    "CO Issued",
}


def _accela_expected_status(d: dict) -> Optional[str]:
    raw = d.get("status")
    if isinstance(raw, str) and raw.strip():
        return _ACCELA_STATUS_MAP.get(raw.strip())
    sd = d.get("search_data") or {}
    sd_status = sd.get("Status")
    if isinstance(sd_status, str) and sd_status.strip():
        return _ACCELA_STATUS_MAP.get(sd_status.strip())
    return None


def _first_issued_date(tasks: list):
    dates = []
    # Prefer Permit Issuance / Issued
    for t in _iter_tasks(tasks):
        name = t.get("name") or ""
        for e in t.get("events") or []:
            if not isinstance(e, dict):
                continue
            if _event_field(e, "Marked as") != "Issued":
                continue
            dt = _safe_to_datetime(_event_field(e, "on"))
            if dt is pd.NaT:
                continue
            if name == "Permit Issuance":
                dates.append((0, dt))
            else:
                dates.append((1, dt))
    if not dates:
        return pd.NaT
    dates.sort(key=lambda x: (x[0], x[1]))
    return dates[0][1]


def _latest_completion_date(tasks: list):
    dates = []
    for t in _iter_tasks(tasks):
        for e in t.get("events") or []:
            if not isinstance(e, dict):
                continue
            if _event_field(e, "Marked as") not in _COMPLETION_MARKS:
                continue
            dt = _safe_to_datetime(_event_field(e, "on"))
            if dt is not pd.NaT:
                dates.append(dt)
    return max(dates) if dates else pd.NaT


def _repair_accela(row, d: dict, repairs: dict):
    expected = _accela_expected_status(d)
    if expected is not None:
        _set_status(repairs, row, expected)

    effective = repairs.get("STATUS_NORMALIZED", row["STATUS_NORMALIZED"])
    tasks = d.get("tasks") or []

    # FILE_DATE from DATA.date (search_data Date as fallback)
    file_src = _safe_to_datetime(d.get("date"))
    if file_src is pd.NaT:
        file_src = _safe_to_datetime((d.get("search_data") or {}).get("Date"))
    if file_src is not pd.NaT:
        if pd.isna(row["FILE_DATE"]):
            _fill_date(repairs, row, "FILE_DATE", file_src)
        elif not _dates_equal(row["FILE_DATE"], file_src):
            _fix_date(repairs, row, "FILE_DATE", file_src)

    # PERMIT_DATE for Active / Final from Issued events
    if effective in ("Active", "Final"):
        issued = _first_issued_date(tasks)
        if issued is not pd.NaT:
            if pd.isna(row["PERMIT_DATE"]):
                _fill_date(repairs, row, "PERMIT_DATE", issued)
            elif not _dates_equal(row["PERMIT_DATE"], issued):
                # Prefer explicit Permit Issuance / Issued over upstream value
                if any(
                    (_event_field(e, "Marked as") == "Issued"
                     and _dates_equal(_event_field(e, "on"), issued))
                    for t in _iter_tasks(tasks)
                    for e in (t.get("events") or [])
                    if isinstance(e, dict) and t.get("name") == "Permit Issuance"
                ):
                    _fix_date(repairs, row, "PERMIT_DATE", issued)

    # FINAL_DATE for Final from completion marks
    completion = _latest_completion_date(tasks)
    if effective == "Final":
        if completion is not pd.NaT:
            if pd.isna(row["FINAL_DATE"]):
                _fill_date(repairs, row, "FINAL_DATE", completion)
            elif not _dates_equal(row["FINAL_DATE"], completion):
                _fix_date(repairs, row, "FINAL_DATE", completion)
    else:
        # Spurious finals on Active / In Review / Inactive
        _clear_date(repairs, row, "FINAL_DATE")


def _repair_search_only(row, d: dict, repairs: dict):
    sd = d.get("search_data") or {}
    file_src = _safe_to_datetime(sd.get("Date"))
    if file_src is not pd.NaT:
        if pd.isna(row["FILE_DATE"]):
            _fill_date(repairs, row, "FILE_DATE", file_src)
        elif not _dates_equal(row["FILE_DATE"], file_src):
            _fix_date(repairs, row, "FILE_DATE", file_src)

    raw_status = sd.get("Status")
    if isinstance(raw_status, str) and raw_status.strip():
        expected = _ACCELA_STATUS_MAP.get(raw_status.strip())
        if expected is not None:
            _set_status(repairs, row, expected)

    effective = repairs.get("STATUS_NORMALIZED", row["STATUS_NORMALIZED"])
    if effective != "Final":
        _clear_date(repairs, row, "FINAL_DATE")


# ── Main entry point ─────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Manteca permit records using information from the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Manteca". Must contain
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

        if schema == "permit_portal":
            _repair_permit_portal(row, d, repairs)
        elif schema in ("accela_tasks", "accela_shell"):
            _repair_accela(row, d, repairs)
        elif schema == "search_only":
            _repair_search_only(row, d, repairs)

        for key, value in repairs.items():
            out.at[idx, key] = value

    # Normalize repaired date columns to datetime64 (avoid mixed date/Timestamp).
    for col in ("FILE_DATE", "PERMIT_DATE", "FINAL_DATE"):
        out[col] = pd.to_datetime(out[col], errors="coerce")

    return out


# ── CLI: run standalone to preview repair stats ──────────────────────────────

if __name__ == "__main__":
    import os
    from dotenv import load_dotenv

    load_dotenv("/Users/ekung/projects/la-permits-data/.env")
    MY_DATA_PATH = os.getenv("MY_DATA_PATH")
    filepath = os.path.join(MY_DATA_PATH, "processed_data", "permits_ca_sample.parquet")
    df = pd.read_parquet(filepath)
    city = df[(df["JURISDICTION"] == "Manteca") & (df["STATE"] == "CA")].copy()

    print(f"Manteca records: {len(city):,}\n")

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

    print("\nFINAL_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FINAL_DATE"].notna().sum()
        n = len(sub)
        pct = n_has / n if n else 0.0
        print(f"  {status:15s}: {n_has:>4,} / {n:>4,} ({pct:.1%})")

    print("\nPERMIT_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["PERMIT_DATE"].notna().sum()
        n = len(sub)
        pct = n_has / n if n else 0.0
        print(f"  {status:15s}: {n_has:>4,} / {n:>4,} ({pct:.1%})")

    print("\nFILE_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FILE_DATE"].notna().sum()
        n = len(sub)
        pct = n_has / n if n else 0.0
        print(f"  {status:15s}: {n_has:>4,} / {n:>4,} ({pct:.1%})")

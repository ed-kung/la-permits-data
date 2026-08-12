"""Data repair for Bradenton (FL) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Bradenton DATA has three schemas in this sample:

  - city_app:     legacy city portal payload with app / permit /
                  inspection_list / fees / init_info / permit_list
  - accela:       Accela Citizen Access payload with status / date /
                  tasks / search_data / inspections
  - search_only:  sparse Accela shell with only search_data (temp
                  records; Status blank)

Canonical mappings:
  - city_app: app.Status (+ Permit Status when unissued Active)
                                                 → STATUS_NORMALIZED
  - city_app: Application Received Date          → FILE_DATE
  - city_app: permit.Issued Date                 → PERMIT_DATE
  - city_app: latest PASS inspection; for
    CERTIFICATE OF COMPLETION types, Issued Date → FINAL_DATE
  - accela: top-level status / search_data.Status
                                                 → STATUS_NORMALIZED
  - accela: date / search_data.Date              → FILE_DATE
  - accela: earliest Permit Issuance
    ``Permit Issued`` event                      → PERMIT_DATE
  - accela: Certificate Issuance
    ``Certificate of Completion``; else Final
    Inspection ``Approved``                      → FINAL_DATE

Known issues repaired:
  - city_app STATUS_NORMALIZED almost entirely null despite
    clear app.Status values (complete / closed, active / issued,
    …) → FILLED from app.Status.
  - Unissued ACTIVE / APPROVED|ISSUED rows with Permit Status
    REVIEWING / FEE → In Review (not Active).
  - Accela Documents Received / More Info Required left null
    → FILLED as In Review.
  - Accela Admin Closed incorrectly labeled Final → FIXED to
    Inactive.
  - Accela PERMIT_DATE / FINAL_DATE never ingested → FILLED from
    Permit Issuance / Certificate Issuance (or Final Inspection)
    task events.
  - city_app FINAL_DATE never ingested → FILLED from PASS
    inspections (or Issued Date on COC permit types).

Not repairable from DATA:
  - city_app rows with blank Issued Date (~139) → PERMIT_DATE
    stays missing (mostly REVIEWING / FEE / WITHDRAWN).
  - Final city_app rows with no dated PASS inspections →
    FINAL_DATE stays missing.
  - search_only temp records (25TMP-*) have blank Status and
    no tasks → STATUS / PERMIT / FINAL stay missing.
  - Accela Approved license registrations have no Permit
    Issuance events → PERMIT_DATE stays missing.
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

_COC_TYPE_RE = re.compile(
    r"certificate\s+of\s+completion|\bcoc\b|\bcc\b",
    re.I,
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
    """Parse a date value, returning pd.NaT on failure / out-of-range."""
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


def _apply_status(repairs: dict, current, expected: Optional[str]) -> Optional[str]:
    """Apply expected STATUS_NORMALIZED; return effective status."""
    if expected is None:
        if pd.isna(current):
            return None
        return current

    if pd.isna(current):
        repairs["STATUS_NORMALIZED"] = expected
        repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"
    elif current != expected:
        repairs["STATUS_NORMALIZED"] = expected
        repairs["STATUS_NORMALIZED_FLAG"] = "FIXED"

    return repairs.get("STATUS_NORMALIZED", current)


def _apply_date(repairs: dict, row, field: str, candidate) -> None:
    """Fill or fix *field* from *candidate* datetime (pd.NaT = no candidate)."""
    cand = _safe_to_datetime(candidate)
    if cand is pd.NaT or pd.isna(cand):
        return

    current = row[field]
    if pd.isna(current):
        repairs[field] = cand
        repairs[f"{field}_FLAG"] = "FILLED"
    elif not _dates_equal(current, cand):
        repairs[field] = cand
        repairs[f"{field}_FLAG"] = "FIXED"


def _clear_date(repairs: dict, row, field: str) -> None:
    """Clear a spurious date value."""
    current = repairs.get(field, row[field])
    if pd.isna(current):
        return
    repairs[field] = pd.NaT
    repairs[f"{field}_FLAG"] = "FIXED"


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())
    if "app" in keys and "permit" in keys:
        return "city_app"
    if "status" in keys and "tasks" in keys:
        return "accela"
    if keys == {"search_data"} or (
        "search_data" in keys and "app" not in keys and "status" not in keys
    ):
        return "search_only"
    return "unknown"


# ── city_app status / dates ──────────────────────────────────────────────────

_CITY_APP_STATUS_MAP = {
    "COMPLETE / CLOSED": "Final",
    "COMPLETE / APPROVED": "Final",
    "COMPLETE / ISSUED": "Final",
    "COMPLETE / CANCELLED": "Inactive",
    "ACTIVE / ISSUED": "Active",
    "ACTIVE / APPROVED": "Active",
    "ACTIVE / EXTENDED": "Active",
    "ACTIVE / CLOSED": "Active",
    "ACTIVE / REVIEWING": "In Review",
    "ACTIVE / INITIAL": "In Review",
    "ACTIVE / EXPIRED": "Inactive",
    "ACTIVE / ENTERED IN ERROR": "Inactive",
    "EXPIRED / EXPIRED": "Inactive",
    "EXPIRED / ISSUED": "Inactive",
    "WITHDRAWN / CANCELLED": "Inactive",
    "WITHDRAWN / CLOSED": "Inactive",
    "WITHDRAWN / WITHDRAWN": "Inactive",
    "WITHDRAWN / VOID": "Inactive",
    "WITHDRAWN / ENTERED IN ERROR": "Inactive",
    "ENTERED IN ERROR / ENTERED IN ERROR": "Inactive",
    "ENTERED IN ERROR / CLOSED": "Inactive",
    "ENTERED IN ERROR / CANCELLED": "Inactive",
    "DENIED / DENIED": "Inactive",
    "DENIED / CLOSED": "Inactive",
    "HOLD / ISSUED": "In Review",
    "HOLD / ON HOLD": "In Review",
}


def _map_city_app_status(app_status: str, permit_status: Optional[str],
                         issued) -> Optional[str]:
    if not app_status:
        return None
    key = app_status.strip().upper()
    expected = _CITY_APP_STATUS_MAP.get(key)
    if expected is None:
        # Fallback on first token.
        head = key.split("/", 1)[0].strip()
        if head == "COMPLETE":
            expected = "Final"
        elif head == "ACTIVE":
            expected = "Active"
        elif head in {"EXPIRED", "WITHDRAWN", "DENIED", "ENTERED IN ERROR"}:
            expected = "Inactive"
        elif head == "HOLD":
            expected = "In Review"
        else:
            return None

    # Unissued "Active" rows that are still in fee/review are In Review.
    if expected == "Active":
        issued_dt = _safe_to_datetime(issued)
        ps = (permit_status or "").strip().upper()
        if (issued_dt is pd.NaT or pd.isna(issued_dt)) and ps in {
            "REVIEWING", "FEE",
        }:
            return "In Review"
    return expected


def _latest_pass_date(inspection_list) -> pd.Timestamp:
    dates = []
    for row in inspection_list or []:
        if not isinstance(row, list) or len(row) < 3:
            continue
        result = str(row[2] or "").strip().upper()
        if result != "PASS":
            continue
        dt = _safe_to_datetime(row[1])
        if dt is not pd.NaT and not pd.isna(dt):
            dates.append(dt)
    return max(dates) if dates else pd.NaT


def _repair_city_app(row, d: dict, repairs: dict) -> None:
    app = d.get("app") if isinstance(d.get("app"), dict) else {}
    permit = d.get("permit") if isinstance(d.get("permit"), dict) else {}

    app_status = app.get("Status") or ""
    permit_status = permit.get("Permit Status")
    issued = permit.get("Issued Date")

    expected = _map_city_app_status(app_status, permit_status, issued)
    effective = _apply_status(repairs, row["STATUS_NORMALIZED"], expected)

    _apply_date(repairs, row, "FILE_DATE", app.get("Application Received Date"))

    issued_dt = _safe_to_datetime(issued)
    if issued_dt is not pd.NaT and not pd.isna(issued_dt):
        _apply_date(repairs, row, "PERMIT_DATE", issued_dt)
    elif effective == "In Review":
        _clear_date(repairs, row, "PERMIT_DATE")

    if effective == "Final":
        final_src = _latest_pass_date(d.get("inspection_list"))
        permit_type = str(permit.get("Permit Type") or "")
        # COC records: Issued Date is the completion / signoff stamp.
        if _COC_TYPE_RE.search(permit_type) and issued_dt is not pd.NaT:
            if final_src is pd.NaT or pd.isna(final_src):
                final_src = issued_dt
            else:
                final_src = max(final_src, issued_dt)
        _apply_date(repairs, row, "FINAL_DATE", final_src)
    else:
        _clear_date(repairs, row, "FINAL_DATE")


# ── Accela status / dates ────────────────────────────────────────────────────

_ACCELA_STATUS_MAP = {
    "Closed-CC Issued": "Final",
    "Completed": "Final",
    "Issued": "Active",
    "Approved": "Active",
    "Documents Received": "In Review",
    "Revisions Required": "In Review",
    "Additional Info Required": "In Review",
    "More Info Required": "In Review",
    "Payment Due": "In Review",
    "Payment Received": "In Review",
    "New": "In Review",
    "In Review": "In Review",
    "Closed-Withdrawn": "Inactive",
    "Denied": "Inactive",
    "Closed-Denied": "Inactive",
    "Expired": "Inactive",
    "Admin Closed": "Inactive",
}

_ACCELA_STATUS_MAP_LOWER = {k.lower(): v for k, v in _ACCELA_STATUS_MAP.items()}


def _accela_raw_status(d: dict) -> str:
    status = d.get("status")
    if isinstance(status, str) and status.strip():
        return status.strip()
    sd = d.get("search_data") if isinstance(d.get("search_data"), dict) else {}
    sd_status = sd.get("Status")
    if isinstance(sd_status, str) and sd_status.strip():
        return sd_status.strip()
    return ""


def _map_accela_status(data_status: str) -> Optional[str]:
    if not data_status:
        return None
    return (
        _ACCELA_STATUS_MAP.get(data_status)
        or _ACCELA_STATUS_MAP_LOWER.get(data_status.lower())
    )


def _iter_task_nodes(tasks: list):
    for t in tasks or []:
        if not isinstance(t, dict):
            continue
        yield (t.get("name") or "").replace("\xa0", " ").strip(), t
        for st in t.get("subtasks") or []:
            if isinstance(st, dict):
                yield (st.get("name") or "").replace("\xa0", " ").strip(), st


def _event_dates(tasks: list, task_names: set, mark_pred) -> list:
    dates = []
    for name, t in _iter_task_nodes(tasks):
        if name not in task_names:
            continue
        for e in t.get("events") or []:
            if not isinstance(e, dict):
                continue
            marked = (e.get("Marked as") or "").replace("\xa0", " ").strip()
            if not mark_pred(marked):
                continue
            dt = _safe_to_datetime(e.get("on"))
            if dt is not pd.NaT and not pd.isna(dt):
                dates.append(dt)
    return dates


def _file_date_from_accela(d: dict):
    dt = _safe_to_datetime(d.get("date"))
    if dt is not pd.NaT and not pd.isna(dt):
        return dt
    sd = d.get("search_data") if isinstance(d.get("search_data"), dict) else {}
    return _safe_to_datetime(sd.get("Date"))


def _permit_date_from_accela(tasks: list):
    issued = _event_dates(
        tasks,
        {"Permit Issuance"},
        lambda m: m == "Permit Issued",
    )
    return min(issued) if issued else pd.NaT


def _final_date_from_accela(tasks: list):
    cc = _event_dates(
        tasks,
        {"Certificate Issuance"},
        lambda m: m == "Certificate of Completion",
    )
    if cc:
        return max(cc)
    fi = _event_dates(
        tasks,
        {"Final Inspection"},
        lambda m: m == "Approved",
    )
    return max(fi) if fi else pd.NaT


def _repair_accela(row, d: dict, repairs: dict) -> None:
    tasks = d.get("tasks") or []

    expected = _map_accela_status(_accela_raw_status(d))
    effective = _apply_status(repairs, row["STATUS_NORMALIZED"], expected)

    _apply_date(repairs, row, "FILE_DATE", _file_date_from_accela(d))

    issued = _permit_date_from_accela(tasks)
    current_permit = row["PERMIT_DATE"]
    if issued is not pd.NaT and not pd.isna(issued):
        if pd.isna(current_permit):
            if effective in ("Active", "Final"):
                repairs["PERMIT_DATE"] = issued
                repairs["PERMIT_DATE_FLAG"] = "FILLED"
        elif not _dates_equal(current_permit, issued):
            repairs["PERMIT_DATE"] = issued
            repairs["PERMIT_DATE_FLAG"] = "FIXED"
    elif effective == "In Review" and not pd.isna(current_permit):
        _clear_date(repairs, row, "PERMIT_DATE")

    if effective == "Final":
        _apply_date(repairs, row, "FINAL_DATE", _final_date_from_accela(tasks))
    else:
        _clear_date(repairs, row, "FINAL_DATE")


def _repair_search_only(row, d: dict, repairs: dict) -> None:
    """Sparse temp records: only FILE_DATE is recoverable."""
    sd = d.get("search_data") if isinstance(d.get("search_data"), dict) else {}
    status = (sd.get("Status") or "").strip()
    expected = _map_accela_status(status) if status else None
    _apply_status(repairs, row["STATUS_NORMALIZED"], expected)
    _apply_date(repairs, row, "FILE_DATE", sd.get("Date") or d.get("date"))


# ── Main entry point ─────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Bradenton permit records using information from the raw DATA JSON.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Bradenton".  Must contain
        columns STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, FINAL_DATE,
        and DATA.

    Returns
    -------
    pd.DataFrame
        Copy of *df* with repaired fields, ``{FIELD}_FLAG`` columns, and
        ``INFERRED_SCHEMA``.
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
        if schema == "city_app":
            _repair_city_app(row, d, repairs)
        elif schema == "accela":
            _repair_accela(row, d, repairs)
        elif schema == "search_only":
            _repair_search_only(row, d, repairs)

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

    repo_root = Path(__file__).resolve().parents[3]
    load_dotenv(repo_root / ".env")
    my_data_path = os.getenv("MY_DATA_PATH")
    agent_data_path = os.getenv("AGENT_DATA_PATH")
    filepath = os.path.join(
        my_data_path, "processed_data", "permits_fl_sample.parquet"
    )
    df = pd.read_parquet(filepath)
    city = df[
        (df["JURISDICTION"] == "Bradenton") & (df["STATE"] == "FL")
    ].copy()

    print(f"Bradenton records: {len(city):,}\n")
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

    print("\nSTATUS_NORMALIZED transitions (before → after):")
    transitions = (
        pd.DataFrame({
            "before": city["STATUS_NORMALIZED"].astype("object"),
            "after": repaired["STATUS_NORMALIZED"].astype("object"),
        })
        .groupby(["before", "after"], dropna=False)
        .size()
        .reset_index(name="n")
    )
    changed = transitions[
        transitions["before"].astype(str) != transitions["after"].astype(str)
    ]
    print(changed.sort_values("n", ascending=False).to_string(index=False))

    print("\nFILE_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FILE_DATE"].notna().sum()
        print(
            f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} "
            f"({(n_has / len(sub) if len(sub) else 0):.1%})"
        )

    print("\nPERMIT_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["PERMIT_DATE"].notna().sum()
        print(
            f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} "
            f"({(n_has / len(sub) if len(sub) else 0):.1%})"
        )

    print("\nFINAL_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FINAL_DATE"].notna().sum()
        print(
            f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} "
            f"({(n_has / len(sub) if len(sub) else 0):.1%})"
        )

    both = repaired[
        repaired["PERMIT_DATE"].notna() & repaired["FINAL_DATE"].notna()
    ]
    n_inv = (
        both["PERMIT_DATE"].dt.normalize() > both["FINAL_DATE"].dt.normalize()
    ).sum()
    print(f"\nPERMIT_DATE > FINAL_DATE inversions after repair: {n_inv}")

    if agent_data_path:
        out_path = os.path.join(
            agent_data_path, "bradenton_repaired_sample.parquet"
        )
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote repaired sample → {out_path}")

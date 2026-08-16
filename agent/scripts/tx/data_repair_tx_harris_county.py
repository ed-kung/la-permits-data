"""Data repair for Harris County (TX) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Harris County DATA has two payload families:

  - permit:       Permit-level scrape with top-level ``permit_status``,
                  ``permit_effective_start_date``, nested ``details`` and
                  ``project_data`` (each with ``event_logs``).
  - application:  Application-level scrape with top-level ``event_logs``,
                  ``project_details``, and ``permit_requests``.

Canonical mappings:
  - permit_status / project_details.status: → STATUS_NORMALIZED
  - First Submit (else Draft) in application event logs → FILE_DATE
  - First Issued event in permit/application logs → PERMIT_DATE
    (fallback: permit_effective_start_date when no Issued event)
  - No reliable final/completion signal → FINAL_DATE cleared unless
    effective status is Final (none observed in sample)

Known issues repaired:
  - STATUS_NORMALIZED null despite usable agency status (Issued, Cancel,
    Return to Customer, Final Approval, etc.) → FILLED.
  - STATUS_NORMALIZED disagrees with agency status (e.g. Revision:
    In-Revision stored as Active; Issued stored as Inactive) → FIXED.
  - FILE_DATE missing on permit-schema rows, or set to Issued /
    In Progress instead of Submit/Draft → FILLED / FIXED.
  - PERMIT_DATE missing on Issued rows, or set to
    permit_effective_start_date when that date is a 180/365-day
    validity offset after the Issued event → FILLED / FIXED.
  - Spurious FINAL_DATE on non-Final rows (often the Issued date, FILE
    date, or an expiration-like offset) → cleared (FIXED).

Not repairable / left as-is:
  - No Final / completion events in DATA → FINAL_DATE stays empty.
  - Active/Issued rows without an Issued event and without
    permit_effective_start_date → PERMIT_DATE stays missing (rare).
"""

from __future__ import annotations

import json
import math
from typing import Optional

import numpy as np
import pandas as pd


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
    """Parse a date value, returning pd.NaT on failure / blanks / sentinels."""
    if val is None:
        return pd.NaT
    if isinstance(val, float) and math.isnan(val):
        return pd.NaT
    if not isinstance(val, str) and pd.isna(val):
        return pd.NaT
    if isinstance(val, dict):
        return pd.NaT
    text = str(val).strip()
    if not text or text.upper() in {
        "TBD", "NONE", "N/A", "NA", "NULL", "NAN",
        "00/00/0000", "0/0/0000",
    }:
        return pd.NaT
    try:
        dt = pd.to_datetime(val, errors="coerce")
    except (ValueError, TypeError, OverflowError):
        return pd.NaT
    if pd.isna(dt):
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


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())
    if "permit_status" in keys and "project_data" in keys:
        return "permit"
    if "event_logs" in keys and "project_details" in keys:
        return "application"
    return "unknown"


def _first_event_date(logs, names) -> pd.Timestamp:
    if not isinstance(logs, list):
        return pd.NaT
    name_set = set(names)
    for event in logs:
        if isinstance(event, dict) and event.get("event_name") in name_set:
            return _safe_to_datetime(event.get("date"))
    return pd.NaT


def _event_logs(obj) -> list:
    if not isinstance(obj, dict):
        return []
    logs = obj.get("event_logs")
    return logs if isinstance(logs, list) else []


# ── Status mapping ───────────────────────────────────────────────────────────

_STATUS_MAP = {
    # Active — permit has been issued (possibly under revision)
    "Issued": "Active",
    "Issued: In-Revision": "Active",
    # In Review — application / payment / review workflow
    "In Progress": "In Review",
    "Ready for Payment": "In Review",
    "Paid": "In Review",
    "Final Approval": "In Review",
    "Dept Approval": "In Review",
    "Assigned": "In Review",
    "Submit": "In Review",
    "Transfer Department": "In Review",
    "Transfer Department: In-Revision": "In Review",
    "Return to Customer": "In Review",
    "Return to Customer: In-Revision": "In Review",
    "Revision: In-Revision": "In Review",
    # Inactive
    "Cancel": "Inactive",
    "Refund": "Inactive",
}


def _raw_status(d: dict, schema: str) -> Optional[str]:
    if schema == "permit":
        val = d.get("permit_status")
    elif schema == "application":
        details = d.get("project_details")
        if not isinstance(details, dict):
            return None
        val = details.get("status:")
        if val is None:
            val = details.get("status")
    else:
        return None
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return None
    text = str(val).strip()
    return text or None


def _expected_status(d: dict, schema: str) -> Optional[str]:
    raw = _raw_status(d, schema)
    if raw is None:
        return None
    return _STATUS_MAP.get(raw)


def _apply_status(repairs: dict, current, expected: Optional[str]):
    """Apply expected STATUS_NORMALIZED; return effective status."""
    if expected is None:
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


def _file_date_candidate(d: dict, schema: str):
    """Application/submittal date: first Submit, else Draft."""
    if schema == "permit":
        logs = _event_logs(d.get("project_data"))
    elif schema == "application":
        logs = d.get("event_logs") if isinstance(d.get("event_logs"), list) else []
    else:
        return pd.NaT

    submit = _first_event_date(logs, {"Submit"})
    if submit is not pd.NaT and not pd.isna(submit):
        return submit
    return _first_event_date(logs, {"Draft"})


def _permit_date_candidate(d: dict, schema: str):
    """Issuance date: first Issued event; else effective start as fallback."""
    if schema == "permit":
        issued = _first_event_date(_event_logs(d.get("details")), {"Issued"})
        if issued is pd.NaT or pd.isna(issued):
            issued = _first_event_date(_event_logs(d.get("project_data")), {"Issued"})
        if issued is not pd.NaT and not pd.isna(issued):
            return issued
        return _safe_to_datetime(d.get("permit_effective_start_date"))

    if schema == "application":
        logs = d.get("event_logs") if isinstance(d.get("event_logs"), list) else []
        issued = _first_event_date(logs, {"Issued"})
        if issued is not pd.NaT and not pd.isna(issued):
            return issued
        starts = []
        for pr in d.get("permit_requests") or []:
            if isinstance(pr, dict):
                start = _safe_to_datetime(pr.get("permit_effective_start_date"))
                if start is not pd.NaT and not pd.isna(start):
                    starts.append(start)
        return min(starts) if starts else pd.NaT

    return pd.NaT


# ── Per-row repair ───────────────────────────────────────────────────────────

def _repair_row(row, d: dict, schema: str, repairs: dict) -> None:
    expected = _expected_status(d, schema)
    effective_status = _apply_status(repairs, row["STATUS_NORMALIZED"], expected)

    _apply_date(repairs, row, "FILE_DATE", _file_date_candidate(d, schema))
    _apply_date(repairs, row, "PERMIT_DATE", _permit_date_candidate(d, schema))

    # Harris County payloads have no finaled / CO / completion mark.
    if effective_status == "Final":
        # No known FINAL_DATE source; leave as-is if already present.
        pass
    else:
        _clear_date(repairs, row, "FINAL_DATE")


# ── Main entry point ─────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Harris County permit records using the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Harris County".  Must contain
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
        if d is None:
            continue

        repairs: dict = {}
        if schema in {"permit", "application"}:
            _repair_row(row, d, schema, repairs)

        for key, value in repairs.items():
            out.at[idx, key] = value

    return out


# ── CLI: run standalone to preview repair stats ─────────────────────────────

if __name__ == "__main__":
    import os

    from dotenv import load_dotenv

    load_dotenv("/Users/ekung/projects/la-permits-data/.env")
    MY_DATA_PATH = os.getenv("MY_DATA_PATH")
    AGENT_DATA_PATH = os.getenv("AGENT_DATA_PATH")
    filepath = os.path.join(MY_DATA_PATH, "processed_data", "permits_tx_sample.parquet")
    df = pd.read_parquet(filepath)
    city = df[(df["JURISDICTION"] == "Harris County") & (df["STATE"] == "TX")].copy()

    print(f"Harris County records: {len(city):,}\n")

    repaired = data_repair(city)

    print("INFERRED_SCHEMA distribution:")
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

    print("\nFILE_DATE overall (after): "
          f"{repaired['FILE_DATE'].notna().sum()}/{len(repaired)}")

    print("\nPERMIT_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        if len(sub) == 0:
            continue
        n_has = sub["PERMIT_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({n_has / len(sub):.1%})")

    print("\nFINAL_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        if len(sub) == 0:
            continue
        n_has = sub["FINAL_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({n_has / len(sub):.1%})")

    if AGENT_DATA_PATH:
        out_dir = os.path.join(AGENT_DATA_PATH, "repaired")
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, "permits_tx_harris_county_repaired.parquet")
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote {out_path}")

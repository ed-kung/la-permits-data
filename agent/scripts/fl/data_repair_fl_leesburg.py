"""Data repair for Leesburg (FL) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Leesburg DATA is a sparse ``mini_set`` portal shell with no date fields.
Two key-set variants (INFERRED_SCHEMA):

  - mini_set_application_{status}: application_status / application_type /
    parcel / contractor / address / mini_set
  - mini_set_job_{status}:         job_status / job_type / job_description /
    address / mini_set
  - missing / unknown

Canonical mappings:
  - application_status or job_status → STATUS_NORMALIZED
  - (no application / issue / final timestamps in DATA)
    → FILE_DATE / PERMIT_DATE / FINAL_DATE unavailable

Status values observed in sample:
  - Closed / Certificate Issued / Certificate of Completion → Final
  - Permit Printed → Active
  - On Hold / Approved → In Review
  - Withdrawn / Abandoned → Inactive

Known issues repaired:
  - All 658 job-schema rows left STATUS_NORMALIZED (and
    STATUS_ORIGINAL) null because upstream only normalized
    application_status → FILLED from job_status.

Not repairable from DATA:
  - FILE_DATE / PERMIT_DATE / FINAL_DATE remain missing on every
    row — the mini_set payload carries no date keys.
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
    """Parse a date value, returning pd.NaT on failure / sentinel / OOR year."""
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


def _slug(val) -> str:
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return "blank"
    text = str(val).strip().lower()
    if not text:
        return "blank"
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_") or "blank"


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())
    if "job_status" in keys:
        return f"mini_set_job_{_slug(data_dict.get('job_status'))}"
    if "application_status" in keys or data_dict.get("mini_set") is True:
        return f"mini_set_application_{_slug(data_dict.get('application_status'))}"
    return "unknown"


# ── Status mapping ───────────────────────────────────────────────────────────

# application_status / job_status (case-insensitive via upper keys)
_STATUS_MAP = {
    # Final / completed
    "CLOSED": "Final",
    "CERTIFICATE ISSUED": "Final",
    "CERTIFICATE OF COMPLETION": "Final",
    # Active / issued
    "PERMIT PRINTED": "Active",
    "PERMIT ISSUED": "Active",
    "ISSUED": "Active",
    # In review / pre-issuance / hold
    "ON HOLD": "In Review",
    "APPROVED": "In Review",
    "IN REVIEW": "In Review",
    "PENDING": "In Review",
    # Inactive
    "WITHDRAWN": "Inactive",
    "ABANDONED": "Inactive",
    "EXPIRED": "Inactive",
    "CANCELLED": "Inactive",
    "CANCELED": "Inactive",
    "VOID": "Inactive",
    "VOIDED": "Inactive",
}


def _map_status(raw) -> Optional[str]:
    if raw is None or (isinstance(raw, float) and math.isnan(raw)):
        return None
    text = str(raw).strip()
    if not text:
        return None
    expected = _STATUS_MAP.get(text.upper())
    if expected is not None:
        return expected

    lower = text.lower()
    if (
        "certificate" in lower
        or "closed" in lower
        or "final" in lower
        or "completion" in lower
    ):
        return "Final"
    if "printed" in lower or ("issued" in lower and "ready" not in lower):
        return "Active"
    if (
        "withdraw" in lower
        or "abandon" in lower
        or "expire" in lower
        or "cancel" in lower
        or "void" in lower
        or "denied" in lower
    ):
        return "Inactive"
    if (
        "hold" in lower
        or "review" in lower
        or "pending" in lower
        or "approved" in lower
    ):
        return "In Review"
    return None


def _raw_status(d: dict) -> Optional[str]:
    for key in ("application_status", "job_status"):
        val = d.get(key)
        if val is None or (isinstance(val, float) and math.isnan(val)):
            continue
        text = str(val).strip()
        if text:
            return text
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


def _clear_date(repairs: dict, row, field: str) -> None:
    current = repairs.get(field, row[field])
    if pd.isna(current):
        return
    repairs[field] = pd.NaT
    repairs[f"{field}_FLAG"] = "FIXED"


# ── Per-record repair ────────────────────────────────────────────────────────

def _repair_mini_set(row, d: dict, repairs: dict) -> None:
    """Repair a Leesburg mini_set shell (status only; no dates in DATA)."""
    expected = _map_status(_raw_status(d))
    effective_status = _apply_status(repairs, row["STATUS_NORMALIZED"], expected)

    # No date keys exist in either Leesburg mini_set variant. Clear any
    # unsupported stamps that somehow appear on non-matching statuses.
    if effective_status == "In Review":
        _clear_date(repairs, row, "PERMIT_DATE")
    if effective_status != "Final":
        _clear_date(repairs, row, "FINAL_DATE")


# ── Main entry point ─────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Leesburg permit records using information from the raw DATA JSON.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Leesburg".  Must contain
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
        if d is None or schema == "unknown":
            continue

        repairs: dict = {}
        _repair_mini_set(row, d, repairs)
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
    filepath = os.path.join(my_data_path, "processed_data", "permits_fl_sample.parquet")
    df = pd.read_parquet(filepath)
    city = df[
        (df["JURISDICTION"] == "Leesburg") & (df["STATE"] == "FL")
    ].copy()

    print(f"Leesburg records: {len(city):,}\n")
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

    print("\nSTATUS fills by raw job_status:")
    filled = repaired[repaired["STATUS_NORMALIZED_FLAG"] == "FILLED"].copy()
    if len(filled):
        filled["raw"] = filled["DATA"].map(
            lambda x: (_safe_parse(x) or {}).get("job_status")
            or (_safe_parse(x) or {}).get("application_status")
        )
        filled["BEFORE"] = city.loc[filled.index, "STATUS_NORMALIZED"]
        print(
            filled.groupby(["raw", "BEFORE", "STATUS_NORMALIZED"])
            .size()
            .to_string()
        )
    else:
        print("  (none)")

    print("\nApp-schema status check (should be unchanged):")
    app = repaired[repaired["INFERRED_SCHEMA"].str.startswith("mini_set_application")]
    mismatches = app[
        app["STATUS_NORMALIZED"] != city.loc[app.index, "STATUS_NORMALIZED"]
    ]
    print(f"  changed rows: {len(mismatches)}")

    print("\nCoverage by STATUS_NORMALIZED (after):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        if len(sub) == 0:
            continue
        for field in ["FILE_DATE", "PERMIT_DATE", "FINAL_DATE"]:
            n_has = sub[field].notna().sum()
            print(
                f"  {status:12s} {field:12s}: "
                f"{n_has:>4,} / {len(sub):>4,} ({n_has / len(sub):.1%})"
            )

    if agent_data_path:
        out_dir = Path(agent_data_path) / "repaired"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "permits_fl_leesburg_repaired.parquet"
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote repaired sample → {out_path}")

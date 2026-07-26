"""Data repair for Corona (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Corona DATA is a single GIS / open-data portal schema. All sample rows
share top-level keys ``contacts``, ``fees``, ``inspections``,
``permit_info``, ``search_data``, and ``site_info``. Two content
variants appear:

  - permit_info_full:  non-empty ``inspections`` list
  - permit_info_basic: empty ``inspections`` list

Canonical fields (from ``permit_info``):

  - PermitStatus                         → STATUS_NORMALIZED
  - PermitAppliedDate                    → FILE_DATE
  - PermitIssuedDate (fallback:
    PermitApprovedDate)                  → PERMIT_DATE
  - PermitFinaledDate (fallback: latest
    passed final / C of O inspection)    → FINAL_DATE

Known issues repaired:
  - 169 rows labeled Active / In Review still carry PermitFinaledDate
    (stale ISSUED / APPROVED / NIC / PENDING labels) → FIXED to Final.
  - 3 SEND NOTICE TO CIP rows labeled Final with no issuance or
    finaling evidence → FIXED to In Review.
  - Active / Final rows missing PERMIT_DATE when Issued is empty but
    Approved is present → FILLED from PermitApprovedDate.
  - Final rows missing FINAL_DATE with a usable final / C of O
    inspection → FILLED from that inspection Completed date.
  - Spurious FINAL_DATE on non-Final rows (e.g. EXPIRED close
    timestamps) → cleared (FIXED).

Not repairable from DATA:
  - 1 FILE_DATE gap (empty PermitAppliedDate and no alternate).
  - ~369 legacy PermitStatus=FINAL rows (1990–1997) have Issued /
    Approved dates but blank PermitFinaledDate and no inspections.
  - Many Active ISSUED / ACTIVE utility, overload, and meter permits
    lack both Issued and Approved dates in DATA.
"""

import json
import math
import re
from datetime import date, datetime
from typing import Optional

import pandas as pd
import numpy as np


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
        return json.loads(data)
    return data


def _safe_to_datetime(val):
    """Parse a date value, returning pd.NaT on failure or implausible year."""
    if val is None or (isinstance(val, str) and not str(val).strip()):
        return pd.NaT
    try:
        dt = pd.to_datetime(val)
    except (ValueError, TypeError):
        return pd.NaT
    if dt is pd.NaT or pd.isna(dt):
        return pd.NaT
    year = int(dt.year)
    if year < _MIN_YEAR or year > _MAX_YEAR:
        return pd.NaT
    return dt


def _as_date(val) -> Optional[date]:
    """Normalize a datelike value to datetime.date."""
    if _is_missing(val):
        return None
    if isinstance(val, date) and not isinstance(val, datetime):
        return val
    if isinstance(val, pd.Timestamp):
        if pd.isna(val):
            return None
        return val.date()
    dt = _safe_to_datetime(val)
    if dt is pd.NaT or pd.isna(dt):
        return None
    return dt.date()


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())
    if not {"permit_info", "search_data"}.issubset(keys):
        return "unknown"
    inspections = data_dict.get("inspections")
    if isinstance(inspections, list) and len(inspections) > 0:
        return "permit_info_full"
    return "permit_info_basic"


# ── Status mapping ──────────────────────────────────────────────────────────

# permit_info.PermitStatus (uppercased) → STATUS_NORMALIZED
_STATUS_MAP = {
    "FINALED": "Final",
    "FINAL": "Final",
    "COMPLETE": "Final",
    "COMPLETED": "Final",
    "C OF O": "Final",
    "MDL COFO": "Final",
    "ISSUED": "Active",
    "APPROVED": "Active",
    "ACTIVE": "Active",
    "APPLIED": "In Review",
    "PENDING": "In Review",
    "FIRE APP": "In Review",
    "PLAN CHECK": "In Review",
    "PLNCHECK": "In Review",
    "PLAN CK": "In Review",
    "PLANCHK": "In Review",
    "PAYMENT REQ": "In Review",
    "PROJECTDOX": "In Review",
    "PAID": "In Review",
    "LNSC APP": "In Review",
    "NIC": "In Review",
    "CORRECTIONS READY": "In Review",
    # Administrative public-works notice; not a completed permit.
    "SEND NOTICE TO CIP": "In Review",
    "WITHDRAWN": "Inactive",
    "VOID": "Inactive",
    "EXPIRED": "Inactive",
    "REVOKE": "Inactive",
}

# Terminal inactive labels: PermitFinaledDate on these is a close/void
# timestamp, not evidence the permit should be treated as Final.
_INACTIVE_KEEP = {"EXPIRED", "VOID", "WITHDRAWN", "REVOKE"}

_FINAL_INSP_OK = {
    "",
    "PASS",
    "PASSED",
    "APPROVED",
    "AP",
    "PA",
    "COMPLETED",
    "COMPLETE",
}

_FINAL_TITLE_RE = re.compile(
    r"(?i)("
    r"permit\s*final|building\s*final|final\s*building|final\s*bldg|"
    r"^final$|^final\*\*|fire\s*final|oh\s*-\s*fire\s*final|"
    r"c\s*of\s*o|certificate\s*of\s*occupancy|cofo"
    r")"
)


def _permit_info(d: dict) -> dict:
    pi = d.get("permit_info")
    return pi if isinstance(pi, dict) else {}


def _normalize_status_key(raw) -> str:
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return ""
    return str(raw).strip().upper()


def _derive_status(pi: dict) -> Optional[str]:
    """Map PermitStatus; prefer Final when a non-inactive row is finaled."""
    raw = _normalize_status_key(pi.get("PermitStatus"))
    status = _STATUS_MAP.get(raw) if raw else None

    if raw in _INACTIVE_KEEP:
        return status or "Inactive"

    if _as_date(pi.get("PermitFinaledDate")) is not None:
        return "Final"

    if status is not None:
        return status

    if raw:
        if "FINAL" in raw or "COFO" in raw or raw in {"C OF O", "COMPLETE", "COMPLETED"}:
            return "Final"
        if "EXPIRE" in raw or "VOID" in raw or "CANCEL" in raw or "WITHDRAW" in raw:
            return "Inactive"
    return None


def _preferred_file_date(pi: dict) -> Optional[date]:
    return _as_date(pi.get("PermitAppliedDate"))


def _preferred_permit_date(pi: dict) -> Optional[date]:
    issued = _as_date(pi.get("PermitIssuedDate"))
    if issued is not None:
        return issued
    return _as_date(pi.get("PermitApprovedDate"))


def _final_from_inspections(d: dict) -> Optional[date]:
    """Latest completion date from a passed final / C of O inspection."""
    inspections = d.get("inspections")
    if not isinstance(inspections, list):
        return None
    dates = []
    for item in inspections:
        if not isinstance(item, dict):
            continue
        text = str(item.get("Type") or item.get("Title") or "")
        if not _FINAL_TITLE_RE.search(text.strip()):
            continue
        result = str(item.get("Result") or "").strip().upper()
        if result not in _FINAL_INSP_OK:
            continue
        completed = _as_date(item.get("Completed") or item.get("Scheduled Date"))
        if completed is not None:
            dates.append(completed)
    return max(dates) if dates else None


def _preferred_final_date(pi: dict, d: dict) -> Optional[date]:
    finaled = _as_date(pi.get("PermitFinaledDate"))
    if finaled is not None:
        return finaled
    return _final_from_inspections(d)


# ── Per-record repair logic ─────────────────────────────────────────────────

def _repair_record(row, d: dict, repairs: dict):
    """Populate *repairs* with corrected values for a single Corona record."""
    pi = _permit_info(d)

    # -- STATUS_NORMALIZED --
    current_status = row["STATUS_NORMALIZED"]
    expected = _derive_status(pi)
    if expected is not None:
        if pd.isna(current_status):
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"
        elif current_status != expected:
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FIXED"

    effective_status = repairs.get("STATUS_NORMALIZED", current_status)

    # -- FILE_DATE --
    preferred_fd = _preferred_file_date(pi)
    current_fd = _as_date(row["FILE_DATE"])
    if preferred_fd is not None:
        if current_fd is None:
            repairs["FILE_DATE"] = pd.Timestamp(preferred_fd)
            repairs["FILE_DATE_FLAG"] = "FILLED"
        elif current_fd != preferred_fd:
            repairs["FILE_DATE"] = pd.Timestamp(preferred_fd)
            repairs["FILE_DATE_FLAG"] = "FIXED"

    # -- PERMIT_DATE --
    preferred_pd = _preferred_permit_date(pi)
    current_pd = _as_date(row["PERMIT_DATE"])
    if preferred_pd is not None:
        if current_pd is None:
            if effective_status in ("Active", "Final"):
                repairs["PERMIT_DATE"] = pd.Timestamp(preferred_pd)
                repairs["PERMIT_DATE_FLAG"] = "FILLED"
        elif current_pd != preferred_pd:
            repairs["PERMIT_DATE"] = pd.Timestamp(preferred_pd)
            repairs["PERMIT_DATE_FLAG"] = "FIXED"

    # -- FINAL_DATE --
    preferred_final = _preferred_final_date(pi, d)
    current_final = _as_date(row["FINAL_DATE"])
    if effective_status != "Final":
        if current_final is not None:
            repairs["FINAL_DATE"] = pd.NaT
            repairs["FINAL_DATE_FLAG"] = "FIXED"
    elif preferred_final is not None:
        if current_final is None:
            repairs["FINAL_DATE"] = pd.Timestamp(preferred_final)
            repairs["FINAL_DATE_FLAG"] = "FILLED"
        elif current_final != preferred_final:
            repairs["FINAL_DATE"] = pd.Timestamp(preferred_final)
            repairs["FINAL_DATE_FLAG"] = "FIXED"


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Corona permit records using information from the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Corona".  Must contain
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
        if d is None:
            continue

        repairs: dict = {}
        _repair_record(row, d, repairs)

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
    filepath = os.path.join(MY_DATA_PATH, "processed_data", "permits_ca_sample.parquet")
    df = pd.read_parquet(filepath)
    city = df[(df["JURISDICTION"] == "Corona") & (df["STATE"] == "CA")].copy()

    print(f"Corona records: {len(city):,}\n")

    repaired = data_repair(city)

    if AGENT_DATA_PATH:
        out_path = os.path.join(AGENT_DATA_PATH, "corona_repaired_sample.parquet")
        repaired.to_parquet(out_path, index=False)
        print(f"Wrote {out_path}\n")

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

    print("\nSTATUS_NORMALIZED_FLAG breakdown:")
    print(repaired["STATUS_NORMALIZED_FLAG"].value_counts(dropna=False).to_string())

    print("\nPERMIT_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["PERMIT_DATE"].notna().sum()
        n = len(sub)
        pct = n_has / n if n else 0.0
        print(f"  {status:15s}: {n_has:>4,} / {n:>4,} ({pct:.1%})")

    print("\nFINAL_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FINAL_DATE"].notna().sum()
        n = len(sub)
        pct = n_has / n if n else 0.0
        print(f"  {status:15s}: {n_has:>4,} / {n:>4,} ({pct:.1%})")

    print("\nFILE_DATE coverage (after repair):")
    n_has = repaired["FILE_DATE"].notna().sum()
    print(f"  {n_has:>4,} / {len(repaired):>4,} ({n_has / len(repaired):.1%})")

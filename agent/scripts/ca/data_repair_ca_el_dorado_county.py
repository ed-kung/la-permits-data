"""Data repair for El Dorado County (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

El Dorado County DATA is a civic portal payload with a single top-level
key set: ``fees``, ``contacts``, ``site_info``, ``inspections``,
``permit_info``, ``search_data``. Canonical fields live under
``permit_info``:

  - PermitStatus                          → STATUS_NORMALIZED
  - PermitAppliedDate                     → FILE_DATE
  - PermitIssuedDate (fallback: Approved) → PERMIT_DATE
  - PermitFinaledDate                     → FINAL_DATE
      (fallback for Final rows: latest passed permit/building/TRPA-final
       inspection Completed date)

Content variants (same top-level keys; differ by optional PermitNotes):

  - permit_info:            standard permit_info fields (n≈1,303)
  - permit_info_with_notes: adds PermitNotes (n≈697)

Known issues repaired:
  - STATUS_NORMALIZED was derived from stale STATUS_ORIGINAL while
    PermitStatus is more current: 5 EXPIRED PERMIT rows labeled Active
    (STATUS_ORIGINAL=issued/approved) → FIXED to Inactive; 1 FINALED
    row labeled Active → FIXED to Final; 1 NONCOMPL labeled In Review
    (sibling NON COMPLIANT already Inactive) → FIXED to Inactive.
  - 12 Active/Final rows missing PERMIT_DATE with blank Issued but
    populated PermitApprovedDate → FILLED from Approved.
  - 1 FINALED row remapped to Final gets FINAL_DATE from
    PermitFinaledDate (also mirrored on a passed PERMIT FINAL**
    inspection) → FILLED.
  - 1 HOLD FINAL (Active) row carrying a spurious FINAL_DATE from
    PermitFinaledDate → cleared (FIXED).

Not repairable / left as-is:
  - FILE_DATE already matches PermitAppliedDate for all 2,000 sample
    rows; none missing.
  - Where PERMIT_DATE and PermitIssuedDate both exist they always match.
  - ~79 Final rows (mostly CLOSED / GREEN shells and a handful of
    FINALED with blank Finaled) have neither Issued nor Approved →
    PERMIT_DATE left missing.
  - ~103 Final rows (mostly CLOSED / GREEN and 7 FINALED with blank
    Finaled and empty inspections) have no PermitFinaledDate and no
    usable finaling inspection → FINAL_DATE left missing.
"""

import json
import math
import re
from datetime import date, datetime
from typing import Optional

import pandas as pd
import numpy as np


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
    """Parse a date value, returning pd.NaT on failure."""
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return pd.NaT
    if isinstance(val, str) and not str(val).strip():
        return pd.NaT
    try:
        return pd.to_datetime(val)
    except (ValueError, TypeError):
        return pd.NaT


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


def _permit_info(d: dict) -> dict:
    pi = d.get("permit_info")
    return pi if isinstance(pi, dict) else {}


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())
    if "permit_info" not in keys:
        return "unknown"
    pi = _permit_info(data_dict)
    if not pi:
        return "permit_info_empty"
    if "PermitNotes" in pi:
        return "permit_info_with_notes"
    return "permit_info"


# ── Status mapping ──────────────────────────────────────────────────────────

# permit_info.PermitStatus (uppercased) → STATUS_NORMALIZED
_STATUS_MAP = {
    # Final — completed / administratively closed outcomes
    "FINALED": "Final",
    "CLOSED": "Final",
    "GREEN": "Final",  # disaster-activity terminal tag in this portal
    # Active — issued / issued awaiting final
    "ISSUED": "Active",
    "HOLD FINAL": "Active",
    # Inactive — expired, voided, withdrawn, non-compliant
    "EXPIRED": "Inactive",
    "EXPIRED APPLICATION": "Inactive",
    "EXPIRED PERMIT": "Inactive",
    "VOID": "Inactive",
    "WITHDRAWN": "Inactive",
    "PCEXPIRE": "Inactive",
    "NON COMPLIANT": "Inactive",
    "NONCOMPL": "Inactive",
    # In Review — pre-issuance / payment / reactivation / revision
    "ACCEPTED": "In Review",
    "ACKNOWLEDGE": "In Review",
    "APPROVED FOR PAYMENT": "In Review",
    "LIST": "In Review",
    "OPEN": "In Review",
    "REACTIVATE": "In Review",
    "REACTVAT": "In Review",
    "REVISION": "In Review",
    "SUBMITTED": "In Review",
    "SUBMITTED ONLINE": "In Review",
    "UNPAID": "In Review",
}


_FINAL_INSP_OK = {
    "",
    "PASS",
    "PASSED",
    "APPROVED",
    "AP",
}

_FINAL_TITLE_RE = re.compile(
    r"(?i)(permit\s*final|building\s*final|final\s*building|final\s*bldg|trpa\s*final)"
)


def _derive_status(pi: dict) -> Optional[str]:
    """Map PermitStatus; infer from dates when status is blank."""
    raw = (pi.get("PermitStatus") or "").strip().upper()
    if raw in _STATUS_MAP:
        return _STATUS_MAP[raw]

    if raw:
        if "FINAL" in raw:
            return "Final"
        if "EXPIRE" in raw or "VOID" in raw or "WITHDRAW" in raw or "CANCEL" in raw:
            return "Inactive"
        if "ISSUE" in raw or "APPROV" in raw:
            return "Active"
        return None

    if _as_date(pi.get("PermitFinaledDate")) is not None:
        return "Final"
    if _as_date(pi.get("PermitIssuedDate")) is not None:
        return "Active"
    if _as_date(pi.get("PermitApprovedDate")) is not None:
        return "Active"
    if _as_date(pi.get("PermitAppliedDate")) is not None:
        return "In Review"
    return None


def _preferred_file_date(pi: dict) -> Optional[date]:
    return _as_date(pi.get("PermitAppliedDate"))


def _preferred_permit_date(pi: dict) -> Optional[date]:
    issued = _as_date(pi.get("PermitIssuedDate"))
    if issued is not None:
        return issued
    return _as_date(pi.get("PermitApprovedDate"))


def _final_from_inspections(d: dict) -> Optional[date]:
    """Latest completion date from a passed permit/building/TRPA-final insp."""
    inspections = d.get("inspections")
    if not isinstance(inspections, list):
        return None
    dates = []
    for item in inspections:
        if not isinstance(item, dict):
            continue
        text = " ".join(str(item.get(k) or "") for k in ("Type", "Title"))
        if not _FINAL_TITLE_RE.search(text):
            continue
        result = str(item.get("Result") or "").strip().upper()
        if result and result not in _FINAL_INSP_OK:
            continue
        completed = _as_date(item.get("Completed") or item.get("Status Date"))
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
    """Populate *repairs* with corrected values for a single record."""
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
        # HOLD FINAL / EXPIRED may carry PermitFinaledDate; that is not a
        # completion finaling for STATUS_NORMALIZED purposes.
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
    El Dorado County permit records using information from the raw DATA
    JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "El Dorado County".  Must
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
    city = df[
        (df["JURISDICTION"] == "El Dorado County") & (df["STATE"] == "CA")
    ].copy()

    print(f"El Dorado County records: {len(city):,}\n")

    repaired = data_repair(city)

    if AGENT_DATA_PATH:
        out_path = os.path.join(
            AGENT_DATA_PATH, "el_dorado_county_repaired_sample.parquet"
        )
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

"""Data repair for Williams (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Williams DATA is a flat civic portal scrape. All rows share core
top-level keys (``Status``, ``Permit Date``, ``Permit Number``,
``fees``, ``payments``, ``contractors``, ``inspections``,
``property_info``, …). Optional keys define the INFERRED_SCHEMA
variants:

  - portal_reviews:               has ``reviews`` (no plan_reviews)
  - portal_plan_reviews:          has ``plan_reviews`` (no record_type)
  - portal_plan_reviews_rtype:    has ``plan_reviews`` +
                                  ``record_type_from_contractor_box``

Canonical mappings:
  - DATA.Status              → STATUS_NORMALIZED
  - DATA['Permit Date']      → FILE_DATE  (application / submittal)
  - (no Issued Date field)   → PERMIT_DATE cannot be filled from DATA
  - Passed final inspection
    completed_date (type or notes
    contain "final")         → FINAL_DATE when status is Final

Known issues repaired:
  - Open rows with a passed final inspection left In Review (portal
    status lag) → FIXED to Final; FINAL_DATE filled from that
    inspection.
  - Final / Closed rows with empty FINAL_DATE but a passed final
    inspection (type name or notes) → FILLED.

Not repairable / left as-is:
  - FILE_DATE already matches Permit Date for every sample row.
  - No Issued Date / Issue Date / Finalized Date field exists;
    Active/Final PERMIT_DATE stays empty. Payment dates are fee
    receipts, not issuance stamps.
  - 71 blank Status rows stay STATUS_NORMALIZED null (no inspections
    to infer from).
  - Most Final/Closed rows lack dated final inspections → FINAL_DATE
    stays missing (~534 of ~659 Final after repair).
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
    """Parse a date value, returning pd.NaT on failure or implausible year.

    Inspection ``scheduled_date`` values look like ``09/22/2021  @ 10:30am``;
    strip the time suffix before parsing.
    """
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return pd.NaT
    if isinstance(val, str) and not str(val).strip():
        return pd.NaT
    if isinstance(val, str):
        val = str(val).split("@")[0].strip()
    try:
        dt = pd.to_datetime(val, errors="coerce")
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
    """Compare two datelike values at calendar-day resolution."""
    da = _safe_to_datetime(a)
    db = _safe_to_datetime(b)
    if da is pd.NaT or db is pd.NaT:
        return False
    return da.normalize() == db.normalize()


_CORE_KEYS = {
    "Status",
    "Permit Date",
    "Permit Number",
    "inspections",
}


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())
    if not _CORE_KEYS <= keys:
        return "unknown"
    if "plan_reviews" in keys and "record_type_from_contractor_box" in keys:
        return "portal_plan_reviews_rtype"
    if "plan_reviews" in keys:
        return "portal_plan_reviews"
    if "reviews" in keys:
        return "portal_reviews"
    return "portal_core"


# ── Status mapping ──────────────────────────────────────────────────────────

_STATUS_MAP = {
    # Final
    "Final": "Final",
    "Closed": "Final",
    # In Review — application / open / quote / pending
    "Open": "In Review",
    "Pending": "In Review",
    "Quote": "In Review",
    # Inactive
    "Expired": "Inactive",
}


def _raw_status(d: dict) -> Optional[str]:
    raw = d.get("Status")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return None


def _notes_text(insp: dict) -> str:
    notes = insp.get("notes")
    if isinstance(notes, list):
        return " ".join(str(n) for n in notes)
    if notes is None:
        return ""
    return str(notes)


def _is_passed_inspection(insp: dict) -> bool:
    status = str(insp.get("status") or "").strip().lower()
    return status.startswith("passed")


def _is_final_inspection(insp: dict) -> bool:
    """True when inspection type or notes indicate a final/sign-off."""
    itype = str(insp.get("inspection_type") or "")
    notes = _notes_text(insp)
    return bool(
        re.search(r"final", itype, re.IGNORECASE)
        or re.search(r"final", notes, re.IGNORECASE)
    )


def _final_inspection_date(d: dict):
    """Latest passed final-inspection completed_date (else scheduled_date).

    Williams often records solar/stucco finals under ``B - Other`` /
    ``B - Electrical`` with "Final" only in the notes field.
    """
    inspections = d.get("inspections")
    if not isinstance(inspections, list):
        return pd.NaT
    best = pd.NaT
    for insp in inspections:
        if not isinstance(insp, dict):
            continue
        if not _is_passed_inspection(insp) or not _is_final_inspection(insp):
            continue
        dt = _safe_to_datetime(insp.get("completed_date"))
        if dt is pd.NaT:
            dt = _safe_to_datetime(insp.get("scheduled_date"))
        if dt is pd.NaT:
            continue
        if best is pd.NaT or dt > best:
            best = dt
    return best


def _expected_status(d: dict) -> Optional[str]:
    """Map portal Status; promote In Review → Final on passed final insp."""
    raw = _raw_status(d)
    mapped = _STATUS_MAP.get(raw) if raw is not None else None
    final_insp = _final_inspection_date(d)
    if mapped == "In Review" and final_insp is not pd.NaT:
        return "Final"
    return mapped


def _file_date_from_data(d: dict):
    return _safe_to_datetime(d.get("Permit Date"))


# ── Repair logic ────────────────────────────────────────────────────────────

def _repair_record(row, d: dict, repairs: dict):
    current_status = row["STATUS_NORMALIZED"]
    expected = _expected_status(d)
    final_insp = _final_inspection_date(d)

    # -- STATUS_NORMALIZED --
    if expected is not None:
        if pd.isna(current_status):
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"
        elif current_status != expected:
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FIXED"

    effective_status = repairs.get("STATUS_NORMALIZED", current_status)

    # -- FILE_DATE (application / Permit Date) --
    file_date = _file_date_from_data(d)
    if file_date is not pd.NaT:
        if pd.isna(row["FILE_DATE"]):
            repairs["FILE_DATE"] = file_date
            repairs["FILE_DATE_FLAG"] = "FILLED"
        elif not _dates_equal(row["FILE_DATE"], file_date):
            repairs["FILE_DATE"] = file_date
            repairs["FILE_DATE_FLAG"] = "FIXED"

    # -- PERMIT_DATE --
    # Williams has no Issued Date. Leave missing; do not copy Permit Date
    # (application) or payment dates (fee receipts).
    # No incorrect non-null PERMIT_DATE values exist in the sample.

    # -- FINAL_DATE --
    current_final = row["FINAL_DATE"]
    if effective_status == "Final":
        if final_insp is not pd.NaT:
            if pd.isna(current_final):
                repairs["FINAL_DATE"] = final_insp
                repairs["FINAL_DATE_FLAG"] = "FILLED"
            elif not _dates_equal(current_final, final_insp):
                repairs["FINAL_DATE"] = final_insp
                repairs["FINAL_DATE_FLAG"] = "FIXED"
    elif not pd.isna(current_final):
        repairs["FINAL_DATE"] = pd.NaT
        repairs["FINAL_DATE_FLAG"] = "FIXED"


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Williams (CA) permit records using information from the raw DATA JSON.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Williams". Must contain
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
        _repair_record(row, d, repairs)

        for key, value in repairs.items():
            out.at[idx, key] = value

    return out


# ── CLI: run standalone to preview repair stats ─────────────────────────────

if __name__ == "__main__":
    import os
    from pathlib import Path

    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[3] / ".env")
    MY_DATA_PATH = os.getenv("MY_DATA_PATH")
    AGENT_DATA_PATH = os.getenv("AGENT_DATA_PATH")
    filepath = os.path.join(MY_DATA_PATH, "processed_data", "permits_ca_sample.parquet")
    df = pd.read_parquet(filepath)
    city = df[(df["JURISDICTION"] == "Williams") & (df["STATE"] == "CA")].copy()

    print(f"Williams records: {len(city):,}\n")

    repaired = data_repair(city)

    print("INFERRED_SCHEMA:")
    for s, c in repaired["INFERRED_SCHEMA"].value_counts(dropna=False).items():
        print(f"  {str(s):45s}: {c:>4,}")
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

    print("\nStatus transitions (where flag set):")
    changed = repaired[repaired["STATUS_NORMALIZED_FLAG"].notna()]
    if len(changed):
        for (a, b), n in (
            pd.DataFrame({
                "before": city.loc[changed.index, "STATUS_NORMALIZED"].fillna("null"),
                "after": changed["STATUS_NORMALIZED"].fillna("null"),
            })
            .value_counts()
            .items()
        ):
            print(f"  {a!s:15s} → {b!s:15s}: {n}")
    else:
        print("  (none)")

    print("\nPERMIT_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["PERMIT_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} "
              f"({n_has / len(sub) if len(sub) else 0:.1%})")

    print("\nFINAL_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FINAL_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} "
              f"({n_has / len(sub) if len(sub) else 0:.1%})")

    print("\nFILE_DATE coverage after repair: "
          f"{repaired['FILE_DATE'].notna().sum()} / {len(repaired)}")

    # Chronology checks among filled finals
    finals = repaired[repaired["STATUS_NORMALIZED"] == "Final"]
    both = finals[finals["FILE_DATE"].notna() & finals["FINAL_DATE"].notna()].copy()
    if len(both):
        inv = (
            both["FINAL_DATE"].map(_safe_to_datetime).dt.normalize()
            < both["FILE_DATE"].map(_safe_to_datetime).dt.normalize()
        ).sum()
        print(f"\nFinal rows with FINAL_DATE < FILE_DATE: {inv}")

    if AGENT_DATA_PATH:
        out_dir = Path(AGENT_DATA_PATH) / "repaired"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "permits_ca_williams_repaired.parquet"
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote repaired sample → {out_path}")

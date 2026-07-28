"""Data repair for Davis (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Davis DATA is a city permit-portal scrape (same family as Bakersfield).
Content variants recorded in INFERRED_SCHEMA:

  - portal_detail:  nonempty ``permit_status_detail`` (Issue / Permit Date)
  - portal_status:  ``permit_status`` / ``insp_status`` present, no detail
  - detail_only:    ``detail`` (+ fees) only
  - unknown / missing

Canonical mappings:
  - Status for Permit Number (fallback: Application Status) → STATUS_NORMALIZED
  - detail['Application Date']                              → FILE_DATE
  - permit_status_detail['Issue Date']
      (fallback: 'Permit Date' only when issued)            → PERMIT_DATE
  - Latest APPROVED inspection on/after FILE_DATE; else
    Permit Date when Status for Permit Number is CLOSED     → FINAL_DATE

Known issues repaired:
  - STATUS_NORMALIZED missing on ~99% of rows (STATUS_ORIGINAL null / {})
    → FILLED from Application Status / Status for Permit Number.
  - PERMIT_DATE on Final/Closed rows taken from Permit Date, which is
    overwritten to the finalization date → FIXED to Issue Date.
  - Spurious PERMIT_DATE on In Review (TO BE ISSUED / APPROVED) → cleared.
  - Missing FINAL_DATE on Final rows with CLOSED Permit Date or APPROVED
    inspections → FILLED.

Not repairable from DATA:
  - FILE_DATE already matches Application Date for every sample row.
  - Vast majority of Active/Final rows lack permit_status_detail →
    PERMIT_DATE stays missing (~1.9k rows).
  - Almost all Final rows (PERMIT COMPLETED / CERTIFICATE ISSUED) lack
    dated inspections and CLOSED permit detail → FINAL_DATE stays
    missing (~1.7k rows).
"""

from __future__ import annotations

import json
import math
from typing import Optional

import numpy as np
import pandas as pd


# Davis FILE_DATE goes back to 1996 in the sample.
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
    """Parse a date value, returning pd.NaT on failure or implausible year."""
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return pd.NaT
    if isinstance(val, str) and not str(val).strip():
        return pd.NaT
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
    da = _safe_to_datetime(a)
    db = _safe_to_datetime(b)
    if da is pd.NaT or db is pd.NaT:
        return False
    return da.normalize() == db.normalize()


def _detail(d: dict) -> dict:
    det = d.get("detail")
    return det if isinstance(det, dict) else {}


def _psd(d: dict) -> dict:
    psd = d.get("permit_status_detail")
    return psd if isinstance(psd, dict) else {}


def _insp_rows(d: dict) -> list:
    insp = d.get("insp_status_detail")
    return insp if isinstance(insp, list) else []


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())
    if "detail" not in keys:
        return "unknown"

    psd = data_dict.get("permit_status_detail")
    if isinstance(psd, dict) and psd:
        return "portal_detail"

    if "permit_status" in keys or "insp_status" in keys:
        return "portal_status"
    if "permit_status_detail" in keys or "insp_status_detail" in keys:
        return "portal_status"
    return "detail_only"


# ── Status mapping ───────────────────────────────────────────────────────────

# Status for Permit Number (case-insensitive) → STATUS_NORMALIZED
_PERMIT_STATUS_MAP = {
    "closed": "Final",
    "permit printed": "Active",
    "to be issued": "In Review",
}

# Application Status when no permit-status block, or as terminal override.
_APP_STATUS_MAP = {
    "permit completed": "Final",
    "certificate issued": "Final",
    "closed": "Final",
    "permit has been issued": "Active",
    "in plan check": "In Review",
    "approved": "In Review",
    "withdrawn by applicant": "Inactive",
    "expired addt'l fees due": "Inactive",
    "expired new permit needed": "Inactive",
    "expired sent to ce": "Inactive",
    "rescinded": "Inactive",
    "rejected": "Inactive",
}

_INACTIVE_APP = {
    "withdrawn by applicant",
    "expired addt'l fees due",
    "expired new permit needed",
    "expired sent to ce",
    "rescinded",
    "rejected",
}


def _expected_status(d: dict) -> Optional[str]:
    detail = _detail(d)
    psd = _psd(d)
    app = str(detail.get("Application Status") or "").strip().lower()
    ps = str(psd.get("Status for Permit Number") or "").strip().lower()

    # Application-level terminal states override a lagging permit status.
    if app in _INACTIVE_APP:
        return "Inactive"

    if ps:
        mapped = _PERMIT_STATUS_MAP.get(ps)
        if mapped is not None:
            return mapped

    if app:
        return _APP_STATUS_MAP.get(app)

    return None


def _issue_date(d: dict):
    return _safe_to_datetime(_psd(d).get("Issue Date"))


def _permit_date_field(d: dict):
    return _safe_to_datetime(_psd(d).get("Permit Date"))


def _application_date(d: dict):
    detail = _detail(d)
    dt = _safe_to_datetime(detail.get("Application Date"))
    if dt is not pd.NaT:
        return dt
    return _safe_to_datetime(_psd(d).get("Application Date"))


def _extract_final_date(d: dict, file_date):
    """Best available final / close date.

    Prefer latest APPROVED inspection completion date on/after FILE_DATE.
    Fall back to Permit Date when Status for Permit Number is CLOSED
    (that field is overwritten to the finalization date on closed rows).
    """
    file_dt = _safe_to_datetime(file_date)
    approved = []

    for ir in _insp_rows(d):
        if not isinstance(ir, (list, tuple)) or len(ir) < 3:
            continue
        status = str(ir[2] or "").strip().upper()
        if status != "APPROVED":
            continue
        # Prefer completion/result date (col 3); else scheduled date (col 1).
        dt = _safe_to_datetime(ir[3] if len(ir) > 3 else None)
        if dt is pd.NaT:
            dt = _safe_to_datetime(ir[1])
        if dt is pd.NaT:
            continue
        if file_dt is not pd.NaT and dt.normalize() < file_dt.normalize():
            continue
        approved.append(dt)

    if approved:
        return max(approved)

    ps = str(_psd(d).get("Status for Permit Number") or "").strip().lower()
    if ps == "closed":
        closed = _permit_date_field(d)
        if closed is not pd.NaT:
            if file_dt is pd.NaT or closed.normalize() >= file_dt.normalize():
                return closed

    return pd.NaT


# ── Per-record repair logic ─────────────────────────────────────────────────

def _repair_record(row, d: dict, repairs: dict):
    current_status = row["STATUS_NORMALIZED"]
    expected = _expected_status(d)

    # -- STATUS_NORMALIZED --
    if expected is not None:
        if pd.isna(current_status):
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"
        elif current_status != expected:
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FIXED"

    effective_status = repairs.get("STATUS_NORMALIZED", current_status)

    # -- FILE_DATE --
    app_date = _application_date(d)
    if app_date is not pd.NaT:
        if pd.isna(row["FILE_DATE"]):
            repairs["FILE_DATE"] = app_date
            repairs["FILE_DATE_FLAG"] = "FILLED"
        elif not _dates_equal(row["FILE_DATE"], app_date):
            repairs["FILE_DATE"] = app_date
            repairs["FILE_DATE_FLAG"] = "FIXED"

    effective_file = repairs.get("FILE_DATE", row["FILE_DATE"])

    # -- PERMIT_DATE --
    # Prefer Issue Date (true issuance). Permit Date on CLOSED rows is
    # often the finalization date, not issuance.
    issue = _issue_date(d)
    permit_field = _permit_date_field(d)
    ps = str(_psd(d).get("Status for Permit Number") or "").strip().lower()

    if effective_status in ("Active", "Final"):
        if issue is not pd.NaT:
            expected_permit = issue
        elif ps and ps != "to be issued":
            expected_permit = permit_field
        else:
            expected_permit = pd.NaT
    elif effective_status == "Inactive" and issue is not pd.NaT:
        expected_permit = issue
    else:
        # In Review / never-issued Inactive — no issuance.
        expected_permit = pd.NaT

    current_permit = row["PERMIT_DATE"]
    if expected_permit is not pd.NaT:
        if pd.isna(current_permit):
            repairs["PERMIT_DATE"] = expected_permit
            repairs["PERMIT_DATE_FLAG"] = "FILLED"
        elif not _dates_equal(current_permit, expected_permit):
            repairs["PERMIT_DATE"] = expected_permit
            repairs["PERMIT_DATE_FLAG"] = "FIXED"
    else:
        if not pd.isna(current_permit):
            repairs["PERMIT_DATE"] = pd.NaT
            repairs["PERMIT_DATE_FLAG"] = "FIXED"

    # -- FINAL_DATE --
    final_src = _extract_final_date(d, effective_file)
    current_final = row["FINAL_DATE"]

    if effective_status == "Final":
        if final_src is not pd.NaT:
            if pd.isna(current_final):
                repairs["FINAL_DATE"] = final_src
                repairs["FINAL_DATE_FLAG"] = "FILLED"
            elif not _dates_equal(current_final, final_src):
                repairs["FINAL_DATE"] = final_src
                repairs["FINAL_DATE_FLAG"] = "FIXED"
    elif not pd.isna(current_final):
        repairs["FINAL_DATE"] = pd.NaT
        repairs["FINAL_DATE_FLAG"] = "FIXED"


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Davis permit records using information from the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Davis".  Must contain
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
    from pathlib import Path
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[3] / ".env")
    MY_DATA_PATH = os.getenv("MY_DATA_PATH")
    AGENT_DATA_PATH = os.getenv("AGENT_DATA_PATH")
    filepath = os.path.join(MY_DATA_PATH, "processed_data", "permits_ca_sample.parquet")
    df = pd.read_parquet(filepath)
    city = df[(df["JURISDICTION"] == "Davis") & (df["STATE"] == "CA")].copy()

    print(f"Davis records: {len(city):,}\n")

    repaired = data_repair(city)

    print("INFERRED_SCHEMA:")
    for s, c in repaired["INFERRED_SCHEMA"].value_counts(dropna=False).items():
        print(f"  {s}: {c:,}")
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

    print("\nFILE_DATE by STATUS_NORMALIZED (after repair):")
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

    # Spot-check the 10 portal_detail rows
    print("\nportal_detail spot-check (Issue / Permit / repaired):")
    detail_rows = repaired[repaired["INFERRED_SCHEMA"] == "portal_detail"]
    for idx, row in detail_rows.iterrows():
        d = _safe_parse(row["DATA"])
        psd = _psd(d)
        print(
            f"  status={row['STATUS_NORMALIZED']:10s} "
            f"Issue={psd.get('Issue Date')!r:12s} PermitFld={psd.get('Permit Date')!r:12s} "
            f"→ PERMIT={row['PERMIT_DATE']} FINAL={row['FINAL_DATE']} "
            f"flags P={row['PERMIT_DATE_FLAG']} F={row['FINAL_DATE_FLAG']}"
        )

    if AGENT_DATA_PATH:
        out_path = os.path.join(AGENT_DATA_PATH, "davis_repaired_sample.parquet")
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote {out_path}")

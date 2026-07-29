"""Data repair for Camarillo (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Camarillo DATA is a city permit-portal scrape (same family as Bakersfield /
Oxnard / Davis). Two sub-schemas:

  - permit_status: detail + fees + permit_status / insp_status blocks
                   (incl. permit_status_detail, insp_status_detail)
  - detail_only:   detail + fees only (no permit / inspection blocks)

Canonical mappings:
  - Status for Permit Number (fallback: Application Status)
      with EXPIRED/CANCELED Application Status override → STATUS_NORMALIZED
  - detail['Application Date']                       → FILE_DATE
  - permit_status_detail['Issue Date']
      (fallback: 'Permit Date')                      → PERMIT_DATE
  - Latest APPROVED FINAL* inspection on/after
    FILE_DATE; else latest APPROVED inspection       → FINAL_DATE

Known issues repaired:
  - 9 detail_only rows with null STATUS_ORIGINAL / STATUS_NORMALIZED
    → FILLED from Application Status (APPROVED / IN PLAN CHECK / ON HOLD
    → In Review).
  - Application Status EXPIRED / CANCELED still labeled Active / In Review
    / Final from a lagging Status for Permit Number → FIXED to Inactive.
  - 15 rows where Status for Permit Number is FINAL INSPECTION COMPLETE
    but STATUS_ORIGINAL lagged at "permit printed" → FIXED to Final.
  - 1 In Review row whose permit block says PERMIT PRINTED → FIXED to
    Active.
  - PERMIT_DATE often taken from Permit Date, which on finaled rows is
    frequently overwritten to the finalization date (~1,142 rows where
    Permit Date == FINAL_DATE). Prefer Issue Date → FIXED.
  - Spurious PERMIT_DATE on In Review (plan check / to be issued) with
    blank Issue Date → cleared (FIXED).
  - Missing FINAL_DATE on rows promoted to Final with dated APPROVED
    inspections → FILLED.
  - Spurious FINAL_DATE on the one Final→Inactive EXPIRED row → cleared.

Not repairable / left as-is:
  - FILE_DATE already matches Application Date for all sample rows.
  - detail_only rows have no Issue Date or inspections → PERMIT_DATE /
    FINAL_DATE stay missing after status fill (all become In Review).
  - PERMIT FINALED Application Status with PERMIT PRINTED permit-number
    status and no FINAL INSPECTION COMPLETE / no FINAL_DATE left as
    Active (Status for Permit Number is canonical; Application Status
    alone is not treated as evidence of finaling).
"""

import json
import math
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
        return json.loads(data)
    return data


def _safe_to_datetime(val):
    """Parse a date value, returning pd.NaT on failure or implausible year."""
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return pd.NaT
    if isinstance(val, str) and not val.strip():
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
    """Compare two datelike values at calendar-day resolution."""
    da = _safe_to_datetime(a)
    db = _safe_to_datetime(b)
    if da is pd.NaT or db is pd.NaT:
        return False
    return da.normalize() == db.normalize()


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())
    if "permit_status_detail" in keys or "insp_status_detail" in keys:
        return "permit_status"
    if "detail" in keys:
        return "detail_only"
    return "unknown"


def _detail(d: dict) -> dict:
    det = d.get("detail")
    return det if isinstance(det, dict) else {}


def _psd(d: dict) -> dict:
    psd = d.get("permit_status_detail")
    return psd if isinstance(psd, dict) else {}


def _insp_rows(d: dict) -> list:
    insp = d.get("insp_status_detail")
    return insp if isinstance(insp, list) else []


# ── Status mapping ───────────────────────────────────────────────────────────

# Status for Permit Number (case-insensitive) → STATUS_NORMALIZED
_PERMIT_STATUS_MAP = {
    "final inspection complete": "Final",
    "c.o. issued": "Final",
    "temporary c.o. issued": "Final",
    "permit printed": "Active",
    "plan check": "In Review",
    "to be issued": "In Review",
    "permit revoked": "Inactive",
}

# Application Status when no permit-status block (detail_only), or as
# terminal override for EXPIRED / CANCELED.
_APP_STATUS_MAP = {
    "permit finaled": "Final",
    "permit issued": "Active",
    # Approved without a permit block: no evidence of issuance.
    "approved": "In Review",
    "in plan check": "In Review",
    "on hold": "In Review",
    "expired": "Inactive",
    "canceled": "Inactive",
}


def _expected_status(d: dict) -> Optional[str]:
    detail = _detail(d)
    psd = _psd(d)
    app = str(detail.get("Application Status") or "").strip().lower()
    ps = str(psd.get("Status for Permit Number") or "").strip().lower()

    # Application-level terminal states override a lagging permit status.
    if app in ("expired", "canceled"):
        return "Inactive"

    if ps:
        return _PERMIT_STATUS_MAP.get(ps)

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


def _is_final_insp_name(name: str) -> bool:
    n = name.upper().strip()
    if "FINAL" in n:
        return True
    if "CERTIFICATE" in n or n in ("C.O.", "C.O", "CO"):
        return True
    return False


def _extract_final_date(d: dict, file_date):
    """Latest APPROVED final-named inspection on/after FILE_DATE; else
    latest any APPROVED inspection on/after FILE_DATE."""
    file_dt = _safe_to_datetime(file_date)
    final_named = []
    any_approved = []

    for ir in _insp_rows(d):
        if not isinstance(ir, (list, tuple)) or len(ir) < 3:
            continue
        name = str(ir[0] or "")
        status = str(ir[2] or "").strip().upper()
        if status != "APPROVED":
            continue
        dt = _safe_to_datetime(ir[3] if len(ir) > 3 else ir[1])
        if dt is pd.NaT:
            continue
        if file_dt is not pd.NaT and dt.normalize() < file_dt.normalize():
            continue
        any_approved.append(dt)
        if _is_final_insp_name(name):
            final_named.append(dt)

    if final_named:
        return max(final_named)
    if any_approved:
        return max(any_approved)
    return pd.NaT


# ── Per-record repair logic ─────────────────────────────────────────────────

def _repair_record(row, d: dict, repairs: dict):
    """Populate *repairs* with corrected values for a single Camarillo record."""
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
    # Prefer Issue Date (true first issuance). Permit Date is often
    # overwritten to the finalization date on finaled rows.
    issue = _issue_date(d)
    permit_field = _permit_date_field(d)
    ps = str(_psd(d).get("Status for Permit Number") or "").strip().lower()

    if effective_status in ("Active", "Final"):
        expected_permit = issue if issue is not pd.NaT else permit_field
    elif effective_status == "Inactive" and ps == "permit revoked":
        # Issued, then revoked — keep issuance date.
        expected_permit = issue if issue is not pd.NaT else permit_field
    elif effective_status == "Inactive" and issue is not pd.NaT:
        # Application expired/canceled after an Issue Date existed.
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
    file_dt = _safe_to_datetime(effective_file)
    any_dates = []
    for ir in _insp_rows(d):
        if not isinstance(ir, (list, tuple)) or len(ir) < 3:
            continue
        if str(ir[2] or "").strip().upper() != "APPROVED":
            continue
        dt = _safe_to_datetime(ir[3] if len(ir) > 3 else ir[1])
        if dt is pd.NaT:
            continue
        if file_dt is not pd.NaT and dt.normalize() < file_dt.normalize():
            continue
        any_dates.append(dt)
    latest_any = max(any_dates) if any_dates else pd.NaT
    current_final = row["FINAL_DATE"]

    if effective_status == "Final":
        if pd.isna(current_final):
            if final_src is not pd.NaT:
                repairs["FINAL_DATE"] = final_src
                repairs["FINAL_DATE_FLAG"] = "FILLED"
        elif final_src is not pd.NaT and not _dates_equal(current_final, final_src):
            if latest_any is pd.NaT or not _dates_equal(current_final, latest_any):
                repairs["FINAL_DATE"] = final_src
                repairs["FINAL_DATE_FLAG"] = "FIXED"
    else:
        if not pd.isna(current_final):
            repairs["FINAL_DATE"] = pd.NaT
            repairs["FINAL_DATE_FLAG"] = "FIXED"


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Camarillo permit records using information from the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Camarillo".  Must contain
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
    city = df[(df["JURISDICTION"] == "Camarillo") & (df["STATE"] == "CA")].copy()

    print(f"Camarillo records: {len(city):,}\n")

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

    print("\nPost-repair completeness by status:")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n = len(sub)
        if n == 0:
            continue
        file_n = sub["FILE_DATE"].notna().sum()
        permit_n = sub["PERMIT_DATE"].notna().sum()
        final_n = sub["FINAL_DATE"].notna().sum()
        print(
            f"  {status:15s} n={n:>4,}  "
            f"FILE={file_n/n:.1%}  PERMIT={permit_n/n:.1%}  FINAL={final_n/n:.1%}"
        )

    if AGENT_DATA_PATH:
        out_path = os.path.join(AGENT_DATA_PATH, "camarillo_repaired_sample.parquet")
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote {out_path}")

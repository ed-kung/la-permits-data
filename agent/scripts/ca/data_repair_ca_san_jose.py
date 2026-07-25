"""Data repair for San Jose (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

San Jose DATA is a City of San Jose permit-portal scrape wrapped as
``{number, old, new}``. Two usable sub-schemas appear in the sample:

  - new_details: ``new`` contains ``details`` / ``process`` /
    ``process_dates`` (rich detail page scrape)
  - old_only:    ``new`` is empty; dates/status come from ``old``
                 (listing + processing_status workflow)

Canonical mappings:
  - new.details.Status (else old.status)     → STATUS_NORMALIZED
  - new.details['Folder Date'] (else old.file_date)
                                             → FILE_DATE
  - details['Issue Date'] and/or Issuance Review
      (later of the two when both present)   → PERMIT_DATE
  - details['Final Date'] (else latest closed
      *Final* / Certificate of Occupancy /
      Closed Out process step)               → FINAL_DATE

Known issues repaired:
  - ``Estimate`` was mapped to Final; these are valuation/estimate
    folders without issuance → FIXED to In Review.
  - PERMIT_DATE often used Issuance Review when Issue Date is a few days
    later (true issue stamp) → FIXED to later(Issue Date, Issuance Review).
  - Missing PERMIT_DATE on Active/Final rows with Issue Date or closed
    Issuance Review → FILLED.
  - Missing FINAL_DATE on Final rows with details.Final Date or closed
    Final inspection steps → FILLED.
  - FINAL_DATE matching an earlier Building Final when details.Final Date
    is later → FIXED.
  - Spurious FINAL_DATE on non-Final (esp. Expired) rows → cleared (FIXED).

Not repairable / left as-is:
  - 5 FILE_DATE gaps with blank Folder Date / old.file_date.
  - Active/Final rows with neither Issue Date nor Issuance Review
    (common for Closed/Completed/Approved planning-style and lean stubs)
    → PERMIT_DATE stays missing.
  - Final rows with no Final Date and no closed Final process step
    → FINAL_DATE stays missing.
"""

import json
import math
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
    if val is None or (isinstance(val, str) and not str(val).strip()):
        return pd.NaT
    if str(val).strip().upper() in {"TBD", "N/A", "NA", "NONE", "NULL"}:
        return pd.NaT
    try:
        return pd.to_datetime(val)
    except (ValueError, TypeError):
        return pd.NaT


def _dates_equal(a, b) -> bool:
    """Compare two datelike values at calendar-day resolution."""
    da = _safe_to_datetime(a)
    db = _safe_to_datetime(b)
    if da is pd.NaT or db is pd.NaT:
        return False
    return da.normalize() == db.normalize()


def _later(*vals):
    """Return the latest non-NaT datetime among vals, else NaT."""
    dates = [_safe_to_datetime(v) for v in vals]
    dates = [d for d in dates if d is not pd.NaT]
    return max(dates) if dates else pd.NaT


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    if not isinstance(data_dict, dict):
        return "unknown"
    keys = set(data_dict.keys())
    if not ({"new", "old", "number"} & keys):
        return "unknown"
    new = data_dict.get("new")
    if isinstance(new, dict) and "details" in new:
        return "new_details"
    if isinstance(data_dict.get("old"), dict):
        return "old_only"
    return "unknown"


# ── Status mapping ──────────────────────────────────────────────────────────

_STATUS_MAP = {
    # Final
    "Finaled": "Final",
    "Closed": "Final",
    "Closed Out": "Final",
    "Complete": "Final",
    "Completed": "Final",
    "Approved/Certified": "Final",
    "Recorded": "Final",
    "Legacy": "Final",
    # Active
    "Under Inspection": "Active",
    "Approved": "Active",
    "Issued": "Active",
    "Permit(s) Issued": "Active",
    "Active": "Active",
    "Upgraded": "Active",
    # Inactive
    "Expired": "Inactive",
    "Cancelled": "Inactive",
    "Withdrawn": "Inactive",
    "Rejected": "Inactive",
    "Model Folder": "Inactive",
    # In Review
    "Intake": "In Review",
    "Technical Review": "In Review",
    "Accepted": "In Review",
    "Under Review": "In Review",
    "Ready to Issue": "In Review",
    "New": "In Review",
    "Tech Rev Complete": "In Review",
    "Pending": "In Review",
    "In Process": "In Review",
    "Approved with Conditions": "In Review",
    "Review Letter Sent": "In Review",
    "Review Complete - Fees Due": "In Review",
    "Pending Closeout": "In Review",
    "Prelim In Progress": "In Review",
    "Tentative Approval": "In Review",
    # Estimate folders are not completed permits (previously mislabeled Final)
    "Estimate": "In Review",
}


def _map_status(data_status: Optional[str]) -> Optional[str]:
    if not data_status or not isinstance(data_status, str):
        return None
    key = data_status.strip()
    return _STATUS_MAP.get(key) if key else None


def _raw_status(d: dict) -> Optional[str]:
    """Prefer new.details.Status; fall back to old.status."""
    new = d.get("new") if isinstance(d.get("new"), dict) else {}
    details = new.get("details") if isinstance(new.get("details"), dict) else {}
    status = details.get("Status")
    if isinstance(status, str) and status.strip():
        return status.strip()
    old = d.get("old") if isinstance(d.get("old"), dict) else {}
    status = old.get("status")
    if isinstance(status, str) and status.strip():
        return status.strip()
    return None


# ── Date extractors ─────────────────────────────────────────────────────────

def _file_date_from_data(d: dict):
    new = d.get("new") if isinstance(d.get("new"), dict) else {}
    details = new.get("details") if isinstance(new.get("details"), dict) else {}
    fd = _safe_to_datetime(details.get("Folder Date"))
    if fd is not pd.NaT:
        return fd
    old = d.get("old") if isinstance(d.get("old"), dict) else {}
    return _safe_to_datetime(old.get("file_date"))


def _process_step_dates_rich(new: dict, name_pred) -> list:
    """Collect dates from rich ``process`` rows matching name_pred(name)."""
    dates = []
    for p in new.get("process") or []:
        if not isinstance(p, (list, tuple)) or len(p) < 2:
            continue
        name = str(p[0]) if p[0] is not None else ""
        if not name_pred(name):
            continue
        # Row shape: [name, status, date_a, date_b, date_c, staff, email]
        for di in (2, 3, 4):
            if di < len(p):
                dt = _safe_to_datetime(p[di])
                if dt is not pd.NaT:
                    dates.append(dt)
    # Also process_dates map (single stamp per step name)
    for k, v in (new.get("process_dates") or {}).items():
        if name_pred(str(k)):
            dt = _safe_to_datetime(v)
            if dt is not pd.NaT:
                dates.append(dt)
    return dates


def _process_step_dates_lean(old: dict, name_pred) -> list:
    """Collect dates from old.processing_status matching name_pred(description)."""
    dates = []
    for p in old.get("processing_status") or []:
        if not isinstance(p, dict):
            continue
        name = str(p.get("description") or "")
        if not name_pred(name):
            continue
        for key in ("date_ended", "date_started"):
            dt = _safe_to_datetime(p.get(key))
            if dt is not pd.NaT:
                dates.append(dt)
                break
    return dates


def _is_issuance_review(name: str) -> bool:
    return name.strip() == "Issuance Review"


def _is_final_step(name: str) -> bool:
    n = name.strip()
    if not n:
        return False
    if "Final" in n:
        return True
    if n in {
        "Certificate of Occupancy",
        "Closed Out",
        "Close Out",
        "Closeout",
    }:
        return True
    return False


def _permit_date_from_data(d: dict):
    """Later of Issue Date and Issuance Review (when both exist)."""
    new = d.get("new") if isinstance(d.get("new"), dict) else {}
    details = new.get("details") if isinstance(new.get("details"), dict) else {}
    issue = _safe_to_datetime(details.get("Issue Date"))

    iss_rev_dates = _process_step_dates_rich(new, _is_issuance_review)
    old = d.get("old") if isinstance(d.get("old"), dict) else {}
    iss_rev_dates.extend(_process_step_dates_lean(old, _is_issuance_review))
    iss_rev = max(iss_rev_dates) if iss_rev_dates else pd.NaT

    if issue is not pd.NaT and iss_rev is not pd.NaT:
        # Issue Date sometimes equals Folder Date while a later Issuance
        # Review is the real issuance; take the later stamp.
        return _later(issue, iss_rev)
    if issue is not pd.NaT:
        return issue
    return iss_rev


def _final_date_from_data(d: dict):
    """Prefer details.Final Date; else latest closed Final process step."""
    new = d.get("new") if isinstance(d.get("new"), dict) else {}
    details = new.get("details") if isinstance(new.get("details"), dict) else {}
    final = _safe_to_datetime(details.get("Final Date"))
    if final is not pd.NaT:
        return final

    finals = _process_step_dates_rich(new, _is_final_step)
    old = d.get("old") if isinstance(d.get("old"), dict) else {}
    # Lean: Final Inspection group or Final* description
    for p in old.get("processing_status") or []:
        if not isinstance(p, dict):
            continue
        name = str(p.get("description") or "")
        group = str(p.get("group") or "")
        if not (_is_final_step(name) or group.strip() == "Final Inspection"):
            continue
        for key in ("date_ended", "date_started"):
            dt = _safe_to_datetime(p.get(key))
            if dt is not pd.NaT:
                finals.append(dt)
                break
    return max(finals) if finals else pd.NaT


# ── Per-record repair ───────────────────────────────────────────────────────

def _repair_record(row, d: dict, repairs: dict):
    """Repair one San Jose permit record."""
    # -- STATUS_NORMALIZED --
    current_status = row["STATUS_NORMALIZED"]
    expected = _map_status(_raw_status(d))
    if expected is not None:
        if pd.isna(current_status):
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"
        elif current_status != expected:
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FIXED"

    effective_status = repairs.get("STATUS_NORMALIZED", current_status)

    # -- FILE_DATE --
    file_src = _file_date_from_data(d)
    if file_src is not pd.NaT:
        if pd.isna(row["FILE_DATE"]):
            repairs["FILE_DATE"] = file_src
            repairs["FILE_DATE_FLAG"] = "FILLED"
        elif not _dates_equal(row["FILE_DATE"], file_src):
            repairs["FILE_DATE"] = file_src
            repairs["FILE_DATE_FLAG"] = "FIXED"

    # -- PERMIT_DATE --
    issued = _permit_date_from_data(d)
    if issued is not pd.NaT:
        if pd.isna(row["PERMIT_DATE"]):
            if effective_status in ("Active", "Final"):
                repairs["PERMIT_DATE"] = issued
                repairs["PERMIT_DATE_FLAG"] = "FILLED"
        elif not _dates_equal(row["PERMIT_DATE"], issued):
            repairs["PERMIT_DATE"] = issued
            repairs["PERMIT_DATE_FLAG"] = "FIXED"

    # -- FINAL_DATE --
    final = _final_date_from_data(d)
    current_final = row["FINAL_DATE"]

    if effective_status == "Final":
        if final is not pd.NaT:
            if pd.isna(current_final):
                repairs["FINAL_DATE"] = final
                repairs["FINAL_DATE_FLAG"] = "FILLED"
            elif not _dates_equal(current_final, final):
                repairs["FINAL_DATE"] = final
                repairs["FINAL_DATE_FLAG"] = "FIXED"
    elif not pd.isna(current_final):
        # Spurious FINAL_DATE on non-Final rows (e.g. Expired).
        repairs["FINAL_DATE"] = pd.NaT
        repairs["FINAL_DATE_FLAG"] = "FIXED"


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    San Jose permit records using information from the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "San Jose".  Must contain
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
        if d is None or schema == "unknown":
            continue

        repairs: dict = {}
        _repair_record(row, d, repairs)

        for key, value in repairs.items():
            if key in ("FILE_DATE", "PERMIT_DATE", "FINAL_DATE"):
                if value is not pd.NaT and not pd.isna(value):
                    value = _safe_to_datetime(value)
                    if value is not pd.NaT:
                        value = value.normalize()
            out.at[idx, key] = value

    for col in ("FILE_DATE", "PERMIT_DATE", "FINAL_DATE"):
        out[col] = pd.to_datetime(out[col], errors="coerce")

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
    city = df[(df["JURISDICTION"] == "San Jose") & (df["STATE"] == "CA")].copy()

    print(f"San Jose records: {len(city):,}\n")

    repaired = data_repair(city)

    if AGENT_DATA_PATH:
        out_path = os.path.join(
            AGENT_DATA_PATH, "processed_data", "permits_ca_san_jose_repaired.parquet"
        )
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
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

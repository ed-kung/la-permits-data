"""Data repair for Sarasota County (FL) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Sarasota County DATA has two sub-schemas:

  - permit_info: EnerGov-style payload with top-level keys
                 'Permit Details', 'Permit Info', 'Processes And Notes'.
                 Status and core dates live under Permit Details;
                 finalization evidence lives in Processes And Notes.
  - accela:      Accela Citizen Access payload with 'status', 'date',
                 'tasks', 'search_data', etc.

Canonical mappings (permit_info):
  - Permit Details.Status              → STATUS_NORMALIZED
  - Permit Details.Application Date    → FILE_DATE
  - Permit Details.Issue Date          → PERMIT_DATE
  - Processes And Notes (final / CO /
    last successful inspection)        → FINAL_DATE

Canonical mappings (accela):
  - DATA.status                        → STATUS_NORMALIZED
  - DATA.date / search_data.Date       → FILE_DATE
  - Permit Issuance Marked as Issued   → PERMIT_DATE
  - Certificate Final CO Issued, else
    Inspection Final Inspection
    Complete                           → FINAL_DATE

Known issues repaired:
  - Three permit_info statuses (Active/Current, Lien Filed, Progressive
    Enforcement) left STATUS_NORMALIZED null → FILLED.
  - Accela Pending CO mapped to Final; two Closed - Complete rows lagged
    on STATUS_ORIGINAL → FIXED.
  - Upstream FINAL_DATE for permit_info is always Expiration Date when
    present (100% of non-null values in the FL sample) → FIXED to a true
    finalization date from processes, or cleared when Expiration was the
    only source.
  - Active / Inactive rows incorrectly carrying Expiration as FINAL_DATE
    → FINAL_DATE cleared (FIXED).
  - Missing FINAL_DATE on Closed / Finaled building and compliance rows
    filled from Certificate / Final inspection / last approved inspection
    process Ended dates when available.
  - Accela FINAL_DATE sometimes set to Final Inspection Complete one day
    before Certificate of Occupancy Final CO Issued → FIXED to CO date.
  - Pending CO rows (Active) carrying Final Inspection Complete as
    FINAL_DATE → cleared until certificate issuance.

Not repairable / left as-is:
  - Many Closed code-enforcement / RFS rows have no Issue Date →
    PERMIT_DATE stays missing (not true building permits).
  - Final rows with no dated finalization process and no usable
    inspection Ended date → FINAL_DATE stays / becomes missing after
    clearing the incorrect Expiration value.
"""

from __future__ import annotations

import json
import math
import re
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
        return json.loads(data)
    return data


def _safe_to_datetime(val):
    """Parse a date value, returning pd.NaT on failure."""
    if val is None or (isinstance(val, str) and not str(val).strip()):
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


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())
    if "Permit Details" in keys or "Permit Info" in keys:
        return "permit_info"
    if "status" in keys and ("tasks" in keys or "search_data" in keys):
        return "accela"
    return "unknown"


def _apply_status(repairs: dict, current, raw_status: Optional[str], status_map: dict) -> Optional[str]:
    """Map raw status → STATUS_NORMALIZED; return effective status."""
    if raw_status is None:
        return current if not (isinstance(current, float) and pd.isna(current)) else None

    expected = status_map.get(raw_status)
    if expected is None:
        return current if not (isinstance(current, float) and pd.isna(current)) else None

    if pd.isna(current):
        repairs["STATUS_NORMALIZED"] = expected
        repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"
    elif current != expected:
        repairs["STATUS_NORMALIZED"] = expected
        repairs["STATUS_NORMALIZED_FLAG"] = "FIXED"

    return repairs.get("STATUS_NORMALIZED", current)


def _apply_date(repairs: dict, row, field: str, candidate, *, allow_fill: bool = True) -> None:
    """Fill or fix *field* from *candidate* datetime (pd.NaT = no candidate)."""
    cand = _safe_to_datetime(candidate)
    if cand is pd.NaT:
        return

    current = row[field]
    if pd.isna(current):
        if allow_fill:
            repairs[field] = cand
            repairs[f"{field}_FLAG"] = "FILLED"
    elif not _dates_equal(current, cand):
        repairs[field] = cand
        repairs[f"{field}_FLAG"] = "FIXED"


def _clear_date(repairs: dict, row, field: str) -> None:
    """Clear an incorrect non-null date field."""
    if pd.isna(row[field]):
        return
    if field in repairs and pd.isna(repairs[field]):
        return
    repairs[field] = pd.NaT
    repairs[f"{field}_FLAG"] = "FIXED"


# ── Status maps ──────────────────────────────────────────────────────────────

_PERMIT_INFO_STATUS_MAP = {
    "Closed": "Final",
    "Finaled": "Final",
    "Adopted": "Final",
    "Issued": "Active",
    "Approved": "Active",
    "Active/Current": "Active",
    "Progressive Enforcement": "Active",
    "Cancelled": "Inactive",
    "Expired": "Inactive",
    "Withdrawn": "Inactive",
    "Deactivated": "Inactive",
    "Lien Filed": "Inactive",
    "Review In Progress": "In Review",
    "Received": "In Review",
}

_ACCELA_STATUS_MAP = {
    "Closed - Complete": "Final",
    "Closed - Approved": "Final",
    "Inspection Phase": "Active",
    "Pending CO": "Active",
    "Ready to Issue": "In Review",
    "Plan Review": "In Review",
    "Revisions Required": "In Review",
    "Submitted": "In Review",
    "Additional Info Required": "In Review",
    "Pending": "In Review",
    "Closed - Withdrawn": "Inactive",
    "Permit Expired": "Inactive",
}


# ── permit_info FINAL_DATE extraction ────────────────────────────────────────

_ADMIN_PROCESS = re.compile(
    r"(application administration|permit administration|accept application|"
    r"^information$|route complaint|billing|retrieval of record|"
    r"lien administration|code enforcement customer contact|"
    r"violation notification|citation|hearing|abatement|towing|research|"
    r"check permit status|affidavit|schedule hearing)",
    re.I,
)

_OK_PROCESS_STATUS = {
    "approved",
    "completed",
    "closed",
    "passed",
    "co issued",
    "cc issued",
    "compliance",
}


def _final_from_processes(notes) -> pd.Timestamp:
    """Best finalization date from EnerGov Processes And Notes."""
    scored: list[tuple[int, pd.Timestamp]] = []

    for n in notes or []:
        if not isinstance(n, dict):
            continue
        desc = n.get("Process Description") or ""
        stl = (n.get("Status") or "").strip().lower()
        ended = _safe_to_datetime(n.get("Ended"))
        if ended is pd.NaT or stl not in _OK_PROCESS_STATUS:
            continue

        dl = desc.lower()
        score = None
        if stl in ("co issued", "cc issued") or "certificate of occupancy" in dl \
                or "certificate of completion" in dl:
            score = 5
        elif re.search(r"\bfinal\b", dl):
            # Flood / CFHA / elevation "final" certs are not permit closeout.
            if any(x in dl for x in ("flood", "cfha", "elevation cert", "survey final", "survey (final)")):
                score = 2
            else:
                score = 4
        elif not _ADMIN_PROCESS.search(desc) and (
            "inspect" in dl
            or "dry-in" in dl
            or "in progress" in dl
            or "replacement" in dl
            or "changeout" in dl
            or "change out" in dl
            or "signoff" in dl
            or "sign-off" in dl
        ):
            score = 1
        elif not _ADMIN_PROCESS.search(desc) and stl in (
            "approved", "completed", "passed", "compliance", "co issued", "cc issued"
        ):
            score = 0

        if score is not None:
            scored.append((score, ended))

    if not scored:
        return pd.NaT

    max_score = max(s for s, _ in scored)
    if max_score >= 4:
        band = [dt for s, dt in scored if s >= 4]
    elif max_score >= 2:
        band = [dt for s, dt in scored if s >= 2]
    else:
        band = [dt for s, dt in scored]
    return max(band)


# ── Accela task helpers ──────────────────────────────────────────────────────

def _event_field(event: dict, *labels: str):
    for label in labels:
        for k, v in event.items():
            if not isinstance(k, str):
                continue
            if k.replace("\xa0", " ").strip().lower() == label.lower():
                if isinstance(v, str):
                    return v.replace("\xa0", " ").strip()
                return v
    return None


def _parse_event(event: dict):
    """Return (marked_as, on_date_str) from an Accela task event."""
    html = (event.get("html") or "").replace("\xa0", " ")
    m = re.search(
        r"Marked as\s*<span[^>]*>([^<]*)</span>\s*on\s*<span[^>]*>([^<]*)</span>",
        html,
        flags=re.I,
    )
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return _event_field(event, "Marked as"), _event_field(event, "on")


def _task_event_dates(d: dict, task_substr: str, marked_substrs: list[str]):
    dates = []
    for t in d.get("tasks") or []:
        name = t.get("name") or ""
        if task_substr.lower() not in name.lower():
            continue
        for e in t.get("events") or []:
            if not isinstance(e, dict):
                continue
            marked, on = _parse_event(e)
            if not marked or not on:
                continue
            if any(ms.lower() in marked.lower() for ms in marked_substrs):
                # Avoid "Ready to Issue" matching a bare "Issued" check upstream.
                if "issued" in marked.lower() and "ready to issue" in marked.lower():
                    continue
                dt = _safe_to_datetime(on)
                if dt is not pd.NaT:
                    dates.append(dt)
    return dates


def _accela_permit_date(d: dict):
    dates = _task_event_dates(d, "Permit Issuance", ["Issued"])
    # Filter out Ready-to-Issue already handled; keep earliest true Issued.
    return min(dates) if dates else pd.NaT


def _accela_final_date(d: dict):
    co_dates = _task_event_dates(
        d,
        "Certificate",
        ["Final CO Issued", "CO Issued", "Cert of Compliance", "Cert of Occupancy", "CC Issued"],
    )
    if co_dates:
        return max(co_dates)
    insp_dates = _task_event_dates(d, "Inspection", ["Final Inspection Complete"])
    if insp_dates:
        return max(insp_dates)
    return pd.NaT


# ── Per-schema repair logic ─────────────────────────────────────────────────

def _repair_permit_info(row, d: dict, repairs: dict):
    details = d.get("Permit Details") if isinstance(d.get("Permit Details"), dict) else {}
    notes = d.get("Processes And Notes") or []

    raw_status = details.get("Status")
    effective_status = _apply_status(
        repairs, row["STATUS_NORMALIZED"], raw_status, _PERMIT_INFO_STATUS_MAP
    )

    # FILE_DATE ← Application Date
    _apply_date(repairs, row, "FILE_DATE", details.get("Application Date"))

    # PERMIT_DATE ← Issue Date (Active / Final; also fix mismatches anytime present)
    issued = _safe_to_datetime(details.get("Issue Date"))
    if issued is not pd.NaT:
        if pd.isna(row["PERMIT_DATE"]):
            if effective_status in ("Active", "Final"):
                repairs["PERMIT_DATE"] = issued
                repairs["PERMIT_DATE_FLAG"] = "FILLED"
        elif not _dates_equal(row["PERMIT_DATE"], issued):
            repairs["PERMIT_DATE"] = issued
            repairs["PERMIT_DATE_FLAG"] = "FIXED"

    # FINAL_DATE ← process finalization; Expiration Date is NOT a final date.
    expiration = _safe_to_datetime(details.get("Expiration Date"))
    true_final = _final_from_processes(notes)
    current_final = row["FINAL_DATE"]
    current_is_expiration = (
        not pd.isna(current_final)
        and expiration is not pd.NaT
        and _dates_equal(current_final, expiration)
    )

    if effective_status == "Final":
        if true_final is not pd.NaT:
            _apply_date(repairs, row, "FINAL_DATE", true_final)
        elif current_is_expiration:
            # Incorrect upstream copy of Expiration Date with no replacement.
            _clear_date(repairs, row, "FINAL_DATE")
    else:
        # Non-Final rows should not carry a finaled date (esp. Expiration).
        if not pd.isna(current_final) and (
            current_is_expiration or effective_status in ("Active", "In Review", "Inactive")
        ):
            if true_final is pd.NaT or effective_status != "Final":
                _clear_date(repairs, row, "FINAL_DATE")


def _repair_accela(row, d: dict, repairs: dict):
    raw_status = d.get("status")
    effective_status = _apply_status(
        repairs, row["STATUS_NORMALIZED"], raw_status, _ACCELA_STATUS_MAP
    )

    # FILE_DATE ← top-level date (application / record date)
    file_candidate = d.get("date")
    if _safe_to_datetime(file_candidate) is pd.NaT:
        sd = d.get("search_data") if isinstance(d.get("search_data"), dict) else {}
        file_candidate = sd.get("Date")
    _apply_date(repairs, row, "FILE_DATE", file_candidate)

    # PERMIT_DATE ← Permit Issuance / Issued
    issued = _accela_permit_date(d)
    if issued is not pd.NaT:
        if pd.isna(row["PERMIT_DATE"]):
            if effective_status in ("Active", "Final"):
                repairs["PERMIT_DATE"] = issued
                repairs["PERMIT_DATE_FLAG"] = "FILLED"
        elif not _dates_equal(row["PERMIT_DATE"], issued):
            repairs["PERMIT_DATE"] = issued
            repairs["PERMIT_DATE_FLAG"] = "FIXED"

    # FINAL_DATE ← CO issuance preferred, else Final Inspection Complete.
    # Pending CO / Inspection Phase may have Final Inspection Complete but are
    # not finaled until certificate issuance → clear FINAL_DATE when not Final.
    final = _accela_final_date(d)
    if effective_status == "Final":
        if final is not pd.NaT:
            _apply_date(repairs, row, "FINAL_DATE", final)
    elif not pd.isna(row["FINAL_DATE"]):
        _clear_date(repairs, row, "FINAL_DATE")


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Sarasota County permit records using information from the raw DATA JSON.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Sarasota County".  Must contain
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

        if schema == "permit_info":
            _repair_permit_info(row, d, repairs)
        elif schema == "accela":
            _repair_accela(row, d, repairs)

        for key, value in repairs.items():
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
    filepath = os.path.join(MY_DATA_PATH, "processed_data", "permits_fl_sample.parquet")
    df = pd.read_parquet(filepath)
    sc = df[df["JURISDICTION"] == "Sarasota County"].copy()

    print(f"Sarasota County records: {len(sc):,}\n")

    repaired = data_repair(sc)

    print("INFERRED_SCHEMA:")
    for s, c in repaired["INFERRED_SCHEMA"].value_counts(dropna=False).items():
        print(f"  {str(s):20s}: {c:>4,}")
    print()

    for field in ["STATUS_NORMALIZED", "FILE_DATE", "PERMIT_DATE", "FINAL_DATE"]:
        flag_col = f"{field}_FLAG"
        n_filled = (repaired[flag_col] == "FILLED").sum()
        n_fixed = (repaired[flag_col] == "FIXED").sum()
        print(f"{field}:")
        print(f"  FILLED: {n_filled:>4,}   FIXED: {n_fixed:>4,}")

        before_missing = sc[field].isna().sum()
        after_missing = repaired[field].isna().sum()
        print(f"  Missing before: {before_missing:>4,}   Missing after: {after_missing:>4,}")
        print()

    print("STATUS_NORMALIZED distribution:")
    print("  Before:")
    for s, c in sc["STATUS_NORMALIZED"].value_counts(dropna=False).items():
        print(f"    {str(s):15s}: {c:>4,}")
    print("  After:")
    for s, c in repaired["STATUS_NORMALIZED"].value_counts(dropna=False).items():
        print(f"    {str(s):15s}: {c:>4,}")

    print("\nFILE_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FILE_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({n_has / max(len(sub), 1):.1%})")

    print("\nPERMIT_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["PERMIT_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({n_has / max(len(sub), 1):.1%})")

    print("\nFINAL_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FINAL_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({n_has / max(len(sub), 1):.1%})")

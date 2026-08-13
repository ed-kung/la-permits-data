"""Data repair for Winter Springs (FL) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Winter Springs DATA is a Logos / TRAKiT-style portal payload with
top-level keys Permit Summary, Permit Details, Inspections, Notes,
Conditions, Payment Summary, Location, etc. Optional sections include
CONTRACTOR INFORMATION and GARAGE SALE INFORMATION. Content variants
(INFERRED_SCHEMA) are labeled by StatusValue lifecycle and optional
section suffixes:

  - logos_completed / logos_completed_contractor / logos_completed_garage
  - logos_issued / logos_issued_contractor
  - logos_pending / logos_pending_review / logos_created
  - missing / unknown

Canonical mappings:
  - Permit Summary.StatusValue           → STATUS_NORMALIZED
    (and embeds a lifecycle date on every sample row)
  - Permit Details.Application Received
    Date (absent in this sample), else
    Created status date, else note /
    routed fallbacks, else Pending
    Payment as-of date                   → FILE_DATE
  - Status date for Permit Issued        → PERMIT_DATE
  - Status date for Permit Completed,
    else latest Completed+Pass final
    inspection                           → FINAL_DATE

Known issues repaired:
  - STATUS_NORMALIZED mirrors stale STATUS_ORIGINAL (permit issued)
    while StatusValue has advanced to Permit Completed → FIXED Final.
  - Missing FINAL_DATE on those Completed-but-mislabeled rows → FILLED
    from the Completed status date after status repair.
  - Missing FILE_DATE on Pending Payment rows → FILLED from as-of date
    (weak submittal proxy, same Logos convention as Winter Haven /
    Greenacres).

Not repairable from DATA:
  - No Application Received Date, Notes, or Application Routed
    conditions → FILE_DATE remains missing for Issued / Completed /
    Pending Review rows (Created already populated upstream).
  - Completed StatusValue only embeds the completion date; PaidValue is
    fee payment, not a reliable PERMIT_DATE → Final issuance dates stay
    missing except where an earlier Active mapping already stored one.
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

_FINAL_INSP_RE = re.compile(
    r"final|fnl|closeout|certificate|\bco\b|\bcc\b|\bcoc\b",
    re.IGNORECASE,
)

_APP_RECEIVED_RE = re.compile(
    r"APPLICATION\s+RECEIVED\s+(\d{1,2}/\d{1,2}/\d{2,4})",
    re.IGNORECASE,
)

_STATUS_MAP = {
    "Permit Completed": "Final",
    "Permit Issued": "Active",
    "Permit Expired": "Inactive",
    "Pending Payment": "In Review",
    "Pending Review": "In Review",
    "Permit Created": "In Review",
    "Application Created": "In Review",
}


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
    """Parse a date value, returning pd.NaT on failure / sentinels."""
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return pd.NaT
    if isinstance(val, dict):
        return pd.NaT
    if isinstance(val, str):
        s = val.strip().replace("\xa0", " ")
        if not s or s.upper() in {
            "TBD", "NULL", "NONE", "N/A", "NA", "NAN", "NOT PAID",
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


def _present(dt) -> bool:
    return dt is not pd.NaT and not pd.isna(dt)


def _dates_equal(a, b) -> bool:
    """Compare two datelike values at calendar-day resolution."""
    da = _safe_to_datetime(a)
    db = _safe_to_datetime(b)
    if not _present(da) or not _present(db):
        return False
    return pd.Timestamp(da).normalize() == pd.Timestamp(db).normalize()


def _status_value(d: dict) -> Optional[str]:
    summary = d.get("Permit Summary")
    if isinstance(summary, dict):
        sv = summary.get("StatusValue")
        if sv is not None and str(sv).strip():
            return str(sv).strip()
    sv = d.get("Status")
    if sv is not None and str(sv).strip():
        return str(sv).strip()
    return None


def _parse_status(sv: Optional[str]) -> tuple[Optional[str], object]:
    """Return (status base, embedded lifecycle date)."""
    if not sv:
        return None, pd.NaT
    s = str(sv).strip()

    m = re.match(
        r"^(.*?)\s+(?:on|as of)\s+(\d{1,2}/\d{1,2}/\d{2,4})\s*$",
        s,
        flags=re.IGNORECASE,
    )
    if m:
        return m.group(1).strip(), _safe_to_datetime(m.group(2))

    m = re.match(
        r"^(Permit Expired)\s+(\d{1,2}/\d{1,2}/\d{2,4})\s*$",
        s,
        flags=re.IGNORECASE,
    )
    if m:
        return "Permit Expired", _safe_to_datetime(m.group(2))

    base = re.sub(r"\s+\d{1,2}/\d{1,2}/\d{2,4}.*$", "", s).strip()
    return base or None, pd.NaT


def _on_or_before(dt, upper) -> bool:
    if not _present(dt):
        return False
    if not _present(upper):
        return True
    return pd.Timestamp(dt).normalize() <= pd.Timestamp(upper).normalize()


def _permit_details(d: dict) -> dict:
    det = d.get("Permit Details")
    return det if isinstance(det, dict) else {}


def _application_received_field(d: dict, upper=None):
    """Permit Details.Application Received Date when present."""
    dt = _safe_to_datetime(_permit_details(d).get("Application Received Date"))
    if _on_or_before(dt, upper):
        return dt
    return pd.NaT


def _has_application_received_field(d: dict) -> bool:
    det = _permit_details(d)
    if "Application Received Date" not in det:
        return False
    return _present(_safe_to_datetime(det.get("Application Received Date")))


def _earliest_note_date(d: dict, upper=None):
    """Earliest Logos note date, skipping archival Microfilm/Historical."""
    notes = d.get("Notes")
    if not isinstance(notes, list):
        return pd.NaT

    candidates = []
    for note in notes:
        if not isinstance(note, dict):
            continue
        subject = str(note.get("LogosNotesSubjectColumn") or "").strip().lower()
        if subject == "historical" or "microfilm" in subject:
            continue
        dt = _safe_to_datetime(note.get("LogosNotesDateColumn"))
        if _on_or_before(dt, upper):
            candidates.append(dt)
    return min(candidates) if candidates else pd.NaT


def _application_received_date(d: dict, upper=None):
    """Parse APPLICATION RECEIVED / Application Rcvd stamps from Notes."""
    notes = d.get("Notes")
    if not isinstance(notes, list):
        return pd.NaT

    candidates = []
    for note in notes:
        if not isinstance(note, dict):
            continue
        text = str(note.get("LogosNotesNoteColumn") or "")
        m = _APP_RECEIVED_RE.search(text)
        if m:
            dt = _safe_to_datetime(m.group(1))
            if _on_or_before(dt, upper):
                candidates.append(dt)

        subject = str(note.get("LogosNotesSubjectColumn") or "")
        if re.search(r"APPLICATION\s+(STATUS|RECEIVED|RCVD)", subject, re.I):
            dt = _safe_to_datetime(note.get("LogosNotesDateColumn"))
            if _on_or_before(dt, upper):
                candidates.append(dt)

    return min(candidates) if candidates else pd.NaT


def _application_routed_date(d: dict, upper=None):
    """Earliest Application Routed condition due-date (submittal proxy)."""
    conditions = d.get("Conditions")
    if not isinstance(conditions, list):
        return pd.NaT

    candidates = []
    for cond in conditions:
        if not isinstance(cond, dict):
            continue
        code = str(cond.get("PermitConditionCodeColumn") or "").strip().lower()
        if code != "application routed":
            continue
        dt = _safe_to_datetime(cond.get("PermitConditionDueDateColumn"))
        if _on_or_before(dt, upper):
            candidates.append(dt)
    return min(candidates) if candidates else pd.NaT


def _final_inspection_date(d: dict):
    """Latest Completed+Pass inspection whose type looks final."""
    inspections = d.get("Inspections")
    if not isinstance(inspections, list):
        inspections = d.get("Inspection")
    if not isinstance(inspections, list):
        return pd.NaT

    candidates = []
    for insp in inspections:
        if not isinstance(insp, dict):
            continue
        status = str(insp.get("InspectionStatusColumn") or "").strip().lower()
        if status != "completed":
            continue
        result = str(insp.get("PassFailColumn") or "").strip().lower()
        if result and result != "pass":
            continue
        typ = str(insp.get("InspectionTypeColumn") or "")
        if not _FINAL_INSP_RE.search(typ):
            continue
        dt = _safe_to_datetime(insp.get("InspectionDateColumn"))
        if _present(dt):
            candidates.append(dt)
    return max(candidates) if candidates else pd.NaT


def _section_suffix(d: dict) -> str:
    """Optional top-level section markers for schema variants."""
    parts = []
    if "CONTRACTOR INFORMATION" in d:
        parts.append("contractor")
    if "GARAGE SALE INFORMATION" in d:
        parts.append("garage")
    return ("_" + "_".join(parts)) if parts else ""


# ── Schema classification ────────────────────────────────────────────────────

def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"

    keys = set(data_dict.keys())
    if "Permit Summary" in keys:
        base = "logos"
    elif "Status" in keys and ("Permit #" in keys or "Application #" in keys):
        base = "logos_flat"
    else:
        return "unknown"

    sv = _status_value(data_dict)
    status_base, status_dt = _parse_status(sv)
    has_status_dt = _present(status_dt)
    has_app = _has_application_received_field(data_dict)
    suffix = ("_app" if has_app else "") + _section_suffix(data_dict)

    final_insp = _final_inspection_date(data_dict)
    has_final_insp = _present(final_insp)
    note_dt = _earliest_note_date(data_dict)
    has_note = _present(note_dt)
    has_routed = _present(_application_routed_date(data_dict))

    if status_base == "Permit Completed":
        if has_status_dt or has_final_insp:
            return f"{base}_completed{suffix}"
        return f"{base}_completed_bare{suffix}"
    if status_base == "Permit Issued" and has_status_dt:
        return f"{base}_issued{suffix}"
    if status_base in ("Permit Created", "Application Created"):
        if has_status_dt or has_app:
            return f"{base}_created{suffix}"
        return f"{base}_status_only{suffix}"
    if status_base == "Permit Expired":
        return (
            f"{base}_expired{suffix}" if has_status_dt
            else f"{base}_expired_bare{suffix}"
        )
    if status_base == "Pending Payment":
        return (
            f"{base}_pending{suffix}" if (has_status_dt or has_app)
            else f"{base}_pending_bare{suffix}"
        )
    if status_base == "Pending Review":
        return (
            f"{base}_pending_review{suffix}" if has_status_dt
            else f"{base}_pending_review_bare{suffix}"
        )
    if has_note or has_routed or has_app:
        return f"{base}_notes_only{suffix}"
    return f"{base}_status_only{suffix}"


def _expected_status(status_base: Optional[str]) -> Optional[str]:
    if status_base is None:
        return None
    if status_base in _STATUS_MAP:
        return _STATUS_MAP[status_base]
    for key, val in _STATUS_MAP.items():
        if key.lower() == status_base.lower():
            return val
    return None


# ── Apply helpers ────────────────────────────────────────────────────────────

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


def _apply_date(repairs: dict, row, field: str, candidate) -> None:
    cand = _safe_to_datetime(candidate)
    if not _present(cand):
        return
    current = row[field]
    if pd.isna(current):
        repairs[field] = cand
        repairs[f"{field}_FLAG"] = "FILLED"
        return
    if not _dates_equal(current, cand):
        repairs[field] = cand
        repairs[f"{field}_FLAG"] = "FIXED"


def _clear_date(repairs: dict, row, field: str) -> None:
    current = repairs.get(field, row[field])
    if pd.isna(current):
        return
    repairs[field] = pd.NaT
    repairs[f"{field}_FLAG"] = "FIXED"


def _file_date_candidate(d: dict, status_base: Optional[str], status_dt, row) -> object:
    """Best available application / submittal stamp."""
    upper = pd.NaT
    if status_base == "Permit Issued":
        upper = status_dt
    elif status_base == "Permit Completed":
        upper = status_dt
        if not _present(upper):
            upper = _safe_to_datetime(row["FINAL_DATE"])
        if not _present(upper):
            upper = _final_inspection_date(d)
    elif status_base in (
        "Permit Expired", "Pending Payment", "Pending Review",
        "Permit Created", "Application Created",
    ):
        upper = status_dt

    # Explicit Permit Details field (newer Logos schema; absent here).
    field_recv = _application_received_field(d, upper=upper)
    if _present(field_recv):
        return field_recv

    # Created statuses: embedded status date is the application stamp.
    if status_base in ("Permit Created", "Application Created") and _present(status_dt):
        return status_dt

    # Note-based APPLICATION RECEIVED / Application Rcvd.
    app_recv = _application_received_date(d, upper=upper)
    if _present(app_recv):
        return app_recv

    candidates = []
    note = _earliest_note_date(d, upper=upper)
    if _present(note):
        candidates.append(note)
    routed = _application_routed_date(d, upper=upper)
    if _present(routed):
        candidates.append(routed)
    if candidates:
        return min(candidates)

    # Pending Payment "as of" date is a weak but usable submittal proxy
    # when no Application Received Date exists.
    if status_base == "Pending Payment" and _present(status_dt):
        return status_dt

    return pd.NaT


# ── Per-record repair ────────────────────────────────────────────────────────

def _repair_record(row, d: dict, repairs: dict) -> None:
    status_base, status_dt = _parse_status(_status_value(d))
    expected = _expected_status(status_base)
    effective_status = _apply_status(repairs, row["STATUS_NORMALIZED"], expected)

    # -- FILE_DATE --
    file_cand = _file_date_candidate(d, status_base, status_dt, row)
    if _present(file_cand):
        _apply_date(repairs, row, "FILE_DATE", file_cand)

    # -- PERMIT_DATE --
    # Only StatusValue "Permit Issued on …" is a true issuance stamp.
    # PaidValue is fee payment and is not used. Existing PERMIT_DATE on
    # Completed rows (from an earlier Issued mapping) is left intact.
    if status_base == "Permit Issued" and _present(status_dt):
        if effective_status in ("Active", "Final", "Inactive"):
            _apply_date(repairs, row, "PERMIT_DATE", status_dt)
        elif effective_status == "In Review":
            _clear_date(repairs, row, "PERMIT_DATE")
    elif effective_status == "In Review":
        _clear_date(repairs, row, "PERMIT_DATE")

    # -- FINAL_DATE --
    final_cand = pd.NaT
    if status_base == "Permit Completed":
        final_cand = status_dt
        if not _present(final_cand):
            final_cand = _final_inspection_date(d)

    if effective_status == "Final":
        if _present(final_cand):
            _apply_date(repairs, row, "FINAL_DATE", final_cand)
    else:
        _clear_date(repairs, row, "FINAL_DATE")


# ── Main entry point ─────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Winter Springs permit records using the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Winter Springs". Must contain
        columns STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, FINAL_DATE,
        and DATA.

    Returns
    -------
    pd.DataFrame
        Copy of *df* with corrected field values, an INFERRED_SCHEMA
        column naming the DATA JSON sub-schema identified for each
        record, and flag columns: STATUS_NORMALIZED_FLAG, FILE_DATE_FLAG,
        PERMIT_DATE_FLAG, FINAL_DATE_FLAG. Flag values are "FILLED"
        (was missing, now populated) or "FIXED" (had an incorrect value,
        now corrected).
    """
    out = df.copy()

    for col in ("FILE_DATE", "PERMIT_DATE", "FINAL_DATE"):
        out[col] = pd.to_datetime(out[col], errors="coerce", utc=True).dt.tz_localize(None)

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
        if d is None or schema in {"missing", "unknown"}:
            continue

        repairs: dict = {}
        _repair_record(row, d, repairs)
        for key, value in repairs.items():
            out.at[idx, key] = value

    for col in ("FILE_DATE", "PERMIT_DATE", "FINAL_DATE"):
        out[col] = pd.to_datetime(out[col], errors="coerce", utc=True).dt.tz_localize(None)

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
        (df["JURISDICTION"] == "Winter Springs") & (df["STATE"] == "FL")
    ].copy()

    print(f"Winter Springs records: {len(city):,}\n")
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

    both = repaired[repaired["PERMIT_DATE"].notna() & repaired["FINAL_DATE"].notna()]
    n_inv = (
        both["PERMIT_DATE"].dt.normalize() > both["FINAL_DATE"].dt.normalize()
    ).sum() if len(both) else 0
    print(f"\nPERMIT_DATE > FINAL_DATE inversions after repair: {n_inv}")

    fd = repaired["FILE_DATE"]
    pd_ = repaired["PERMIT_DATE"]
    both_fp = repaired[fd.notna() & pd_.notna()]
    n_fp_inv = (
        both_fp["FILE_DATE"].dt.normalize() > both_fp["PERMIT_DATE"].dt.normalize()
    ).sum() if len(both_fp) else 0
    print(f"FILE_DATE > PERMIT_DATE inversions after repair: {n_fp_inv}")

    fd2 = repaired["FILE_DATE"]
    final = repaired["FINAL_DATE"]
    both_ff = repaired[fd2.notna() & final.notna()]
    n_ff_inv = (
        both_ff["FILE_DATE"].dt.normalize() > both_ff["FINAL_DATE"].dt.normalize()
    ).sum() if len(both_ff) else 0
    print(f"FILE_DATE > FINAL_DATE inversions after repair: {n_ff_inv}")

    active_final = repaired["STATUS_NORMALIZED"].isin(["Active", "Final"])
    is_final = repaired["STATUS_NORMALIZED"] == "Final"
    print(f"\nAny missing FILE_DATE: {repaired['FILE_DATE'].isna().sum()}")
    print(
        f"Active/Final missing PERMIT_DATE: "
        f"{(active_final & repaired['PERMIT_DATE'].isna()).sum()}"
    )
    print(f"Final missing FINAL_DATE: {(is_final & repaired['FINAL_DATE'].isna()).sum()}")

    if agent_data_path:
        out_dir = Path(agent_data_path) / "repaired"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "permits_fl_winter_springs_repaired.parquet"
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote repaired sample → {out_path}")

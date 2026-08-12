"""Data repair for Clay County (FL) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Clay County DATA has two portal families:

  - legacy (Permit Information / inspections / Charges / Permit Notes /
    Plan Reviews / Holds): older county portal. Canonical dates are
    ``issue_date`` and ``co_date`` (sentinel ``0001-01-01`` / years
    outside 1980–2035 treated as missing). There is no application date
    field; FILE_DATE can only be weakly inferred from earliest Permit
    Note ``created_on`` or Plan Review ``received_date`` when present.
  - energov (entity / details / fees / …): Tyler EnerGov payload.
    Canonical dates are entity.ApplyDate / IssueDate / FinalDate
    (details.FinalizeDate fallback). Two key-set variants appear:
    ``energov`` and ``energov_full`` (extra reviews/holds/attachments/
    more_info).

Content variants (INFERRED_SCHEMA) further split each family by which
canonical dates / close outcomes are populated.

Canonical mappings:
  - legacy close_type / is_closed / issue_date
      (+ energov CaseStatus / FinalDate)     → STATUS_NORMALIZED
  - ApplyDate or earliest note/PR date       → FILE_DATE
  - issue_date / IssueDate                   → PERMIT_DATE
  - co_date else approved inspection
      / FinalDate (Final only)               → FINAL_DATE

Known issues repaired:
  - Admin Closed (legacy + energov) wrongly labeled Final → Inactive
    (no completion / CO date; matches other FL jurisdictions).
  - Permit Voided labeled Final → Inactive.
  - Opened-but-issued legacy rows labeled In Review → Active.
  - Energov Approved with FinalDate → Final; Approved without IssueDate
    → In Review.
  - Spurious FINAL_DATE on non-Final energov rows (Issued / Approved /
    Plan Approval Expired) cleared.
  - Sentinel / implausible PERMIT_DATE and FINAL_DATE (year 1 / 1900)
    cleared or replaced from DATA.
  - Missing FINAL_DATE on Final rows filled from co_date or last
    approved inspection; FINAL_DATE that matches an inspection but
    disagrees with co_date fixed to co_date.
  - Missing FILE_DATE on legacy rows filled from earliest usable note
    or plan-review received date when available.

Not repairable from DATA:
  - Most legacy rows (≈1,500+) have no application / note / plan-review
    date → FILE_DATE stays missing.
  - Admin Closed (now Inactive) and many closed-without-CO legacy rows
    have no usable final/sign-off date.
  - A few Active/Final energov rows have null IssueDate → PERMIT_DATE
    cannot be filled.
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
    r"final|fnl|cert(?:ificate)?\s*of\s*(?:occupancy|completion)|"
    r"\bco\b|\bcc\b|hff\b",
    re.I,
)
_PASS_RESULTS = {
    "APPROVED",
    "APPROVED W EXCEPTION",
    "APPROVED WITH COMMENTS",
    "APPROVED WITH CONDITIONS",
    "PASS",
    "PASSED",
    "PARTIAL APPROVED",
    "PARTIAL APPROVAL",
    "COMPLIANT",
}
_PASS_ADC = {"A", "P"}


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
    """Parse a date value, returning pd.NaT on failure / out-of-range."""
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
        # SQL / .NET sentinel
        if s.startswith("0001-01-01"):
            return pd.NaT
    try:
        dt = pd.to_datetime(val, utc=True, errors="coerce")
    except (ValueError, TypeError, OverflowError):
        return pd.NaT
    if pd.isna(dt):
        return pd.NaT
    year = int(dt.year)
    if year < _MIN_YEAR or year > _MAX_YEAR:
        return pd.NaT
    return dt.tz_convert("UTC").tz_localize(None)


def _dates_equal(a, b) -> bool:
    """Compare two datelike values at calendar-day resolution."""
    da = _safe_to_datetime(a)
    db = _safe_to_datetime(b)
    if da is pd.NaT or db is pd.NaT or pd.isna(da) or pd.isna(db):
        return False
    return pd.Timestamp(da).normalize() == pd.Timestamp(db).normalize()


def _permit_info(d: dict) -> Optional[dict]:
    info = d.get("Permit Information")
    if isinstance(info, list) and info and isinstance(info[0], dict):
        return info[0]
    if isinstance(info, dict):
        return info
    return None


def _family(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())
    if "Permit Information" in keys:
        return "legacy"
    if "entity" in keys:
        return "energov"
    return "unknown"


def _classify_schema(data_dict: Optional[dict]) -> str:
    family = _family(data_dict)
    if family in ("missing", "unknown"):
        return family

    if family == "legacy":
        pi = _permit_info(data_dict) or {}
        issue = _safe_to_datetime(pi.get("issue_date"))
        co = _safe_to_datetime(pi.get("co_date"))
        void = _safe_to_datetime(pi.get("void_date"))
        close_type = (pi.get("close_type") or "").strip()
        is_closed = bool(pi.get("is_closed"))

        if void is not pd.NaT and not pd.isna(void):
            return "legacy_voided"
        if close_type == "Admin Closed":
            return "legacy_admin_closed"
        if issue is not pd.NaT and not pd.isna(issue) and co is not pd.NaT and not pd.isna(co):
            return "legacy_issued_co"
        if issue is not pd.NaT and not pd.isna(issue) and is_closed:
            return "legacy_issued_closed"
        if issue is not pd.NaT and not pd.isna(issue):
            return "legacy_issued_open"
        if is_closed:
            return "legacy_closed"
        return "legacy_open"

    # energov
    keys = set(data_dict.keys())
    has_extra = bool(keys & {"reviews", "holds", "attachments", "more_info"})
    entity = data_dict.get("entity") if isinstance(data_dict.get("entity"), dict) else {}
    apply = _safe_to_datetime(entity.get("ApplyDate"))
    issue = _safe_to_datetime(entity.get("IssueDate"))
    final = _safe_to_datetime(entity.get("FinalDate"))
    details = data_dict.get("details") if isinstance(data_dict.get("details"), dict) else {}
    if final is pd.NaT or pd.isna(final):
        final = _safe_to_datetime(details.get("FinalizeDate"))

    base = "energov_full" if has_extra else "energov"
    has_apply = apply is not pd.NaT and not pd.isna(apply)
    has_issue = issue is not pd.NaT and not pd.isna(issue)
    has_final = final is not pd.NaT and not pd.isna(final)
    if has_issue and has_final:
        return f"{base}_issued_finaled"
    if has_issue:
        return f"{base}_issued"
    if has_final:
        return f"{base}_finaled"
    if has_apply:
        return f"{base}_applied"
    return f"{base}_status_only"


# ── Status mapping ───────────────────────────────────────────────────────────

# EnerGov CaseStatus → STATUS_NORMALIZED
_ENERGOV_STATUS_MAP = {
    "Complete": "Final",
    "Certificate of Occupancy": "Final",
    "Issued": "Active",
    "Expired": "Inactive",
    "Void": "Inactive",
    "Denied": "Inactive",
    "Plan Approval Expired": "Inactive",
    "Admin Closed": "Inactive",
    "In Review": "In Review",
    "Fees Due": "In Review",
    "Fees Paid": "In Review",
    "On Hold": "In Review",
    "Submitted - Online": "In Review",
}

# Legacy close_type → STATUS_NORMALIZED (when closed)
_LEGACY_CLOSE_MAP = {
    "Certficate of Occupancy": "Final",  # typo in source data
    "Certificate of Occupancy": "Final",
    "Certficate of Completion": "Final",
    "Certificate of Completion": "Final",
    "Passed Final Inspection": "Final",
    "Admin Closed": "Inactive",
    "Permit Voided": "Inactive",
}


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


def _legacy_expected_status(pi: dict, issue) -> Optional[str]:
    close_type = pi.get("close_type")
    close_key = str(close_type).strip() if close_type is not None else ""
    is_closed = bool(pi.get("is_closed"))
    void = _safe_to_datetime(pi.get("void_date"))
    has_issue = issue is not pd.NaT and not pd.isna(issue)
    pfi = bool(pi.get("passed_final_inspection"))

    if void is not pd.NaT and not pd.isna(void):
        return "Inactive"
    if close_key in _LEGACY_CLOSE_MAP:
        return _LEGACY_CLOSE_MAP[close_key]
    if is_closed:
        # Closed without a labeled close_type: treat as Final when a
        # final inspection passed, else Inactive (admin-style close).
        return "Final" if pfi else "Inactive"
    if has_issue:
        return "Active"
    return "In Review"


def _energov_expected_status(d: dict, issue, final) -> Optional[str]:
    entity = d.get("entity") if isinstance(d.get("entity"), dict) else {}
    details = d.get("details") if isinstance(d.get("details"), dict) else {}
    raw = entity.get("CaseStatus") or details.get("PermitStatus")
    if raw is None:
        return None
    status = str(raw).strip()
    if not status:
        return None

    has_issue = issue is not pd.NaT and not pd.isna(issue)
    has_final = final is not pd.NaT and not pd.isna(final)

    if status == "Approved":
        # Prefer Final when a plausible FinalDate is present at/after issue.
        if has_final and (not has_issue or final.normalize() >= issue.normalize()):
            return "Final"
        return "Active" if has_issue else "In Review"

    if status in _ENERGOV_STATUS_MAP:
        return _ENERGOV_STATUS_MAP[status]

    return None


# ── Date helpers ─────────────────────────────────────────────────────────────

def _apply_date(repairs: dict, row, field: str, candidate) -> None:
    cand = _safe_to_datetime(candidate)
    if cand is pd.NaT or pd.isna(cand):
        return
    current = row[field]
    current_ok = _safe_to_datetime(current)
    # Missing or implausible upstream value → FILLED / FIXED respectively.
    if pd.isna(current):
        repairs[field] = cand
        repairs[f"{field}_FLAG"] = "FILLED"
        return
    if current_ok is pd.NaT or pd.isna(current_ok):
        repairs[field] = cand
        repairs[f"{field}_FLAG"] = "FIXED"
        return
    if not _dates_equal(current_ok, cand):
        repairs[field] = cand
        repairs[f"{field}_FLAG"] = "FIXED"


def _clear_date(repairs: dict, row, field: str) -> None:
    current = repairs.get(field, row[field])
    if pd.isna(current):
        return
    # Also clear when current parses to NaT under our rules (sentinel).
    repairs[field] = pd.NaT
    repairs[f"{field}_FLAG"] = "FIXED"


def _is_pass_inspection(insp: dict) -> bool:
    res = str(insp.get("ResultDescription") or insp.get("Result") or "").strip().upper()
    if res in _PASS_RESULTS:
        return True
    adc = str(insp.get("ResultADC") or "").strip().upper()
    return adc in _PASS_ADC


def _inspection_datetime(insp: dict):
    for key in ("InspDateTime", "DisplayInspDateTime", "SchedDateTime", "DisplaySchedDateTime"):
        dt = _safe_to_datetime(insp.get(key))
        if dt is not pd.NaT and not pd.isna(dt):
            return dt
    return pd.NaT


def _last_approved_final_inspection(d: dict):
    dates = []
    for insp in d.get("inspections") or []:
        if not isinstance(insp, dict) or not _is_pass_inspection(insp):
            continue
        desc = str(insp.get("InsDesc") or insp.get("InspectionCode") or "")
        if not _FINAL_INSP_RE.search(desc):
            continue
        dt = _inspection_datetime(insp)
        if dt is not pd.NaT and not pd.isna(dt):
            dates.append(dt)
    return max(dates) if dates else pd.NaT


def _last_approved_inspection(d: dict):
    dates = []
    for insp in d.get("inspections") or []:
        if not isinstance(insp, dict) or not _is_pass_inspection(insp):
            continue
        dt = _inspection_datetime(insp)
        if dt is not pd.NaT and not pd.isna(dt):
            dates.append(dt)
    return max(dates) if dates else pd.NaT


def _legacy_file_date(d: dict, issue):
    """Earliest note/plan-review date as a weak FILE_DATE proxy."""
    candidates = []
    for note in d.get("Permit Notes") or []:
        if not isinstance(note, dict):
            continue
        dt = _safe_to_datetime(note.get("created_on"))
        if dt is not pd.NaT and not pd.isna(dt):
            candidates.append(dt)
    for pr in d.get("Plan Reviews") or []:
        if not isinstance(pr, dict):
            continue
        dt = _safe_to_datetime(pr.get("received_date"))
        if dt is not pd.NaT and not pd.isna(dt):
            candidates.append(dt)
    if not candidates:
        return pd.NaT
    earliest = min(candidates)
    # Prefer dates on/before issuance when an issue date exists.
    if issue is not pd.NaT and not pd.isna(issue):
        before = [c for c in candidates if c.normalize() <= issue.normalize()]
        if before:
            return min(before)
    return earliest


def _entity_date(d: dict, entity_key: str, *detail_keys: str):
    entity = d.get("entity") if isinstance(d.get("entity"), dict) else {}
    dt = _safe_to_datetime(entity.get(entity_key))
    if dt is not pd.NaT and not pd.isna(dt):
        return dt
    details = d.get("details") if isinstance(d.get("details"), dict) else {}
    for key in detail_keys:
        dt = _safe_to_datetime(details.get(key))
        if dt is not pd.NaT and not pd.isna(dt):
            return dt
    return pd.NaT


# ── Per-schema repair ────────────────────────────────────────────────────────

def _repair_legacy(row, d: dict, repairs: dict) -> None:
    pi = _permit_info(d)
    if pi is None:
        return

    issue = _safe_to_datetime(pi.get("issue_date"))
    co = _safe_to_datetime(pi.get("co_date"))
    expected = _legacy_expected_status(pi, issue)
    effective_status = _apply_status(repairs, row["STATUS_NORMALIZED"], expected)

    # FILE_DATE — no ApplyDate in legacy portal; weak proxies only.
    file_src = _legacy_file_date(d, issue)
    if file_src is not pd.NaT and not pd.isna(file_src):
        _apply_date(repairs, row, "FILE_DATE", file_src)

    # PERMIT_DATE ← issue_date; clear sentinel-only values.
    if issue is not pd.NaT and not pd.isna(issue):
        if effective_status in ("Active", "Final", "Inactive"):
            _apply_date(repairs, row, "PERMIT_DATE", issue)
        elif effective_status == "In Review":
            # Unissued review rows should not carry an issue stamp.
            _clear_date(repairs, row, "PERMIT_DATE")
    else:
        current_permit_ok = _safe_to_datetime(row["PERMIT_DATE"])
        if not pd.isna(row["PERMIT_DATE"]) and (
            current_permit_ok is pd.NaT or pd.isna(current_permit_ok)
        ):
            _clear_date(repairs, row, "PERMIT_DATE")

    # FINAL_DATE ← co_date else approved final-ish / any approved inspection.
    final_src = co
    if final_src is pd.NaT or pd.isna(final_src):
        final_src = _last_approved_final_inspection(d)
    if final_src is pd.NaT or pd.isna(final_src):
        final_src = _last_approved_inspection(d)

    current_final = row["FINAL_DATE"]
    current_final_ok = _safe_to_datetime(current_final)

    if effective_status == "Final":
        if final_src is not pd.NaT and not pd.isna(final_src):
            # Prefer CO date over an inspection-derived upstream value.
            if pd.isna(current_final) or current_final_ok is pd.NaT or pd.isna(current_final_ok):
                repairs["FINAL_DATE"] = final_src
                repairs["FINAL_DATE_FLAG"] = (
                    "FIXED"
                    if not pd.isna(current_final)
                    else "FILLED"
                )
            elif not _dates_equal(current_final_ok, final_src):
                # If CO exists, always prefer it; otherwise only fill gaps
                # (do not overwrite a plausible inspection date with another
                # inspection date unless current is implausible — handled above).
                if co is not pd.NaT and not pd.isna(co):
                    repairs["FINAL_DATE"] = co
                    repairs["FINAL_DATE_FLAG"] = "FIXED"
        elif not pd.isna(current_final) and (
            current_final_ok is pd.NaT or pd.isna(current_final_ok)
        ):
            _clear_date(repairs, row, "FINAL_DATE")
    elif not pd.isna(current_final):
        _clear_date(repairs, row, "FINAL_DATE")


def _repair_energov(row, d: dict, repairs: dict) -> None:
    apply = _entity_date(d, "ApplyDate", "ApplyDate")
    issue = _entity_date(d, "IssueDate", "IssueDate")
    final = _entity_date(d, "FinalDate", "FinalizeDate")

    expected = _energov_expected_status(d, issue, final)
    effective_status = _apply_status(repairs, row["STATUS_NORMALIZED"], expected)

    # FILE_DATE ← ApplyDate
    if apply is not pd.NaT and not pd.isna(apply):
        _apply_date(repairs, row, "FILE_DATE", apply)

    # PERMIT_DATE ← IssueDate for issued / completed statuses
    if issue is not pd.NaT and not pd.isna(issue):
        if effective_status in ("Active", "Final", "Inactive"):
            _apply_date(repairs, row, "PERMIT_DATE", issue)
        elif effective_status == "In Review":
            _clear_date(repairs, row, "PERMIT_DATE")
    elif effective_status in ("Active", "Final"):
        # Active/Final but no IssueDate: leave missing (cannot invent).
        current_permit_ok = _safe_to_datetime(row["PERMIT_DATE"])
        if not pd.isna(row["PERMIT_DATE"]) and (
            current_permit_ok is pd.NaT or pd.isna(current_permit_ok)
        ):
            _clear_date(repairs, row, "PERMIT_DATE")

    # FINAL_DATE ← FinalDate / FinalizeDate for Final only.
    # Skip FinalDate values that predate IssueDate on non-completion
    # statuses (observed junk stamps on Issued driveways).
    usable_final = final
    if (
        usable_final is not pd.NaT
        and not pd.isna(usable_final)
        and issue is not pd.NaT
        and not pd.isna(issue)
        and usable_final.normalize() < issue.normalize()
        and expected not in ("Final",)
    ):
        usable_final = pd.NaT

    current_final = row["FINAL_DATE"]
    if effective_status == "Final":
        if usable_final is not pd.NaT and not pd.isna(usable_final):
            _apply_date(repairs, row, "FINAL_DATE", usable_final)
        else:
            current_final_ok = _safe_to_datetime(current_final)
            if not pd.isna(current_final) and (
                current_final_ok is pd.NaT or pd.isna(current_final_ok)
            ):
                _clear_date(repairs, row, "FINAL_DATE")
    elif not pd.isna(current_final):
        _clear_date(repairs, row, "FINAL_DATE")


# ── Main entry point ─────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Clay County permit records using the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Clay County".  Must contain
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

    # Use object dtype while repairing so sub-second DATA timestamps
    # (e.g. ApplyDate / note created_on) can be written regardless of the
    # incoming datetime unit (ns vs s).
    for col in ("FILE_DATE", "PERMIT_DATE", "FINAL_DATE"):
        out[col] = pd.to_datetime(out[col], errors="coerce", utc=True).dt.tz_localize(None)
        out[col] = out[col].astype(object)

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
        family = _family(d)
        if family == "legacy":
            _repair_legacy(row, d, repairs)
        elif family == "energov":
            _repair_energov(row, d, repairs)

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
    city = df[df["JURISDICTION"] == "Clay County"].copy()

    print(f"Clay County records: {len(city):,}\n")

    repaired = data_repair(city)

    print("INFERRED_SCHEMA:")
    for s, c in repaired["INFERRED_SCHEMA"].value_counts(dropna=False).items():
        print(f"  {str(s):30s}: {c:>4,}")
    print()

    for field in ["STATUS_NORMALIZED", "FILE_DATE", "PERMIT_DATE", "FINAL_DATE"]:
        flag_col = f"{field}_FLAG"
        n_filled = (repaired[flag_col] == "FILLED").sum()
        n_fixed = (repaired[flag_col] == "FIXED").sum()
        print(f"{field}:")
        print(f"  FILLED: {n_filled:,}  FIXED: {n_fixed:,}")
        if field == "STATUS_NORMALIZED":
            print("  before:", city[field].value_counts(dropna=False).to_dict())
            print("  after: ", repaired[field].value_counts(dropna=False).to_dict())
        else:
            before_miss = city[field].isna().sum()
            # also count sentinel-like before
            before_dt = pd.to_datetime(city[field], errors="coerce")
            after_miss = repaired[field].isna().sum()
            print(f"  missing before/after: {before_miss:,} → {after_miss:,}")
        print()

    # Ideal coverage
    print("Ideal coverage after repair:")
    print(f"  FILE_DATE populated: {repaired['FILE_DATE'].notna().mean()*100:.1f}%")
    for status in ("Active", "Final"):
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        if len(sub) == 0:
            continue
        print(
            f"  {status} PERMIT_DATE: "
            f"{sub['PERMIT_DATE'].notna().mean()*100:.1f}% ({sub['PERMIT_DATE'].notna().sum()}/{len(sub)})"
        )
    final = repaired[repaired["STATUS_NORMALIZED"] == "Final"]
    if len(final):
        print(
            f"  Final FINAL_DATE: "
            f"{final['FINAL_DATE'].notna().mean()*100:.1f}% "
            f"({final['FINAL_DATE'].notna().sum()}/{len(final)})"
        )
    non_final_with = repaired[
        (repaired["STATUS_NORMALIZED"] != "Final") & repaired["FINAL_DATE"].notna()
    ]
    print(f"  Non-Final with FINAL_DATE: {len(non_final_with)}")

    if agent_data_path:
        out_path = Path(agent_data_path) / "clay_county_repaired_sample.parquet"
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote {out_path}")

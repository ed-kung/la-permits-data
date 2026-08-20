"""Data repair for Navasota (TX) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Navasota DATA is a CitizenServe-style municipal portal payload with three
top-level shapes (INFERRED_SCHEMA bases):

  - portal_full:     colon-suffixed shell (``Status:``, ``Permit #:``,
                     ``Permit Details``, ``Reviews``, ``Inspections``)
  - portal_compact:  short form (``Status``, ``Permit #``, ``Issue Date``,
                     no Reviews / Permit Details)
  - portal_minimal:  short form without ``Issue Date``; ``Status`` is often
                     a work-description scrap rather than a portal status

Content suffixes further split by which canonical dates are recoverable
(``_issued_finaled``, ``_issued``, ``_finaled``, ``_applied``,
``_status_only``).

Canonical mappings:
  - Status: / Status                      → STATUS_NORMALIZED
    (In Review + Issue Date → Active)
  - earliest non-issuance Review Start,
    else Completion, on/before Issue      → FILE_DATE
  - Permit Details["Issue Date:"]
    (else top-level Issue Date)           → PERMIT_DATE
  - latest Pass/Complete/Approved
    inspection (floored at Issue)         → FINAL_DATE (Final only)

Known issues repaired:
  - FILE_DATE often equals Issue Permit Card Completion / Issue Date
    rather than earlier Plan / Application Review Start → FIXED;
    missing FILE filled from Reviews; FILE cleared when no application
    Review source exists (issue-date proxy or post-issue stamp).
  - Five Under Review / Online Application Received rows already carry
    Issue Date → FIXED to Active; spurious In Review PERMIT_DATE cleared
    for remaining pure review rows.
  - FINAL_DATE missing on every sample row; Final shells lack Pass
    inspections in this sample so FINAL stays empty.

Not repairable from DATA:
  - portal_compact / portal_minimal: no Reviews → FILE_DATE stays missing.
  - Empty Status: shells and work-description ``Status`` scrapes
    (~128 rows) → STATUS_NORMALIZED stays missing.
  - Closed / Final shells without Pass inspections → FINAL_DATE stays
    missing. Issued rows with passed Final inspections remain Active
    (portal status authoritative).
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

_PASS_STATUS = {
    "passed",
    "pass",
    "approved",
    "approved with comments",
    "pass with comments",
    "complete",
    "completed",
    "inspection passed",
}

_STATUS_MAP = {
    # Final
    "Closed": "Final",
    "Finaled": "Final",
    "Finaled - CO": "Final",
    "Finaled - CC": "Final",
    "Certificate of Occupancy": "Final",
    "Inspection Completed": "Final",
    # Active
    "Issued": "Active",
    "Approved": "Active",
    # In Review
    "Under Review": "In Review",
    "Online Application Received": "In Review",
    "Payment Required": "In Review",
    "Resubmittal Required": "In Review",
    "Re-Submittal Required": "In Review",
    "On Hold": "In Review",
    "Pending Payment": "In Review",
    # Inactive
    "Canceled": "Inactive",
    "Cancelled": "Inactive",
    "Denied": "Inactive",
    "Expired": "Inactive",
    "Withdrawn": "Inactive",
    "Void": "Inactive",
    "Voided": "Inactive",
    "Revoked": "Inactive",
    "Abandoned": "Inactive",
    "Admin Close": "Inactive",
}

# Post-issuance / payment / messaging — not application / submittal dates.
_NON_FILE_TASK_RE = re.compile(
    r"online document upload|online message|online resubmittal|"
    r"online payment|online inspection|co requirements|issue permit|"
    r"issue revision|issue co|certificate review|admin co fee|"
    r"remodel final|wire lath",
    re.IGNORECASE,
)


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
    """Parse a date value, returning pd.NaT on failure / sentinel / OOR."""
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return pd.NaT
    if isinstance(val, dict):
        return pd.NaT
    if isinstance(val, str):
        s = val.strip().replace("\xa0", " ")
        if not s or s.upper() in {
            "TBD", "NULL", "NONE", "N/A", "NA", "NAN",
            "00/00/0000", "0/0/0000",
        }:
            return pd.NaT
        if s.startswith("0001-01-01") or s.startswith("1900-01-01"):
            return pd.NaT
        if s.lower().startswith("scheduled"):
            return pd.NaT
        # Prefer strict whole-string dates so polluted text is not scraped.
        if not re.match(r"^\d{1,2}/\d{1,2}/\d{2,4}$", s):
            m = re.search(r"(\d{1,2}/\d{1,2}/\d{2,4})", s)
            if m and len(s) <= 24:
                s = m.group(1)
            else:
                return pd.NaT
        try:
            dt = pd.to_datetime(s, errors="coerce")
        except (ValueError, TypeError, OverflowError):
            return pd.NaT
    else:
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
    da = _safe_to_datetime(a)
    db = _safe_to_datetime(b)
    if not _present(da) or not _present(db):
        return False
    return pd.Timestamp(da).normalize() == pd.Timestamp(db).normalize()


def _has_usable_date(val) -> bool:
    return _present(_safe_to_datetime(val))


def _nonempty_str(val) -> Optional[str]:
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return None
    s = str(val).strip()
    return s or None


def _raw_status(d: dict) -> Optional[str]:
    return _nonempty_str(d.get("Status:")) or _nonempty_str(d.get("Status"))


def _permit_details(d: dict) -> dict:
    det = d.get("Permit Details")
    return det if isinstance(det, dict) else {}


def _issue_date(d: dict):
    """Prefer Permit Details Issue Date; fall back to top-level."""
    det = _permit_details(d)
    dt = _safe_to_datetime(det.get("Issue Date:"))
    if _present(dt):
        return dt
    return _safe_to_datetime(d.get("Issue Date"))


def _insp_status_token(status: Optional[str]) -> str:
    if not status:
        return ""
    token = re.split(r"[\r\n]", str(status), maxsplit=1)[0]
    token = re.sub(r"view comments", "", token, flags=re.IGNORECASE)
    return token.strip().lower()


def _is_pass_status(status: Optional[str]) -> bool:
    token = _insp_status_token(status)
    if not token:
        return False
    if token in _PASS_STATUS:
        return True
    return (
        token.startswith("approved")
        or token.startswith("complete")
        or token.startswith("pass")
        or "inspection passed" in token
    )


def _latest_passed_inspection(d: dict):
    """Latest Pass/Complete/Approved inspection date (any trade type)."""
    insp = d.get("Inspections")
    if not isinstance(insp, list):
        return pd.NaT
    dates = []
    for item in insp:
        if not isinstance(item, dict):
            continue
        date_raw = str(item.get("Date") or "")
        if date_raw.lower().startswith("scheduled"):
            continue
        if not _is_pass_status(item.get("Status")):
            continue
        dt = _safe_to_datetime(item.get("Date"))
        if _present(dt):
            dates.append(dt)
    return max(dates) if dates else pd.NaT


def _final_date(d: dict):
    """Final / sign-off proxy: latest Pass inspection, ≥ Issue."""
    latest = _latest_passed_inspection(d)
    if not _present(latest):
        return pd.NaT
    issue = _issue_date(d)
    if _present(issue):
        return max(
            pd.Timestamp(latest).normalize(),
            pd.Timestamp(issue).normalize(),
        )
    return latest


def _normalize_reviews(d: dict) -> list:
    """CitizenServe sometimes returns a single review dict instead of a list."""
    reviews = d.get("Reviews")
    if isinstance(reviews, list):
        return [r for r in reviews if isinstance(r, dict)]
    if isinstance(reviews, dict) and reviews:
        return [reviews]
    return []


def _review_lists(d: dict):
    """Return intake_dates, early_starts, early_comps."""
    intake = []
    early_starts = []
    early_comps = []
    for r in _normalize_reviews(d):
        task = str(r.get("Task") or "")
        st = _safe_to_datetime(r.get("Start"))
        cp = _safe_to_datetime(r.get("Completion"))
        if "application intake" in task.lower():
            if _present(st):
                intake.append(st)
            elif _present(cp):
                intake.append(cp)
        if _NON_FILE_TASK_RE.search(task):
            continue
        if _present(st):
            early_starts.append(st)
        if _present(cp):
            early_comps.append(cp)
    return intake, early_starts, early_comps


def _on_or_before(candidate, issue) -> bool:
    if not _present(candidate):
        return False
    if not _present(issue):
        return True
    return pd.Timestamp(candidate).normalize() <= pd.Timestamp(issue).normalize()


def _file_date(d: dict):
    """Application / submittal date proxy.

    Prefer Application Intake; fall back to earliest non-issuance Review
    Start / Completion on or before Issue. Upstream FILE_DATE often
    equals Issue Permit Card Completion / Issue Date rather than the
    earlier Plan / Application Review Start.
    """
    issue = _issue_date(d)
    intake, early_starts, early_comps = _review_lists(d)

    intake = [dt for dt in intake if _on_or_before(dt, issue)]
    if intake:
        return min(intake)

    early_starts = [dt for dt in early_starts if _on_or_before(dt, issue)]
    if early_starts:
        return min(early_starts)

    early_comps = [dt for dt in early_comps if _on_or_before(dt, issue)]
    if early_comps:
        return min(early_comps)

    return pd.NaT


def _has_file_source(d: dict) -> bool:
    return _present(_file_date(d))


# ── Schema classification ────────────────────────────────────────────────────

def _schema_base(data_dict: dict) -> str:
    keys = set(data_dict.keys())
    if "Status:" in keys and "Permit Details" in keys:
        return "portal_full"
    if "Status" in keys and "Issue Date" in keys:
        return "portal_compact"
    if "Status" in keys:
        return "portal_minimal"
    return "unknown"


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    base = _schema_base(data_dict)
    if base == "unknown":
        return "unknown"

    has_issue = _present(_issue_date(data_dict))
    has_final = _present(_latest_passed_inspection(data_dict))
    has_applied = _has_file_source(data_dict)

    if has_issue and has_final:
        return f"{base}_issued_finaled"
    if has_issue:
        return f"{base}_issued"
    if has_final:
        return f"{base}_finaled"
    if has_applied:
        return f"{base}_applied"
    return f"{base}_status_only"


# ── Status mapping ───────────────────────────────────────────────────────────

def _map_status(raw: Optional[str]) -> Optional[str]:
    if raw is None:
        return None
    if raw in _STATUS_MAP:
        return _STATUS_MAP[raw]
    for key, val in _STATUS_MAP.items():
        if key.lower() == raw.lower():
            return val
    return None


def _expected_status(d: dict) -> Optional[str]:
    """Map portal Status: / Status → STATUS_NORMALIZED.

    Unmapped Status values (work-description scrapes on portal_minimal,
    shifted fields, empty shells) are left unrepaired rather than forced
    into In Review.
    """
    raw = _raw_status(d)
    has_issue = _present(_issue_date(d))

    if raw is None:
        if has_issue:
            return "Active"
        return None

    mapped = _map_status(raw)
    if mapped is None:
        # Do not treat free-text / shifted Status as In Review.
        if has_issue:
            return "Active"
        return None

    # Pre-issuance labels that already carry Issue Date → Active.
    if mapped == "In Review" and has_issue:
        return "Active"
    return mapped


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
    if pd.isna(current) or not _has_usable_date(current):
        if pd.isna(current):
            repairs[field] = cand
            repairs[f"{field}_FLAG"] = "FILLED"
        else:
            repairs[field] = cand
            repairs[f"{field}_FLAG"] = "FIXED"
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


# ── Per-record repair ────────────────────────────────────────────────────────

def _repair_record(row, d: dict, repairs: dict) -> None:
    expected = _expected_status(d)
    effective_status = _apply_status(repairs, row["STATUS_NORMALIZED"], expected)

    file_dt = _file_date(d)
    issue = _issue_date(d)
    final = _final_date(d)

    # FILE_DATE ← earliest early Review Start/Completion (≤ Issue).
    if _present(file_dt):
        _apply_date(repairs, row, "FILE_DATE", file_dt)
    elif pd.notna(row["FILE_DATE"]):
        # No application-source Review date: upstream often stored Issue
        # Permit Card Completion / Issue Date as FILE_DATE.
        _clear_date(repairs, row, "FILE_DATE")

    # PERMIT_DATE ← Issue Date for issued lifecycles.
    if effective_status == "In Review":
        _clear_date(repairs, row, "PERMIT_DATE")
    elif _present(issue) and effective_status in ("Active", "Final", "Inactive"):
        _apply_date(repairs, row, "PERMIT_DATE", issue)
    elif pd.notna(row["PERMIT_DATE"]) and not _has_usable_date(row["PERMIT_DATE"]):
        _clear_date(repairs, row, "PERMIT_DATE")

    # FINAL_DATE ← latest Pass inspection for Final only.
    if effective_status == "Final":
        if _present(final):
            _apply_date(repairs, row, "FINAL_DATE", final)
        elif pd.notna(row["FINAL_DATE"]) and not _has_usable_date(row["FINAL_DATE"]):
            _clear_date(repairs, row, "FINAL_DATE")
    else:
        _clear_date(repairs, row, "FINAL_DATE")


# ── Main entry point ─────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Navasota permit records using the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Navasota". Must contain
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
        if d is None or schema in ("missing", "unknown"):
            continue

        repairs: dict = {}
        _repair_record(row, d, repairs)

        for key, value in repairs.items():
            out.at[idx, key] = value

    for col in ("FILE_DATE", "PERMIT_DATE", "FINAL_DATE"):
        out[col] = pd.to_datetime(out[col], errors="coerce")

    return out


# ── CLI: run standalone to preview repair stats ─────────────────────────────

if __name__ == "__main__":
    import os
    from pathlib import Path

    from dotenv import load_dotenv

    repo_root = Path(__file__).resolve().parents[3]
    load_dotenv(repo_root / ".env")
    my_data_path = os.getenv("MY_DATA_PATH")
    agent_data_path = os.getenv("AGENT_DATA_PATH")
    filepath = os.path.join(my_data_path, "processed_data", "permits_tx_sample.parquet")
    df = pd.read_parquet(filepath)
    city = df[
        (df["JURISDICTION"] == "Navasota") & (df["STATE"] == "TX")
    ].copy()

    print(f"Navasota records: {len(city):,}\n")
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
        print(
            f"  Missing before: {before_missing:>4,}   "
            f"Missing after: {after_missing:>4,}"
        )
        print()

    print("STATUS_NORMALIZED distribution:")
    print("  Before:")
    for s, c in city["STATUS_NORMALIZED"].value_counts(dropna=False).items():
        print(f"    {str(s):15s}: {c:>4,}")
    print("  After:")
    for s, c in repaired["STATUS_NORMALIZED"].value_counts(dropna=False).items():
        print(f"    {str(s):15s}: {c:>4,}")

    print("\nSTATUS changes:")
    changed = city["STATUS_NORMALIZED"].fillna("__NA__") != repaired[
        "STATUS_NORMALIZED"
    ].fillna("__NA__")
    if changed.any():
        tmp = pd.DataFrame(
            {
                "before": city.loc[changed, "STATUS_NORMALIZED"].fillna("__NA__"),
                "after": repaired.loc[changed, "STATUS_NORMALIZED"].fillna("__NA__"),
            }
        )
        print(tmp.value_counts().to_string())
    else:
        print("  (none)")

    print("\nCoverage by STATUS_NORMALIZED (after):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        if len(sub) == 0:
            continue
        for field in ["FILE_DATE", "PERMIT_DATE", "FINAL_DATE"]:
            n_has = sub[field].notna().sum()
            print(
                f"  {status:12s} {field:12s}: "
                f"{n_has:>4,} / {len(sub):>4,} "
                f"({n_has / len(sub):.1%})"
            )

    f = repaired["FILE_DATE"]
    p = repaired["PERMIT_DATE"]
    fin = repaired["FINAL_DATE"]
    fp = ((f.notna()) & (p.notna()) & (f.dt.normalize() > p.dt.normalize())).sum()
    pf = ((p.notna()) & (fin.notna()) & (p.dt.normalize() > fin.dt.normalize())).sum()
    ff = ((f.notna()) & (fin.notna()) & (f.dt.normalize() > fin.dt.normalize())).sum()
    print(
        f"\nDate-order violations: FILE>PERMIT={fp}, "
        f"PERMIT>FINAL={pf}, FILE>FINAL={ff}"
    )

    # Ideal coverage checks
    af = repaired[repaired["STATUS_NORMALIZED"].isin(["Active", "Final"])]
    print(
        f"\nActive/Final PERMIT_DATE: "
        f"{af['PERMIT_DATE'].notna().sum()}/{len(af)}"
    )
    fin_rows = repaired[repaired["STATUS_NORMALIZED"] == "Final"]
    print(
        f"Final FINAL_DATE: "
        f"{fin_rows['FINAL_DATE'].notna().sum()}/{len(fin_rows)}"
    )
    print(
        f"FILE_DATE overall: "
        f"{repaired['FILE_DATE'].notna().sum()}/{len(repaired)}"
    )

    if agent_data_path:
        out_dir = Path(agent_data_path) / "repaired"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "permits_tx_navasota_repaired.parquet"
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote repaired sample → {out_path}")

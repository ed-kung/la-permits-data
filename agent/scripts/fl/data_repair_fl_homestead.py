"""Data repair for Homestead (FL) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Homestead DATA is a single flat portal schema (all 2,000 sample rows share
the same top-level keys):

  apply_date, issue_date, permit_status, permit_number, permit_type,
  permit_address, folio_number, owner_*, general_contractor_name,
  plan_review (list), inspection_review (list)

Canonical mappings:
  - permit_status (+ issue_date for OPEN / HOLD) → STATUS_NORMALIZED
  - apply_date                                   → FILE_DATE
  - issue_date                                   → PERMIT_DATE
  - latest successful FINAL* inspection date,
    else latest successful inspection date       → FINAL_DATE

INFERRED_SCHEMA is ``homestead_{status_slug}_{date_profile}`` where
date_profile is one of issued_finalable / issued / applied / status_only.

Known issues repaired:
  - OPEN / HOLD rows with a real issue_date labeled In Review → FIXED
    to Active (issued, not yet closed).
  - All Final rows missing FINAL_DATE → FILLED from inspection_review
    when a PASSED inspection date exists (~1,536 / 1,728). When the
    latest PASSED date precedes issue_date (portal quirk on ~18 rows),
    FINAL_DATE is clamped to issue_date so PERMIT_DATE ≤ FINAL_DATE.

Not repairable from DATA:
  - issue_date is "-" on 299 rows (141 Final CLOSED, mostly SHOP DRAWING /
    REVISION / GARAGE SALE shells with empty or PENDING-only inspections)
    → PERMIT_DATE stays missing; FINAL_DATE also stays missing when no
    PASSED inspection date exists (~192 Final rows).
  - FILE_DATE already matches apply_date for every sample row.
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

_SUCCESS_RESULTS = {
    "PASSED",
    "APPROVED",
    "APPROVED WITH EXCEPTION",
    "SATISFACTORY",
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
        if not s or s in {"-", "--"}:
            return pd.NaT
        if s.upper() in {
            "TBD", "NULL", "NONE", "N/A", "NA", "NAN",
            "00/00/0000", "0/0/0000",
        }:
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


def _slug(text: Optional[str]) -> str:
    if text is None:
        return "none"
    s = re.sub(r"[^a-z0-9]+", "_", str(text).strip().lower()).strip("_")
    return s or "none"


def _apply_status(repairs: dict, current, expected: Optional[str]) -> Optional[str]:
    """Apply expected STATUS_NORMALIZED; return effective status."""
    if expected is None:
        if pd.isna(current):
            return None
        return current

    if pd.isna(current):
        repairs["STATUS_NORMALIZED"] = expected
        repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"
    elif current != expected:
        repairs["STATUS_NORMALIZED"] = expected
        repairs["STATUS_NORMALIZED_FLAG"] = "FIXED"

    return repairs.get("STATUS_NORMALIZED", current)


def _apply_date(repairs: dict, row, field: str, candidate) -> None:
    """Fill or fix *field* from *candidate* datetime (pd.NaT = no candidate)."""
    cand = _safe_to_datetime(candidate)
    if not _present(cand):
        return

    current = row[field]
    if pd.isna(current):
        repairs[field] = cand
        repairs[f"{field}_FLAG"] = "FILLED"
    elif not _dates_equal(current, cand):
        repairs[field] = cand
        repairs[f"{field}_FLAG"] = "FIXED"


def _clear_date(repairs: dict, row, field: str) -> None:
    """Clear a spurious date value."""
    current = repairs.get(field, row[field])
    if pd.isna(current):
        return
    repairs[field] = pd.NaT
    repairs[f"{field}_FLAG"] = "FIXED"


# ── Schema classification ────────────────────────────────────────────────────

def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    if not isinstance(data_dict, dict):
        return "unknown"
    if not data_dict:
        return "empty"

    keys = set(data_dict.keys())
    if "permit_status" not in keys or "apply_date" not in keys:
        return "unknown"

    status = _slug(data_dict.get("permit_status"))
    apply = _safe_to_datetime(data_dict.get("apply_date"))
    issue = _safe_to_datetime(data_dict.get("issue_date"))
    final_cand = _final_date_from_inspections(data_dict.get("inspection_review"))

    if _present(issue) and _present(final_cand):
        profile = "issued_finalable"
    elif _present(issue):
        profile = "issued"
    elif _present(apply):
        profile = "applied"
    else:
        profile = "status_only"

    return f"homestead_{status}_{profile}"


# ── Status mapping ───────────────────────────────────────────────────────────

_STATUS_MAP = {
    "CLOSED": "Final",
    "EXPIRED": "Inactive",
    "VOIDED": "Inactive",
    "REJECTED": "Inactive",
    # OPEN / HOLD depend on whether issue_date is present — handled below.
    "OPEN": "In Review",
    "HOLD": "In Review",
}


def _expected_status(d: dict) -> Optional[str]:
    raw = d.get("permit_status")
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None

    upper = text.upper()
    issue = _safe_to_datetime(d.get("issue_date"))

    # Issued but not closed → Active (upstream left these as In Review).
    if upper in {"OPEN", "HOLD"} and _present(issue):
        return "Active"

    if upper in _STATUS_MAP:
        return _STATUS_MAP[upper]
    return _STATUS_MAP.get(text)


# ── Date extractors ──────────────────────────────────────────────────────────

def _is_final_inspection_name(name: str) -> bool:
    upper = str(name or "").upper()
    if "FINAL" in upper:
        return True
    if "CO SIGN" in upper or "C.O" in upper:
        return True
    if "CERTIFICATE" in upper:
        return True
    return False


def _inspection_dt(insp: dict):
    """Prefer Inspection Date; fall back to Scheduled Date."""
    dt = _safe_to_datetime(insp.get("Inspection Date"))
    if _present(dt):
        return dt
    return _safe_to_datetime(insp.get("Scheduled Date"))


def _final_date_from_inspections(insp_review) -> pd.Timestamp:
    """Latest successful FINAL/CO date; else latest successful inspection."""
    if not isinstance(insp_review, list):
        return pd.NaT

    final_dates = []
    passed_dates = []
    for insp in insp_review:
        if not isinstance(insp, dict):
            continue
        result = str(insp.get("Inspection Status") or "").strip().upper()
        if result not in _SUCCESS_RESULTS:
            continue
        dt = _inspection_dt(insp)
        if not _present(dt):
            continue
        header = insp.get("inspection_header")
        if _is_final_inspection_name(header):
            final_dates.append(dt)
        else:
            passed_dates.append(dt)

    if final_dates:
        return max(final_dates)
    if passed_dates:
        return max(passed_dates)
    return pd.NaT


# ── Per-record repair ────────────────────────────────────────────────────────

def _repair_record(row, d: dict, repairs: dict) -> None:
    expected = _expected_status(d)
    effective_status = _apply_status(repairs, row["STATUS_NORMALIZED"], expected)

    apply = _safe_to_datetime(d.get("apply_date"))
    issue = _safe_to_datetime(d.get("issue_date"))

    # FILE_DATE ← apply_date (fallback issue_date if apply somehow blank)
    file_src = apply if _present(apply) else issue
    if _present(file_src):
        _apply_date(repairs, row, "FILE_DATE", file_src)

    # PERMIT_DATE ← issue_date for issued / completed / expired statuses.
    if _present(issue):
        if effective_status in ("Active", "Final", "Inactive"):
            _apply_date(repairs, row, "PERMIT_DATE", issue)
        elif effective_status == "In Review":
            # Pre-issuance In Review should not carry an issuance stamp.
            _clear_date(repairs, row, "PERMIT_DATE")
    else:
        if effective_status == "In Review":
            _clear_date(repairs, row, "PERMIT_DATE")

    # FINAL_DATE ← inspection-derived close stamp for Final only.
    # Clamp to issue_date when the portal recorded a PASSED inspection
    # before formal issuance (18 sample rows; keeps PERMIT ≤ FINAL).
    if effective_status == "Final":
        final_src = _final_date_from_inspections(d.get("inspection_review"))
        if _present(final_src) and _present(issue):
            if pd.Timestamp(final_src).normalize() < pd.Timestamp(issue).normalize():
                final_src = issue
        if _present(final_src):
            _apply_date(repairs, row, "FINAL_DATE", final_src)
    else:
        _clear_date(repairs, row, "FINAL_DATE")


# ── Main entry point ─────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Homestead permit records using information from the raw DATA JSON.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Homestead". Must contain
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
        if d is None or schema in {"missing", "unknown", "empty"}:
            continue

        repairs: dict = {}
        _repair_record(row, d, repairs)

        for key, value in repairs.items():
            out.at[idx, key] = value

    for col in ("FILE_DATE", "PERMIT_DATE", "FINAL_DATE"):
        out[col] = pd.to_datetime(out[col], errors="coerce")

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
        (df["JURISDICTION"] == "Homestead") & (df["STATE"] == "FL")
    ].copy()

    print(f"Homestead records: {len(city):,}\n")
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

    print("\nSTATUS_NORMALIZED transitions (before → after):")
    transitions = (
        pd.DataFrame({
            "before": city["STATUS_NORMALIZED"].astype("object"),
            "after": repaired["STATUS_NORMALIZED"].astype("object"),
        })
        .groupby(["before", "after"], dropna=False)
        .size()
        .reset_index(name="n")
    )
    changed = transitions[
        transitions["before"].astype(str) != transitions["after"].astype(str)
    ]
    print(changed.sort_values("n", ascending=False).to_string(index=False))

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
    ).sum()
    print(f"\nPERMIT_DATE > FINAL_DATE inversions after repair: {n_inv}")

    fd = repaired["FILE_DATE"]
    pd_ = repaired["PERMIT_DATE"]
    both_fp = repaired[fd.notna() & pd_.notna()]
    n_fp_inv = (
        both_fp["FILE_DATE"].dt.normalize() > both_fp["PERMIT_DATE"].dt.normalize()
    ).sum()
    print(f"FILE_DATE > PERMIT_DATE inversions after repair: {n_fp_inv}")

    still_null = repaired[repaired["STATUS_NORMALIZED"].isna()]
    print(f"\nRemaining null STATUS_NORMALIZED: {len(still_null):,}")

    # Sanity: PERMIT_DATE should match issue_date when present
    n_issue_mismatch = 0
    n_issue = 0
    for idx in repaired.index:
        d = _safe_parse(repaired.at[idx, "DATA"]) or {}
        issue = _safe_to_datetime(d.get("issue_date"))
        if not _present(issue):
            continue
        n_issue += 1
        status = repaired.at[idx, "STATUS_NORMALIZED"]
        if status in ("Active", "Final", "Inactive"):
            if not _dates_equal(repaired.at[idx, "PERMIT_DATE"], issue):
                n_issue_mismatch += 1
    print(
        f"Active/Final/Inactive PERMIT_DATE != issue_date: "
        f"{n_issue_mismatch} (of {n_issue} with issue_date)"
    )

    print(f"\nAny missing FILE_DATE: {repaired['FILE_DATE'].isna().sum()}")
    active_final = repaired["STATUS_NORMALIZED"].isin(["Active", "Final"])
    final = repaired["STATUS_NORMALIZED"] == "Final"
    print(
        f"Active/Final missing PERMIT_DATE: "
        f"{(active_final & repaired['PERMIT_DATE'].isna()).sum()}"
    )
    print(f"Final missing FINAL_DATE: {(final & repaired['FINAL_DATE'].isna()).sum()}")

    # Residual FILE mismatches vs apply_date
    n_file_mm = 0
    for idx in repaired.index:
        d = _safe_parse(repaired.at[idx, "DATA"]) or {}
        app_date = _safe_to_datetime(d.get("apply_date"))
        if _present(app_date) and not pd.isna(repaired.at[idx, "FILE_DATE"]):
            if not _dates_equal(repaired.at[idx, "FILE_DATE"], app_date):
                n_file_mm += 1
    print(f"FILE_DATE != apply_date (when both present): {n_file_mm}")

    if agent_data_path:
        out_dir = Path(agent_data_path) / "repaired"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "permits_fl_homestead_repaired.parquet"
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote repaired sample → {out_path}")

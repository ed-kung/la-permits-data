"""Data repair for Orange Park (FL) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Orange Park DATA is a city-portal payload in the same family as Mascotte /
Haines City / Indian River Shores, but the sample scrape is unusually
sparse: top-level ``Request Date`` / ``Request #`` / ``permit_id`` /
``Status`` / project fields are present, while nested ``inspections``,
``reviews`` / ``plan_reviews``, ``fees``, and ``payments`` are always
empty. There is no ``Permit Date`` / Issue / Final Inspection Date field.

Canonical mappings:
  - DATA["Status"] (+ blank + passed FINAL-ish inspection → Final)
                                           → STATUS_NORMALIZED
  - DATA["Request Date"]                   → FILE_DATE
    (application / submittal stamp — present on every sample row)
  - Latest approved review completed_date
    (Building* preferred; never Request Date)
                                           → PERMIT_DATE
  - Latest passed FINAL-ish inspection
    completed_date                         → FINAL_DATE

Key-set variants (INFERRED_SCHEMA prefixes):
  - city_portal:              reviews present, no plan_reviews
  - city_portal_plan_reviews: plan_reviews, no record_type box
  - city_portal_record_type:  plan_reviews + record_type_from_contractor_box
  - city_portal_minimal:      neither reviews nor plan_reviews

Content suffixes further split by which canonical dates are recoverable
(``_issued_finaled``, ``_issued``, ``_finaled``, ``_applied``,
``_status_only``).

Known issues repaired:
  - STATUS_NORMALIZED / STATUS_ORIGINAL entirely null upstream → FILLED
    for the minority of rows with a non-blank DATA Status (Open /
    Complete / Closed / Awaiting Schedule).
  - FILE_DATE entirely null → FILLED from Request Date for all rows
    with a usable stamp.
  - Spurious PERMIT_DATE / FINAL_DATE on non-qualifying statuses cleared
    if present (none in the current sample).

Not repairable from DATA:
  - ~1,835 blank-Status shells with empty inspections → STATUS_NORMALIZED
    stays missing.
  - No Issue / Approved / review-completion stamp in the sample →
    PERMIT_DATE stays missing for Active / Final.
  - Empty inspections and no Final Inspection Date → FINAL_DATE stays
    missing for Final rows.
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
    r"final|fnl|certificate|\bco\b|\bcc\b|\bcoc\b|\bcofc\b",
    re.IGNORECASE,
)

_PASS_STATUS_FRAGMENTS = (
    "approved",
    "pass",
    "private provider",
    "completed",
    "complete",
    "final -",
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
        if s in {"01/01/1900", "1/1/1900", "01/01/0001"}:
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
    da = _safe_to_datetime(a)
    db = _safe_to_datetime(b)
    if da is pd.NaT or db is pd.NaT or pd.isna(da) or pd.isna(db):
        return False
    return pd.Timestamp(da).normalize() == pd.Timestamp(db).normalize()


def _present(dt) -> bool:
    return dt is not pd.NaT and not pd.isna(dt)


def _has_usable_date(val) -> bool:
    return _present(_safe_to_datetime(val))


def _norm_text(val) -> str:
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return ""
    return str(val).strip()


def _review_lists(d: dict) -> list:
    out = []
    for key in ("reviews", "plan_reviews"):
        val = d.get(key)
        if isinstance(val, list):
            out.extend(val)
    return out


def _is_approved_review(status: str) -> bool:
    st = (status or "").lower()
    if "reject" in st or "fail" in st or "denied" in st:
        return False
    return "approv" in st


def _is_building_review(review_type: str) -> bool:
    return "building" in (review_type or "").lower()


# ── Field extractors ─────────────────────────────────────────────────────────

def _file_date(d: dict):
    """Application / submittal stamp.

    Orange Park uses top-level Request Date (no Permit Date field in the
    sample). Fall back to Permit Date for schema-compatible shells.
    """
    rd = _safe_to_datetime(d.get("Request Date"))
    if _present(rd):
        return rd
    return _safe_to_datetime(d.get("Permit Date"))


def _permit_date(d: dict):
    """Latest approved review completion stamp.

    Prefer Building* approvals when present. Never use Request Date /
    Permit Date (application stamps).
    """
    reviews = _review_lists(d)
    building_completed = []
    nonpayment_completed = []
    approved_completed = []
    approved_fallback = []

    for r in reviews:
        if not isinstance(r, dict):
            continue
        status = _norm_text(r.get("status"))
        if not _is_approved_review(status):
            continue
        rtype = _norm_text(r.get("review_type"))
        completed = _safe_to_datetime(r.get("completed_date"))
        if _present(completed):
            approved_completed.append(completed)
            if "payment" not in rtype.lower():
                nonpayment_completed.append(completed)
            if _is_building_review(rtype):
                building_completed.append(completed)
            continue
        if "payment" in rtype.lower():
            continue
        for key in ("date", "review_date"):
            dt = _safe_to_datetime(r.get(key))
            if _present(dt):
                approved_fallback.append(dt)
                break

    if building_completed:
        return max(building_completed)
    if nonpayment_completed:
        return max(nonpayment_completed)
    if approved_completed:
        return max(approved_completed)
    if approved_fallback:
        return max(approved_fallback)
    return pd.NaT


def _final_from_inspections(d: dict):
    """Latest completed_date among approved/passed final-ish inspections."""
    inspections = d.get("inspections")
    if not isinstance(inspections, list):
        return pd.NaT
    best = pd.NaT
    for insp in inspections:
        if not isinstance(insp, dict):
            continue
        itype = str(insp.get("inspection_type") or "")
        if not _FINAL_INSP_RE.search(itype):
            continue
        status = str(insp.get("status") or "").lower()
        if not any(frag in status for frag in _PASS_STATUS_FRAGMENTS):
            continue
        if "cancel" in status or "fail" in status or "pending" in status:
            continue
        dt = _safe_to_datetime(insp.get("completed_date"))
        if not _present(dt):
            continue
        if not _present(best) or dt > best:
            best = dt
    return best


def _has_passed_final_inspection(d: dict, require_date: bool = False) -> bool:
    inspections = d.get("inspections")
    if not isinstance(inspections, list):
        return False
    for insp in inspections:
        if not isinstance(insp, dict):
            continue
        itype = str(insp.get("inspection_type") or "")
        if not _FINAL_INSP_RE.search(itype):
            continue
        status = str(insp.get("status") or "").lower()
        if not any(frag in status for frag in _PASS_STATUS_FRAGMENTS):
            continue
        if "cancel" in status or "fail" in status or "pending" in status:
            continue
        if require_date and not _present(_safe_to_datetime(insp.get("completed_date"))):
            continue
        return True
    return False


def _final_date(d: dict):
    fid = _safe_to_datetime(d.get("Final Inspection Date"))
    if _present(fid):
        return fid
    return _final_from_inspections(d)


# ── Schema classification ────────────────────────────────────────────────────

def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())
    # Orange Park shells carry Request Date + permit_id; sibling portals
    # use Permit Date / Permit Number.
    if (
        "Request Date" not in keys
        and "Permit Date" not in keys
        and "Permit Number" not in keys
        and "permit_id" not in keys
    ):
        return "unknown"

    if "record_type_from_contractor_box" in keys:
        base = "city_portal_record_type"
    elif "plan_reviews" in keys:
        base = "city_portal_plan_reviews"
    elif "reviews" in keys:
        base = "city_portal"
    else:
        base = "city_portal_minimal"

    has_file = _present(_file_date(data_dict))
    has_issue = _present(_permit_date(data_dict))
    has_final = _present(_final_date(data_dict))

    if has_issue and has_final:
        return f"{base}_issued_finaled"
    if has_issue:
        return f"{base}_issued"
    if has_final:
        return f"{base}_finaled"
    if has_file:
        return f"{base}_applied"
    return f"{base}_status_only"


# ── Status mapping ───────────────────────────────────────────────────────────

# Open → Active: sibling city portals (e.g. Indian River Shores) use Open /
# OPEN for issued/active work; pre-issuance here is Awaiting Schedule.
_STATUS_MAP = {
    "open": "Active",
    "issued": "Active",
    "issued / work started": "Active",
    "approved": "Active",
    "complete": "Final",
    "completed": "Final",
    "closed": "Final",
    "final": "Final",
    "final / completed": "Final",
    "awaiting schedule": "In Review",
    "in review": "In Review",
    "pending": "In Review",
    "waiting payment": "In Review",
    "void": "Inactive",
    "expired": "Inactive",
    "denied": "Inactive",
    "canceled": "Inactive",
    "cancelled": "Inactive",
    "withdrawn": "Inactive",
}


def _expected_status(row, d: dict) -> Optional[str]:
    """Infer STATUS_NORMALIZED from DATA Status + inspection overrides."""
    raw = _norm_text(d.get("Status")).lower()
    orig = _norm_text(row.get("STATUS_ORIGINAL")).lower()
    mapped = _STATUS_MAP.get(raw) or _STATUS_MAP.get(orig)

    # Blank Status: only infer Final from a dated passed FINAL-ish
    # inspection (sample has none today).
    if not raw:
        if _has_passed_final_inspection(d, require_date=True):
            return "Final"
        return None

    if mapped != "Inactive":
        if _present(_safe_to_datetime(d.get("Final Inspection Date"))):
            return "Final"
        if mapped in ("Active", "Final") and _has_passed_final_inspection(
            d, require_date=False
        ):
            return "Final"

    if mapped is not None:
        return mapped
    return None


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
    expected = _expected_status(row, d)
    effective_status = _apply_status(repairs, row["STATUS_NORMALIZED"], expected)

    file_dt = _file_date(d)
    issue_dt = _permit_date(d)
    final_dt = _final_date(d)

    # -- FILE_DATE --
    if not _has_usable_date(row["FILE_DATE"]):
        _apply_date(repairs, row, "FILE_DATE", file_dt)
    elif _present(file_dt) and not _dates_equal(row["FILE_DATE"], file_dt):
        _apply_date(repairs, row, "FILE_DATE", file_dt)

    # -- PERMIT_DATE --
    # Never copy Request Date / Permit Date into PERMIT_DATE.
    if effective_status in ("Active", "Final"):
        if _has_usable_date(row["PERMIT_DATE"]):
            if _present(issue_dt) and not _dates_equal(row["PERMIT_DATE"], issue_dt):
                _apply_date(repairs, row, "PERMIT_DATE", issue_dt)
        else:
            if not pd.isna(row["PERMIT_DATE"]) and not _has_usable_date(row["PERMIT_DATE"]):
                if _present(issue_dt):
                    _apply_date(repairs, row, "PERMIT_DATE", issue_dt)
                else:
                    _clear_date(repairs, row, "PERMIT_DATE")
            else:
                _apply_date(repairs, row, "PERMIT_DATE", issue_dt)
    else:
        if not pd.isna(row["PERMIT_DATE"]):
            _clear_date(repairs, row, "PERMIT_DATE")

    # -- FINAL_DATE --
    if effective_status == "Final":
        if _has_usable_date(row["FINAL_DATE"]):
            if _present(final_dt) and not _dates_equal(row["FINAL_DATE"], final_dt):
                supporting = [
                    _safe_to_datetime(d.get("Final Inspection Date")),
                    _final_from_inspections(d),
                ]
                if not any(
                    _present(s) and _dates_equal(row["FINAL_DATE"], s)
                    for s in supporting
                ):
                    _apply_date(repairs, row, "FINAL_DATE", final_dt)
        else:
            if not pd.isna(row["FINAL_DATE"]) and not _has_usable_date(row["FINAL_DATE"]):
                if _present(final_dt):
                    _apply_date(repairs, row, "FINAL_DATE", final_dt)
                else:
                    _clear_date(repairs, row, "FINAL_DATE")
            else:
                _apply_date(repairs, row, "FINAL_DATE", final_dt)
    else:
        if not pd.isna(row["FINAL_DATE"]):
            _clear_date(repairs, row, "FINAL_DATE")


# ── Main entry point ─────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Orange Park permit records using information from the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Orange Park".  Must contain
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
        if d is None:
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

    load_dotenv(Path(__file__).resolve().parents[3] / ".env")
    MY_DATA_PATH = os.getenv("MY_DATA_PATH")
    AGENT_DATA_PATH = os.getenv("AGENT_DATA_PATH")
    filepath = os.path.join(
        MY_DATA_PATH, "processed_data", "permits_fl_sample.parquet"
    )
    df = pd.read_parquet(filepath)
    city = df[
        (df["JURISDICTION"] == "Orange Park") & (df["STATE"] == "FL")
    ].copy()

    print(f"Orange Park records: {len(city):,}\n")

    repaired = data_repair(city)

    print("INFERRED_SCHEMA distribution:")
    for s, c in repaired["INFERRED_SCHEMA"].value_counts(dropna=False).items():
        print(f"  {str(s):45s}: {c:>5,}")
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

    print("\nDATA.Status → STATUS_NORMALIZED (after):")
    status_from_data = repaired["DATA"].map(
        lambda x: str((_safe_parse(x) or {}).get("Status") or "").strip() or "__BLANK__"
    )
    ct = (
        pd.DataFrame({
            "DATA_STATUS": status_from_data,
            "STATUS_NORMALIZED": repaired["STATUS_NORMALIZED"],
        })
        .groupby(["DATA_STATUS", "STATUS_NORMALIZED"], dropna=False)
        .size()
        .reset_index(name="n")
        .sort_values("n", ascending=False)
    )
    print(ct.to_string(index=False))

    print("\nFILE_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FILE_DATE"].notna().sum()
        print(
            f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} "
            f"({(n_has / len(sub) if len(sub) else 0):.1%})"
        )
    null_status = repaired[repaired["STATUS_NORMALIZED"].isna()]
    print(
        f"  {'(null)':15s}: {null_status['FILE_DATE'].notna().sum():>4,} / "
        f"{len(null_status):>4,} "
        f"({(null_status['FILE_DATE'].notna().sum() / len(null_status) if len(null_status) else 0):.1%})"
    )

    print("\nPERMIT_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = int(sub["PERMIT_DATE"].map(_has_usable_date).sum()) if len(sub) else 0
        print(
            f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} "
            f"({(n_has / len(sub) if len(sub) else 0):.1%})"
        )

    print("\nFINAL_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = int(sub["FINAL_DATE"].map(_has_usable_date).sum()) if len(sub) else 0
        print(
            f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} "
            f"({(n_has / len(sub) if len(sub) else 0):.1%})"
        )

    # Date-order checks
    file_dt = repaired["FILE_DATE"]
    permit_dt = repaired["PERMIT_DATE"]
    final_dt = repaired["FINAL_DATE"]
    both_fp = file_dt.notna() & permit_dt.notna()
    both_pf = permit_dt.notna() & final_dt.notna()
    both_ff = file_dt.notna() & final_dt.notna()
    print("\nDate-order violations:")
    print(f"  FILE > PERMIT: {(both_fp & (file_dt > permit_dt)).sum()}")
    print(f"  PERMIT > FINAL: {(both_pf & (permit_dt > final_dt)).sum()}")
    print(f"  FILE > FINAL: {(both_ff & (file_dt > final_dt)).sum()}")

    n_file_mm = 0
    n_file_cmp = 0
    for idx in repaired.index:
        d = _safe_parse(repaired.at[idx, "DATA"]) or {}
        rdt = _safe_to_datetime(d.get("Request Date"))
        if not _present(rdt):
            continue
        n_file_cmp += 1
        if not _dates_equal(repaired.at[idx, "FILE_DATE"], rdt):
            n_file_mm += 1
    print(f"\nFILE_DATE != Request Date (when Request Date valid): {n_file_mm} / {n_file_cmp}")

    active_final = repaired["STATUS_NORMALIZED"].isin(["Active", "Final"])
    final = repaired["STATUS_NORMALIZED"] == "Final"
    print(f"Remaining null STATUS_NORMALIZED: {repaired['STATUS_NORMALIZED'].isna().sum():,}")
    print(f"Any missing FILE_DATE: {repaired['FILE_DATE'].isna().sum()}")
    print(
        f"Active/Final missing PERMIT_DATE: "
        f"{(active_final & repaired['PERMIT_DATE'].isna()).sum()}"
    )
    print(f"Final missing FINAL_DATE: {(final & repaired['FINAL_DATE'].isna()).sum()}")

    if AGENT_DATA_PATH:
        out_dir = Path(AGENT_DATA_PATH) / "repaired"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "permits_fl_orange_park_repaired.parquet"
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote {out_path}")

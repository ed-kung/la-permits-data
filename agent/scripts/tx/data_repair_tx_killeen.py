"""Data repair for Killeen (TX) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Killeen DATA is a municipal permit-portal payload with top-level keys
``fees``, ``detail``, ``fees_total``, and (usually) ``insp_status``,
``permit_status``, ``insp_status_detail``, ``permit_status_detail``.
Content variants (INFERRED_SCHEMA):

  - full_portal:   detail + permit_status_detail populated (most rows)
  - detail_only:   detail only; no permit_status / permit_status_detail
                   (unissued REJECTED / PLAN REVIEW shells)
  - missing / unknown

Canonical mappings:
  - permit_status_detail["Status for Permit Number"]
      → STATUS_NORMALIZED
    (detail_only fallback: detail["Application Status"])
  - detail["Application Date"]              → FILE_DATE
    (fallback: permit_status_detail Application Date)
  - permit_status_detail["Issue Date"]      → PERMIT_DATE
    (fallback: "Permit Date" when Issue Date blank)
  - approved BUILDING FINAL / FINAL insp
      → FINAL_DATE (Final status only)
    (fallback: other approved *FINAL* insp excl. TEMPORARY;
     then permit_status_detail["Permit Date"])

Known issues repaired:
  - STATUS_NORMALIZED missing on 15 detail_only rows (REJECTED /
    PLAN REVIEW) → FILLED from Application Status.
  - PERMIT_DATE was taken from "Permit Date". For completed permits
    that field is frequently overwritten with the final / completion
    stamp while Issue Date retains issuance → FIXED to Issue Date
    (509 Final + 69 Active + 8 Inactive in sample).
  - FINAL_DATE on many C.O. ISSUED rows matched an intermediate
    inspection (TEMP POLE, insulation, rough-in) rather than a true
    completion date → FIXED from BUILDING FINAL / FINAL insp or
    Permit Date fallback.
  - Two CLOSED Final rows missing FINAL_DATE → FILLED from Permit Date.

Not repairable / left as-is:
  - FILE_DATE already matches Application Date on every sample row.
  - Application Status disagreements with permit status (e.g. CLOSED /
    EXPIRED / ON HOLD while Status for Permit Number remains
    PERMIT PRINTED) — permit status is treated as authoritative,
    consistent with STATUS_ORIGINAL.
  - Active PERMIT PRINTED rows that already have an approved BUILDING
    FINAL are left Active (portal status authoritative); FINAL_DATE
    stays empty for non-Final.
"""

from __future__ import annotations

import json
import math
from typing import Optional

import numpy as np
import pandas as pd


_MIN_YEAR = 1900
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
        try:
            parsed = json.loads(data)
        except (json.JSONDecodeError, TypeError):
            return None
        return parsed if isinstance(parsed, dict) else None
    return data if isinstance(data, dict) else None


def _safe_to_datetime(val):
    """Parse a date value, returning pd.NaT on failure / blanks / sentinels."""
    if val is None:
        return pd.NaT
    if isinstance(val, float) and math.isnan(val):
        return pd.NaT
    if not isinstance(val, str) and pd.isna(val):
        return pd.NaT
    if isinstance(val, dict):
        return pd.NaT
    text = str(val).strip()
    if not text or text.upper() in {
        "TBD", "NONE", "N/A", "NA", "NULL", "NAN",
        "00/00/0000", "0/0/0000",
    }:
        return pd.NaT
    try:
        dt = pd.to_datetime(val, errors="coerce")
    except (ValueError, TypeError, OverflowError):
        return pd.NaT
    if pd.isna(dt):
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
    if da is pd.NaT or db is pd.NaT or pd.isna(da) or pd.isna(db):
        return False
    return pd.Timestamp(da).normalize() == pd.Timestamp(db).normalize()


def _detail(d: dict) -> dict:
    detail = d.get("detail")
    return detail if isinstance(detail, dict) else {}


def _permit_status_detail(d: dict) -> dict:
    psd = d.get("permit_status_detail")
    return psd if isinstance(psd, dict) else {}


def _classify_schema(d: Optional[dict]) -> str:
    if d is None:
        return "missing"
    has_psd = bool(_permit_status_detail(d))
    has_detail = bool(_detail(d))
    if has_psd and has_detail:
        return "full_portal"
    if has_detail and not has_psd:
        return "detail_only"
    if has_psd:
        return "permit_status_only"
    return "unknown"


# ── Status mapping ───────────────────────────────────────────────────────────

# permit_status_detail["Status for Permit Number"] → STATUS_NORMALIZED
_PERMIT_STATUS_MAP = {
    "PERMIT PRINTED": "Active",
    "FINAL INSPECTION COMPLETE": "Final",
    "C.O. ISSUED": "Final",
    "CLOSED": "Final",
    "TO BE ISSUED": "In Review",
    "PLAN CHECK": "In Review",
    "PERMIT REVOKED": "Inactive",
}

# detail["Application Status"] → STATUS_NORMALIZED (detail_only fallback)
_APP_STATUS_MAP = {
    "REJECTED": "Inactive",
    "WITHDRAWN": "Inactive",
    "EXPIRED": "Inactive",
    "PLAN REVIEW": "In Review",
    "APPROVED": "In Review",
    "ON HOLD": "In Review",
    "TO BE ISSUED": "In Review",
    "PERMIT ISSUED": "Active",
    "CERTIFICATE OF OCCUPANCY": "Final",
    "CLOSED": "Final",
}


def _normalize_key(val) -> str:
    if val is None:
        return ""
    return str(val).strip().upper()


def _expected_status(d: dict) -> Optional[str]:
    """Prefer Status for Permit Number; else Application Status."""
    psd = _permit_status_detail(d)
    pst = _normalize_key(psd.get("Status for Permit Number"))
    if pst in _PERMIT_STATUS_MAP:
        return _PERMIT_STATUS_MAP[pst]

    app = _normalize_key(_detail(d).get("Application Status"))
    if app in _APP_STATUS_MAP:
        return _APP_STATUS_MAP[app]
    return None


# ── Date candidates ──────────────────────────────────────────────────────────

def _file_date_candidate(d: dict):
    """Prefer detail Application Date; else permit_status_detail."""
    detail = _detail(d)
    psd = _permit_status_detail(d)
    applied = _safe_to_datetime(detail.get("Application Date"))
    if applied is not pd.NaT and not pd.isna(applied):
        return applied
    return _safe_to_datetime(psd.get("Application Date"))


def _permit_date_candidate(d: dict):
    """Prefer Issue Date (issuance); fall back to Permit Date."""
    psd = _permit_status_detail(d)
    issued = _safe_to_datetime(psd.get("Issue Date"))
    if issued is not pd.NaT and not pd.isna(issued):
        return issued
    return _safe_to_datetime(psd.get("Permit Date"))


def _is_approved_result(result) -> bool:
    text = str(result or "").strip().upper()
    if not text:
        return False
    return text.startswith("APPROVED")


def _inspection_completed_date(item: list):
    """insp_status_detail rows are [name, scheduled?, result, completed?]."""
    if len(item) > 3:
        completed = _safe_to_datetime(item[3])
        if completed is not pd.NaT and not pd.isna(completed):
            return completed
    if len(item) > 1:
        return _safe_to_datetime(item[1])
    return pd.NaT


def _last_completion_inspection_date(d: dict):
    """Latest approved BUILDING FINAL / FINAL; else other *FINAL* (not TEMP)."""
    preferred = []
    other = []
    for item in d.get("insp_status_detail") or []:
        if not isinstance(item, list) or len(item) < 3:
            continue
        if not _is_approved_result(item[2]):
            continue
        name = str(item[0] or "").strip().upper()
        if not name or "FINAL" not in name:
            continue
        if "TEMPORARY" in name:
            continue
        dt = _inspection_completed_date(item)
        if dt is pd.NaT or pd.isna(dt):
            continue
        if name in {"BUILDING FINAL", "FINAL"}:
            preferred.append(dt)
        else:
            other.append(dt)
    if preferred:
        return max(preferred)
    if other:
        return max(other)
    return pd.NaT


def _final_date_candidate(d: dict):
    """Prefer approved final inspection; else Permit Date completion stamp."""
    insp = _last_completion_inspection_date(d)
    if insp is not pd.NaT and not pd.isna(insp):
        return insp
    return _safe_to_datetime(_permit_status_detail(d).get("Permit Date"))


# ── Apply helpers ────────────────────────────────────────────────────────────

def _apply_status(repairs: dict, current, expected: Optional[str]):
    """Apply expected STATUS_NORMALIZED; return effective status."""
    if expected is None:
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
    if cand is pd.NaT or pd.isna(cand):
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


# ── Per-row repair ───────────────────────────────────────────────────────────

def _repair_row(row, d: dict, repairs: dict) -> None:
    """Repair one Killeen full_portal / detail_only record."""
    expected = _expected_status(d)
    effective_status = _apply_status(repairs, row["STATUS_NORMALIZED"], expected)

    _apply_date(repairs, row, "FILE_DATE", _file_date_candidate(d))
    _apply_date(repairs, row, "PERMIT_DATE", _permit_date_candidate(d))

    if effective_status == "Final":
        _apply_date(repairs, row, "FINAL_DATE", _final_date_candidate(d))
    else:
        _clear_date(repairs, row, "FINAL_DATE")


# ── Main entry point ─────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Killeen permit records using the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Killeen".  Must contain
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
        if schema in {"full_portal", "detail_only", "permit_status_only"}:
            _repair_row(row, d, repairs)

        for key, value in repairs.items():
            out.at[idx, key] = value

    return out


# ── CLI: run standalone to preview repair stats ─────────────────────────────

if __name__ == "__main__":
    import os

    from dotenv import load_dotenv

    load_dotenv("/Users/ekung/projects/la-permits-data/.env")
    MY_DATA_PATH = os.getenv("MY_DATA_PATH")
    AGENT_DATA_PATH = os.getenv("AGENT_DATA_PATH")
    filepath = os.path.join(MY_DATA_PATH, "processed_data", "permits_tx_sample.parquet")
    df = pd.read_parquet(filepath)
    city = df[(df["JURISDICTION"] == "Killeen") & (df["STATE"] == "TX")].copy()

    print(f"Killeen records: {len(city):,}\n")

    repaired = data_repair(city)

    print("INFERRED_SCHEMA distribution:")
    for s, c in repaired["INFERRED_SCHEMA"].value_counts(dropna=False).items():
        print(f"  {str(s):40s}: {c:>4,}")
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

    print("\nFILE_DATE overall (after): "
          f"{repaired['FILE_DATE'].notna().sum()}/{len(repaired)}")

    print("\nPERMIT_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        if len(sub) == 0:
            continue
        n_has = sub["PERMIT_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({n_has / len(sub):.1%})")

    print("\nFINAL_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        if len(sub) == 0:
            continue
        n_has = sub["FINAL_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({n_has / len(sub):.1%})")

    fin = repaired[repaired["STATUS_NORMALIZED"] == "Final"]
    print(f"\nFinal still missing FINAL_DATE: {fin['FINAL_DATE'].isna().sum()}")
    print(f"Final still missing PERMIT_DATE: {fin['PERMIT_DATE'].isna().sum()}")
    act = repaired[repaired["STATUS_NORMALIZED"] == "Active"]
    print(f"Active still missing PERMIT_DATE: {act['PERMIT_DATE'].isna().sum()}")

    still_null = repaired[repaired["STATUS_NORMALIZED"].isna()]
    print(f"\nSTATUS still null: {len(still_null)}")

    # Sanity: PERMIT_DATE should now match Issue Date when present
    n_match_issue = 0
    n_with_issue = 0
    for idx in repaired.index:
        d = _safe_parse(repaired.at[idx, "DATA"])
        if d is None:
            continue
        issue = _safe_to_datetime(_permit_status_detail(d).get("Issue Date"))
        if issue is pd.NaT or pd.isna(issue):
            continue
        n_with_issue += 1
        if _dates_equal(repaired.at[idx, "PERMIT_DATE"], issue):
            n_match_issue += 1
    print(f"PERMIT_DATE == Issue Date: {n_match_issue}/{n_with_issue}")

    same_pf = (
        (repaired["STATUS_NORMALIZED"] == "Final")
        & repaired["PERMIT_DATE"].notna()
        & repaired["FINAL_DATE"].notna()
        & (
            pd.to_datetime(repaired["PERMIT_DATE"]).dt.normalize()
            == pd.to_datetime(repaired["FINAL_DATE"]).dt.normalize()
        )
    ).sum()
    print(f"Final rows with PERMIT_DATE == FINAL_DATE after repair: {same_pf}")

    if AGENT_DATA_PATH:
        out_dir = os.path.join(AGENT_DATA_PATH, "repaired")
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, "permits_tx_killeen_repaired.parquet")
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote {out_path}")

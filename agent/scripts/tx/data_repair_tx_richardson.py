"""Data repair for Richardson (TX) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Richardson DATA is a municipal portal payload keyed by ``record_id`` /
``Application Data``, with an optional nested ``Permit`` block and
``Structure`` section. The ``Permit`` block is frequently a *different*
permit scraped for the same Location ID — only trust it when
``Permit Number`` aligns with ``Application Data.Number`` / ``record_id``.

INFERRED_SCHEMA values:
  - app_only:            Permit block empty; Application Data only
  - app_only_structure:  app_only + Structure
  - permit_aligned:      Permit Number matches Application Data / record_id
  - permit_aligned_structure
  - permit_mismatched:   Permit block present but belongs to another case
  - permit_mismatched_structure

Canonical mappings (record identity = Application Data / record_id):
  - Application Data.Status               → STATUS_NORMALIZED
    (permit_aligned: Permit.Permit Status may override when more specific,
    e.g. PERMIT REVOKED)
  - Application Data.Date                 → FILE_DATE for In Review only
    (no true apply/submittal stamp exists for Active/Final rows)
  - Permit.Issue Date (aligned only)      → PERMIT_DATE
    (Active APPROVED without Issue Date: Application Data.Date)
  - Permit.Status Updated (aligned) else
    Application Data.Date                 → FINAL_DATE (Final only)

Known issues repaired:
  - All sample rows have null STATUS_NORMALIZED / FILE_DATE / PERMIT_DATE /
    FINAL_DATE (upstream never mapped this feed) → FILLED from DATA.
  - permit_mismatched Issue Date / Status Updated ignored (wrong permit).
  - Sentinel Issue Date ``00/00/00`` treated as missing.

Not repairable / left as-is:
  - ~65 shell rows with null Application Data.Status and empty Permit.
  - FILE_DATE for Active/Final: no apply/submittal field in DATA.
  - PERMIT_DATE for most Final/Active rows: Issue Date only available when
    Permit block aligns (~155 rows); mismatched Issue Dates are discarded.
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
        "00/00/0000", "0/0/0000", "00/00/00", "0/0/00",
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


def _norm_num(n) -> Optional[str]:
    if n is None or (isinstance(n, float) and math.isnan(n)):
        return None
    text = str(n).strip()
    if not text:
        return None
    text = re.sub(r"^0+", "", text) or "0"
    return text


def _permit_number_key(pnum) -> Optional[str]:
    """Extract comparable numeric key from Permit Number like '00-2943'."""
    if pnum is None or (isinstance(pnum, float) and math.isnan(pnum)):
        return None
    text = str(pnum).strip()
    if not text:
        return None
    parts = text.split("-")
    return _norm_num(parts[-1]) if parts else _norm_num(text)


def _record_id_number(record_id) -> Optional[str]:
    if not record_id or not isinstance(record_id, str):
        return None
    m = re.match(r"^\d{4}-(\d+)-", record_id.strip())
    return _norm_num(m.group(1)) if m else None


def _permit(d: dict) -> dict:
    p = d.get("Permit")
    return p if isinstance(p, dict) else {}


def _app(d: dict) -> dict:
    a = d.get("Application Data")
    return a if isinstance(a, dict) else {}


def _permit_block_empty(permit: dict) -> bool:
    keys = [
        "Permit", "Valuation", "Contractor", "Issue Date", "Permit Type",
        "Permit Number", "Permit Status", "Square Footage", "Status Updated",
    ]
    for k in keys:
        v = permit.get(k)
        if v is None or v == "" or v == [] or v == "00/00/00":
            continue
        return False
    return True


def _permit_aligned(d: dict) -> bool:
    """True when Permit Number matches Application Data.Number or record_id."""
    permit = _permit(d)
    if _permit_block_empty(permit):
        return False
    p_key = _permit_number_key(permit.get("Permit Number"))
    if p_key is None:
        return False
    a_key = _norm_num(_app(d).get("Number"))
    r_key = _record_id_number(d.get("record_id"))
    return (a_key is not None and p_key == a_key) or (
        r_key is not None and p_key == r_key
    )


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())
    if not ({"Application Data", "Permit", "record_id"} <= keys):
        return "unknown"

    has_structure = "Structure" in keys
    permit = _permit(data_dict)
    if _permit_block_empty(permit):
        base = "app_only"
    elif _permit_aligned(data_dict):
        base = "permit_aligned"
    else:
        base = "permit_mismatched"

    if has_structure:
        return f"{base}_structure"
    return base


def _schema_family(schema: str) -> str:
    """Strip optional _structure suffix for repair branching."""
    if schema.endswith("_structure"):
        return schema[: -len("_structure")]
    return schema


# ── Status mapping ───────────────────────────────────────────────────────────

_APP_STATUS_MAP = {
    "CLOSED": "Final",
    "CERTIFICATE OF OCC ISSUED": "Final",
    "APPROVED": "Active",
    "IN PLAN CHECK": "In Review",
    "ON HOLD": "In Review",
}

_PERMIT_STATUS_MAP = {
    "PERMIT CLOSED": "Final",
    "CERTIFICATE OF OCCUPANCY ISSUED": "Final",
    "FINAL INSPECTION COMPLETE": "Final",
    "PERMIT ISSUED": "Active",
    "PERMIT REVOKED": "Inactive",
    "PERMIT READY TO BE ISSUED": "In Review",
    "PERMIT IN PLAN CHECK": "In Review",
}


def _expected_status(d: dict, family: str) -> Optional[str]:
    """Derive STATUS_NORMALIZED from Application Data (and aligned Permit)."""
    app = _app(d)
    permit = _permit(d)
    app_raw = app.get("Status")
    app_key = str(app_raw).strip() if app_raw not in (None, "") else ""
    app_status = _APP_STATUS_MAP.get(app_key) if app_key else None

    if family == "permit_aligned":
        ps_raw = permit.get("Permit Status")
        ps_key = str(ps_raw).strip() if ps_raw not in (None, "") else ""
        permit_status = _PERMIT_STATUS_MAP.get(ps_key) if ps_key else None
        # Prefer Permit Status when present: catches REVOKED vs CLOSED, etc.
        if permit_status is not None:
            return permit_status
        return app_status

    # app_only / permit_mismatched: ignore Permit (mismatched = wrong case)
    return app_status


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


def _issue_date(d: dict, family: str):
    """Issue Date only when Permit block is aligned to this record."""
    if family != "permit_aligned":
        return pd.NaT
    return _safe_to_datetime(_permit(d).get("Issue Date"))


def _status_updated(d: dict, family: str):
    if family != "permit_aligned":
        return pd.NaT
    return _safe_to_datetime(_permit(d).get("Status Updated"))


def _app_date(d: dict):
    return _safe_to_datetime(_app(d).get("Date"))


def _latest_inspection_date(d: dict, family: str):
    """Latest non-null inspection Date from aligned Permit.Inspection List."""
    if family != "permit_aligned":
        return pd.NaT
    insp = _permit(d).get("Inspection List") or []
    best = pd.NaT
    if not isinstance(insp, list):
        return best
    for item in insp:
        if not isinstance(item, dict):
            continue
        dt = _safe_to_datetime(item.get("Date"))
        if dt is pd.NaT or pd.isna(dt):
            continue
        if best is pd.NaT or pd.isna(best) or dt > best:
            best = dt
    return best


def _final_date_candidate(d: dict, family: str):
    """Prefer Status Updated (aligned); else App Date; else latest inspection."""
    for cand in (
        _status_updated(d, family),
        _app_date(d),
        _latest_inspection_date(d, family),
    ):
        if cand is not pd.NaT and not pd.isna(cand):
            return cand
    return pd.NaT


# ── Per-row repair ───────────────────────────────────────────────────────────

def _repair_row(row, d: dict, family: str, repairs: dict) -> None:
    """Repair one Richardson portal record."""
    expected = _expected_status(d, family)
    effective_status = _apply_status(repairs, row["STATUS_NORMALIZED"], expected)

    app_dt = _app_date(d)
    issue = _issue_date(d, family)

    # -- FILE_DATE --
    # No dedicated apply/submittal field. For In Review, Application Data.Date
    # is the best available activity/submittal stamp. For Active/Final, App Date
    # is usually a close/approval stamp (often == Status Updated when aligned).
    if effective_status == "In Review":
        _apply_date(repairs, row, "FILE_DATE", app_dt)

    # -- PERMIT_DATE --
    if issue is not pd.NaT and not pd.isna(issue):
        _apply_date(repairs, row, "PERMIT_DATE", issue)
    elif effective_status == "Active":
        # APPROVED rows without aligned Issue Date: Application Data.Date
        # is the approval / last-status stamp.
        app_raw = _app(d).get("Status")
        app_key = str(app_raw).strip().upper() if app_raw not in (None, "") else ""
        if app_key == "APPROVED":
            _apply_date(repairs, row, "PERMIT_DATE", app_dt)

    # -- FINAL_DATE --
    if effective_status == "Final":
        _apply_date(repairs, row, "FINAL_DATE", _final_date_candidate(d, family))
    else:
        _clear_date(repairs, row, "FINAL_DATE")


# ── Main entry point ─────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Richardson permit records using the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Richardson".  Must contain
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

        family = _schema_family(schema)
        if family not in {"app_only", "permit_aligned", "permit_mismatched"}:
            continue

        repairs: dict = {}
        _repair_row(row, d, family, repairs)

        for key, value in repairs.items():
            out.at[idx, key] = value

    return out


# ── CLI: run standalone to preview repair stats ─────────────────────────────

if __name__ == "__main__":
    import os
    from pathlib import Path

    from dotenv import load_dotenv

    repo_root = Path(__file__).resolve().parents[3]
    load_dotenv(repo_root / ".env")
    MY_DATA_PATH = os.getenv("MY_DATA_PATH")
    AGENT_DATA_PATH = os.getenv("AGENT_DATA_PATH")
    filepath = os.path.join(MY_DATA_PATH, "processed_data", "permits_tx_sample.parquet")
    df = pd.read_parquet(filepath)
    city = df[(df["JURISDICTION"] == "Richardson") & (df["STATE"] == "TX")].copy()

    print(f"Richardson records: {len(city):,}\n")

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

    print("\nSTATUS fills by Application Data.Status / Permit Status:")
    ch_mask = repaired["STATUS_NORMALIZED_FLAG"].notna()
    if ch_mask.any():
        rows = []
        for idx in repaired.index[ch_mask]:
            d = _safe_parse(city.at[idx, "DATA"]) or {}
            rows.append({
                "APP_STATUS": _app(d).get("Status"),
                "PERMIT_STATUS": _permit(d).get("Permit Status"),
                "SCHEMA": repaired.at[idx, "INFERRED_SCHEMA"],
                "AFTER": repaired.at[idx, "STATUS_NORMALIZED"],
                "FLAG": repaired.at[idx, "STATUS_NORMALIZED_FLAG"],
            })
        ch = pd.DataFrame(rows)
        print(ch.groupby(["SCHEMA", "APP_STATUS", "PERMIT_STATUS", "AFTER", "FLAG"]).size().to_string())
    else:
        print("  (none)")

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

    # Date-order checks
    f = repaired["FILE_DATE"]
    p = repaired["PERMIT_DATE"]
    fin = repaired["FINAL_DATE"]
    fp = ((f.notna()) & (p.notna()) & (f.dt.normalize() > p.dt.normalize())).sum()
    pf = ((p.notna()) & (fin.notna()) & (p.dt.normalize() > fin.dt.normalize())).sum()
    ff = ((f.notna()) & (fin.notna()) & (f.dt.normalize() > fin.dt.normalize())).sum()
    print(f"\nDate-order violations: FILE>PERMIT={fp}, PERMIT>FINAL={pf}, FILE>FINAL={ff}")

    if AGENT_DATA_PATH:
        out_dir = os.path.join(AGENT_DATA_PATH, "repaired")
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, "permits_tx_richardson_repaired.parquet")
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote {out_path}")

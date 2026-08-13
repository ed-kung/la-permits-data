"""Data repair for Fort Myers Beach (FL) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Fort Myers Beach DATA is a flat city-portal payload with top-level
Status, Permit Date, Issued Date, Finaled Date, inspections, fees,
payments, contractors, and property_info. Key-set variants add optional
fields (Square Feet, Gross Square Feet, Repair Damage Due To, reviews
vs plan_reviews, record_type_from_contractor_box) but share the same
canonical date/status fields.

Canonical mappings:
  - Status, with Finaled Date / Issued Date overrides → STATUS_NORMALIZED
  - Permit Date (application / submittal stamp)       → FILE_DATE
  - Issued Date                                       → PERMIT_DATE
  - Finaled Date; else latest passed Final/CO
    inspection                                        → FINAL_DATE

INFERRED_SCHEMA is ``city_portal_{status_slug}_{content}`` where content
is issued_finaled / issued / finaled / applied / status_only.

Known issues repaired:
  - Waiting-on-docs / resubmittal / fire-fee statuses left
    STATUS_NORMALIZED null → FILLED as In Review.
  - Stale STATUS_ORIGINAL=issued on IN REVIEW / WAITING FOR
    REQUIRED DOC rows labeled Active → FIXED to In Review.
  - One ISSUED row labeled Final via stale STATUS_ORIGINAL=finaled
    → FIXED to Active (no Finaled Date).
  - ISSUED rows that already carry Finaled Date → FIXED to Final.
  - Spurious PERMIT_DATE copied from Permit Date or review
    timestamps on unissued In Review / Inactive rows → cleared;
    Active/Final PERMIT_DATE aligned to Issued Date.
  - Spurious FINAL_DATE on non-Final (ISSUED / DENIED / EXPIRED / …)
    cleared; Final gaps filled from Finaled Date or passed Final
    inspections.

Not repairable from DATA:
  - 10 blank-Status shells → STATUS_NORMALIZED stays missing.
  - Final / Active rows with blank Issued Date → PERMIT_DATE stays
    missing (Permit Date is the application stamp, not issuance).
  - Final rows with blank Finaled Date and no dated Final/CO pass
    inspection → FINAL_DATE stays missing.
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
    r"final|\bco\b|certificate|c\.?o\.?|sign.?off|complet",
    re.IGNORECASE,
)
_PASS_RE = re.compile(r"\bpass", re.IGNORECASE)


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
        return "blank"
    s = re.sub(r"[^a-z0-9]+", "_", str(text).strip().lower()).strip("_")
    return s or "blank"


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


# ── Field extractors ─────────────────────────────────────────────────────────

def _raw_status(d: dict) -> Optional[str]:
    raw = d.get("Status")
    if raw is None or (isinstance(raw, float) and math.isnan(raw)):
        return None
    s = str(raw).strip()
    return s or None


def _permit_date(d: dict):
    """Portal Permit Date = application / submittal stamp here."""
    return _safe_to_datetime(d.get("Permit Date"))


def _issued_date(d: dict):
    return _safe_to_datetime(d.get("Issued Date"))


def _finaled_date(d: dict):
    return _safe_to_datetime(d.get("Finaled Date"))


def _latest_final_inspection(d: dict):
    """Latest completed/scheduled date of a passed Final/CO inspection."""
    best = pd.NaT
    for insp in d.get("inspections") or []:
        if not isinstance(insp, dict):
            continue
        status = str(insp.get("status") or "")
        itype = str(insp.get("inspection_type") or "")
        if not _PASS_RE.search(status):
            continue
        if not _FINAL_INSP_RE.search(itype):
            continue
        for key in ("completed_date", "scheduled_date"):
            dt = _safe_to_datetime(insp.get(key))
            if not _present(dt):
                continue
            if not _present(best) or dt > best:
                best = dt
            break
    return best


# ── Status mapping ───────────────────────────────────────────────────────────

_STATUS_MAP = {
    "FINALED": "Final",
    "CLOSED": "Final",
    "ISSUED": "Active",
    "APPROVED": "Active",
    "IN REVIEW": "In Review",
    "WAITING FOR PAYMENT": "In Review",
    "WAITING ON RESUBMITTAL": "In Review",
    "WAITING FOR REQUIRED DOC": "In Review",
    "INCOMPLETE SUBMITTAL": "In Review",
    "REVISION REVIEW": "In Review",
    "HOLD": "In Review",
    "FIRE FEES TO BE PAID": "In Review",
    "VOID": "Inactive",
    "ABANDONED": "Inactive",
    "EXPIRED": "Inactive",
    "DENIED": "Inactive",
    "INACTIVE": "Inactive",
    "REVOKED": "Inactive",
    "ISSUED - INACTIVE": "Inactive",
}

_INACTIVE = {
    "VOID",
    "ABANDONED",
    "EXPIRED",
    "DENIED",
    "INACTIVE",
    "REVOKED",
    "ISSUED - INACTIVE",
}


def _expected_status(d: dict) -> Optional[str]:
    """Derive STATUS_NORMALIZED from Status with date overrides.

    Priority:
      1. Terminal inactive Status → Inactive
      2. Finaled Date present, or FINALED / CLOSED → Final
      3. Issued Date present, or ISSUED / APPROVED → Active
      4. Otherwise map Status
    """
    status = (_raw_status(d) or "").upper() or None
    finaled = _finaled_date(d)
    issued = _issued_date(d)

    if status in _INACTIVE:
        return "Inactive"

    if _present(finaled) or status in {"FINALED", "CLOSED"}:
        return "Final"

    if _present(issued) or status in {"ISSUED", "APPROVED"}:
        return "Active"

    if status is not None:
        return _STATUS_MAP.get(status)

    return None


# ── Schema classification ────────────────────────────────────────────────────

def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    if not isinstance(data_dict, dict):
        return "unknown"
    if "Status" not in data_dict and "Permit Date" not in data_dict:
        return "unknown"

    status_slug = _slug(_raw_status(data_dict))
    has_issued = _present(_issued_date(data_dict))
    has_finaled = _present(_finaled_date(data_dict))
    has_applied = _present(_permit_date(data_dict))

    if has_issued and has_finaled:
        content = "issued_finaled"
    elif has_issued:
        content = "issued"
    elif has_finaled:
        content = "finaled"
    elif has_applied:
        content = "applied"
    else:
        content = "status_only"

    return f"city_portal_{status_slug}_{content}"


# ── Per-record repair ────────────────────────────────────────────────────────

def _repair_record(row, d: dict, repairs: dict) -> None:
    expected = _expected_status(d)
    effective = _apply_status(repairs, row["STATUS_NORMALIZED"], expected)

    # FILE_DATE ← portal Permit Date (application / submittal)
    _apply_date(repairs, row, "FILE_DATE", _permit_date(d))

    issued = _issued_date(d)
    current_permit = row["PERMIT_DATE"]

    # PERMIT_DATE ← Issued Date for Active / Final; keep Issued on Inactive;
    # clear spurious stamps on In Review and unissued Inactive.
    if effective in ("Active", "Final"):
        if _present(issued):
            _apply_date(repairs, row, "PERMIT_DATE", issued)
        elif not pd.isna(current_permit):
            # Unissued but carrying Permit Date / review stamp → clear.
            _clear_date(repairs, row, "PERMIT_DATE")
    elif effective == "Inactive":
        if _present(issued):
            _apply_date(repairs, row, "PERMIT_DATE", issued)
        elif not pd.isna(current_permit):
            _clear_date(repairs, row, "PERMIT_DATE")
    else:
        # In Review / unknown
        if not pd.isna(current_permit):
            _clear_date(repairs, row, "PERMIT_DATE")

    # FINAL_DATE ← Finaled Date, else passed Final/CO inspection
    finaled = _finaled_date(d)
    if effective == "Final":
        final_src = finaled
        if not _present(final_src):
            final_src = _latest_final_inspection(d)
        if _present(final_src):
            _apply_date(repairs, row, "FINAL_DATE", final_src)
    else:
        _clear_date(repairs, row, "FINAL_DATE")


# ── Main entry point ─────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Fort Myers Beach permit records using information from the raw DATA JSON.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Fort Myers Beach". Must contain
        columns STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, FINAL_DATE, and DATA.

    Returns
    -------
    pd.DataFrame
        Copy of *df* with repaired fields, ``{FIELD}_FLAG`` columns, and
        ``INFERRED_SCHEMA``.
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
    filepath = os.path.join(
        my_data_path, "processed_data", "permits_fl_sample.parquet"
    )
    df = pd.read_parquet(filepath)
    city = df[
        (df["JURISDICTION"] == "Fort Myers Beach") & (df["STATE"] == "FL")
    ].copy()

    print(f"Fort Myers Beach records: {len(city):,}\n")
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
        part = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = part["FILE_DATE"].notna().sum()
        print(
            f"  {status:15s}: {n_has:>4,} / {len(part):>4,} "
            f"({(n_has / len(part) if len(part) else 0):.1%})"
        )

    print("\nPERMIT_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        part = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = part["PERMIT_DATE"].notna().sum()
        print(
            f"  {status:15s}: {n_has:>4,} / {len(part):>4,} "
            f"({(n_has / len(part) if len(part) else 0):.1%})"
        )

    print("\nFINAL_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        part = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = part["FINAL_DATE"].notna().sum()
        print(
            f"  {status:15s}: {n_has:>4,} / {len(part):>4,} "
            f"({(n_has / len(part) if len(part) else 0):.1%})"
        )

    both = repaired[
        repaired["PERMIT_DATE"].notna() & repaired["FINAL_DATE"].notna()
    ]
    n_inv = (
        both["PERMIT_DATE"].dt.normalize() > both["FINAL_DATE"].dt.normalize()
    ).sum()
    print(f"\nPERMIT_DATE > FINAL_DATE inversions after repair: {n_inv}")

    if agent_data_path:
        out_path = os.path.join(
            agent_data_path, "fort_myers_beach_repaired_sample.parquet"
        )
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote repaired sample → {out_path}")

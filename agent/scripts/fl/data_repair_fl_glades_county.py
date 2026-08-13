"""Data repair for Glades County (FL) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Glades County DATA is a city permit-portal payload with top-level
``Applied Date``, ``Permit Date``, ``Issued Date``, ``Completed Date``,
nested ``fees`` / ``payments`` / ``contractors`` / ``inspections`` /
``property_info``, and either ``reviews`` or ``plan_reviews`` (sometimes
plus ``record_type_from_contractor_box``). A small legacy key-set carries
blank ``Status`` and omits ``Permit Date``.

Almost every sample row has null STATUS_NORMALIZED / STATUS_ORIGINAL;
status must be inferred from dates and inspections.

INFERRED_SCHEMA prefixes:
  - portal:         standard shells with reviews array
  - contractor_box: record_type_from_contractor_box present
  - plan_reviews:   plan_reviews key (no contractor_box)
  - legacy:         Status key, no Permit Date

Suffix is a content slug: completed_issued / completed / issued_final_insp
/ issued / applied / empty.

Canonical mappings:
  - Completed Date, else passed Final/CO inspection, else Issued Date,
    else Applied/Permit Date presence → STATUS_NORMALIZED
  - Applied Date; else Permit Date     → FILE_DATE
  - Issued Date                        → PERMIT_DATE
  - Completed Date; else latest passed
    Final/CO inspection completed_date → FINAL_DATE

Known issues repaired:
  - STATUS_NORMALIZED entirely null → FILLED from date/inspection
    lifecycle (Final / Active / In Review).
  - FILE_DATE often copied from Permit Date when Applied Date differs
    → FIXED to Applied Date; 1900-01-01 sentinel FILE_DATE cleared /
    replaced.
  - PERMIT_DATE copied from review completed_date on unissued rows,
    or stored as 1900-01-01 when Issued Date is the sentinel → FIXED
    (cleared or aligned to Issued Date).
  - FINAL_DATE missing one Completed Date; 1900-01-01 FINAL_DATE
    sentinels cleared; Final gaps filled from Completed Date or passed
    Final/CO inspections.

Not repairable from DATA:
  - Empty / sentinel-only shells (no usable Applied / Permit / Issued /
    Completed dates and no passed Final inspection) → STATUS stays null;
    dates stay missing.
  - Final rows with blank Completed Date and no dated Final/CO pass
    → FINAL_DATE stays missing.
  - Active / Final with blank Issued Date → PERMIT_DATE stays missing.
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
    r"final|fnl|\bc/?o\b|certificate|c\.?o\.?|sign.?off",
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
        # Portal null sentinel.
        if s.startswith("01/01/1900") or s.startswith("1900-01-01"):
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

def _applied_date(d: dict):
    return _safe_to_datetime(d.get("Applied Date"))


def _permit_stamp(d: dict):
    """Portal Permit Date — often a record stamp, not issuance."""
    return _safe_to_datetime(d.get("Permit Date"))


def _issued_date(d: dict):
    return _safe_to_datetime(d.get("Issued Date"))


def _completed_date(d: dict):
    return _safe_to_datetime(d.get("Completed Date"))


def _file_date_candidate(d: dict):
    """Prefer Applied Date (application / submittal); else Permit Date."""
    applied = _applied_date(d)
    if _present(applied):
        return applied
    return _permit_stamp(d)


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


def _expected_status(d: dict) -> Optional[str]:
    """Infer STATUS_NORMALIZED from lifecycle dates / inspections.

    Priority:
      1. Valid Completed Date → Final
      2. Passed Final/CO inspection → Final
      3. Valid Issued Date → Active
      4. Applied Date or Permit Date → In Review
    """
    if _present(_completed_date(d)):
        return "Final"
    if _present(_latest_final_inspection(d)):
        return "Final"
    if _present(_issued_date(d)):
        return "Active"
    if _present(_applied_date(d)) or _present(_permit_stamp(d)):
        return "In Review"
    return None


# ── Schema classification ────────────────────────────────────────────────────

def _schema_family(d: Optional[dict]) -> str:
    if d is None:
        return "missing"
    if not isinstance(d, dict):
        return "unknown"
    keys = set(d.keys())
    if "Status" in keys and "Permit Date" not in keys:
        return "legacy"
    if "record_type_from_contractor_box" in keys:
        return "contractor_box"
    if "plan_reviews" in keys:
        return "plan_reviews"
    if "Permit Date" in keys or "Applied Date" in keys:
        return "portal"
    return "unknown"


def _content_slug(d: dict) -> str:
    has_completed = _present(_completed_date(d))
    has_issued = _present(_issued_date(d))
    has_final_insp = _present(_latest_final_inspection(d))
    has_file = _present(_file_date_candidate(d))

    if has_completed and has_issued:
        return "completed_issued"
    if has_completed:
        return "completed"
    if has_issued and has_final_insp:
        return "issued_final_insp"
    if has_issued:
        return "issued"
    if has_file:
        return "applied"
    return "empty"


def _classify_schema(data_dict: Optional[dict]) -> str:
    family = _schema_family(data_dict)
    if family in {"missing", "unknown"}:
        return family
    return f"{family}_{_content_slug(data_dict)}"


# ── Per-record repair ────────────────────────────────────────────────────────

def _repair_record(row, d: dict, repairs: dict) -> None:
    expected = _expected_status(d)
    effective = _apply_status(repairs, row["STATUS_NORMALIZED"], expected)

    # FILE_DATE ← Applied Date, else Permit Date; clear unfillable sentinels.
    file_src = _file_date_candidate(d)
    if _present(file_src):
        _apply_date(repairs, row, "FILE_DATE", file_src)
    else:
        current_file = row["FILE_DATE"]
        if not pd.isna(current_file):
            stored = pd.to_datetime(current_file, errors="coerce")
            if (
                pd.isna(stored)
                or int(stored.year) < _MIN_YEAR
                or int(stored.year) > _MAX_YEAR
            ):
                _clear_date(repairs, row, "FILE_DATE")

    issued = _issued_date(d)
    current_permit = row["PERMIT_DATE"]

    # PERMIT_DATE ← Issued Date for Active / Final; clear spurious stamps
    # (review completed_date, 1900 sentinel, Permit Date copy) otherwise.
    if effective in ("Active", "Final"):
        if _present(issued):
            _apply_date(repairs, row, "PERMIT_DATE", issued)
        elif not pd.isna(current_permit):
            _clear_date(repairs, row, "PERMIT_DATE")
    else:
        # In Review / null / Inactive (unused here)
        if not pd.isna(current_permit):
            _clear_date(repairs, row, "PERMIT_DATE")

    # FINAL_DATE ← Completed Date, else passed Final/CO inspection.
    completed = _completed_date(d)
    final_insp = _latest_final_inspection(d)
    if effective == "Final":
        final_src = completed if _present(completed) else final_insp
        if _present(final_src):
            _apply_date(repairs, row, "FINAL_DATE", final_src)
        else:
            current_final = row["FINAL_DATE"]
            if not pd.isna(current_final):
                stored = pd.to_datetime(current_final, errors="coerce")
                if (
                    pd.isna(stored)
                    or int(stored.year) < _MIN_YEAR
                    or int(stored.year) > _MAX_YEAR
                ):
                    _clear_date(repairs, row, "FINAL_DATE")
    else:
        _clear_date(repairs, row, "FINAL_DATE")


# ── Main entry point ─────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Glades County permit records using information from the raw DATA JSON.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Glades County". Must contain
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
        (df["JURISDICTION"] == "Glades County") & (df["STATE"] == "FL")
    ].copy()

    print(f"Glades County records: {len(city):,}\n")
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
    null_part = repaired[repaired["STATUS_NORMALIZED"].isna()]
    if len(null_part):
        n_has = null_part["FILE_DATE"].notna().sum()
        print(
            f"  {'null':15s}: {n_has:>4,} / {len(null_part):>4,} "
            f"({(n_has / len(null_part) if len(null_part) else 0):.1%})"
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

    # Alignment checks vs DATA
    n_file_mm = 0
    n_file_cmp = 0
    n_permit_mm = 0
    n_permit_cmp = 0
    n_final_mm = 0
    n_final_cmp = 0
    for idx in repaired.index:
        d = _safe_parse(repaired.at[idx, "DATA"])
        if d is None:
            continue
        file_src = _file_date_candidate(d)
        if _present(file_src) and pd.notna(repaired.at[idx, "FILE_DATE"]):
            n_file_cmp += 1
            if not _dates_equal(repaired.at[idx, "FILE_DATE"], file_src):
                n_file_mm += 1
        issued = _issued_date(d)
        if _present(issued) and pd.notna(repaired.at[idx, "PERMIT_DATE"]):
            n_permit_cmp += 1
            if not _dates_equal(repaired.at[idx, "PERMIT_DATE"], issued):
                n_permit_mm += 1
        completed = _completed_date(d)
        final_src = completed if _present(completed) else _latest_final_inspection(d)
        if _present(final_src) and pd.notna(repaired.at[idx, "FINAL_DATE"]):
            n_final_cmp += 1
            if not _dates_equal(repaired.at[idx, "FINAL_DATE"], final_src):
                n_final_mm += 1

    print(f"\nFILE_DATE != Applied/Permit candidate: {n_file_mm} / {n_file_cmp}")
    print(f"PERMIT_DATE != Issued Date: {n_permit_mm} / {n_permit_cmp}")
    print(f"FINAL_DATE != Completed/insp: {n_final_mm} / {n_final_cmp}")

    both = repaired[
        repaired["PERMIT_DATE"].notna() & repaired["FINAL_DATE"].notna()
    ]
    n_inv = (
        both["PERMIT_DATE"].dt.normalize() > both["FINAL_DATE"].dt.normalize()
    ).sum()
    print(f"\nPERMIT_DATE > FINAL_DATE inversions after repair: {n_inv}")

    if agent_data_path:
        out_path = os.path.join(
            agent_data_path, "glades_county_repaired_sample.parquet"
        )
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote repaired sample → {out_path}")

"""Data repair for Citrus County (FL) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Citrus County DATA has two portal families in this sample:

  - cityview_*:  newer detail.xhtml / CityView-style payload with
                 ``Added On``, ``Issued On``, ``Final On``, ``Certified On``,
                 ``Reviews``, and often ``init_info`` (Type / Status /
                 Date Opened).
  - legacy_*:    older flat payload with ``Date Created``, ``Issued Date``,
                 ``Exp. Date``, ``Permit Type`` — no status field and no
                 true final/completion date.

Content variants (INFERRED_SCHEMA) further split by which dates are set:

  - cityview_issued_finaled / cityview_issued / cityview_finaled /
    cityview_applied / cityview_status_only
  - legacy_issued / legacy_applied / legacy_status_only
  - missing / unknown

Canonical mappings:
  CityView
    - init_info.Status (preferred); else STATUS_ORIGINAL
      + Final On (unless Void/Expired/Withdrawn) → STATUS_NORMALIZED
    - Added On                                    → FILE_DATE
    - Issued On                                   → PERMIT_DATE
    - Final On (Final rows only)                  → FINAL_DATE

  Legacy
    - no portal status: Issued Date → Active,
      else In Review                              → STATUS_NORMALIZED
    - Date Created                                → FILE_DATE
    - Issued Date                                 → PERMIT_DATE
    - Exp. Date is NOT a final date; clear any
      FINAL_DATE that was copied from it          → FINAL_DATE

Known issues repaired:
  - Upstream STATUS_ORIGINAL often says ``closed`` even when
    init_info.Status is Issued / Out To Applicant / Void / etc.
    → FIXED from init_info (+ Final On override).
  - 587 legacy rows have null STATUS_NORMALIZED → FILLED from
    presence of Issued Date.
  - Many CityView Final rows have Issued On / Final On in DATA but
    null PERMIT_DATE / FINAL_DATE → FILLED.
  - Nearly all legacy FINAL_DATE values equal Exp. Date → FIXED
    (cleared); non-Final FINAL_DATE cleared after status repair.

Not repairable from DATA:
  - FILE_DATE already matches Added On / Date Created for every
    sample row.
  - Legacy rows have no final/completion field → cannot populate
    FINAL_DATE or promote to Final.
  - A minority of CityView Final rows lack Final On → FINAL_DATE
    stays missing.
  - A few CityView / legacy rows lack Issued On / Issued Date →
    PERMIT_DATE stays missing.
"""

from __future__ import annotations

import json
import math
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
    """Parse a date value, returning pd.NaT on failure / out-of-range."""
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return pd.NaT
    if isinstance(val, str):
        s = val.strip()
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


def _dates_equal(a, b) -> bool:
    da = _safe_to_datetime(a)
    db = _safe_to_datetime(b)
    if da is pd.NaT or db is pd.NaT or pd.isna(da) or pd.isna(db):
        return False
    return pd.Timestamp(da).normalize() == pd.Timestamp(db).normalize()


def _is_legacy(d: dict) -> bool:
    return "Date Created" in d or "Issued Date" in d


def _is_cityview(d: dict) -> bool:
    return "Added On" in d or "Issued On" in d or "Final On" in d


def _classify_schema(d: Optional[dict]) -> str:
    if d is None:
        return "missing"
    if not isinstance(d, dict):
        return "unknown"

    if _is_legacy(d) and not _is_cityview(d):
        issued = _safe_to_datetime(d.get("Issued Date"))
        created = _safe_to_datetime(d.get("Date Created"))
        if issued is not pd.NaT and not pd.isna(issued):
            return "legacy_issued"
        if created is not pd.NaT and not pd.isna(created):
            return "legacy_applied"
        return "legacy_status_only"

    if _is_cityview(d):
        issued = _safe_to_datetime(d.get("Issued On"))
        final_on = _safe_to_datetime(d.get("Final On"))
        added = _safe_to_datetime(d.get("Added On"))
        has_issued = issued is not pd.NaT and not pd.isna(issued)
        has_final = final_on is not pd.NaT and not pd.isna(final_on)
        if has_issued and has_final:
            return "cityview_issued_finaled"
        if has_issued:
            return "cityview_issued"
        if has_final:
            return "cityview_finaled"
        if added is not pd.NaT and not pd.isna(added):
            return "cityview_applied"
        init = d.get("init_info") if isinstance(d.get("init_info"), dict) else {}
        if init.get("Status") or d.get("Type"):
            return "cityview_status_only"
        return "cityview_applied"

    return "unknown"


# ── Status mapping ───────────────────────────────────────────────────────────

_INIT_STATUS_MAP = {
    "closed": "Final",
    "finalized": "Final",
    "co issued": "Final",
    "issued": "Active",
    "hold inspections": "Active",
    "open": "In Review",
    "submitted": "In Review",
    "in review": "In Review",
    "out to applicant": "In Review",
    "amendment in progress": "In Review",
    "void": "Inactive",
    "expired": "Inactive",
    "withdrawn": "Inactive",
}

_STATUS_ORIGINAL_MAP = {
    "closed": "Final",
    "finalized": "Final",
    "issued": "Active",
    "open": "In Review",
    "in review": "In Review",
    "void": "Inactive",
}

_INACTIVE_INIT = {"void", "expired", "withdrawn"}


def _init_status(d: dict) -> Optional[str]:
    init = d.get("init_info") if isinstance(d.get("init_info"), dict) else {}
    raw = init.get("Status")
    if raw is None:
        return None
    s = str(raw).strip()
    return s or None


def _expected_status_cityview(d: dict, row) -> Optional[str]:
    init = _init_status(d)
    expected: Optional[str] = None
    if init is not None:
        expected = _INIT_STATUS_MAP.get(init.strip().lower())
    if expected is None:
        orig = row.get("STATUS_ORIGINAL")
        if not (isinstance(orig, float) and math.isnan(orig)) and orig is not None:
            expected = _STATUS_ORIGINAL_MAP.get(str(orig).strip().lower())

    final_on = _safe_to_datetime(d.get("Final On"))
    has_final = final_on is not pd.NaT and not pd.isna(final_on)
    init_key = (init or "").strip().lower()
    if has_final and init_key not in _INACTIVE_INIT:
        # Final On is a strong completion signal unless the permit was
        # voided / expired / withdrawn.
        if expected != "Inactive":
            expected = "Final"
    return expected


def _expected_status_legacy(d: dict) -> Optional[str]:
    issued = _safe_to_datetime(d.get("Issued Date"))
    if issued is not pd.NaT and not pd.isna(issued):
        return "Active"
    created = _safe_to_datetime(d.get("Date Created"))
    if created is not pd.NaT and not pd.isna(created):
        return "In Review"
    return None


def _set_status(repairs: dict, current, expected: Optional[str]) -> None:
    if expected is None:
        return
    if pd.isna(current):
        repairs["STATUS_NORMALIZED"] = expected
        repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"
    elif current != expected:
        repairs["STATUS_NORMALIZED"] = expected
        repairs["STATUS_NORMALIZED_FLAG"] = "FIXED"


def _set_date_from_source(repairs: dict, field: str, current, candidate) -> None:
    cand = _safe_to_datetime(candidate)
    if cand is pd.NaT or pd.isna(cand):
        return
    if pd.isna(current):
        repairs[field] = cand
        repairs[f"{field}_FLAG"] = "FILLED"
    elif not _dates_equal(current, cand):
        repairs[field] = cand
        repairs[f"{field}_FLAG"] = "FIXED"


def _clear_date(repairs: dict, row, field: str) -> None:
    current = repairs.get(field, row[field])
    if pd.isna(current):
        return
    repairs[field] = pd.NaT
    repairs[f"{field}_FLAG"] = "FIXED"


# ── Per-record repair ────────────────────────────────────────────────────────

def _repair_cityview(row, d: dict, repairs: dict) -> None:
    expected = _expected_status_cityview(d, row)
    _set_status(repairs, row["STATUS_NORMALIZED"], expected)
    effective_status = repairs.get("STATUS_NORMALIZED", row["STATUS_NORMALIZED"])

    _set_date_from_source(repairs, "FILE_DATE", row["FILE_DATE"], d.get("Added On"))

    issued = _safe_to_datetime(d.get("Issued On"))
    if issued is not pd.NaT and not pd.isna(issued):
        _set_date_from_source(repairs, "PERMIT_DATE", row["PERMIT_DATE"], issued)

    final_on = _safe_to_datetime(d.get("Final On"))
    if effective_status == "Final":
        _set_date_from_source(repairs, "FINAL_DATE", row["FINAL_DATE"], final_on)
    else:
        _clear_date(repairs, row, "FINAL_DATE")


def _repair_legacy(row, d: dict, repairs: dict) -> None:
    expected = _expected_status_legacy(d)
    _set_status(repairs, row["STATUS_NORMALIZED"], expected)
    effective_status = repairs.get("STATUS_NORMALIZED", row["STATUS_NORMALIZED"])

    _set_date_from_source(repairs, "FILE_DATE", row["FILE_DATE"], d.get("Date Created"))

    issued = _safe_to_datetime(d.get("Issued Date"))
    if issued is not pd.NaT and not pd.isna(issued):
        _set_date_from_source(repairs, "PERMIT_DATE", row["PERMIT_DATE"], issued)

    # Legacy payloads expose Exp. Date only — never a completion / final
    # stamp. Upstream often copied Exp. Date into FINAL_DATE; clear it.
    if effective_status == "Final":
        # Should not occur for legacy (no Final signal); still avoid
        # treating Exp. Date as FINAL_DATE.
        exp = _safe_to_datetime(d.get("Exp. Date"))
        current_final = row["FINAL_DATE"]
        if (
            exp is not pd.NaT
            and not pd.isna(exp)
            and not pd.isna(current_final)
            and _dates_equal(current_final, exp)
        ):
            _clear_date(repairs, row, "FINAL_DATE")
    else:
        _clear_date(repairs, row, "FINAL_DATE")


# ── Main entry point ─────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Citrus County permit records using the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Citrus County".  Must
        contain columns STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE,
        FINAL_DATE, and DATA.

    Returns
    -------
    pd.DataFrame
        Copy of *df* with corrected field values, an INFERRED_SCHEMA
        column naming the DATA JSON sub-schema identified for each
        record, and flag columns: STATUS_NORMALIZED_FLAG, FILE_DATE_FLAG,
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
        if _is_legacy(d) and not _is_cityview(d):
            _repair_legacy(row, d, repairs)
        elif _is_cityview(d):
            _repair_cityview(row, d, repairs)

        for key, value in repairs.items():
            out.at[idx, key] = value

    for col in ("FILE_DATE", "PERMIT_DATE", "FINAL_DATE"):
        out[col] = pd.to_datetime(out[col], errors="coerce", utc=True).dt.tz_localize(None)

    return out


# ── CLI: run standalone to preview repair stats ──────────────────────────────

if __name__ == "__main__":
    import os
    from collections import Counter
    from pathlib import Path

    from dotenv import load_dotenv

    repo_root = Path(__file__).resolve().parents[3]
    load_dotenv(repo_root / ".env")
    my_data_path = os.getenv("MY_DATA_PATH")
    agent_data_path = os.getenv("AGENT_DATA_PATH")
    filepath = os.path.join(my_data_path, "processed_data", "permits_fl_sample.parquet")
    df = pd.read_parquet(filepath)
    city = df[df["JURISDICTION"] == "Citrus County"].copy()

    print(f"Citrus County records: {len(city):,}\n")
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

    print("\nSTATUS_NORMALIZED_FLAG breakdown:")
    for flag in ["FILLED", "FIXED"]:
        sub = repaired[repaired["STATUS_NORMALIZED_FLAG"] == flag]
        print(f"  {flag} ({len(sub)}):")
        labels = []
        for idx in sub.index:
            d = _safe_parse(city.loc[idx, "DATA"])
            init = _init_status(d) if d else None
            labels.append(
                (
                    repaired.loc[idx, "INFERRED_SCHEMA"],
                    init,
                    city.loc[idx, "STATUS_ORIGINAL"],
                    city.loc[idx, "STATUS_NORMALIZED"],
                    repaired.loc[idx, "STATUS_NORMALIZED"],
                )
            )
        for (schema, init, orig, before, after), n in Counter(labels).most_common(25):
            print(
                f"    [{schema}] init={init!r} orig={orig!r}: "
                f"{before!r} → {after!r}  x{n}"
            )

    print("\nFILE_DATE coverage by status (after):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FILE_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({(n_has / len(sub) if len(sub) else 0):.1%})")

    print("\nPERMIT_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["PERMIT_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({(n_has / len(sub) if len(sub) else 0):.1%})")

    print("\nFINAL_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FINAL_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({(n_has / len(sub) if len(sub) else 0):.1%})")

    r = repaired.copy()
    for c in ("FILE_DATE", "PERMIT_DATE", "FINAL_DATE"):
        r[c] = pd.to_datetime(r[c], errors="coerce")
    print("\nChronology after repair:")
    print(
        "  PERMIT < FILE:",
        (r.PERMIT_DATE.notna() & r.FILE_DATE.notna()
         & (r.PERMIT_DATE.dt.normalize() < r.FILE_DATE.dt.normalize())).sum(),
    )
    print(
        "  FINAL < PERMIT:",
        (r.FINAL_DATE.notna() & r.PERMIT_DATE.notna()
         & (r.FINAL_DATE.dt.normalize() < r.PERMIT_DATE.dt.normalize())).sum(),
    )
    print(
        "  FINAL on non-Final:",
        (r.STATUS_NORMALIZED.ne("Final") & r.FINAL_DATE.notna()).sum(),
    )

    if agent_data_path:
        out_path = Path(agent_data_path) / "citrus_county_repaired_sample.parquet"
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote {out_path}")

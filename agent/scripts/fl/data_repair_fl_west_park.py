"""Data repair for West Park (FL) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

West Park DATA is a flat city-portal export with top-level Status,
Issue Date, and optionally Close Date / Work Description. Two keying
variants appear (INFERRED_SCHEMA base):

  - portal_permit_space: ``Permit #`` + ``Address `` (trailing space)
  - portal_permit:       ``Permit#``  + ``Address``

Content suffixes reflect which canonical dates parse cleanly
(``_issued_finaled`` / ``_issued`` / ``_finaled`` / ``_minimal``).

Canonical mappings:
  - Status (with Issue Date / Close Date overrides) → STATUS_NORMALIZED
  - (no application / filed date in DATA)           → FILE_DATE unavailable
  - Issue Date (when parseable as a real date)      → PERMIT_DATE
  - Close Date (when parseable as a real date)      → FINAL_DATE

Source quirks:
  - Issue Date and Close Date frequently hold work-description text
    from a shifted CSV export; non-date strings are ignored.
  - A few Status values are work descriptions; Sub Type or keyword
    hints are used when possible.

Known issues repaired:
  - Payment Needed / On Hold / Permit Ready for Pickup left
    STATUS_NORMALIZED null → FILLED as In Review (or Active when a
    real Issue Date is present).
  - Under Review / Payment Needed rows that already carry a real
    Issue Date → FIXED/FILLED to Active; PERMIT_DATE filled.
  - FINAL_DATE missing on all rows → FILLED from parseable Close Date
    for Closed / Final records.
  - Spurious PERMIT_DATE on Inactive (Expired / Cancelled / Void /
    Denied) cleared.

Not repairable from DATA:
  - No application / submittal timestamp → FILE_DATE stays missing
    on every row.
  - Closed / Approved rows whose Issue Date is description text →
    PERMIT_DATE stays missing.
  - Closed rows without a parseable Close Date → FINAL_DATE stays
    missing.
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

# Strict mm/dd/yyyy (source export format) — rejects description text that
# pandas would otherwise coerce via fuzzy parsing.
_DATE_RE = re.compile(r"^\d{1,2}/\d{1,2}/\d{2,4}$")


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
    """Parse a date value, returning pd.NaT on failure / text / OOR year."""
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return pd.NaT
    if isinstance(val, dict):
        return pd.NaT
    if isinstance(val, str):
        s = val.strip().replace("\xa0", " ")
        if not s or s.lower() in {"none", "null", "n/a", "na", "nan", "tbd"}:
            return pd.NaT
        # West Park Issue/Close Date fields often contain work descriptions.
        if not _DATE_RE.match(s):
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


def _present(dt) -> bool:
    return dt is not pd.NaT and not pd.isna(dt)


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
    elif not _dates_equal(current, cand):
        repairs[field] = cand
        repairs[f"{field}_FLAG"] = "FIXED"


def _clear_date(repairs: dict, row, field: str) -> None:
    current = repairs.get(field, row[field])
    if pd.isna(current):
        return
    repairs[field] = pd.NaT
    repairs[f"{field}_FLAG"] = "FIXED"


# ── Extractors ───────────────────────────────────────────────────────────────

def _raw_status(d: dict) -> Optional[str]:
    raw = d.get("Status")
    if raw is None:
        return None
    text = str(raw).strip()
    return text or None


def _issue_date(d: dict):
    return _safe_to_datetime(d.get("Issue Date"))


def _close_date(d: dict):
    return _safe_to_datetime(d.get("Close Date"))


# ── Status mapping ───────────────────────────────────────────────────────────

_STATUS_MAP = {
    # Final
    "Closed": "Final",
    # Active / issued / approved
    "Issued": "Active",
    "Approved": "Active",
    # In review / pre-issuance / hold
    "Under Review": "In Review",
    "Online Application Received": "In Review",
    "Payment Needed": "In Review",
    "On Hold Due to Missing Paperwork": "In Review",
    "On Hold Due to Missing Payment": "In Review",
    "Permit Ready for Pickup": "In Review",
    # Inactive
    "Denied": "Inactive",
    "Expired": "Inactive",
    "Void": "Inactive",
    "Cancelled": "Inactive",
    "Canceled": "Inactive",
}


def _derive_status_from_text(text: str) -> Optional[str]:
    """Map a free-text / shifted Status (or Sub Type) value."""
    if not text:
        return None
    if text in _STATUS_MAP:
        return _STATUS_MAP[text]
    lower_map = {k.lower(): v for k, v in _STATUS_MAP.items()}
    if text.lower() in lower_map:
        return lower_map[text.lower()]

    lower = text.lower()
    if "closed" in lower or "final" in lower or "complete" in lower:
        return "Final"
    if "denied" in lower or "expire" in lower or "void" in lower or "cancel" in lower:
        return "Inactive"
    if (
        "pending" in lower
        or "payment" in lower
        or "review" in lower
        or "on hold" in lower
        or "hold due" in lower
        or "ready for pickup" in lower
        or "application received" in lower
    ):
        return "In Review"
    if "issued" in lower or "approved" in lower:
        return "Active"
    return None


def _expected_status(d: dict) -> Optional[str]:
    raw = _raw_status(d)
    expected = _derive_status_from_text(raw) if raw else None

    # Column-shift recovery: Status holds a work description; Sub Type
    # sometimes carries the real workflow label (e.g. "Under Review").
    if expected is None:
        sub = d.get("Sub Type")
        if isinstance(sub, str) and sub.strip():
            expected = _derive_status_from_text(sub.strip())

    issued = _issue_date(d)
    closed = _close_date(d)

    # Date overrides: a parseable Close Date implies Final; a parseable
    # Issue Date on an In Review / null label implies Active.
    if _present(closed):
        return "Final"
    if expected in (None, "In Review") and _present(issued):
        return "Active"
    return expected


# ── Schema classification ────────────────────────────────────────────────────

def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())
    if "Status" not in keys:
        return "unknown"

    if "Permit #" in keys:
        base = "portal_permit_space"
    elif "Permit#" in keys:
        base = "portal_permit"
    else:
        base = "portal"

    has_issued = _present(_issue_date(data_dict))
    has_finaled = _present(_close_date(data_dict))

    if has_issued and has_finaled:
        return f"{base}_issued_finaled"
    if has_issued:
        return f"{base}_issued"
    if has_finaled:
        return f"{base}_finaled"
    return f"{base}_minimal"


# ── Per-record repair ────────────────────────────────────────────────────────

def _repair_record(row, d: dict, repairs: dict) -> None:
    expected = _expected_status(d)
    effective_status = _apply_status(repairs, row["STATUS_NORMALIZED"], expected)

    issued = _issue_date(d)
    closed = _close_date(d)

    # -- FILE_DATE --
    # No application / submittal / filed date exists in the West Park
    # export. Nothing to fill or fix.

    # -- PERMIT_DATE ← Issue Date for Active/Final only --
    if effective_status in ("Active", "Final"):
        if _present(issued):
            _apply_date(repairs, row, "PERMIT_DATE", issued)
    else:
        _clear_date(repairs, row, "PERMIT_DATE")

    # -- FINAL_DATE ← Close Date for Final only --
    if effective_status == "Final":
        if _present(closed):
            _apply_date(repairs, row, "FINAL_DATE", closed)
    else:
        _clear_date(repairs, row, "FINAL_DATE")


# ── Main entry point ─────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    West Park permit records using information from the raw DATA JSON.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "West Park". Must contain
        columns STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, FINAL_DATE,
        and DATA.

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
        if d is None or schema == "unknown":
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
    city = df[(df["JURISDICTION"] == "West Park") & (df["STATE"] == "FL")].copy()

    print(f"West Park records: {len(city):,}\n")
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

    print("\nStatus transitions (before → after):")
    mask = repaired["STATUS_NORMALIZED_FLAG"].notna()
    if mask.any():
        transitions = (
            pd.DataFrame({
                "before": city.loc[mask, "STATUS_NORMALIZED"].fillna("nan").astype(str),
                "after": repaired.loc[mask, "STATUS_NORMALIZED"].fillna("nan").astype(str),
            })
            .value_counts()
            .reset_index(name="n")
        )
        for _, trow in transitions.iterrows():
            print(f"  {trow['before']:15s} → {trow['after']:15s}: {trow['n']:>4,}")
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
                f"{n_has:>4,} / {len(sub):>4,} ({n_has / len(sub):.1%})"
            )

    af = repaired[repaired["STATUS_NORMALIZED"].isin(["Active", "Final"])]
    print(
        f"\nActive/Final missing PERMIT_DATE: "
        f"{af['PERMIT_DATE'].isna().sum()} / {len(af)}"
    )
    final = repaired[repaired["STATUS_NORMALIZED"] == "Final"]
    print(
        f"Final missing FINAL_DATE: "
        f"{final['FINAL_DATE'].isna().sum()} / {len(final)}"
    )
    print(f"Any missing FILE_DATE: {repaired['FILE_DATE'].isna().sum()}")

    pd_ = repaired["PERMIT_DATE"]
    ff = repaired["FINAL_DATE"]
    both = pd_.notna() & ff.notna()
    n_inv = (both & (pd_.dt.normalize() > ff.dt.normalize())).sum()
    print(f"PERMIT_DATE > FINAL_DATE inversions: {n_inv}")

    if agent_data_path:
        out_dir = Path(agent_data_path) / "repaired"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "permits_fl_west_park_repaired.parquet"
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote repaired sample → {out_path}")

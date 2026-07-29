"""Data repair for Twentynine Palms (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Twentynine Palms DATA is a flat scraped-table payload. Key naming and
optional columns vary across four sub-schemas:

  - compact_keys_with_work: Address / Permit# + Work Description
  - spaced_keys_with_work:  Address  / Permit # + Work Description
  - compact_keys:           Address / Permit# (no Work Description)
  - spaced_keys:            Address  / Permit # (no Work Description)

Canonical fields:
  - Status      → STATUS_NORMALIZED
  - Issue Date  → PERMIT_DATE (when parseable as a date)

Known issues repaired:
  - Null STATUS_NORMALIZED on ``Changes Required`` / ``Payment Needed``
    (and one ``Issued`` row whose STATUS_ORIGINAL was payment needed)
    → FILLED.
  - ``Final`` / ``Closed`` shells left Active → FIXED to Final.
  - ``Payment Needed`` left Active despite Status label → FIXED via
    Issue Date override to Active when a real issue stamp exists, else
    In Review.
  - Stale ``In Plan Review`` / ``On Hold`` rows with a parseable
    Issue Date left In Review → FIXED to Active.
  - One ``Issued`` Active/null row missing PERMIT_DATE while Issue Date
    is present → FILLED.
  - Column-shift corruption where Status holds a date and Issue Date
    holds work-description text → recover Issue Date from Status and
    treat as Active.

Not repairable / left as-is:
  - FILE_DATE is null for every sample row; DATA has no application /
    submittal date field.
  - FINAL_DATE is null for every sample row; DATA has no finaled /
    completion / signoff date field.
  - ~395 rows have a non-date string in Issue Date (work description /
    subtype text from a shifted column). PERMIT_DATE stays missing.
  - Two fully corrupted shells (Status = ``Commercial - Motel``; Status
    missing with no Issue Date) cannot be mapped.
"""

from __future__ import annotations

import json
import math
import re
from typing import Optional

import numpy as np
import pandas as pd


_MIN_YEAR = 1990
_MAX_YEAR = 2035

# MM/DD/YYYY (with optional time) — used to detect date-in-Status corruption.
_DATE_IN_STATUS_RE = re.compile(
    r"^\s*\d{1,2}/\d{1,2}/\d{2,4}(?:\s+\d{1,2}:\d{2}(?::\d{2})?)?\s*$"
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
        return json.loads(data)
    return data


def _safe_to_datetime(val):
    """Parse a date value as UTC, returning pd.NaT on failure or sentinel."""
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return pd.NaT
    if isinstance(val, str) and not str(val).strip():
        return pd.NaT
    # Reject obvious non-dates early (work-description text in Issue Date).
    if isinstance(val, str):
        s = val.strip()
        # pandas may coerce bare years / numeric junk; require a date-like token.
        if not re.search(r"\d{1,4}", s):
            return pd.NaT
        if not re.search(r"[/\-]", s) and not re.search(
            r"\d{4}-\d{2}-\d{2}", s
        ):
            # Allow ISO-ish and slash dates only; reject "Reroof", "Gas Line", etc.
            # Also reject pure integers that aren't year-month-day shaped.
            if not re.match(r"^\d{4}$", s):
                return pd.NaT
    try:
        dt = pd.to_datetime(val, utc=True, errors="coerce")
    except (ValueError, TypeError):
        return pd.NaT
    if dt is pd.NaT or pd.isna(dt):
        return pd.NaT
    year = int(dt.year)
    if year < _MIN_YEAR or year > _MAX_YEAR:
        return pd.NaT
    return dt


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())
    has_wd = "Work Description" in keys
    spaced = ("Address " in keys) or ("Permit #" in keys)
    compact = ("Address" in keys) or ("Permit#" in keys)
    if spaced and has_wd:
        return "spaced_keys_with_work"
    if spaced:
        return "spaced_keys"
    if compact and has_wd:
        return "compact_keys_with_work"
    if compact:
        return "compact_keys"
    return "unknown"


def _raw_status(d: dict) -> Optional[str]:
    raw = d.get("Status")
    if raw is None:
        return None
    s = str(raw).strip()
    return s if s else None


def _issue_date(d: dict):
    """UTC Issue Date, recovering from Status when columns are shifted."""
    issue = _safe_to_datetime(d.get("Issue Date"))
    if issue is not pd.NaT:
        return issue
    # Column-shift: Status holds MM/DD/YYYY and Issue Date holds description.
    status = _raw_status(d)
    if status and _DATE_IN_STATUS_RE.match(status):
        return _safe_to_datetime(status)
    return pd.NaT


def _dates_equal(a, b) -> bool:
    """Compare two datelike values at calendar-day resolution (UTC)."""
    da = _safe_to_datetime(a)
    db = _safe_to_datetime(b)
    if da is pd.NaT or db is pd.NaT:
        return False
    return da.date() == db.date()


# ── Status mapping ──────────────────────────────────────────────────────────

_STATUS_MAP = {
    # Final
    "Closed": "Final",
    "Final": "Final",
    "Finaled": "Final",
    "Complete": "Final",
    # Active
    "Issued": "Active",
    "Active": "Active",
    # Inactive
    "Void": "Inactive",
    "Voided": "Inactive",
    "Expired": "Inactive",
    "Withdrawn": "Inactive",
    "Canceled": "Inactive",
    "Cancelled": "Inactive",
    "Denied": "Inactive",
    # In Review
    "In Plan Review": "In Review",
    "Under Review": "In Review",
    "Changes Required": "In Review",
    "Payment Needed": "In Review",
    "Online Application Received": "In Review",
    "On Hold": "In Review",
    "In Review": "In Review",
}

_INACTIVE_LABELS = {
    "Void",
    "Voided",
    "Expired",
    "Withdrawn",
    "Canceled",
    "Cancelled",
    "Denied",
}

_FINAL_LABELS = {
    "Closed",
    "Final",
    "Finaled",
    "Complete",
}


def _mapped_status(raw: Optional[str]) -> Optional[str]:
    if raw is None:
        return None
    mapped = _STATUS_MAP.get(raw)
    if mapped is not None:
        return mapped
    lower = raw.lower()
    if lower in {"closed", "final", "finaled", "complete", "completed"}:
        return "Final"
    if lower.startswith("issued") or lower == "active":
        return "Active"
    if any(
        tok in lower
        for tok in ("void", "expired", "withdrawn", "cancel", "denied", "revoked")
    ):
        return "Inactive"
    if any(
        tok in lower
        for tok in (
            "review",
            "changes required",
            "payment",
            "on hold",
            "application received",
            "pending",
            "submitted",
        )
    ):
        return "In Review"
    return None


def _expected_status(d: dict) -> Optional[str]:
    """Derive STATUS_NORMALIZED from Status with Issue Date overrides.

    Inactive terminal labels (Void / Expired / Withdrawn) are sticky even
    when Issue Date is present (permit may have been issued then voided /
    expired). Explicit Closed / Final labels → Final. Otherwise a
    parseable Issue Date (including date recovered from a corrupted
    Status field) → Active, overriding stale In Plan Review / Payment
    Needed / On Hold labels. Else fall back to the Status map.
    """
    raw = _raw_status(d)

    # Date-in-Status corruption: no usable label; Issue Date recovered below.
    if raw and _DATE_IN_STATUS_RE.match(raw):
        if _issue_date(d) is not pd.NaT:
            return "Active"
        return None

    if raw in _INACTIVE_LABELS:
        return "Inactive"

    if raw in _FINAL_LABELS:
        return "Final"

    if _issue_date(d) is not pd.NaT:
        return "Active"

    return _mapped_status(raw)


# ── Per-record repair logic ─────────────────────────────────────────────────

def _repair_record(row, d: dict, repairs: dict):
    """Populate *repairs* with corrected values for a single record."""
    current_status = row["STATUS_NORMALIZED"]
    expected = _expected_status(d)

    # -- STATUS_NORMALIZED --
    if expected is not None:
        if pd.isna(current_status):
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"
        elif current_status != expected:
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FIXED"

    effective_status = repairs.get("STATUS_NORMALIZED", current_status)

    # -- FILE_DATE --
    # DATA has no application / submittal date. Nothing to fill or fix.

    # -- PERMIT_DATE (issuance / Issue Date) --
    issue = _issue_date(d)
    current_permit = row["PERMIT_DATE"]

    if not pd.isna(current_permit):
        if issue is not pd.NaT and not _dates_equal(current_permit, issue):
            repairs["PERMIT_DATE"] = issue
            repairs["PERMIT_DATE_FLAG"] = "FIXED"
        elif (
            effective_status == "In Review"
            and issue is pd.NaT
        ):
            # Spurious permit date on a non-issued review row.
            repairs["PERMIT_DATE"] = pd.NaT
            repairs["PERMIT_DATE_FLAG"] = "FIXED"
    elif effective_status in ("Active", "Final") and issue is not pd.NaT:
        repairs["PERMIT_DATE"] = issue
        repairs["PERMIT_DATE_FLAG"] = "FILLED"
    elif (
        effective_status == "Inactive"
        and issue is not pd.NaT
        and pd.isna(current_permit)
    ):
        # Optional: fill issuance stamp on voided/expired shells that had one.
        repairs["PERMIT_DATE"] = issue
        repairs["PERMIT_DATE_FLAG"] = "FILLED"

    # -- FINAL_DATE --
    # DATA has no finaled / completion date. Clear any spurious FINAL_DATE
    # on non-Final rows if present (none in the sample).
    current_final = row["FINAL_DATE"]
    if effective_status != "Final" and not pd.isna(current_final):
        repairs["FINAL_DATE"] = pd.NaT
        repairs["FINAL_DATE_FLAG"] = "FIXED"


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Twentynine Palms permit records using information from the raw DATA JSON.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Twentynine Palms".  Must
        contain columns STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE,
        FINAL_DATE, and DATA.

    Returns
    -------
    pd.DataFrame
        Copy of *df* with corrected field values, an INFERRED_SCHEMA column
        naming the DATA JSON schema identified for each record, and new
        flag columns: STATUS_NORMALIZED_FLAG, FILE_DATE_FLAG,
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
        _repair_record(row, d, repairs)

        for key, value in repairs.items():
            out.at[idx, key] = value

    for col in ("FILE_DATE", "PERMIT_DATE", "FINAL_DATE"):
        if col in out.columns:
            out[col] = pd.to_datetime(out[col], utc=True, errors="coerce")

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
        MY_DATA_PATH, "processed_data", "permits_ca_sample.parquet"
    )
    df = pd.read_parquet(filepath)
    city = df[
        (df["JURISDICTION"] == "Twentynine Palms") & (df["STATE"] == "CA")
    ].copy()

    print(f"Twentynine Palms records: {len(city):,}\n")

    repaired = data_repair(city)

    if AGENT_DATA_PATH:
        out_dir = Path(AGENT_DATA_PATH) / "repaired"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "permits_ca_twentynine_palms_repaired.parquet"
        repaired.to_parquet(out_path, index=False)
        print(f"Wrote {out_path}\n")

    print("INFERRED_SCHEMA:")
    print(repaired["INFERRED_SCHEMA"].value_counts(dropna=False).to_string())
    print()

    for field in ["STATUS_NORMALIZED", "FILE_DATE", "PERMIT_DATE", "FINAL_DATE"]:
        flag_col = f"{field}_FLAG"
        n_filled = (repaired[flag_col] == "FILLED").sum()
        n_fixed = (repaired[flag_col] == "FIXED").sum()
        print(f"{field}:")
        print(f"  FILLED: {n_filled:>4,}   FIXED: {n_fixed:>4,}")

        before_missing = city[field].isna().sum()
        after_missing = repaired[field].isna().sum()
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

    print("\nPERMIT_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["PERMIT_DATE"].notna().sum()
        n = len(sub)
        pct = n_has / n if n else 0.0
        print(f"  {status:15s}: {n_has:>4,} / {n:>4,} ({pct:.1%})")

    print("\nFINAL_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FINAL_DATE"].notna().sum()
        n = len(sub)
        pct = n_has / n if n else 0.0
        print(f"  {status:15s}: {n_has:>4,} / {n:>4,} ({pct:.1%})")

    print("\nFILE_DATE coverage (after repair):")
    n_has = repaired["FILE_DATE"].notna().sum()
    print(f"  {n_has:>4,} / {len(repaired):>4,} ({n_has / len(repaired):.1%})")

    fd = pd.to_datetime(repaired["FILE_DATE"], utc=True, errors="coerce")
    pd_ = pd.to_datetime(repaired["PERMIT_DATE"], utc=True, errors="coerce")
    ff = pd.to_datetime(repaired["FINAL_DATE"], utc=True, errors="coerce")
    both_fp = fd.notna() & pd_.notna()
    both_pf = pd_.notna() & ff.notna()
    print("\nChronology inversions:")
    print(f"  FILE > PERMIT: {(both_fp & (fd.dt.normalize() > pd_.dt.normalize())).sum()}")
    print(f"  PERMIT > FINAL: {(both_pf & (pd_.dt.normalize() > ff.dt.normalize())).sum()}")

    print("\nRemaining ideal-coverage gaps:")
    active_final = repaired["STATUS_NORMALIZED"].isin(["Active", "Final"])
    final = repaired["STATUS_NORMALIZED"] == "Final"
    print(
        f"  Active/Final missing PERMIT_DATE: "
        f"{(active_final & repaired['PERMIT_DATE'].isna()).sum()}"
    )
    print(
        f"  Final missing FINAL_DATE: "
        f"{(final & repaired['FINAL_DATE'].isna()).sum()}"
    )
    print(f"  Any missing FILE_DATE: {repaired['FILE_DATE'].isna().sum()}")
    print(f"  Any missing STATUS_NORMALIZED: {repaired['STATUS_NORMALIZED'].isna().sum()}")

    from collections import Counter

    print("\nActive/Final still missing PERMIT_DATE (by Status):")
    gap = Counter()
    for idx in repaired.index:
        if repaired.at[idx, "STATUS_NORMALIZED"] not in ("Active", "Final"):
            continue
        if pd.notna(repaired.at[idx, "PERMIT_DATE"]):
            continue
        d = _safe_parse(city.at[idx, "DATA"])
        gap[(d or {}).get("Status")] += 1
    for k, v in gap.most_common():
        print(f"  {k}: {v}")

    print("\nRemaining null STATUS (raw Status):")
    for idx in repaired.index:
        if pd.notna(repaired.at[idx, "STATUS_NORMALIZED"]):
            continue
        d = _safe_parse(city.at[idx, "DATA"])
        print(f"  Status={(d or {}).get('Status')!r} keys={sorted((d or {}).keys())}")

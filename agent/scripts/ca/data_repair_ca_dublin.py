"""Data repair for Dublin (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Dublin DATA is a single Accela-style payload with top-level keys
``main``, ``details``, ``fees``, ``address``, ``parcel``, ``actions``,
``routing``, ``valuation``, ``conditions``, ``contractors``,
``description``, and ``permit_number``. Canonical fields live under
``main``:

  - Status    → STATUS_NORMALIZED
  - Applied   → FILE_DATE
  - Issued (fallback: Approved) → PERMIT_DATE
  - Final     → FINAL_DATE

Content variants (same keys; differ by which date fields are populated):

  - main_issued_finaled: Issued + Final present
  - main_issued:         Issued present, Final blank
  - main_finaled_only:   Final present, Issued blank
  - main_approved_only:  Approved present, Issued/Final blank
  - main_applied_only:   only Applied populated
  - main_empty:          ``main`` is ``{}``
  - missing / unknown:   null DATA or unrecognized top-level keys

Known issues repaired:
  - Active ``approved`` rows missing PERMIT_DATE → FILLED from Approved
    (Issued is blank).
  - Final rows missing PERMIT_DATE with blank Issued but Approved
    present → FILLED from Approved.
  - Spurious FINAL_DATE on canceled Inactive rows (copied from
    ``main.Final``, a close/void stamp) → cleared.

Not repairable / left as-is:
  - STATUS_NORMALIZED already matches ``main.Status`` for every sample
    row (final→Final, issued/approved→Active, pending→In Review,
    expired/canceled→Inactive).
  - FILE_DATE already matches ``main.Applied`` on every row.
  - 18 Final planning / zoning / addressing shells with blank
    ``main.Final`` and empty ``actions`` → FINAL_DATE stays missing.
  - ``Expires`` is a validity window, not a completion date.
  - Action-level ``* FINAL *`` inspection dates often disagree with
    ``main.Final``; do not override ``main.Final`` from actions.
"""

from __future__ import annotations

import json
import math
from typing import Optional

import numpy as np
import pandas as pd


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
    """Parse a date value, returning pd.NaT on failure."""
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return pd.NaT
    if isinstance(val, str) and not str(val).strip():
        return pd.NaT
    try:
        dt = pd.to_datetime(val)
    except (ValueError, TypeError):
        return pd.NaT
    if dt is pd.NaT or pd.isna(dt):
        return pd.NaT
    if getattr(dt, "tzinfo", None) is not None:
        dt = dt.tz_convert("UTC").tz_localize(None)
    return dt


def _dates_equal(a, b) -> bool:
    """Compare two datelike values at calendar-day resolution."""
    da = _safe_to_datetime(a)
    db = _safe_to_datetime(b)
    if da is pd.NaT or db is pd.NaT or pd.isna(da) or pd.isna(db):
        return False
    return da.normalize() == db.normalize()


def _main(d: dict) -> dict:
    main = d.get("main")
    return main if isinstance(main, dict) else {}


def _main_status(d: dict) -> Optional[str]:
    status = _main(d).get("Status")
    if status is None:
        return None
    status = str(status).strip().lower()
    return status or None


def _main_date(d: dict, *keys: str):
    main = _main(d)
    for key in keys:
        dt = _safe_to_datetime(main.get(key))
        if dt is not pd.NaT:
            return dt
    return pd.NaT


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())
    if "main" not in keys:
        return "unknown"
    main = _main(data_dict)
    if not main:
        return "main_empty"

    issued = _safe_to_datetime(main.get("Issued"))
    finaled = _safe_to_datetime(main.get("Final"))
    approved = _safe_to_datetime(main.get("Approved"))
    applied = _safe_to_datetime(main.get("Applied"))

    has_issued = issued is not pd.NaT
    has_finaled = finaled is not pd.NaT
    has_approved = approved is not pd.NaT
    has_applied = applied is not pd.NaT

    if has_issued and has_finaled:
        return "main_issued_finaled"
    if has_issued:
        return "main_issued"
    if has_finaled:
        return "main_finaled_only"
    if has_approved:
        return "main_approved_only"
    if has_applied:
        return "main_applied_only"
    return "main_empty_dates"


# ── Status mapping ──────────────────────────────────────────────────────────

# main.Status (lowercase as stored in DATA) → STATUS_NORMALIZED
_STATUS_MAP = {
    "final": "Final",
    "issued": "Active",
    "approved": "Active",
    "pending": "In Review",
    "expired": "Inactive",
    "canceled": "Inactive",
    "cancelled": "Inactive",
}


# ── Per-record repair logic ─────────────────────────────────────────────────

def _repair_record(row, d: dict, repairs: dict):
    """Populate *repairs* with corrected values for a single Dublin record."""
    current_status = row["STATUS_NORMALIZED"]
    raw_status = _main_status(d)
    expected = _STATUS_MAP.get(raw_status) if raw_status else None

    # -- STATUS_NORMALIZED --
    if expected is not None:
        if pd.isna(current_status):
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"
        elif current_status != expected:
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FIXED"

    effective_status = repairs.get("STATUS_NORMALIZED", current_status)

    # -- FILE_DATE (application / Applied) --
    applied = _main_date(d, "Applied")
    if applied is not pd.NaT:
        if pd.isna(row["FILE_DATE"]):
            repairs["FILE_DATE"] = applied
            repairs["FILE_DATE_FLAG"] = "FILLED"
        elif not _dates_equal(row["FILE_DATE"], applied):
            repairs["FILE_DATE"] = applied
            repairs["FILE_DATE_FLAG"] = "FIXED"

    # -- PERMIT_DATE (issuance / Issued; fallback Approved) --
    issued = _main_date(d, "Issued")
    approved = _main_date(d, "Approved")
    permit_src = issued if issued is not pd.NaT else approved

    if not pd.isna(row["PERMIT_DATE"]):
        if issued is not pd.NaT and not _dates_equal(row["PERMIT_DATE"], issued):
            repairs["PERMIT_DATE"] = issued
            repairs["PERMIT_DATE_FLAG"] = "FIXED"
        elif (
            issued is pd.NaT
            and permit_src is not pd.NaT
            and not _dates_equal(row["PERMIT_DATE"], permit_src)
        ):
            repairs["PERMIT_DATE"] = permit_src
            repairs["PERMIT_DATE_FLAG"] = "FIXED"
    elif effective_status in ("Active", "Final") and permit_src is not pd.NaT:
        repairs["PERMIT_DATE"] = permit_src
        repairs["PERMIT_DATE_FLAG"] = "FILLED"

    # -- FINAL_DATE (finaled / Final; not Expires) --
    final = _main_date(d, "Final")
    current_final = row["FINAL_DATE"]

    if effective_status == "Final":
        if final is not pd.NaT:
            if pd.isna(current_final):
                repairs["FINAL_DATE"] = final
                repairs["FINAL_DATE_FLAG"] = "FILLED"
            elif not _dates_equal(current_final, final):
                repairs["FINAL_DATE"] = final
                repairs["FINAL_DATE_FLAG"] = "FIXED"
    elif not pd.isna(current_final):
        # Spurious FINAL_DATE on non-Final rows (canceled with a Final
        # date that is a close/void stamp, not a permit sign-off).
        repairs["FINAL_DATE"] = pd.NaT
        repairs["FINAL_DATE_FLAG"] = "FIXED"


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Dublin permit records using information from the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Dublin".  Must contain
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

    return out


# ── CLI: run standalone to preview repair stats ─────────────────────────────

if __name__ == "__main__":
    import os
    from pathlib import Path
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[3] / ".env")
    MY_DATA_PATH = os.getenv("MY_DATA_PATH")
    AGENT_DATA_PATH = os.getenv("AGENT_DATA_PATH")
    filepath = os.path.join(MY_DATA_PATH, "processed_data", "permits_ca_sample.parquet")
    df = pd.read_parquet(filepath)
    city = df[(df["JURISDICTION"] == "Dublin") & (df["STATE"] == "CA")].copy()

    print(f"Dublin records: {len(city):,}\n")

    repaired = data_repair(city)

    if AGENT_DATA_PATH:
        out_dir = Path(AGENT_DATA_PATH) / "repaired"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "permits_ca_dublin_repaired.parquet"
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
    print(repaired["STATUS_NORMALIZED_FLAG"].value_counts(dropna=False).to_string())

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

    # Chronology sanity
    print("\nChronology checks (after repair):")
    f = pd.to_datetime(repaired["FILE_DATE"], errors="coerce")
    p = pd.to_datetime(repaired["PERMIT_DATE"], errors="coerce")
    fin = pd.to_datetime(repaired["FINAL_DATE"], errors="coerce")
    inv_fp = f.notna() & p.notna() & (p.dt.normalize() < f.dt.normalize())
    inv_pf = p.notna() & fin.notna() & (fin.dt.normalize() < p.dt.normalize())
    print(f"  PERMIT < FILE: {inv_fp.sum()}")
    print(f"  FINAL < PERMIT: {inv_pf.sum()}")

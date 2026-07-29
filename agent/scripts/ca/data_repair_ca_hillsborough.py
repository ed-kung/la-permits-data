"""Data repair for Hillsborough (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Hillsborough DATA is a civic portal payload with top-level keys
``fees``, ``contacts``, ``site_info``, ``inspections``,
``permit_info``, and ``search_data``. In this sample, ``permit_info``
status / issued / approved / finaled fields are blank for every row;
usable workflow dates live under ``search_data`` (with
``permit_info.PermitAppliedDate`` populated only on the long-key
variant).

Two ``search_data`` key-set variants appear:

  - search_short: Applied / Issued / Approved / Finaled
  - search_long:  Application Date / Issued Date / Finaled Date
                  (+ PermitAppliedDate under permit_info)

Content subtypes (same keys; differ by which dates are populated):

  - search_short_issued_finaled
  - search_short_issued
  - search_short_finaled_only
  - search_short_approved_only
  - search_short_applied_only
  - search_short_empty_dates
  - search_long_applied_only
  - search_long_empty_dates

Known issues repaired:
  - STATUS_NORMALIZED missing on every row → FILLED from dates /
    VOID-like Description text (Finaled → Final, Issued/Approved →
    Active, Applied only → In Review, void/cancel/reuse/test shells →
    Inactive).
  - FILE_DATE missing when Applied / Application Date /
    PermitAppliedDate is present → FILLED.
  - PERMIT_DATE missing on Active/Final when Issued (fallback Approved)
    is present → FILLED.
  - FINAL_DATE missing on Final when Finaled is present → FILLED.

Not repairable / left as-is:
  - Empty-date shells with no VOID/reuse/test cue → STATUS stays
    missing; no dates to fill.
  - Final rows with neither Issued nor Approved → PERMIT_DATE stays
    missing.
  - Active/Final rows with null Issued and null Approved → PERMIT_DATE
    stays missing.
  - Final rows with null Finaled (should not occur after status
    inference, since Final requires Finaled unless mislabeled) →
    FINAL_DATE stays missing.
  - VOID shells that carry Finaled stamps stay Inactive; Finaled is
    treated as a close/void stamp, not a permit finaled date.
"""

from __future__ import annotations

import json
import math
import re
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
    if isinstance(val, str) and not val.strip():
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


def _permit_info(d: dict) -> dict:
    pi = d.get("permit_info")
    return pi if isinstance(pi, dict) else {}


def _search_data(d: dict) -> dict:
    sd = d.get("search_data")
    return sd if isinstance(sd, dict) else {}


def _description(d: dict) -> str:
    sd = _search_data(d)
    pi = _permit_info(d)
    parts = [
        str(sd.get("Description") or ""),
        str(pi.get("PermitDesc") or ""),
        str(pi.get("PermitNotes") or ""),
    ]
    return " ".join(p for p in parts if p).strip()


_VOID_RE = re.compile(
    r"(?i)\b(void|cancel(?:led|ed)?|withdraw(?:n)?|denied?|abandon(?:ed)?)\b"
)
_JUNK_RE = re.compile(r"(?i)^\s*(test|reuse|re-use|re_use)\s*$")


def _is_void_like(d: dict) -> bool:
    desc = _description(d)
    if not desc:
        return False
    if _VOID_RE.search(desc):
        return True
    if _JUNK_RE.match(desc):
        return True
    return False


def _applied_date(d: dict):
    pi = _permit_info(d)
    sd = _search_data(d)
    for src in (
        pi.get("PermitAppliedDate"),
        sd.get("Applied"),
        sd.get("Application Date"),
        sd.get("Application"),
    ):
        dt = _safe_to_datetime(src)
        if dt is not pd.NaT:
            return dt
    return pd.NaT


def _issued_date(d: dict):
    pi = _permit_info(d)
    sd = _search_data(d)
    for src in (
        pi.get("PermitIssuedDate"),
        sd.get("Issued"),
        sd.get("Issued Date"),
    ):
        dt = _safe_to_datetime(src)
        if dt is not pd.NaT:
            return dt
    return pd.NaT


def _approved_date(d: dict):
    pi = _permit_info(d)
    sd = _search_data(d)
    for src in (
        pi.get("PermitApprovedDate"),
        sd.get("Approved"),
        sd.get("Approved Date"),
    ):
        dt = _safe_to_datetime(src)
        if dt is not pd.NaT:
            return dt
    return pd.NaT


def _finaled_date(d: dict):
    pi = _permit_info(d)
    sd = _search_data(d)
    for src in (
        pi.get("PermitFinaledDate"),
        sd.get("Finaled"),
        sd.get("Finaled Date"),
    ):
        dt = _safe_to_datetime(src)
        if dt is not pd.NaT:
            return dt
    return pd.NaT


def _preferred_permit_date(d: dict):
    issued = _issued_date(d)
    if issued is not pd.NaT:
        return issued
    return _approved_date(d)


def _search_variant(d: dict) -> str:
    sd = _search_data(d)
    if "Applied" in sd or "Issued" in sd or "Finaled" in sd or "Approved" in sd:
        return "search_short"
    if (
        "Application Date" in sd
        or "Issued Date" in sd
        or "Finaled Date" in sd
    ):
        return "search_long"
    if _permit_info(d):
        return "search_long" if _safe_to_datetime(
            _permit_info(d).get("PermitAppliedDate")
        ) is not pd.NaT else "unknown"
    return "unknown"


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())
    if "search_data" not in keys and "permit_info" not in keys:
        return "unknown"

    variant = _search_variant(data_dict)
    if variant == "unknown":
        return "unknown"

    has_issued = _issued_date(data_dict) is not pd.NaT
    has_finaled = _finaled_date(data_dict) is not pd.NaT
    has_approved = _approved_date(data_dict) is not pd.NaT
    has_applied = _applied_date(data_dict) is not pd.NaT

    if has_issued and has_finaled:
        suffix = "issued_finaled"
    elif has_issued:
        suffix = "issued"
    elif has_finaled:
        suffix = "finaled_only"
    elif has_approved:
        suffix = "approved_only"
    elif has_applied:
        suffix = "applied_only"
    else:
        suffix = "empty_dates"

    return f"{variant}_{suffix}"


# ── Status / date repair ────────────────────────────────────────────────────

def _derive_status(d: dict) -> Optional[str]:
    """Infer STATUS_NORMALIZED from Description + workflow dates.

    PermitStatus is blank for every Hillsborough sample row, so status is
    driven entirely by search_data dates and VOID-like description text.
    """
    if _is_void_like(d):
        return "Inactive"

    finaled = _finaled_date(d)
    issued = _issued_date(d)
    approved = _approved_date(d)
    applied = _applied_date(d)

    if finaled is not pd.NaT:
        return "Final"
    if issued is not pd.NaT or approved is not pd.NaT:
        return "Active"
    if applied is not pd.NaT:
        return "In Review"

    # Empty shells with no cue stay missing.
    return None


def _repair_record(row, d: dict, repairs: dict):
    """Populate *repairs* with corrected values for a single record."""
    # -- STATUS_NORMALIZED --
    current_status = row["STATUS_NORMALIZED"]
    expected = _derive_status(d)
    if expected is not None:
        if pd.isna(current_status):
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"
        elif current_status != expected:
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FIXED"

    effective_status = repairs.get("STATUS_NORMALIZED", current_status)

    # -- FILE_DATE (application / Applied) --
    applied = _applied_date(d)
    if applied is not pd.NaT:
        if pd.isna(row["FILE_DATE"]):
            repairs["FILE_DATE"] = applied
            repairs["FILE_DATE_FLAG"] = "FILLED"
        elif not _dates_equal(row["FILE_DATE"], applied):
            repairs["FILE_DATE"] = applied
            repairs["FILE_DATE_FLAG"] = "FIXED"

    # -- PERMIT_DATE (Issued; fallback Approved) --
    issued = _issued_date(d)
    permit_src = _preferred_permit_date(d)

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

    # -- FINAL_DATE --
    preferred_final = _finaled_date(d)
    current_final = row["FINAL_DATE"]

    if effective_status == "Final":
        if preferred_final is not pd.NaT:
            if pd.isna(current_final):
                repairs["FINAL_DATE"] = preferred_final
                repairs["FINAL_DATE_FLAG"] = "FILLED"
            elif not _dates_equal(current_final, preferred_final):
                repairs["FINAL_DATE"] = preferred_final
                repairs["FINAL_DATE_FLAG"] = "FIXED"
    elif not pd.isna(current_final):
        # Spurious FINAL_DATE on non-Final rows (incl. VOID close stamps).
        repairs["FINAL_DATE"] = pd.NaT
        repairs["FINAL_DATE_FLAG"] = "FIXED"


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Hillsborough permit records using information from the raw DATA JSON.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Hillsborough".  Must contain
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

    # Normalize date columns (source sample uses datetime.date objects;
    # repairs insert Timestamps — unify for parquet compatibility).
    for col in ["FILE_DATE", "PERMIT_DATE", "FINAL_DATE"]:
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
    filepath = os.path.join(MY_DATA_PATH, "processed_data", "permits_ca_sample.parquet")
    df = pd.read_parquet(filepath)
    city = df[(df["JURISDICTION"] == "Hillsborough") & (df["STATE"] == "CA")].copy()

    print(f"Hillsborough records: {len(city):,}\n")

    repaired = data_repair(city)

    if AGENT_DATA_PATH:
        out_dir = Path(AGENT_DATA_PATH) / "repaired"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "permits_ca_hillsborough_repaired.parquet"
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

    print("\nSTATUS transitions (where flagged):")
    flagged = repaired[repaired["STATUS_NORMALIZED_FLAG"].notna()].copy()
    flagged["before"] = city.loc[flagged.index, "STATUS_NORMALIZED"]
    print(
        flagged.groupby(
            [flagged["before"].fillna("(null)"), "STATUS_NORMALIZED", "STATUS_NORMALIZED_FLAG"]
        )
        .size()
        .rename("n")
        .reset_index()
        .to_string(index=False)
    )

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

    print("\nFILE_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FILE_DATE"].notna().sum()
        n = len(sub)
        pct = n_has / n if n else 0.0
        print(f"  {status:15s}: {n_has:>4,} / {n:>4,} ({pct:.1%})")

    print("\nChronology checks (after repair):")
    f = pd.to_datetime(repaired["FILE_DATE"], errors="coerce")
    p = pd.to_datetime(repaired["PERMIT_DATE"], errors="coerce")
    fin = pd.to_datetime(repaired["FINAL_DATE"], errors="coerce")
    inv_fp = f.notna() & p.notna() & (p.dt.normalize() < f.dt.normalize())
    inv_pf = p.notna() & fin.notna() & (fin.dt.normalize() < p.dt.normalize())
    print(f"  PERMIT < FILE: {inv_fp.sum()}")
    print(f"  FINAL < PERMIT: {inv_pf.sum()}")

    # Remaining gaps
    print("\nRemaining Active/Final without PERMIT_DATE:")
    for status in ["Active", "Final"]:
        sub = repaired[
            (repaired["STATUS_NORMALIZED"] == status) & repaired["PERMIT_DATE"].isna()
        ]
        print(f"  {status}: {len(sub)}")
        for _, r in sub.head(5).iterrows():
            sd = _safe_parse(r["DATA"]).get("search_data") or {}
            print(f"    {r['PERMIT_NUMBER']} schema={r['INFERRED_SCHEMA']} sd={sd}")

    print("\nRemaining status-null rows:")
    null_status = repaired[repaired["STATUS_NORMALIZED"].isna()]
    print(f"  n={len(null_status)}")
    for _, r in null_status.iterrows():
        sd = _safe_parse(r["DATA"]).get("search_data") or {}
        print(f"    {r['PERMIT_NUMBER']} Desc={sd.get('Description')!r} schema={r['INFERRED_SCHEMA']}")

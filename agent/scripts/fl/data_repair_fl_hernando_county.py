"""Data repair for Hernando County (FL) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Hernando County DATA is a county portal payload with a uniform top-level
key set (Parcel info / Permit info / Application Progress History /
Inspection History / Payments / …). Canonical fields:

  - Permit info['Appl Status: ']           → STATUS_NORMALIZED
  - Parcel info['Application Date']        → FILE_DATE
  - Parcel info['Permit Date'] else
    earliest PERMIT ISSUED progress mark
    else earliest PERMIT FEE payment       → PERMIT_DATE
  - Latest Inspection History Insp Date
    among Status FINALED and FINAL*
    types with COMPLETED OK /
    ELECTRICAL RELEASE                     → FINAL_DATE

Key-set variants (INFERRED_SCHEMA prefixes):
  - hernando_portal: full portal payload (all sample rows)

Content suffixes further split by which canonical dates are recoverable
(``_issued_finaled``, ``_issued``, ``_finaled``, ``_applied``).

Known issues repaired:
  - PERMIT_DATE often copied from Application Date (FILE_DATE) or from
    IMPACT FEE payment instead of Parcel Permit Date / PERMIT ISSUED
    → FIXED.
  - Missing PERMIT_DATE on Final rows that carry Parcel Permit Date or
    PERMIT ISSUED → FILLED.
  - Spurious PERMIT_DATE on Voided (Inactive) shells with only ADVANCE
    PAY / IMPACT FEE and no issuance evidence → cleared.
  - FINAL_DATE earlier than the true FINALED inspection (often an
    intermediate FINAL* COMPLETED OK / RED TAGGED date) → FIXED.
  - Missing FINAL_DATE on Final rows with FINALED inspections → FILLED.
  - Spurious FINAL_DATE from Invalid Status GENERAL FINAL sentinel
    (1990-01-05) or INCOMPLETE-only finals → cleared.
  - Spurious FINAL_DATE on Voided (Inactive) → cleared.

Not repairable from DATA:
  - STATUS_NORMALIZED already matches Appl Status for every sample row
    (Final / Inactive only; no Active or In Review in sample).
  - FILE_DATE already matches Application Date for every sample row.
  - A few Final shells have neither Parcel Permit Date, PERMIT ISSUED,
    nor PERMIT FEE → PERMIT_DATE stays missing.
  - Some Final / Closed shells lack FINALED and FINAL* pass inspections
    → FINAL_DATE stays missing.
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

_FINAL_TYPE_RE = re.compile(r"final", re.IGNORECASE)

_INSP_PASS = {
    "COMPLETED  OK",
    "COMPLETED OK",
    "ELECTRICAL RELEASE",
}


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
    """Parse a date value, returning pd.NaT on failure / sentinels."""
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return pd.NaT
    if isinstance(val, dict):
        return pd.NaT
    if isinstance(val, str):
        s = val.strip()
        if not s or s.upper() in {
            "TBD", "NULL", "NONE", "N/A", "NA", "NAN",
            "00/00/0000", "0/0/0000", "NO PAYMENTS FOUND",
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
    """Compare two datelike values at calendar-day resolution."""
    da = _safe_to_datetime(a)
    db = _safe_to_datetime(b)
    if da is pd.NaT or db is pd.NaT or pd.isna(da) or pd.isna(db):
        return False
    return pd.Timestamp(da).normalize() == pd.Timestamp(db).normalize()


def _present(dt) -> bool:
    return dt is not pd.NaT and not pd.isna(dt)


def _norm_key(key: str) -> str:
    return (key or "").replace("\xa0", " ").strip().lower().rstrip(":")


def _dict_get(d: Optional[dict], *labels: str):
    """Read a dict field, tolerating trailing spaces / colons / NBSP."""
    if not isinstance(d, dict):
        return None
    wanted = {_norm_key(x) for x in labels}
    for k, v in d.items():
        if not isinstance(k, str):
            continue
        if _norm_key(k) in wanted:
            if isinstance(v, str):
                return v.replace("\xa0", " ").strip()
            return v
    return None


# ── Schema classification ────────────────────────────────────────────────────

def _base_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    if not isinstance(data_dict, dict):
        return "unknown"

    keys = set(data_dict.keys())
    if "Parcel info" in keys and "Permit info" in keys:
        return "hernando_portal"
    if "Parcel info" in keys or "Permit info" in keys:
        return "hernando_partial"
    return "unknown"


def _classify_schema(data_dict: Optional[dict]) -> str:
    base = _base_schema(data_dict)
    if base in {"missing", "unknown"} or data_dict is None:
        return base

    issued = _permit_date_from_data(data_dict)
    final = _final_date_from_data(data_dict)
    has_issued = _present(issued)
    has_final = _present(final)

    if has_issued and has_final:
        suffix = "issued_finaled"
    elif has_issued:
        suffix = "issued"
    elif has_final:
        suffix = "finaled"
    else:
        suffix = "applied"
    return f"{base}_{suffix}"


# ── Status mapping ───────────────────────────────────────────────────────────

def _raw_status(d: dict) -> str:
    pi = d.get("Permit info")
    status = _dict_get(pi if isinstance(pi, dict) else None, "Appl Status")
    if isinstance(status, str) and status.strip():
        return status.strip()
    return ""


def _map_status(data_status: str) -> Optional[str]:
    if not data_status:
        return None
    s = data_status.strip().upper()
    # Codes look like "F ** FINALED *", "C ** CLOSED *", "V ** VOIDED *"
    code = s.split("*", 1)[0].strip()
    if code.startswith("F") or "FINALED" in s:
        return "Final"
    if code.startswith("C") or "CLOSED" in s:
        return "Final"
    if code.startswith("V") or "VOIDED" in s or "VOID" in s:
        return "Inactive"
    if "CANCEL" in s or "EXPIRED" in s or "WITHDRAW" in s:
        return "Inactive"
    if "ISSUED" in s or "ACTIVE" in s:
        return "Active"
    if "REVIEW" in s or "PENDING" in s or "APPLIED" in s:
        return "In Review"
    return None


def _expected_status(d: dict) -> Optional[str]:
    return _map_status(_raw_status(d))


# ── Date extractors ──────────────────────────────────────────────────────────

def _file_date_from_data(d: dict):
    parc = d.get("Parcel info")
    return _safe_to_datetime(
        _dict_get(parc if isinstance(parc, dict) else None, "Application Date")
    )


def _permit_issued_progress_dates(d: dict) -> list:
    dates = []
    for e in d.get("Application Progress History") or []:
        if not isinstance(e, dict):
            continue
        loc = (e.get("Location") or "").replace("\xa0", " ").strip().upper()
        if loc != "PERMIT ISSUED":
            continue
        dt = _safe_to_datetime(e.get("Date"))
        if _present(dt):
            dates.append(dt)
    return dates


def _permit_fee_dates(d: dict) -> list:
    dates = []
    for e in d.get("Payments") or []:
        if not isinstance(e, dict):
            continue
        desc = (e.get("Description") or "").replace("\xa0", " ").strip().upper()
        if "PERMIT FEE" not in desc:
            continue
        dt = _safe_to_datetime(e.get("Date"))
        if _present(dt):
            dates.append(dt)
    return dates


def _permit_date_from_data(d: dict):
    """Best available issuance date from the Hernando portal payload."""
    parc = d.get("Parcel info")
    dt = _safe_to_datetime(
        _dict_get(parc if isinstance(parc, dict) else None, "Permit Date")
    )
    if _present(dt):
        return dt

    issued = _permit_issued_progress_dates(d)
    if issued:
        return min(issued)

    fees = _permit_fee_dates(d)
    if fees:
        return min(fees)
    return pd.NaT


def _final_date_from_data(d: dict):
    """Latest close-out inspection date.

    Use the latest of (a) Status == FINALED and (b) FINAL* inspections
    marked COMPLETED OK / ELECTRICAL RELEASE. Taking the union max
    handles re-issued shells whose older FINALED mark predates a later
    COMPLETED OK close-out. Ignore Invalid Status, INCOMPLETE, DELETED,
    RED TAGGED, ACTIVE, etc.
    """
    dates: list = []
    for e in d.get("Inspection History") or []:
        if not isinstance(e, dict):
            continue
        status = (e.get("Status") or "").replace("\xa0", " ").strip().upper()
        typ = (e.get("Type") or "").replace("\xa0", " ").strip()
        dt = _safe_to_datetime(e.get("Insp Date"))
        if not _present(dt):
            continue
        if status == "FINALED":
            dates.append(dt)
        elif status in _INSP_PASS and _FINAL_TYPE_RE.search(typ or ""):
            dates.append(dt)
    if dates:
        return max(dates)
    return pd.NaT


# ── Per-record repair ────────────────────────────────────────────────────────

def _apply_date(repairs: dict, row, field: str, candidate, *, allow_fill: bool = True) -> None:
    cand = _safe_to_datetime(candidate)
    if not _present(cand):
        return
    current = row[field]
    if pd.isna(current):
        if allow_fill:
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


def _apply_status(repairs: dict, current, expected: Optional[str]) -> Optional[str]:
    if expected is None:
        return None if pd.isna(current) else current
    if pd.isna(current):
        repairs["STATUS_NORMALIZED"] = expected
        repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"
        return expected
    if current != expected:
        repairs["STATUS_NORMALIZED"] = expected
        repairs["STATUS_NORMALIZED_FLAG"] = "FIXED"
        return expected
    return current


def _repair_record(row, d: dict, repairs: dict) -> None:
    expected = _expected_status(d)
    effective = _apply_status(repairs, row["STATUS_NORMALIZED"], expected)

    _apply_date(repairs, row, "FILE_DATE", _file_date_from_data(d))

    issued = _permit_date_from_data(d)
    if _present(issued):
        if effective in ("Active", "Final", "Inactive"):
            _apply_date(repairs, row, "PERMIT_DATE", issued, allow_fill=True)
        elif effective == "In Review":
            if not pd.isna(row["PERMIT_DATE"]):
                _apply_date(
                    repairs, row, "PERMIT_DATE", issued, allow_fill=False
                )
    else:
        # No issuance evidence — drop spurious stamps (common on Voided).
        if not pd.isna(row["PERMIT_DATE"]):
            _clear_date(repairs, row, "PERMIT_DATE")

    final_src = _final_date_from_data(d)
    if effective == "Final":
        if _present(final_src):
            _apply_date(repairs, row, "FINAL_DATE", final_src)
        else:
            # Drop Invalid Status / INCOMPLETE-only finals with no real close-out.
            _clear_date(repairs, row, "FINAL_DATE")
    else:
        _clear_date(repairs, row, "FINAL_DATE")


# ── Main entry point ─────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Hernando County permit records using information from the raw DATA JSON.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Hernando County".  Must
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
        if d is None or schema in ("missing", "unknown"):
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
        (df["JURISDICTION"] == "Hernando County") & (df["STATE"] == "FL")
    ].copy()

    print(f"Hernando County records: {len(city):,}\n")
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

    print("\nDATA Appl Status → STATUS_NORMALIZED (after):")
    status_from_data = repaired["DATA"].map(
        lambda x: _raw_status(_safe_parse(x) or {})
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

    print("\nFILE_DATE coverage by status (after):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FILE_DATE"].notna().sum()
        print(
            f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} "
            f"({(n_has / len(sub) if len(sub) else 0):.1%})"
        )

    print("\nPERMIT_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["PERMIT_DATE"].notna().sum()
        print(
            f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} "
            f"({(n_has / len(sub) if len(sub) else 0):.1%})"
        )

    print("\nFINAL_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FINAL_DATE"].notna().sum()
        print(
            f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} "
            f"({(n_has / len(sub) if len(sub) else 0):.1%})"
        )

    # Sanity: PERMIT_DATE should equal Parcel Permit Date when both exist
    parcel_permit = []
    for x in repaired["DATA"]:
        d = _safe_parse(x) or {}
        parc = d.get("Parcel info") if isinstance(d.get("Parcel info"), dict) else {}
        parcel_permit.append(
            _safe_to_datetime(_dict_get(parc, "Permit Date"))
        )
    parcel_s = pd.Series(
        pd.to_datetime(parcel_permit, errors="coerce"), index=repaired.index
    )
    both = repaired["PERMIT_DATE"].notna() & parcel_s.notna()
    match = int(
        (
            repaired.loc[both, "PERMIT_DATE"].dt.normalize()
            == parcel_s.loc[both].dt.normalize()
        ).sum()
    )
    print(
        f"\nPERMIT_DATE == Parcel Permit Date (both present): "
        f"{match} / {int(both.sum())}"
    )

    final_src_vals = []
    for x in repaired["DATA"]:
        d = _safe_parse(x) or {}
        final_src_vals.append(_final_date_from_data(d))
    final_src_s = pd.Series(
        pd.to_datetime(final_src_vals, errors="coerce"), index=repaired.index
    )
    both_f = (
        (repaired["STATUS_NORMALIZED"] == "Final")
        & repaired["FINAL_DATE"].notna()
        & final_src_s.notna()
    )
    match_f = int(
        (
            repaired.loc[both_f, "FINAL_DATE"].dt.normalize()
            == final_src_s.loc[both_f].dt.normalize()
        ).sum()
    )
    print(
        f"FINAL_DATE == extracted final (Final, both present): "
        f"{match_f} / {int(both_f.sum())}"
    )

    af_miss = repaired[
        repaired["STATUS_NORMALIZED"].isin(["Active", "Final"])
        & repaired["PERMIT_DATE"].isna()
    ]
    print(f"Active/Final still missing PERMIT_DATE: {len(af_miss)}")
    if len(af_miss):
        from collections import Counter

        ps_counts = Counter()
        for idx in af_miss.index:
            d = _safe_parse(repaired.at[idx, "DATA"])
            if d is None:
                continue
            ps_counts[(_raw_status(d) or "__EMPTY__")] += 1
        print("  by DATA Appl Status:", dict(ps_counts))

    final_miss = repaired[
        (repaired["STATUS_NORMALIZED"] == "Final") & repaired["FINAL_DATE"].isna()
    ]
    print(f"Final still missing FINAL_DATE: {len(final_miss)}")
    if len(final_miss):
        from collections import Counter

        ps_counts = Counter()
        for idx in final_miss.index:
            d = _safe_parse(repaired.at[idx, "DATA"])
            if d is None:
                continue
            ps_counts[(_raw_status(d) or "__EMPTY__")] += 1
        print("  by DATA Appl Status:", dict(ps_counts))

    inv_fp = (
        repaired["FILE_DATE"].notna()
        & repaired["PERMIT_DATE"].notna()
        & (repaired["FILE_DATE"].dt.normalize() > repaired["PERMIT_DATE"].dt.normalize())
    ).sum()
    inv_pf = (
        repaired["PERMIT_DATE"].notna()
        & repaired["FINAL_DATE"].notna()
        & (
            repaired["PERMIT_DATE"].dt.normalize()
            > repaired["FINAL_DATE"].dt.normalize()
        )
    ).sum()
    print(f"FILE_DATE > PERMIT_DATE inversions: {inv_fp}")
    print(f"PERMIT_DATE > FINAL_DATE inversions: {inv_pf}")

    print(f"\nSTATUS_NORMALIZED still null: {repaired['STATUS_NORMALIZED'].isna().sum()}")

    if agent_data_path:
        out_dir = Path(agent_data_path) / "repaired"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "permits_fl_hernando_county_repaired.parquet"
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote repaired sample → {out_path}")

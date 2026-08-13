"""Data repair for Indian River Shores (FL) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Indian River Shores DATA is a city permit-portal payload (same family as
St. Pete Beach / Daytona Beach Shores) with top-level ``Status``,
``Permit Date``, ``Permit Number``, ``permit_id``, nested ``fees`` /
``payments`` / ``contractors`` / ``inspections`` / ``property_info``,
and either ``reviews`` or ``plan_reviews`` (sometimes plus
``record_type_from_contractor_box``).

INFERRED_SCHEMA prefixes:
  - contractor_box: record_type_from_contractor_box present
  - plan_reviews:   plan_reviews key (no reviews array)
  - portal:         standard shells with reviews array

Suffix is a slug of DATA["Status"] (or ``blank``).

Canonical mappings:
  - DATA["Status"] (+ blank + passed inspection → Final)
                                           → STATUS_NORMALIZED
  - DATA["Permit Date"]                    → FILE_DATE
    (application / record stamp — present on Pending / Online Portal
     Application rows; not an issuance date)
  - (no issuance field in DATA)            → PERMIT_DATE left missing
  - Latest successful final-named / C/O inspection completed_date,
    else latest successful inspection (Final only)
                                           → FINAL_DATE

Known issues repaired:
  - OPEN mapped to In Review → FIXED to Active (portal uses Pending /
    On-line Portal Permit Application Request for pre-issuance).
  - Null STATUS_NORMALIZED on On-line Portal Permit Application
    Request and blank-Status shells that already have a passed
    inspection → FILLED.
  - FINAL_DATE entirely missing → FILLED from inspections for Final.

Not repairable from DATA:
  - No Issued / Approved date field. Permit Date is the file date
    (present on unissued Pending / Online Portal rows) so it must not
    be copied into PERMIT_DATE. Active / Final PERMIT_DATE stays missing.
  - Blank-Status shells with empty / non-passed inspections →
    STATUS_NORMALIZED stays null.
  - Final rows with empty / non-passed inspections → FINAL_DATE
    stays missing.
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

# Final-ish inspection types: FINAL / FNL / C/O / certificate.
_FINAL_TYPE_RE = re.compile(r"final|fnl|\bc/?o\b|certificate", re.I)


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
    """Parse a date value, returning pd.NaT on failure or implausible year."""
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return pd.NaT
    if isinstance(val, dict):
        return pd.NaT
    if isinstance(val, str):
        s = val.strip()
        if not s or s.upper() in {
            "TBD", "NULL", "NONE", "N/A", "NA", "NAN",
            "00/00/0000", "0/0/0000",
        }:
            return pd.NaT
        # Misaligned portal scrape artifacts.
        if s.lower().startswith("completed date") or s.lower().startswith("scheduled date"):
            return pd.NaT
        if s.startswith("0001-01-01") or s.startswith("1900-01-01"):
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


def _present(val) -> bool:
    if val is None:
        return False
    if isinstance(val, float) and math.isnan(val):
        return False
    try:
        if pd.isna(val):
            return False
    except (TypeError, ValueError):
        pass
    return True


def _slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_")
    return s or "blank"


# ── Schema classification ────────────────────────────────────────────────────

def _schema_family(d: Optional[dict]) -> str:
    if d is None:
        return "missing"
    if not isinstance(d, dict):
        return "unknown"
    keys = set(d.keys())
    if "Status" not in keys or "Permit Date" not in keys:
        return "unknown"
    if "record_type_from_contractor_box" in keys:
        return "contractor_box"
    if "plan_reviews" in keys:
        return "plan_reviews"
    return "portal"


def _classify_schema(d: Optional[dict]) -> str:
    family = _schema_family(d)
    if family in {"missing", "unknown"}:
        return family
    raw = str(d.get("Status") or "").strip()
    return f"{family}_{_slug(raw)}"


# ── Status mapping ───────────────────────────────────────────────────────────

# Portal Status → STATUS_NORMALIZED. OPEN is Active because this portal
# uses Pending / On-line Portal Permit Application Request for pre-issuance.
_STATUS_MAP = {
    "Closed": "Final",
    "CO": "Final",
    "OPEN": "Active",
    "Open": "Active",
    "Pending": "In Review",
    "On-line Portal Permit Application Request": "In Review",
    "Expired": "Inactive",
    "Canceled": "Inactive",
    "Cancelled": "Inactive",
    "Void": "Inactive",
    "Withdrawn": "Inactive",
}


def _insp_status_passed(status: str) -> bool:
    """Indian River Shores uses ``A (APPROVED) - inspector`` / ``R (FAILED)``."""
    s = (status or "").strip().lower()
    if not s:
        return False
    if "(failed)" in s or s.startswith("r ") or s.startswith("fail"):
        return False
    if s.startswith("*n") or "(scheduled)" in s:
        return False
    if "(conditional)" in s or s.startswith("c "):
        return False
    if "(approved)" in s:
        return True
    if s.startswith("a ") or s.startswith("approved"):
        return True
    if s.startswith("pass") or s.startswith("complete"):
        return True
    if "(partial)" in s or s.startswith("p "):
        # Partial is not a full pass for closeout dating.
        return False
    return False


def _has_passed_inspection(d: dict) -> bool:
    for insp in d.get("inspections") or []:
        if not isinstance(insp, dict):
            continue
        if not _insp_status_passed(str(insp.get("status") or "")):
            continue
        if _present(_safe_to_datetime(insp.get("completed_date"))):
            return True
    return False


def _expected_status(d: dict) -> Optional[str]:
    raw = str(d.get("Status") or "").strip()
    if raw:
        if raw in _STATUS_MAP:
            return _STATUS_MAP[raw]
        for key, val in _STATUS_MAP.items():
            if key.lower() == raw.lower():
                return val
        return None
    # Blank Status: shells with a passed inspection are treated as Final.
    if _has_passed_inspection(d):
        return "Final"
    return None


# ── Inspection FINAL_DATE ────────────────────────────────────────────────────

def _insp_is_final_type(insp: dict) -> bool:
    itype = str(insp.get("inspection_type") or "")
    return bool(_FINAL_TYPE_RE.search(itype))


def _final_date_from_inspections(d: dict):
    """Prefer latest passed final-named / C/O insp; else latest any passed."""
    final_dates = []
    pass_dates = []
    for insp in d.get("inspections") or []:
        if not isinstance(insp, dict):
            continue
        if not _insp_status_passed(str(insp.get("status") or "")):
            continue
        cd = _safe_to_datetime(insp.get("completed_date"))
        if not _present(cd):
            cd = _safe_to_datetime(insp.get("scheduled_date"))
        if not _present(cd):
            continue
        pass_dates.append(cd)
        if _insp_is_final_type(insp):
            final_dates.append(cd)
    if final_dates:
        return max(final_dates)
    if pass_dates:
        return max(pass_dates)
    return pd.NaT


# ── Per-row repair ───────────────────────────────────────────────────────────

def _apply_status(repairs: dict, current, expected: Optional[str]):
    if expected is None:
        return None if not _present(current) else current
    if not _present(current):
        repairs["STATUS_NORMALIZED"] = expected
        repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"
    elif current != expected:
        repairs["STATUS_NORMALIZED"] = expected
        repairs["STATUS_NORMALIZED_FLAG"] = "FIXED"
    return repairs.get("STATUS_NORMALIZED", current)


def _repair_row(row, d: dict, repairs: dict) -> None:
    expected = _expected_status(d)
    effective_status = _apply_status(repairs, row["STATUS_NORMALIZED"], expected)

    # -- FILE_DATE ← Permit Date (application / record stamp) --
    permit_date = _safe_to_datetime(d.get("Permit Date"))
    current_file = row["FILE_DATE"]
    if _present(permit_date):
        if not _present(current_file):
            repairs["FILE_DATE"] = permit_date
            repairs["FILE_DATE_FLAG"] = "FILLED"
        elif not _dates_equal(current_file, permit_date):
            repairs["FILE_DATE"] = permit_date
            repairs["FILE_DATE_FLAG"] = "FIXED"
    else:
        if _present(current_file) and not _present(_safe_to_datetime(current_file)):
            repairs["FILE_DATE"] = pd.NaT
            repairs["FILE_DATE_FLAG"] = "FIXED"

    # -- PERMIT_DATE --
    # No issuance field in this portal. Permit Date is the file stamp
    # (also present on Pending / Online Portal Application). Do not copy it.
    if _present(row["PERMIT_DATE"]):
        repairs["PERMIT_DATE"] = pd.NaT
        repairs["PERMIT_DATE_FLAG"] = "FIXED"

    # -- FINAL_DATE ← successful inspections (Final only) --
    final_src = _final_date_from_inspections(d)
    current_final = row["FINAL_DATE"]
    if effective_status == "Final":
        if _present(final_src):
            if not _present(current_final):
                repairs["FINAL_DATE"] = final_src
                repairs["FINAL_DATE_FLAG"] = "FILLED"
            elif not _dates_equal(current_final, final_src):
                repairs["FINAL_DATE"] = final_src
                repairs["FINAL_DATE_FLAG"] = "FIXED"
    elif _present(current_final):
        repairs["FINAL_DATE"] = pd.NaT
        repairs["FINAL_DATE_FLAG"] = "FIXED"


# ── Main entry point ─────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Indian River Shores permit records using the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Indian River Shores".
        Must contain STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE,
        FINAL_DATE, and DATA.

    Returns
    -------
    pd.DataFrame
        Copy of *df* with corrected field values, an INFERRED_SCHEMA
        column naming the DATA JSON sub-schema identified for each
        record, and flag columns: STATUS_NORMALIZED_FLAG, FILE_DATE_FLAG,
        PERMIT_DATE_FLAG, FINAL_DATE_FLAG. Flag values are "FILLED"
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
        if d is None or schema in {"missing", "unknown"}:
            continue

        repairs: dict = {}
        _repair_row(row, d, repairs)
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
    city = df[
        (df["JURISDICTION"] == "Indian River Shores") & (df["STATE"] == "FL")
    ].copy()

    print(f"Indian River Shores records: {len(city):,}\n")
    repaired = data_repair(city)

    print("INFERRED_SCHEMA:")
    print(repaired["INFERRED_SCHEMA"].value_counts(dropna=False).to_string())
    print()

    for field in ["STATUS_NORMALIZED", "FILE_DATE", "PERMIT_DATE", "FINAL_DATE"]:
        flag_col = f"{field}_FLAG"
        n_filled = (repaired[flag_col] == "FILLED").sum()
        n_fixed = (repaired[flag_col] == "FIXED").sum()
        if field == "STATUS_NORMALIZED":
            before_missing = city[field].isna().sum()
            after_missing = repaired[field].isna().sum()
        else:
            before_missing = pd.to_datetime(city[field], errors="coerce").isna().sum()
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

    print("\nDATA.Status → STATUS_NORMALIZED (after):")
    status_from_data = repaired["DATA"].map(
        lambda x: str((_safe_parse(x) or {}).get("Status") or "").strip() or "__BLANK__"
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

    print("\nFILE_DATE by STATUS_NORMALIZED (after repair):")
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

    n_file_mm = 0
    n_file_cmp = 0
    for idx in repaired.index:
        d = _safe_parse(repaired.at[idx, "DATA"]) or {}
        pdt = _safe_to_datetime(d.get("Permit Date"))
        if not _present(pdt):
            continue
        n_file_cmp += 1
        if not _dates_equal(repaired.at[idx, "FILE_DATE"], pdt):
            n_file_mm += 1
    print(f"\nFILE_DATE != Permit Date (when Permit Date valid): {n_file_mm} / {n_file_cmp}")

    still_null = repaired[repaired["STATUS_NORMALIZED"].isna()]
    print(f"Remaining null STATUS_NORMALIZED: {len(still_null):,}")

    active_final = repaired["STATUS_NORMALIZED"].isin(["Active", "Final"])
    final = repaired["STATUS_NORMALIZED"] == "Final"
    print(f"Any missing FILE_DATE: {repaired['FILE_DATE'].isna().sum()}")
    print(
        f"Active/Final missing PERMIT_DATE: "
        f"{(active_final & repaired['PERMIT_DATE'].isna()).sum()}"
    )
    print(f"Final missing FINAL_DATE: {(final & repaired['FINAL_DATE'].isna()).sum()}")

    if agent_data_path:
        out_dir = Path(agent_data_path) / "repaired"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "permits_fl_indian_river_shores_repaired.parquet"
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote {out_path}")

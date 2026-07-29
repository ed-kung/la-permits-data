"""Data repair for Selma (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Selma DATA is a CitizenServe / OpenGov-style payload with top-level keys
``main``, ``extra``, and ``location``. Content variants
(INFERRED_SCHEMA) are classified by record-type family and distinctive
extra fields:

  - citizenserve_building_trade:   building / trade / pool / grading /
                                   demolition / fire trade forms
  - citizenserve_code:             code enforcement / complaint / violation
  - citizenserve_yard_sale:        Yard Sale Permit
  - citizenserve_business_license: business license forms
  - citizenserve_work_order:       Work Order Request (+ Completion Date)
  - citizenserve_encroachment:     Encroachment (Permit Issued / Finaled /
                                   City Engineer approval dates)
  - citizenserve_solar:            solar / SolarAPP+ forms
  - citizenserve_planning:         master planning / improvement plan
  - citizenserve_special_event:    special events / fireworks
  - citizenserve_records_request:  public records / citizen concerns
  - citizenserve_transport:        transportation / road closure
  - citizenserve_form_other:       remaining named forms
  - empty_extra / unknown / missing

Canonical mappings:
  - main.status (0/1/2/-1), with Final overrides from Permit Finaled
    Date / Completion Date → STATUS_NORMALIZED
  - main.dateSubmitted (else dateCreated) → FILE_DATE
  - Permit Issued Date / Permit Issue Date / Permit Approval Date
                                                      → PERMIT_DATE
  - Permit Finaled Date / Completion Date (when Final) → FINAL_DATE

Known issues repaired:
  - STATUS_NORMALIZED was derived from STATUS_ORIGINAL (active / draft /
    complete / stopped), which can lag the live numeric main.status.
    Sample mismatches (status=2 still Active, status=1 still Final /
    Inactive, status=-1 still In Review) → FIXED to the code map.
  - Active shells carrying Permit Finaled Date (encroachment) or
    Completion Date (work order) → FIXED to Final.
  - FILE_DATE was taken from main.dateCreated. When dateSubmitted falls
    on a later calendar day → FIXED to the submittal date.
  - PERMIT_DATE / FINAL_DATE universally missing; fill from named
    issuance / finaling / completion stamps when present.

Not repairable from DATA:
  - Most building / solar / yard-sale / business-license / code shells
    have no issuance or finaling timestamp. Generic extra['Date'],
    Yard Sale Start/End, Project Start/End, Date Signed, Work Order
    Request Date, expirationDate, and lastUpdatedDate are not safe
    proxies. City Engineer's Permit Approval Date is plan approval and
    is redundant with Permit Issued / Issue Date when present — not
    used as PERMIT_DATE.
"""

from __future__ import annotations

import json
import math
from datetime import date, datetime
from typing import Optional

import numpy as np
import pandas as pd


_MIN_YEAR = 1900
_MAX_YEAR = 2035

# Prefer explicit issuance labels, then pool-drainage approval stamps.
_PERMIT_DATE_KEYS = (
    "Permit Issued Date",
    "Permit Issue Date",
    "Permit Approval Date",
)

_FINAL_DATE_KEYS = (
    "Permit Finaled Date",
    "Completion Date",
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
    """Parse a date value, returning pd.NaT on failure or implausible year."""
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return pd.NaT
    if isinstance(val, dict):
        return pd.NaT
    if isinstance(val, str):
        s = val.strip()
        if not s or s.upper() in {"TBD", "NULL", "NONE", "N/A", "NA"}:
            return pd.NaT
    try:
        dt = pd.to_datetime(val, errors="coerce")
    except (ValueError, TypeError):
        return pd.NaT
    if pd.isna(dt):
        return pd.NaT
    year = int(dt.year)
    if year < _MIN_YEAR or year > _MAX_YEAR:
        return pd.NaT
    if getattr(dt, "tzinfo", None) is not None:
        dt = dt.tz_convert("UTC").tz_localize(None)
    return dt


def _utc_date(val) -> Optional[date]:
    """Parse a timestamp and return its UTC calendar date."""
    if val is None or (isinstance(val, str) and not str(val).strip()):
        return None
    try:
        ts = pd.to_datetime(val, utc=True, errors="coerce")
    except (ValueError, TypeError):
        return None
    if pd.isna(ts):
        return None
    year = int(ts.year)
    if year < _MIN_YEAR or year > _MAX_YEAR:
        return None
    return ts.date()


def _as_date(val) -> Optional[date]:
    """Normalize a FILE_DATE-like value to datetime.date."""
    if _is_missing(val):
        return None
    if isinstance(val, date) and not isinstance(val, datetime):
        return val
    dt = _safe_to_datetime(val)
    if dt is pd.NaT or pd.isna(dt):
        return None
    if getattr(dt, "tzinfo", None) is not None:
        dt = dt.tz_convert("UTC") if hasattr(dt, "tz_convert") else dt
        return dt.date()
    return dt.date()


def _main(d: dict) -> dict:
    main = d.get("main")
    return main if isinstance(main, dict) else {}


def _extra(d: dict) -> dict:
    extra = d.get("extra")
    return extra if isinstance(extra, dict) else {}


def _first_date(extra: dict, keys: tuple[str, ...]):
    for key in keys:
        dt = _safe_to_datetime(extra.get(key))
        if dt is not pd.NaT and not pd.isna(dt):
            return dt
    return pd.NaT


# ── Schema classification ───────────────────────────────────────────────────

_BUILDING_TRADE_FRAGMENTS = (
    "building",
    "electrical",
    "plumbing",
    "mechanical",
    "reroof",
    "re-roof",
    "roof",
    "pool",
    "spa",
    "grading",
    "demolition",
    "fire sprinkler",
    "fire hood",
    "fire alarm",
    "stop work",
)


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    if not isinstance(data_dict, dict) or "main" not in data_dict:
        return "unknown"

    extra = _extra(data_dict)
    if not extra:
        return "empty_extra"

    main = _main(data_dict)
    rt = (main.get("recordTypeName") or "").strip().lower()

    if (
        _safe_to_datetime(extra.get("Permit Issued Date")) is not pd.NaT
        or _safe_to_datetime(extra.get("Permit Finaled Date")) is not pd.NaT
        or _safe_to_datetime(extra.get("City Engineer's Permit Approval Date"))
        is not pd.NaT
        or "encroach" in rt
    ):
        return "citizenserve_encroachment"

    if (
        _safe_to_datetime(extra.get("Completion Date")) is not pd.NaT
        or "work order" in rt
    ):
        return "citizenserve_work_order"

    if "yard sale" in rt:
        return "citizenserve_yard_sale"
    if (
        "code enforcement" in rt
        or "code complaint" in rt
        or "code violation" in rt
    ):
        return "citizenserve_code"
    if "business license" in rt or rt == "business license":
        return "citizenserve_business_license"
    if "solar" in rt:
        return "citizenserve_solar"
    if any(frag in rt for frag in _BUILDING_TRADE_FRAGMENTS):
        return "citizenserve_building_trade"
    if "planning" in rt or "improvement plan" in rt:
        return "citizenserve_planning"
    if "special event" in rt or "firework" in rt:
        return "citizenserve_special_event"
    if (
        "public record" in rt
        or "public service" in rt
        or "citizen concern" in rt
    ):
        return "citizenserve_records_request"
    if "transport" in rt or "road closure" in rt:
        return "citizenserve_transport"

    return "citizenserve_form_other"


# ── Status / date derivation ────────────────────────────────────────────────

# main.status (int) → STATUS_NORMALIZED
_STATUS_CODE_MAP = {
    0: "In Review",  # draft
    1: "Active",     # active
    2: "Final",      # complete
    -1: "Inactive",  # stopped
}


def _derive_status(main: dict, extra: dict) -> Optional[str]:
    """Map CitizenServe portal lifecycle code to STATUS_NORMALIZED.

    Prefer live ``main.status`` over lagged STATUS_ORIGINAL. Promote to
    Final when Permit Finaled Date or Completion Date is present, unless
    the shell is already Inactive (stopped).
    """
    status = main.get("status")
    if status is None:
        mapped = None
    else:
        try:
            mapped = _STATUS_CODE_MAP.get(int(status))
        except (TypeError, ValueError):
            mapped = None

    if mapped == "Inactive":
        return "Inactive"

    finaled = _first_date(extra, _FINAL_DATE_KEYS)
    if finaled is not pd.NaT and not pd.isna(finaled):
        return "Final"

    return mapped


def _preferred_file_date(main: dict) -> Optional[date]:
    """Application/submittal date: dateSubmitted, else dateCreated."""
    submitted = _utc_date(main.get("dateSubmitted"))
    if submitted is not None:
        return submitted
    return _utc_date(main.get("dateCreated"))


def _permit_date_from_extra(extra: dict):
    """Issuance/approval stamp from named permit date fields."""
    return _first_date(extra, _PERMIT_DATE_KEYS)


def _final_date_from_extra(extra: dict, effective_status):
    """Finaling/completion stamp when effective status is Final."""
    if effective_status != "Final":
        return pd.NaT
    return _first_date(extra, _FINAL_DATE_KEYS)


def _dates_equal(a, b) -> bool:
    da = _safe_to_datetime(a)
    db = _safe_to_datetime(b)
    if da is pd.NaT or db is pd.NaT or pd.isna(da) or pd.isna(db):
        return False
    return da.normalize() == db.normalize()


# ── Per-record repair logic ─────────────────────────────────────────────────

def _repair_record(row, d: dict, repairs: dict):
    """Populate *repairs* with corrected values for a single Selma record."""
    main = _main(d)
    extra = _extra(d)

    # -- STATUS_NORMALIZED --
    current_status = row["STATUS_NORMALIZED"]
    expected = _derive_status(main, extra)
    if expected is not None:
        if pd.isna(current_status):
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"
        elif current_status != expected:
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FIXED"

    effective_status = repairs.get("STATUS_NORMALIZED", current_status)

    # -- FILE_DATE --
    preferred = _preferred_file_date(main)
    current_fd = _as_date(row["FILE_DATE"])
    if preferred is not None:
        if current_fd is None:
            repairs["FILE_DATE"] = pd.Timestamp(preferred)
            repairs["FILE_DATE_FLAG"] = "FILLED"
        elif current_fd != preferred:
            repairs["FILE_DATE"] = pd.Timestamp(preferred)
            repairs["FILE_DATE_FLAG"] = "FIXED"

    # -- PERMIT_DATE --
    permit_dt = _permit_date_from_extra(extra)
    current_permit = row["PERMIT_DATE"]

    if not pd.isna(current_permit):
        if permit_dt is not pd.NaT and not pd.isna(permit_dt):
            if not _dates_equal(current_permit, permit_dt):
                repairs["PERMIT_DATE"] = permit_dt
                repairs["PERMIT_DATE_FLAG"] = "FIXED"
        elif effective_status == "In Review":
            # Clear spurious permit dates on non-issued review rows.
            repairs["PERMIT_DATE"] = pd.NaT
            repairs["PERMIT_DATE_FLAG"] = "FIXED"
    elif effective_status in ("Active", "Final"):
        if permit_dt is not pd.NaT and not pd.isna(permit_dt):
            repairs["PERMIT_DATE"] = permit_dt
            repairs["PERMIT_DATE_FLAG"] = "FILLED"

    # -- FINAL_DATE --
    final_dt = _final_date_from_extra(extra, effective_status)
    current_final = row["FINAL_DATE"]

    if effective_status == "Final":
        if final_dt is not pd.NaT and not pd.isna(final_dt):
            if pd.isna(current_final):
                repairs["FINAL_DATE"] = final_dt
                repairs["FINAL_DATE_FLAG"] = "FILLED"
            elif not _dates_equal(current_final, final_dt):
                repairs["FINAL_DATE"] = final_dt
                repairs["FINAL_DATE_FLAG"] = "FIXED"
    elif not pd.isna(current_final):
        repairs["FINAL_DATE"] = pd.NaT
        repairs["FINAL_DATE_FLAG"] = "FIXED"


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Selma permit records using information from the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Selma".  Must contain
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
    city = df[(df["JURISDICTION"] == "Selma") & (df["STATE"] == "CA")].copy()

    print(f"Selma records: {len(city):,}\n")

    repaired = data_repair(city)

    if AGENT_DATA_PATH:
        out_dir = Path(AGENT_DATA_PATH) / "repaired"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "permits_ca_selma_repaired.parquet"
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

    from collections import Counter

    print("\nActive/Final still missing PERMIT_DATE (by recordTypeName):")
    gap = Counter()
    for idx in repaired.index:
        if repaired.at[idx, "STATUS_NORMALIZED"] not in ("Active", "Final"):
            continue
        if pd.notna(repaired.at[idx, "PERMIT_DATE"]):
            continue
        d = _safe_parse(city.at[idx, "DATA"])
        main = _main(d or {})
        gap[main.get("recordTypeName")] += 1
    for k, v in gap.most_common(15):
        print(f"  {k}: {v}")

    print("\nFinal still missing FINAL_DATE (by recordTypeName):")
    gap = Counter()
    for idx in repaired.index:
        if repaired.at[idx, "STATUS_NORMALIZED"] != "Final":
            continue
        if pd.notna(repaired.at[idx, "FINAL_DATE"]):
            continue
        d = _safe_parse(city.at[idx, "DATA"])
        main = _main(d or {})
        gap[main.get("recordTypeName")] += 1
    for k, v in gap.most_common(15):
        print(f"  {k}: {v}")

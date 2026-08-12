"""Data repair for Daytona Beach Shores (FL) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Daytona Beach Shores DATA is a city permit-portal payload with top-level
``Status``, ``Permit Date``, ``Permit Number``, ``permit_id``, nested
``fees`` / ``payments`` / ``contractors`` / ``inspections`` /
``property_info`` / ``reviews``. This sample has two sub-schemas:

  - job:       Job Cost / Site Address / Expiration Date (2010–2025)
  - applicant: Applicant Name / Application Expiration / Permit
               Expiration (1998–2013; a few sentinel 2099 dates)

INFERRED_SCHEMA is ``job_{status_slug}`` or ``applicant_{status_slug}``.

Canonical mappings:
  - DATA["Status"]                         → STATUS_NORMALIZED
  - DATA["Permit Date"]                    → FILE_DATE
    (application / record date — present even on Never Issued /
     Incomplete / Under Review rows; not an issuance stamp)
  - (no issuance field in DATA)            → PERMIT_DATE left missing
  - Latest successful Final inspection
    completed_date (Final only)            → FINAL_DATE

Known issues repaired:
  - Upstream only mapped a handful of plain STATUS_ORIGINAL labels
    (closed / denied / expired / withdrawn / approved). ~1,952 rows
    with coded Status values like "(5b) Closed, Final Inspection
    Approved" / "Final Approved, Permit Closed" / "(4) Permit Issued"
    left STATUS_NORMALIZED null → FILLED.
  - "closed." (trailing period) treated like "closed" → Final.
  - FINAL_DATE entirely missing upstream → FILLED from inspections
    whose status carries Final Approved / Approved Final / Permit
    Closed language (completed_date, else scheduled_date; plus legacy
    Scheduled/Completed Date shells whose notes say Final).

Not repairable from DATA:
  - No Permit Issued / Approved date field exists. PERMIT_DATE stays
    missing for all Active / Final rows (Permit Date is the file /
    application date, not issuance).
  - Most Final rows have empty inspections or non-close inspection
    statuses → FINAL_DATE stays missing (~1,300 of ~1,700 Finals).
  - 5 rows with Permit Date year 2099 → FILE_DATE stays missing.
  - 2 blank-Status shells → STATUS_NORMALIZED stays missing.
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

_FINAL_TYPE_RE = re.compile(r"final", re.I)
_FAIL_RE = re.compile(r"\bfail", re.I)
# Successful close language on inspection status (not "Approved Until Next").
_FINAL_SUCCESS_RE = re.compile(
    r"(?:approved\s+final|final\s+approved|permit\s+closed)",
    re.I,
)
_DATE_IN_LABEL_RE = re.compile(
    r"(?:Scheduled|Completed)\s+Date:\s*(\d{1,2}/\d{1,2}/\d{2,4})",
    re.I,
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
    parse_val = val
    if isinstance(val, str):
        s = val.strip()
        if not s or s.upper() in {
            "TBD", "NULL", "NONE", "N/A", "NA", "NAN",
            "00/00/0000", "0/0/0000",
        }:
            return pd.NaT
        # Legacy inspection shells: "Completed Date: 06/06/2007"
        m = _DATE_IN_LABEL_RE.search(s)
        parse_val = m.group(1) if m else s
    try:
        dt = pd.to_datetime(parse_val, errors="coerce")
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


# ── Schema / status ──────────────────────────────────────────────────────────

def _schema_family(d: Optional[dict]) -> str:
    if d is None:
        return "missing"
    if not isinstance(d, dict):
        return "unknown"
    if "Applicant Name" in d or "Application Expiration" in d:
        return "applicant"
    if "Job Cost" in d or "Site Address" in d or "Expiration Date" in d:
        return "job"
    if "Status" in d and "Permit Date" in d and "permit_id" in d:
        # Sparse shells still in the same portal family.
        return "job"
    return "unknown"


def _classify_schema(d: Optional[dict]) -> str:
    family = _schema_family(d)
    if family in {"missing", "unknown"}:
        return family
    raw = ""
    if isinstance(d, dict):
        raw = str(d.get("Status") or "").strip()
    return f"{family}_{_slug(raw)}"


_STATUS_MAP = {
    # Final / completed
    "(5b) closed, final inspection approved": "Final",
    "(5b) closed, final inspection approved after reinstatement": "Final",
    "final approved, permit closed": "Final",
    "closed": "Final",
    # Active / issued / work underway
    "(4) permit issued": "Active",
    "permit issued, work underway": "Active",
    "(4b2) permit re-issued": "Active",
    "(4d) fl hb 447 (7-1-19) not final inspected or approved": "Active",
    "(4b1) sent to c. e.": "Active",
    "approved": "Active",
    "permit printed, waiting for pick": "Active",
    "(5a) inspection completed but need final engineer's letter to satisfy": "Active",
    # In Review / pre-issuance
    "(2a) under review": "In Review",
    "(1a) application incomplete - see notes": "In Review",
    "permit waiting for review": "In Review",
    "site plan under review": "In Review",
    "conceptual review completed": "In Review",
    "approved site plan": "In Review",
    "(3a) printed, waiting to be signed": "In Review",
    "(3b) contractor called": "In Review",
    # Inactive
    "denied": "Inactive",
    "denied-per joy deen": "Inactive",
    "expired": "Inactive",
    "withdrawn": "Inactive",
    "withdrawn/closed": "Inactive",
    "permit application closed, never issued": "Inactive",
    # Admin close without final-inspection language → Inactive
    "permit closed administratively": "Inactive",
}


def _normalize_status_key(raw) -> str:
    if raw is None:
        return ""
    s = str(raw).strip().lower()
    s = re.sub(r"\s+", " ", s)
    # "closed." → "closed", but keep abbreviation periods ("c. e.").
    if s.endswith(".") and not re.search(r"\b[a-z]\.$", s):
        s = s[:-1]
    return s


def _expected_status(d: dict) -> Optional[str]:
    key = _normalize_status_key(d.get("Status"))
    if not key:
        return None
    return _STATUS_MAP.get(key)


# ── Inspection FINAL_DATE ────────────────────────────────────────────────────

def _insp_completed(insp: dict):
    """Best completed stamp from a single inspection row."""
    for key in ("completed_date", "scheduled_date"):
        cd = _safe_to_datetime(insp.get(key))
        if _present(cd):
            return cd
    # Legacy shells pack dates into type/status labels.
    for key in ("status", "inspection_type"):
        cd = _safe_to_datetime(insp.get(key))
        if _present(cd):
            return cd
    return pd.NaT


def _is_final_success_inspection(insp: dict) -> bool:
    if not isinstance(insp, dict):
        return False
    itype = str(insp.get("inspection_type") or "")
    status = str(insp.get("status") or "")
    notes = insp.get("notes") or []
    if isinstance(notes, list):
        notes_text = " ".join(str(n) for n in notes)
    else:
        notes_text = str(notes)

    if _FAIL_RE.search(status):
        return False

    # Close language on status is definitive even when type is trade-only
    # (e.g. inspection_type="Electrical", status="Final Approved, Permit Closed").
    if _FINAL_SUCCESS_RE.search(status):
        return True

    # Legacy shells: type/status are "Scheduled/Completed Date: …" and
    # notes include "Final".
    if _DATE_IN_LABEL_RE.search(itype) or _DATE_IN_LABEL_RE.search(status):
        if _FINAL_TYPE_RE.search(notes_text) and not _FAIL_RE.search(notes_text):
            return True

    return False


def _final_date_from_inspections(d: dict):
    dates = []
    for insp in d.get("inspections") or []:
        if not _is_final_success_inspection(insp):
            continue
        cd = _insp_completed(insp)
        if _present(cd):
            dates.append(cd)
    return max(dates) if dates else pd.NaT


# ── Per-row repair ───────────────────────────────────────────────────────────

def _repair_row(row, d: dict, repairs: dict) -> None:
    # -- STATUS_NORMALIZED --
    expected = _expected_status(d)
    current_status = row["STATUS_NORMALIZED"]
    if expected is not None:
        if not _present(current_status):
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"
        elif current_status != expected:
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FIXED"

    effective_status = repairs.get("STATUS_NORMALIZED", current_status)

    # -- FILE_DATE ← Permit Date (application / record date) --
    permit_date = _safe_to_datetime(d.get("Permit Date"))
    current_file = row["FILE_DATE"]
    if _present(permit_date):
        if not _present(current_file):
            repairs["FILE_DATE"] = permit_date
            repairs["FILE_DATE_FLAG"] = "FILLED"
        elif not _dates_equal(current_file, permit_date):
            repairs["FILE_DATE"] = permit_date
            repairs["FILE_DATE_FLAG"] = "FIXED"

    # -- PERMIT_DATE --
    # No issuance / approval date exists in this portal payload. Permit Date
    # is the file date (present on Never Issued / Incomplete). Do not copy
    # it into PERMIT_DATE. Clear any unsupported stamp if somehow present.
    current_permit = row["PERMIT_DATE"]
    if _present(current_permit):
        repairs["PERMIT_DATE"] = pd.NaT
        repairs["PERMIT_DATE_FLAG"] = "FIXED"

    # -- FINAL_DATE ← successful Final inspection (Final only) --
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
    else:
        # Non-Final should not carry a FINAL_DATE.
        if _present(current_final):
            repairs["FINAL_DATE"] = pd.NaT
            repairs["FINAL_DATE_FLAG"] = "FIXED"


# ── Main entry point ─────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Daytona Beach Shores permit records using the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Daytona Beach Shores".
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
        (df["JURISDICTION"] == "Daytona Beach Shores") & (df["STATE"] == "FL")
    ].copy()

    print(f"Daytona Beach Shores records: {len(city):,}\n")
    repaired = data_repair(city)

    print("INFERRED_SCHEMA (top 20):")
    print(repaired["INFERRED_SCHEMA"].value_counts(dropna=False).head(20).to_string())
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

    # Sanity: FILE_DATE vs Permit Date
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
    if len(still_null):
        for idx in still_null.index:
            d = _safe_parse(still_null.at[idx, "DATA"]) or {}
            print("  Status=", repr(d.get("Status")), "schema=", still_null.at[idx, "INFERRED_SCHEMA"])

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
        out_path = out_dir / "permits_fl_daytona_beach_shores_repaired.parquet"
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote {out_path}")

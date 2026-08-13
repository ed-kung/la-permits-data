"""Data repair for South Miami (FL) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

South Miami DATA is an Accela / eTRAKiT-style portal payload with
top-level keys ``fees``, ``contacts``, ``site_info``, ``inspections``,
``permit_info``, and ``search_data`` (same family as Pinecrest / Key West
/ Parkland). All sample rows share that keyset; content variants
(INFERRED_SCHEMA) split by which canonical permit_info dates are set:

  - accela_issued_finaled:  PermitIssuedDate + PermitFinaledDate
  - accela_issued:          issued, no finaled
  - accela_finaled:         finaled, no issued
  - accela_approved:        PermitApprovedDate only
  - accela_applied:         PermitAppliedDate only
  - accela_status_only:     PermitStatus present, no dates
  - missing / unknown

Canonical mappings:
  - permit_info.PermitStatus
    + override to Final when PermitFinaledDate is set
                                           → STATUS_NORMALIZED
  - permit_info.PermitAppliedDate          → FILE_DATE
  - PermitIssuedDate else PermitApprovedDate
    (Approved fallback for Active/Final)   → PERMIT_DATE
  - PermitFinaledDate else latest passed
    final-ish inspection else latest
    passed inspection (Final only)         → FINAL_DATE

Known issues repaired:
  - Unmapped PermitStatus ``REVISION IN CHECK`` left STATUS_NORMALIZED
    null → FILLED as In Review.
  - STATUS_ORIGINAL lag: PermitStatus FINALED / ISSUED while
    STATUS_ORIGINAL still said issued / approved / under review
    → FIXED to Final / Active.
  - Rows with PermitFinaledDate still labeled Active → FIXED to Final
    and FINAL_DATE filled.
  - PERMIT_DATE missing when Issued is blank but Approved exists on
    Active/Final (APPROVED / CERTIFIED shells) → FILLED from approved.
  - Final CLOSED / CO / certificate shells missing FINAL_DATE filled
    from PermitFinaledDate or passed inspections (APPROVED).
  - Non-Final rows incorrectly carrying FINAL_DATE are cleared.

Not repairable from DATA:
  - 1 CERTIFIED shell with blank PermitAppliedDate → FILE_DATE stays
    missing.
  - Some CLOSED / CERTIFIED Finals with no Issued/Approved →
    PERMIT_DATE stays missing.
  - Finals with blank PermitFinaledDate and no usable passed
    inspections → FINAL_DATE stays missing.
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

# Inspection type patterns that indicate finaling / certificate closeout.
_FINAL_INSP_RE = re.compile(
    r"final|fnl|cert(?:ificate)?\s*of\s*(?:occupancy|completion)|"
    r"\bco\b|\bcc\b",
    re.I,
)

# South Miami portal inspection Result values that count as successful.
_PASS_RESULTS = {
    "PASS",
    "PASSED",
    "APPROVED",
    "PARTIAL",
    "VERIFIED",
    "OK",
    "COMPLETE",
    "COMPLETED",
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
    """Parse a date value, returning pd.NaT on failure or implausible year."""
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return pd.NaT
    if isinstance(val, dict):
        return pd.NaT
    if isinstance(val, str):
        s = val.strip().replace("\xa0", " ")
        if not s or s.upper() in {
            "TBD", "NULL", "NONE", "N/A", "NA", "NAN",
            "00/00/0000", "0/0/0000", "SCHEDULE",
        }:
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
    """Compare two datelike values at calendar-day resolution."""
    da = _safe_to_datetime(a)
    db = _safe_to_datetime(b)
    if da is pd.NaT or db is pd.NaT or pd.isna(da) or pd.isna(db):
        return False
    return pd.Timestamp(da).normalize() == pd.Timestamp(db).normalize()


def _classify_schema(d: Optional[dict]) -> str:
    if d is None:
        return "missing"
    if not isinstance(d, dict):
        return "unknown"
    if "permit_info" not in d and "search_data" not in d:
        return "unknown"

    pi = d.get("permit_info") if isinstance(d.get("permit_info"), dict) else {}
    sd = d.get("search_data") if isinstance(d.get("search_data"), dict) else {}

    applied = _safe_to_datetime(pi.get("PermitAppliedDate") or sd.get("APPLIED"))
    issued = _safe_to_datetime(pi.get("PermitIssuedDate"))
    approved = _safe_to_datetime(pi.get("PermitApprovedDate"))
    finaled = _safe_to_datetime(pi.get("PermitFinaledDate"))
    status = (pi.get("PermitStatus") or sd.get("STATUS") or "").strip()

    has_issued = issued is not pd.NaT and not pd.isna(issued)
    has_finaled = finaled is not pd.NaT and not pd.isna(finaled)
    has_approved = approved is not pd.NaT and not pd.isna(approved)
    has_applied = applied is not pd.NaT and not pd.isna(applied)

    if has_issued and has_finaled:
        return "accela_issued_finaled"
    if has_issued:
        return "accela_issued"
    if has_finaled:
        return "accela_finaled"
    if has_approved:
        return "accela_approved"
    if has_applied:
        return "accela_applied"
    if status:
        return "accela_status_only"
    return "accela_shell"


# ── Status mapping ───────────────────────────────────────────────────────────

_STATUS_MAP = {
    # Final / completed / certificate
    "FINALED": "Final",
    "CLOSED": "Final",
    "CO ISSUED": "Final",
    "CC ISSUED": "Final",
    "CERTIFICATE ISSUED": "Final",
    "CERTIFIED": "Final",
    "ADMINISTRATIVELY CLOSED": "Final",
    "COMPLETED": "Final",
    # Active / issued / approved
    "ISSUED": "Active",
    "APPROVED": "Active",
    "ACTIVE": "Active",
    # In review / pre-issuance / revision check
    "UNDER REVIEW": "In Review",
    "PLAN CHECK": "In Review",
    "REVISION IN CHECK": "In Review",
    "SUBMITTED": "In Review",
    "ON HOLD": "In Review",
    # Inactive
    "VOID": "Inactive",
    "EXPIRED": "Inactive",
    "DENIED": "Inactive",
    "WITHDRAWN": "Inactive",
    "CANCELLED": "Inactive",
    "VOIDED": "Inactive",
}


def _raw_status(d: dict) -> str:
    pi = d.get("permit_info") if isinstance(d.get("permit_info"), dict) else {}
    sd = d.get("search_data") if isinstance(d.get("search_data"), dict) else {}
    return (pi.get("PermitStatus") or sd.get("STATUS") or "").strip().upper()


def _expected_status(d: dict) -> Optional[str]:
    """Map portal status → STATUS_NORMALIZED; finaled date forces Final."""
    raw = _raw_status(d)
    expected = _STATUS_MAP.get(raw)
    pi = d.get("permit_info") if isinstance(d.get("permit_info"), dict) else {}
    finaled = _safe_to_datetime(pi.get("PermitFinaledDate"))
    if finaled is not pd.NaT and not pd.isna(finaled):
        # Agency stamped a finaled date → treat as Final even if
        # PermitStatus / STATUS_ORIGINAL still say APPROVED / ISSUED.
        return "Final"

    if expected is not None:
        return expected

    # Issued stamp with unmapped status → Active historical shell.
    issued = _safe_to_datetime(pi.get("PermitIssuedDate"))
    if issued is not pd.NaT and not pd.isna(issued):
        return "Active"

    return None


# ── Inspection date helpers ──────────────────────────────────────────────────

def _is_pass_result(result) -> bool:
    if result is None:
        return False
    return str(result).strip().upper() in _PASS_RESULTS


def _last_approved_final_inspection(d: dict, *, min_date=None):
    """Latest passed final-ish inspection on/after *min_date* (if given)."""
    dates = []
    min_d = _safe_to_datetime(min_date)
    for insp in d.get("inspections") or []:
        if not isinstance(insp, dict):
            continue
        if not _is_pass_result(insp.get("Result")):
            continue
        typ = str(insp.get("Type") or "")
        if not _FINAL_INSP_RE.search(typ):
            continue
        dc = _safe_to_datetime(insp.get("Completed"))
        if dc is pd.NaT or pd.isna(dc):
            continue
        if min_d is not pd.NaT and not pd.isna(min_d):
            if pd.Timestamp(dc).normalize() < pd.Timestamp(min_d).normalize():
                continue
        dates.append(dc)
    return max(dates) if dates else pd.NaT


def _last_approved_inspection(d: dict, *, min_date=None):
    """Latest passed inspection on/after *min_date* (if given)."""
    dates = []
    min_d = _safe_to_datetime(min_date)
    for insp in d.get("inspections") or []:
        if not isinstance(insp, dict):
            continue
        if not _is_pass_result(insp.get("Result")):
            continue
        dc = _safe_to_datetime(insp.get("Completed"))
        if dc is pd.NaT or pd.isna(dc):
            continue
        if min_d is not pd.NaT and not pd.isna(min_d):
            if pd.Timestamp(dc).normalize() < pd.Timestamp(min_d).normalize():
                continue
        dates.append(dc)
    return max(dates) if dates else pd.NaT


# ── Per-record repair ────────────────────────────────────────────────────────

def _apply_date(repairs: dict, row, field: str, candidate, *, allow_fill: bool = True) -> None:
    cand = _safe_to_datetime(candidate)
    if cand is pd.NaT or pd.isna(cand):
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


def _repair_record(row, d: dict, repairs: dict) -> None:
    pi = d.get("permit_info") if isinstance(d.get("permit_info"), dict) else {}
    sd = d.get("search_data") if isinstance(d.get("search_data"), dict) else {}

    # -- STATUS_NORMALIZED --
    current_status = row["STATUS_NORMALIZED"]
    expected = _expected_status(d)
    if expected is not None:
        if pd.isna(current_status):
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"
        elif current_status != expected:
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FIXED"

    effective_status = repairs.get("STATUS_NORMALIZED", current_status)

    applied = _safe_to_datetime(pi.get("PermitAppliedDate") or sd.get("APPLIED"))
    issued = _safe_to_datetime(pi.get("PermitIssuedDate"))
    approved = _safe_to_datetime(pi.get("PermitApprovedDate"))
    finaled = _safe_to_datetime(pi.get("PermitFinaledDate"))

    # -- FILE_DATE ← PermitAppliedDate (search APPLIED as fallback) --
    _apply_date(repairs, row, "FILE_DATE", applied)

    # -- PERMIT_DATE ← Issued (any status) else Approved (Active/Final) --
    has_issued = issued is not pd.NaT and not pd.isna(issued)
    has_approved = approved is not pd.NaT and not pd.isna(approved)

    if has_issued:
        if pd.isna(row["PERMIT_DATE"]):
            repairs["PERMIT_DATE"] = issued
            repairs["PERMIT_DATE_FLAG"] = "FILLED"
        elif not _dates_equal(row["PERMIT_DATE"], issued):
            repairs["PERMIT_DATE"] = issued
            repairs["PERMIT_DATE_FLAG"] = "FIXED"
    elif has_approved and effective_status in ("Active", "Final"):
        if pd.isna(row["PERMIT_DATE"]):
            repairs["PERMIT_DATE"] = approved
            repairs["PERMIT_DATE_FLAG"] = "FILLED"
    elif effective_status == "In Review" and not pd.isna(row["PERMIT_DATE"]):
        # In Review without an Issued stamp should not keep a permit date
        # (Approved-only pre-issuance is not issuance).
        if not has_issued:
            _clear_date(repairs, row, "PERMIT_DATE")

    # -- FINAL_DATE --
    if effective_status == "Final":
        candidate = finaled
        if candidate is pd.NaT or pd.isna(candidate):
            # Prefer inspections on/after issuance so pre-issue FINAL
            # stamps (bad Scheduled/Completed pairs) do not invert dates.
            floor = issued if has_issued else None
            candidate = _last_approved_final_inspection(d, min_date=floor)
            if candidate is pd.NaT or pd.isna(candidate):
                candidate = _last_approved_inspection(d, min_date=floor)

        if candidate is not pd.NaT and not pd.isna(candidate):
            if pd.isna(row["FINAL_DATE"]):
                repairs["FINAL_DATE"] = candidate
                repairs["FINAL_DATE_FLAG"] = "FILLED"
            elif not _dates_equal(row["FINAL_DATE"], candidate):
                if finaled is not pd.NaT and not pd.isna(finaled):
                    repairs["FINAL_DATE"] = finaled
                    repairs["FINAL_DATE_FLAG"] = "FIXED"
                else:
                    repairs["FINAL_DATE"] = candidate
                    repairs["FINAL_DATE_FLAG"] = "FIXED"
    else:
        # Non-Final rows should not carry a finaled / completion date.
        _clear_date(repairs, row, "FINAL_DATE")


# ── Main entry point ─────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    South Miami permit records using information from the raw DATA JSON.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "South Miami". Must contain
        columns STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, FINAL_DATE,
        and DATA.

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
    city = df[
        (df["JURISDICTION"] == "South Miami") & (df["STATE"] == "FL")
    ].copy()

    print(f"South Miami records: {len(city):,}\n")
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

    print("\nDATA.PermitStatus → STATUS_NORMALIZED (after):")
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

    both = repaired[repaired["PERMIT_DATE"].notna() & repaired["FINAL_DATE"].notna()]
    n_inv = (
        both["PERMIT_DATE"].dt.normalize() > both["FINAL_DATE"].dt.normalize()
    ).sum()
    print(f"\nPERMIT_DATE > FINAL_DATE inversions after repair: {n_inv}")

    fd = repaired["FILE_DATE"]
    pd_ = repaired["PERMIT_DATE"]
    both_fp = repaired[fd.notna() & pd_.notna()]
    n_fp_inv = (
        both_fp["FILE_DATE"].dt.normalize() > both_fp["PERMIT_DATE"].dt.normalize()
    ).sum()
    print(f"FILE_DATE > PERMIT_DATE inversions after repair: {n_fp_inv}")

    still_null = repaired[repaired["STATUS_NORMALIZED"].isna()]
    print(f"\nRemaining null STATUS_NORMALIZED: {len(still_null):,}")

    # Sanity vs Accela sources
    n_issue_mismatch = 0
    n_issue = 0
    n_file_mm = 0
    n_final_mm = 0
    for idx in repaired.index:
        d = _safe_parse(repaired.at[idx, "DATA"]) or {}
        pi = d.get("permit_info") if isinstance(d.get("permit_info"), dict) else {}
        sd = d.get("search_data") if isinstance(d.get("search_data"), dict) else {}
        applied = _safe_to_datetime(
            (pi or {}).get("PermitAppliedDate") or (sd or {}).get("APPLIED")
        )
        issued = _safe_to_datetime((pi or {}).get("PermitIssuedDate"))
        finaled = _safe_to_datetime((pi or {}).get("PermitFinaledDate"))
        if applied is not pd.NaT and not pd.isna(applied) and not pd.isna(repaired.at[idx, "FILE_DATE"]):
            if not _dates_equal(repaired.at[idx, "FILE_DATE"], applied):
                n_file_mm += 1
        if issued is not pd.NaT and not pd.isna(issued):
            n_issue += 1
            status = repaired.at[idx, "STATUS_NORMALIZED"]
            if status in ("Active", "Final", "Inactive"):
                if not _dates_equal(repaired.at[idx, "PERMIT_DATE"], issued):
                    n_issue_mismatch += 1
        if (
            finaled is not pd.NaT and not pd.isna(finaled)
            and repaired.at[idx, "STATUS_NORMALIZED"] == "Final"
            and not pd.isna(repaired.at[idx, "FINAL_DATE"])
        ):
            if not _dates_equal(repaired.at[idx, "FINAL_DATE"], finaled):
                n_final_mm += 1

    print(
        f"Active/Final/Inactive PERMIT_DATE != Issue Date: "
        f"{n_issue_mismatch} (of {n_issue} with Issue Date)"
    )
    print(f"FILE_DATE != PermitAppliedDate (when both present): {n_file_mm}")
    print(f"Final FINAL_DATE != PermitFinaledDate (when both present): {n_final_mm}")

    active_final = repaired["STATUS_NORMALIZED"].isin(["Active", "Final"])
    final = repaired["STATUS_NORMALIZED"] == "Final"
    print(f"\nAny missing FILE_DATE: {repaired['FILE_DATE'].isna().sum()}")
    print(
        f"Active/Final missing PERMIT_DATE: "
        f"{(active_final & repaired['PERMIT_DATE'].isna()).sum()}"
    )
    print(f"Final missing FINAL_DATE: {(final & repaired['FINAL_DATE'].isna()).sum()}")

    # Break down remaining gaps
    from collections import Counter

    af_miss = repaired[active_final & repaired["PERMIT_DATE"].isna()]
    if len(af_miss):
        ps_counts = Counter()
        for idx in af_miss.index:
            d = _safe_parse(repaired.at[idx, "DATA"]) or {}
            ps_counts[_raw_status(d) or "__EMPTY__"] += 1
        print("  Active/Final missing PERMIT by PermitStatus:", dict(ps_counts))

    final_miss = repaired[final & repaired["FINAL_DATE"].isna()]
    if len(final_miss):
        ps_counts = Counter()
        for idx in final_miss.index:
            d = _safe_parse(repaired.at[idx, "DATA"]) or {}
            ps_counts[_raw_status(d) or "__EMPTY__"] += 1
        print("  Final missing FINAL_DATE by PermitStatus:", dict(ps_counts))

    if agent_data_path:
        out_dir = Path(agent_data_path) / "repaired"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "permits_fl_south_miami_repaired.parquet"
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote repaired sample → {out_path}")

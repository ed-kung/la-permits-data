"""Data repair for Edgewater (FL) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Edgewater DATA is an eGov WebPermits portal payload with top-level keys
``Address``, ``Inspections``, ``Parent Permit``, ``Permit Number``, and
usually ``Application Status``. A minority also carry ``Fees Due``; 81
rows omit ``Application Status`` entirely. There are no explicit
application / issue / finaled date fields — only inspection
``Scheduled Date`` values and a YYMMDD stamp embedded in
``Permit Number`` (trailing ``…YYMMDD00``, absent when the stamp is
``00000000``).

Canonical fields:

  - Application Status (+ passed Final* inspection upgrade for
    PermitExpired / PermitStatusNotOK / blank status)
      → STATUS_NORMALIZED
  - Permit Number embedded YYMMDD          → FILE_DATE
  - Permit Number embedded YYMMDD when the
    record shows issuance evidence
    (Active / Final)                       → PERMIT_DATE
  - Latest passed Final* inspection
    Scheduled Date                         → FINAL_DATE

Key-set variants (INFERRED_SCHEMA prefixes):
  - webpermits_status:  core keys + Application Status
  - webpermits_fees:    status + Fees Due
  - webpermits_nostatus: core keys, no Application Status

Content suffixes further split by which canonical dates are recoverable
(``_issued_finaled``, ``_issued``, ``_finaled``, ``_applied``).

Known issues repaired:
  - Null STATUS_NORMALIZED for PermitCanceled / PermitFeesDue /
    PermitNotIssued / PermitNoContractor / PermitOnHold /
    PermitStatusNotOK / blank Application Status → FILLED from the
    status map (with Final / Active inference from inspections).
  - PermitExpired kept Inactive even when an approved Final*
    inspection exists → FIXED to Final (portal terminal "expired"
    label on completed trade/building permits).
  - FILE_DATE / PERMIT_DATE 100% missing despite parseable Permit
    Number stamps → FILLED.
  - FINAL_DATE often copied from a Disapproved Building Final
    Scheduled Date, or left blank on trade-only Final* approvals →
    FIXED / FILLED from latest passed Final* inspection for Final
    rows; cleared on non-Final rows.

Not repairable from DATA:
  - 27 rows with Permit Number stamp ``00000000`` (mostly Fees Due /
    On Hold / StatusNotOK shells) → FILE_DATE / PERMIT_DATE stay
    missing.
  - No distinct issue-date field; PERMIT_DATE uses the same Permit
    Number stamp as FILE_DATE when issuance is evidenced.
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

_FINAL_INSP_RE = re.compile(
    r"final|fnl|certificate|\bco\b|\bcc\b|\bcoc\b|\bcofc\b",
    re.IGNORECASE,
)

_PASS_STATUS = {
    "approved",
    "approved with exception",
    "passed",
    "pass",
    "complete",
    "completed",
}

# Application Status values that stay In Review even when inspections
# look complete (label contradicts evidence; trust the portal label).
_FORCE_IN_REVIEW = {
    "PermitFeesDue",
    "PermitNotIssued",
    "PermitNoContractor",
    "PermitOnHold",
}

_FORCE_INACTIVE = {
    "PermitCanceled",
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
    """Parse a date value, returning pd.NaT on failure / sentinel / OOR."""
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return pd.NaT
    if isinstance(val, dict):
        return pd.NaT
    if isinstance(val, str):
        s = val.strip().replace("\xa0", " ")
        if not s or s.upper() in {
            "TBD", "NULL", "NONE", "N/A", "NA", "NAN",
            "00/00/0000", "0/0/0000",
        }:
            return pd.NaT
        if s.startswith("0001-01-01") or s.startswith("1900-01-01"):
            return pd.NaT
    else:
        s = val
    try:
        dt = pd.to_datetime(s, errors="coerce")
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


def _present(dt) -> bool:
    return dt is not pd.NaT and not pd.isna(dt)


def _dates_equal(a, b) -> bool:
    da = _safe_to_datetime(a)
    db = _safe_to_datetime(b)
    if not _present(da) or not _present(db):
        return False
    return pd.Timestamp(da).normalize() == pd.Timestamp(db).normalize()


def _nonempty_str(val) -> Optional[str]:
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return None
    s = str(val).strip()
    return s or None


def _app_status(d: dict) -> Optional[str]:
    return _nonempty_str(d.get("Application Status"))


def _permit_number_date(d: dict):
    """Extract YYMMDD stamp from Permit Number (…YYMMDD00)."""
    pn = _nonempty_str(d.get("Permit Number"))
    if pn is None:
        return pd.NaT
    compact = pn.replace(" ", "")
    m = re.search(r"(\d{6})(\d{2})$", compact)
    if not m:
        return pd.NaT
    yymmdd = m.group(1)
    if yymmdd == "000000":
        return pd.NaT
    yy = int(yymmdd[:2])
    mm = int(yymmdd[2:4])
    dd = int(yymmdd[4:6])
    if not (1 <= mm <= 12 and 1 <= dd <= 31):
        return pd.NaT
    year = 2000 + yy if yy < 80 else 1900 + yy
    try:
        dt = pd.Timestamp(year=year, month=mm, day=dd)
    except (ValueError, TypeError):
        return pd.NaT
    if dt.year < _MIN_YEAR or dt.year > _MAX_YEAR:
        return pd.NaT
    return dt


def _insp_status_token(status: Optional[str]) -> str:
    if not status:
        return ""
    return str(status).strip().lower()


def _inspection_is_passed(item: dict) -> bool:
    if not isinstance(item, dict):
        return False
    return _insp_status_token(item.get("Status")) in _PASS_STATUS


def _inspection_is_passed_final(item: dict) -> bool:
    if not _inspection_is_passed(item):
        return False
    itype = str(item.get("Inspections") or "")
    return bool(_FINAL_INSP_RE.search(itype))


def _final_from_inspections(d: dict):
    insp = d.get("Inspections")
    if not isinstance(insp, list):
        return pd.NaT
    dates = []
    for item in insp:
        if _inspection_is_passed_final(item):
            dt = _safe_to_datetime(item.get("Scheduled Date"))
            if _present(dt):
                dates.append(dt)
    return max(dates) if dates else pd.NaT


def _has_passed_final(d: dict) -> bool:
    return _present(_final_from_inspections(d))


def _has_passed_inspection(d: dict) -> bool:
    insp = d.get("Inspections")
    if not isinstance(insp, list):
        return False
    return any(_inspection_is_passed(item) for item in insp)


# ── Schema classification ────────────────────────────────────────────────────

def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    keys = set(data_dict.keys())
    if "Permit Number" not in keys or "Inspections" not in keys:
        return "unknown"

    if "Fees Due" in keys:
        base = "webpermits_fees"
    elif "Application Status" in keys:
        base = "webpermits_status"
    else:
        base = "webpermits_nostatus"

    has_pn = _present(_permit_number_date(data_dict))
    has_final = _has_passed_final(data_dict)
    # "Issued" evidence: parseable PN stamp plus any passed inspection,
    # or a Final lifecycle (completed permits are necessarily issued).
    has_issued = has_pn and (_has_passed_inspection(data_dict) or has_final)

    if has_issued and has_final:
        return f"{base}_issued_finaled"
    if has_issued:
        return f"{base}_issued"
    if has_final:
        return f"{base}_finaled"
    if has_pn:
        return f"{base}_applied"
    return f"{base}_shell"


# ── Status mapping ───────────────────────────────────────────────────────────

def _expected_status(d: dict) -> Optional[str]:
    """Map Application Status → STATUS_NORMALIZED with inspection upgrades."""
    raw = _app_status(d)
    has_final = _has_passed_final(d)
    has_passed = _has_passed_inspection(d)

    if raw in _FORCE_INACTIVE:
        return "Inactive"

    if raw in _FORCE_IN_REVIEW:
        return "In Review"

    if raw == "PermitExpired":
        # Completed permits commonly remain labeled PermitExpired in this
        # portal dump; upgrade when a passed Final* inspection exists.
        return "Final" if has_final else "Inactive"

    if raw == "PermitStatusNotOK":
        if has_final:
            return "Final"
        if has_passed or _present(_permit_number_date(d)):
            return "Active"
        return "In Review"

    if raw is None:
        if has_final:
            return "Final"
        if has_passed:
            return "Active"
        if _present(_permit_number_date(d)):
            return "In Review"
        return "In Review"

    # Unknown Application Status: infer from evidence.
    if has_final:
        return "Final"
    if has_passed:
        return "Active"
    return "In Review"


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
        return
    if not _dates_equal(current, cand):
        repairs[field] = cand
        repairs[f"{field}_FLAG"] = "FIXED"


def _clear_date(repairs: dict, row, field: str) -> None:
    current = repairs.get(field, row[field])
    if pd.isna(current):
        return
    repairs[field] = pd.NaT
    repairs[f"{field}_FLAG"] = "FIXED"


# ── Per-record repair ────────────────────────────────────────────────────────

def _repair_record(row, d: dict, repairs: dict) -> None:
    expected = _expected_status(d)
    effective_status = _apply_status(repairs, row["STATUS_NORMALIZED"], expected)

    pn_date = _permit_number_date(d)
    final = _final_from_inspections(d)

    # FILE_DATE ← Permit Number YYMMDD (only recoverable application stamp).
    if _present(pn_date):
        _apply_date(repairs, row, "FILE_DATE", pn_date)

    # PERMIT_DATE ← same stamp for Active / Final (issuance evidenced by
    # lifecycle). Cleared for In Review. Left alone for Inactive when
    # missing (no reliable distinct issue date); cleared if somehow set
    # on In Review.
    if effective_status == "In Review":
        _clear_date(repairs, row, "PERMIT_DATE")
    elif effective_status in ("Active", "Final") and _present(pn_date):
        _apply_date(repairs, row, "PERMIT_DATE", pn_date)

    # FINAL_DATE ← passed Final* inspection for Final only.
    if effective_status == "Final":
        if _present(final):
            _apply_date(repairs, row, "FINAL_DATE", final)
    else:
        _clear_date(repairs, row, "FINAL_DATE")


# ── Main entry point ─────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Edgewater permit records using the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Edgewater".  Must contain
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


# ── CLI: run standalone to preview repair stats ─────────────────────────────

if __name__ == "__main__":
    import os
    from collections import Counter

    from dotenv import load_dotenv

    load_dotenv("/Users/ekung/projects/la-permits-data/.env")
    MY_DATA_PATH = os.getenv("MY_DATA_PATH")
    AGENT_DATA_PATH = os.getenv("AGENT_DATA_PATH")
    filepath = os.path.join(
        MY_DATA_PATH, "processed_data", "permits_fl_sample.parquet"
    )
    df = pd.read_parquet(filepath)
    city = df[df["JURISDICTION"] == "Edgewater"].copy()

    print(f"Edgewater records: {len(city):,}\n")

    repaired = data_repair(city)

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

    print("\nSTATUS_NORMALIZED changes (before → after):")
    changed = city["STATUS_NORMALIZED"].fillna("__NA__") != repaired[
        "STATUS_NORMALIZED"
    ].fillna("__NA__")
    if changed.any():
        tmp = pd.DataFrame(
            {
                "before": city.loc[changed, "STATUS_NORMALIZED"].fillna("__NA__"),
                "after": repaired.loc[changed, "STATUS_NORMALIZED"].fillna("__NA__"),
            }
        )
        print(tmp.value_counts().to_string())
    else:
        print("  (none)")

    print("\nFILE_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FILE_DATE"].notna().sum()
        pct = n_has / len(sub) if len(sub) else 0.0
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({pct:.1%})")

    print("\nPERMIT_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["PERMIT_DATE"].notna().sum()
        pct = n_has / len(sub) if len(sub) else 0.0
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({pct:.1%})")

    print("\nFINAL_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FINAL_DATE"].notna().sum()
        pct = n_has / len(sub) if len(sub) else 0.0
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({pct:.1%})")

    final_miss = repaired[
        (repaired["STATUS_NORMALIZED"] == "Final") & repaired["FINAL_DATE"].isna()
    ]
    print(f"\nFinal still missing FINAL_DATE: {len(final_miss)}")

    status_null = repaired["STATUS_NORMALIZED"].isna().sum()
    print(f"STATUS_NORMALIZED still null: {status_null}")

    af_miss = repaired[
        repaired["STATUS_NORMALIZED"].isin(["Active", "Final"])
        & repaired["PERMIT_DATE"].isna()
    ]
    print(f"Active/Final still missing PERMIT_DATE: {len(af_miss)}")
    if len(af_miss):
        ps_counts = Counter()
        for idx in af_miss.index:
            d = _safe_parse(repaired.at[idx, "DATA"])
            if d is None:
                continue
            raw = (_app_status(d) or "").strip() or "__EMPTY__"
            ps_counts[raw] += 1
        print("  by Application Status:", dict(ps_counts))

    file_gt_permit = 0
    permit_gt_final = 0
    for idx in repaired.index:
        f = repaired.at[idx, "FILE_DATE"]
        p = repaired.at[idx, "PERMIT_DATE"]
        fin = repaired.at[idx, "FINAL_DATE"]
        if (
            pd.notna(f)
            and pd.notna(p)
            and pd.Timestamp(f).normalize() > pd.Timestamp(p).normalize()
        ):
            file_gt_permit += 1
        if (
            pd.notna(p)
            and pd.notna(fin)
            and pd.Timestamp(p).normalize() > pd.Timestamp(fin).normalize()
        ):
            permit_gt_final += 1
    print(f"\nFILE_DATE > PERMIT_DATE: {file_gt_permit}")
    print(f"PERMIT_DATE > FINAL_DATE: {permit_gt_final}")

    # Save repaired artifact
    if AGENT_DATA_PATH:
        out_dir = os.path.join(AGENT_DATA_PATH, "repaired")
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, "permits_fl_edgewater_repaired.parquet")
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote {out_path}")

"""Data repair for Coral Gables (FL) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Coral Gables DATA mixes two agency payloads:

  1) Accela-style (majority): top-level ``main`` / ``details`` / ``fees``
     / ``actions`` / ``routing`` / …
       - main.Status → STATUS_NORMALIZED
         (when Status is null, infer from presence of Final / Issued /
         Approved / Applied dates)
       - main.Applied (fallback details['DATE CREATED/SIGNED IN'])
         → FILE_DATE
       - main.Issued (fallback main.Approved) → PERMIT_DATE
       - main.Final → FINAL_DATE

  2) Tyler EnerGov (minority): ``entity`` / ``details`` / ``contacts`` /
     ``fees`` / ``processing_status`` (+ optional reviews/holds/…)
       - entity.CaseStatus (fallback details.PermitStatus)
         → STATUS_NORMALIZED
       - entity.ApplyDate → FILE_DATE
       - entity.IssueDate → PERMIT_DATE
       - entity.FinalDate / details.FinalizeDate
         (else Passed/Approved final-ish inspection)
         → FINAL_DATE

INFERRED_SCHEMA prefixes: ``accela`` / ``accela_shell`` /
``energov`` / ``energov_full``, with content suffixes for which
canonical dates are populated.

Known issues repaired:
  - Accela: 230+ missing STATUS_NORMALIZED where main.Status is null
    but Final/Issued/Approved/Applied dates imply a status; 6 Final
    and 1 pending with Status set but SN null; 1 canceled labeled
    Active; 1 final labeled In Review (stale STATUS_ORIGINAL).
  - EnerGov: 11 Approved/Pay Fees with missing STATUS_NORMALIZED
    → In Review.
  - Spurious FINAL_DATE on Inactive Accela canceled / EnerGov
    Cancelled (and one Issued) cleared — FinalDate there is a
    cancel/close stamp, not a Final completion date.
  - Missing FILE_DATE / PERMIT_DATE / FINAL_DATE filled from the
    canonical DATA fields when present.
  - Spurious PERMIT_DATE on In Review (Approved/Pay Fees) cleared.

Not repairable from DATA:
  - ~8 Accela shells with empty ``main`` (dates exist only on the
    flat columns, not in DATA) — leave as-is.
  - ~33 EnerGov Finaled / ~110 Accela Active/Final rows with no
    IssueDate/Issued → PERMIT_DATE stays missing.
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
    r"final|fnl|closeout|certificate|\bco\b|\bcc\b|\bcoc\b",
    re.IGNORECASE,
)

_INSP_PASS = {
    "approved",
    "passed",
    "pass",
    "complete",
    "completed",
    "finaled",
    "partial pass",
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
    """Parse a date value, returning pd.NaT on failure / out-of-range."""
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
        if s.startswith("0001-01-01"):
            return pd.NaT
    try:
        dt = pd.to_datetime(val, utc=True, errors="coerce")
    except (ValueError, TypeError, OverflowError):
        return pd.NaT
    if pd.isna(dt):
        return pd.NaT
    year = int(dt.year)
    if year < _MIN_YEAR or year > _MAX_YEAR:
        return pd.NaT
    return dt.tz_convert("UTC").tz_localize(None)


def _dates_equal(a, b) -> bool:
    """Compare two datelike values at calendar-day resolution."""
    da = _safe_to_datetime(a)
    db = _safe_to_datetime(b)
    if da is pd.NaT or db is pd.NaT or pd.isna(da) or pd.isna(db):
        return False
    return pd.Timestamp(da).normalize() == pd.Timestamp(db).normalize()


def _present(dt) -> bool:
    return dt is not pd.NaT and not pd.isna(dt)


# ── Schema classification ────────────────────────────────────────────────────

def _payload_kind(d: Optional[dict]) -> str:
    if d is None:
        return "missing"
    keys = set(d.keys())
    if "entity" in keys:
        return "energov"
    if "main" in keys:
        main = d.get("main") if isinstance(d.get("main"), dict) else {}
        # Shell: empty main with no usable status/date fields
        useful = any(
            main.get(k) not in (None, "", {})
            for k in ("Status", "Applied", "Issued", "Approved", "Final", "Type")
        )
        return "accela" if useful else "accela_shell"
    return "unknown"


def _date_suffix(has_apply: bool, has_issue: bool, has_final: bool) -> str:
    if has_issue and has_final:
        return "issued_finaled"
    if has_issue:
        return "issued"
    if has_final:
        return "finaled"
    if has_apply:
        return "applied"
    return "status_only"


def _classify_schema(d: Optional[dict]) -> str:
    kind = _payload_kind(d)
    if kind in ("missing", "unknown", "accela_shell"):
        return kind

    if kind == "energov":
        keys = set(d.keys())
        has_extra = bool(keys & {"reviews", "holds", "attachments", "more_info"})
        base = "energov_full" if has_extra else "energov"
        apply = _energov_date(d, "ApplyDate", "ApplyDate")
        issue = _energov_date(d, "IssueDate", "IssueDate")
        final = _energov_date(d, "FinalDate", "FinalizeDate")
    else:
        base = "accela"
        apply, issue, final = _accela_dates(d)

    return f"{base}_{_date_suffix(_present(apply), _present(issue), _present(final))}"


# ── Accela extractors ────────────────────────────────────────────────────────

_ACCELA_STATUS_MAP = {
    "final": "Final",
    "issued": "Active",
    "approved": "Active",
    "pending": "In Review",
    "stop work": "In Review",
    "canceled": "Inactive",
    "cancelled": "Inactive",
}


def _accela_dates(d: dict):
    main = d.get("main") if isinstance(d.get("main"), dict) else {}
    details = d.get("details") if isinstance(d.get("details"), dict) else {}
    applied = _safe_to_datetime(main.get("Applied"))
    if not _present(applied):
        applied = _safe_to_datetime(details.get("DATE CREATED/SIGNED IN"))
    issued = _safe_to_datetime(main.get("Issued"))
    approved = _safe_to_datetime(main.get("Approved"))
    # Prefer Issued for permit; Approved is a fallback used by caller
    final = _safe_to_datetime(main.get("Final"))
    permit = issued if _present(issued) else approved
    return applied, permit, final


def _accela_raw_status(d: dict) -> Optional[str]:
    main = d.get("main") if isinstance(d.get("main"), dict) else {}
    status = main.get("Status")
    if status is None:
        return None
    status = str(status).strip()
    return status or None


def _expected_status_accela(d: dict) -> Optional[str]:
    raw = _accela_raw_status(d)
    if raw is not None:
        mapped = _ACCELA_STATUS_MAP.get(raw.lower())
        if mapped is not None:
            return mapped
        return None

    # Status null: infer from date presence (common on older Accela rows)
    main = d.get("main") if isinstance(d.get("main"), dict) else {}
    final = _safe_to_datetime(main.get("Final"))
    issued = _safe_to_datetime(main.get("Issued"))
    approved = _safe_to_datetime(main.get("Approved"))
    applied = _safe_to_datetime(main.get("Applied"))
    if _present(final):
        return "Final"
    if _present(issued) or _present(approved):
        return "Active"
    if _present(applied):
        return "In Review"
    return None


# ── EnerGov extractors ───────────────────────────────────────────────────────

_ENERGOV_STATUS_MAP = {
    "Finaled": "Final",
    "Closed": "Final",
    "Issued": "Active",
    "Denied": "Inactive",
    "Cancelled": "Inactive",
    "Canceled": "Inactive",
    "Expired": "Inactive",
    "In Review": "In Review",
    "Submitted": "In Review",
    "Submitted - Online": "In Review",
    "Application Review": "In Review",
    "Approved/Pay Fees": "In Review",
}

_ENERGOV_STATUS_MAP_LOWER = {k.lower(): v for k, v in _ENERGOV_STATUS_MAP.items()}


def _energov_date(d: dict, entity_key: str, *detail_keys: str):
    entity = d.get("entity") if isinstance(d.get("entity"), dict) else {}
    dt = _safe_to_datetime(entity.get(entity_key))
    if _present(dt):
        return dt
    details = d.get("details") if isinstance(d.get("details"), dict) else {}
    for key in detail_keys:
        dt = _safe_to_datetime(details.get(key))
        if _present(dt):
            return dt
    return pd.NaT


def _case_status(d: dict) -> Optional[str]:
    entity = d.get("entity") if isinstance(d.get("entity"), dict) else {}
    details = d.get("details") if isinstance(d.get("details"), dict) else {}
    status = entity.get("CaseStatus") or details.get("PermitStatus")
    if status is None:
        return None
    status = str(status).strip()
    return status or None


def _expected_status_energov(d: dict) -> Optional[str]:
    raw = _case_status(d)
    if raw is None:
        return None
    return _ENERGOV_STATUS_MAP.get(raw) or _ENERGOV_STATUS_MAP_LOWER.get(raw.lower())


def _final_inspection_date(d: dict):
    """Latest Passed/Approved processing_status inspection that looks final."""
    ps = d.get("processing_status")
    if not isinstance(ps, list):
        return pd.NaT
    candidates = []
    for insp in ps:
        if not isinstance(insp, dict):
            continue
        status = str(insp.get("status") or "").strip().lower()
        if status not in _INSP_PASS:
            continue
        desc = str(insp.get("description") or "")
        if not _FINAL_INSP_RE.search(desc):
            continue
        dt = _safe_to_datetime(insp.get("scheduled_date"))
        if not _present(dt):
            dt = _safe_to_datetime(insp.get("requested_date"))
        if _present(dt):
            candidates.append(dt)
    return max(candidates) if candidates else pd.NaT


# ── Shared apply helpers ─────────────────────────────────────────────────────

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

def _repair_accela(row, d: dict, repairs: dict) -> None:
    expected = _expected_status_accela(d)
    effective = _apply_status(repairs, row["STATUS_NORMALIZED"], expected)

    apply, permit, final = _accela_dates(d)

    if _present(apply):
        _apply_date(repairs, row, "FILE_DATE", apply)

    if _present(permit):
        if effective in ("Active", "Final", "Inactive"):
            _apply_date(repairs, row, "PERMIT_DATE", permit)
        elif effective == "In Review":
            _clear_date(repairs, row, "PERMIT_DATE")
    elif effective == "In Review":
        _clear_date(repairs, row, "PERMIT_DATE")

    if effective == "Final":
        if _present(final):
            _apply_date(repairs, row, "FINAL_DATE", final)
    else:
        _clear_date(repairs, row, "FINAL_DATE")


def _repair_energov(row, d: dict, repairs: dict) -> None:
    expected = _expected_status_energov(d)
    effective = _apply_status(repairs, row["STATUS_NORMALIZED"], expected)

    apply = _energov_date(d, "ApplyDate", "ApplyDate")
    issue = _energov_date(d, "IssueDate", "IssueDate")
    final = _energov_date(d, "FinalDate", "FinalizeDate")

    if _present(apply):
        _apply_date(repairs, row, "FILE_DATE", apply)

    if _present(issue):
        if effective in ("Active", "Final", "Inactive"):
            _apply_date(repairs, row, "PERMIT_DATE", issue)
        elif effective == "In Review":
            _clear_date(repairs, row, "PERMIT_DATE")
    elif effective == "In Review":
        _clear_date(repairs, row, "PERMIT_DATE")

    if not _present(final) and effective == "Final":
        final = _final_inspection_date(d)

    if effective == "Final":
        if _present(final):
            _apply_date(repairs, row, "FINAL_DATE", final)
    else:
        _clear_date(repairs, row, "FINAL_DATE")


def _repair_record(row, d: dict, repairs: dict) -> None:
    kind = _payload_kind(d)
    if kind == "accela":
        _repair_accela(row, d, repairs)
    elif kind == "energov":
        _repair_energov(row, d, repairs)
    # accela_shell / unknown: no DATA-backed repair


# ── Main entry point ─────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Coral Gables permit records using the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Coral Gables".  Must contain
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
        out[col] = pd.to_datetime(out[col], errors="coerce", utc=True).dt.tz_localize(None)
        out[col] = out[col].astype(object)

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
        out[col] = pd.to_datetime(out[col], errors="coerce", utc=True).dt.tz_localize(None)

    return out


# ── CLI: run standalone to preview repair stats ─────────────────────────────

if __name__ == "__main__":
    import os

    from dotenv import load_dotenv

    load_dotenv("/Users/ekung/projects/la-permits-data/.env")
    MY_DATA_PATH = os.getenv("MY_DATA_PATH")
    filepath = os.path.join(MY_DATA_PATH, "processed_data", "permits_fl_sample.parquet")
    df = pd.read_parquet(filepath)
    city = df[df["JURISDICTION"] == "Coral Gables"].copy()

    print(f"Coral Gables records: {len(city):,}\n")

    repaired = data_repair(city)

    print("INFERRED_SCHEMA:")
    for s, c in repaired["INFERRED_SCHEMA"].value_counts(dropna=False).items():
        print(f"  {str(s):40s}: {c:>4,}")
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

    print("\nFILE_DATE coverage:", repaired["FILE_DATE"].notna().sum(), "/", len(repaired))

    print("\nPERMIT_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["PERMIT_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({(n_has / len(sub) if len(sub) else 0):.1%})")

    print("\nFINAL_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        n_has = sub["FINAL_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({(n_has / len(sub) if len(sub) else 0):.1%})")

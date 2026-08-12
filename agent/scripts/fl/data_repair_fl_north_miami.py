"""Data repair for North Miami (FL) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

North Miami DATA is a single Accela-style portal payload with top-level
keys ``main``, ``details``, ``actions``, ``fees``, ``routing``, etc.
Content variants (INFERRED_SCHEMA) are labeled by portal status plus
which canonical dates are populated:

  - accela_{status}_issued_finaled
  - accela_{status}_issued
  - accela_{status}_finaled
  - accela_{status}_approved
  - accela_{status}_applied
  - accela_{status}_status_only
  - accela_shell / missing / unknown

Canonical mappings:
  - main.Status, else dates on main
    (Final → Final; Issued/Approved → Active;
     Applied only → In Review)             → STATUS_NORMALIZED
  - main.Applied                           → FILE_DATE
  - main.Issued else main.Approved else
    completed issue / collissue action     → PERMIT_DATE
  - main.Final else completed
    ``final - FINALIZE PERMIT`` action     → FINAL_DATE

Known issues repaired:
  - ~817 rows (mostly LEGACY BUILDING PERMITS) lack main.Status and
    STATUS_ORIGINAL / STATUS_NORMALIZED; status is FILLED from the
    Applied / Issued / Final date pattern on main.
  - Active ``approved`` (and sparse Final) rows missing PERMIT_DATE
    are FILLED from Approved when Issued is blank.
  - Non-Final rows (esp. canceled Inactive) incorrectly carrying
    main.Final as FINAL_DATE are cleared (FIXED).
  - In Review ``stop work`` rows that retained issuance / final stamps
    have those date fields cleared to match the normalized status.

Not repairable from DATA:
  - 3 empty ``Building Property Search`` shells with blank main.
  - ~389 Final rows (reoccupancy / code-enforcement style) have neither
    Issued nor Approved → PERMIT_DATE stays missing.
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

_PASS_CODES = {
    "completed",
    "approved",
    "passed inspection",
    "passed",
}

_FINALIZE_RE = re.compile(r"final\s*-\s*finalize\s+permit|finalize\s+permit", re.I)
_ISSUE_RE = re.compile(r"collissue|issue\s+permit|\bissue\b", re.I)


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
        s = val.strip().replace("\xa0", " ")
        if not s or s.upper() in {
            "TBD", "NULL", "NONE", "N/A", "NA", "NAN",
            "00/00/0000", "0/0/0000",
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


def _present(dt) -> bool:
    return dt is not pd.NaT and not pd.isna(dt)


def _dates_equal(a, b) -> bool:
    """Compare two datelike values at calendar-day resolution."""
    da = _safe_to_datetime(a)
    db = _safe_to_datetime(b)
    if not _present(da) or not _present(db):
        return False
    return pd.Timestamp(da).normalize() == pd.Timestamp(db).normalize()


def _slug(text: Optional[str]) -> str:
    if text is None:
        return "none"
    s = re.sub(r"[^a-z0-9]+", "_", str(text).strip().lower()).strip("_")
    return s or "none"


def _main(d: dict) -> dict:
    main = d.get("main")
    return main if isinstance(main, dict) else {}


def _actions(d: dict) -> list:
    acts = d.get("actions")
    return acts if isinstance(acts, list) else []


def _action_dates(d: dict, name_re: re.Pattern) -> list:
    """Collect Comp'd Dates for matching completed/approved actions."""
    out = []
    for a in _actions(d):
        if not isinstance(a, dict):
            continue
        action = str(a.get("Action") or "")
        if not name_re.search(action):
            continue
        code = str(a.get("Comp'd Code") or "").strip().lower()
        if code not in _PASS_CODES:
            continue
        dt = _safe_to_datetime(a.get("Comp'd Date"))
        if _present(dt):
            out.append(dt)
    return out


def _finalize_date(d: dict):
    dates = _action_dates(d, _FINALIZE_RE)
    return max(dates) if dates else pd.NaT


def _issue_action_date(d: dict):
    dates = _action_dates(d, _ISSUE_RE)
    return min(dates) if dates else pd.NaT


# ── Schema classification ────────────────────────────────────────────────────

def _date_suffix(
    has_apply: bool,
    has_issue: bool,
    has_approved: bool,
    has_final: bool,
) -> str:
    if has_issue and has_final:
        return "issued_finaled"
    if has_issue:
        return "issued"
    if has_final:
        return "finaled"
    if has_approved:
        return "approved"
    if has_apply:
        return "applied"
    return "status_only"


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    if not isinstance(data_dict, dict):
        return "unknown"
    if "main" not in data_dict:
        return "unknown"

    main = _main(data_dict)
    useful = any(
        main.get(k) not in (None, "", {})
        for k in ("Status", "Applied", "Issued", "Approved", "Final", "Type")
    )
    if not useful:
        return "accela_shell"

    status = _slug(main.get("Status"))
    applied = _safe_to_datetime(main.get("Applied"))
    issued = _safe_to_datetime(main.get("Issued"))
    approved = _safe_to_datetime(main.get("Approved"))
    final = _safe_to_datetime(main.get("Final"))
    return (
        f"accela_{status}_"
        f"{_date_suffix(
            _present(applied),
            _present(issued),
            _present(approved),
            _present(final),
        )}"
    )


# ── Status mapping ───────────────────────────────────────────────────────────

_STATUS_MAP = {
    "final": "Final",
    "issued": "Active",
    "approved": "Active",
    "pending": "In Review",
    "stop work": "In Review",
    "canceled": "Inactive",
    "cancelled": "Inactive",
    "expired": "Inactive",
}


def _raw_status(d: dict) -> Optional[str]:
    status = _main(d).get("Status")
    if status is None:
        return None
    text = str(status).strip()
    return text or None


def _infer_status_from_dates(d: dict) -> Optional[str]:
    """When main.Status is absent, infer from Applied / Issued / Final."""
    main = _main(d)
    applied = _safe_to_datetime(main.get("Applied"))
    issued = _safe_to_datetime(main.get("Issued"))
    approved = _safe_to_datetime(main.get("Approved"))
    final = _safe_to_datetime(main.get("Final"))

    if _present(final):
        return "Final"
    if _present(issued) or _present(approved):
        return "Active"
    if _present(applied):
        return "In Review"
    return None


def _expected_status(d: dict) -> Optional[str]:
    """Map main.Status; fall back to date inference; finalize override."""
    raw = _raw_status(d)
    if raw is None:
        return _infer_status_from_dates(d)

    mapped = _STATUS_MAP.get(raw.lower())
    if mapped is None:
        return _infer_status_from_dates(d)

    # Agency sometimes leaves Status=canceled after a completed finalize.
    if mapped == "Inactive" and raw.lower() in {"canceled", "cancelled"}:
        if _present(_finalize_date(d)):
            return "Final"

    return mapped


# ── Date extractors ──────────────────────────────────────────────────────────

def _file_date(d: dict):
    return _safe_to_datetime(_main(d).get("Applied"))


def _permit_date(d: dict):
    main = _main(d)
    issued = _safe_to_datetime(main.get("Issued"))
    if _present(issued):
        return issued
    approved = _safe_to_datetime(main.get("Approved"))
    if _present(approved):
        return approved
    return _issue_action_date(d)


def _final_date(d: dict):
    final = _safe_to_datetime(_main(d).get("Final"))
    if _present(final):
        return final
    return _finalize_date(d)


# ── Apply helpers ────────────────────────────────────────────────────────────

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
    elif not _dates_equal(current, cand):
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
    effective = _apply_status(repairs, row["STATUS_NORMALIZED"], _expected_status(d))

    _apply_date(repairs, row, "FILE_DATE", _file_date(d))

    permit = _permit_date(d)
    if _present(permit):
        if effective in ("Active", "Final", "Inactive"):
            _apply_date(repairs, row, "PERMIT_DATE", permit)
        elif effective == "In Review":
            _clear_date(repairs, row, "PERMIT_DATE")
    elif effective == "In Review":
        _clear_date(repairs, row, "PERMIT_DATE")

    if effective == "Final":
        _apply_date(repairs, row, "FINAL_DATE", _final_date(d))
    else:
        _clear_date(repairs, row, "FINAL_DATE")


# ── Main entry point ─────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    North Miami permit records using information from the raw DATA JSON.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "North Miami". Must contain
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
        if d is None or schema in {"missing", "unknown", "accela_shell"}:
            continue

        repairs: dict = {}
        _repair_accela(row, d, repairs)
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
        (df["JURISDICTION"] == "North Miami") & (df["STATE"] == "FL")
    ].copy()

    print(f"North Miami records: {len(city):,}\n")
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

    active_final = repaired["STATUS_NORMALIZED"].isin(["Active", "Final"])
    final = repaired["STATUS_NORMALIZED"] == "Final"
    print(f"\nAny missing FILE_DATE: {repaired['FILE_DATE'].isna().sum()}")
    print(
        f"Active/Final missing PERMIT_DATE: "
        f"{(active_final & repaired['PERMIT_DATE'].isna()).sum()}"
    )
    print(f"Final missing FINAL_DATE: {(final & repaired['FINAL_DATE'].isna()).sum()}")

    if agent_data_path:
        out_dir = Path(agent_data_path) / "repaired"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "permits_fl_north_miami_repaired.parquet"
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote repaired sample → {out_path}")

"""Data repair for Weston (FL) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Weston DATA is an Accela Citizen Access payload (status / date / tasks /
search_data / more_details / inspections / fees_details). Canonical
fields:

  - DATA.status (fallback search_data.Status), with
    Issued-event upgrade from In Review → Active
      → STATUS_NORMALIZED
  - search_data.Date else DATA.date else earliest
    Application Submittal Accepted         → FILE_DATE
  - Earliest Permit Issuance Issued        → PERMIT_DATE
  - Latest of Inspection Final Inspection
    Complete; Certificate of Occupancy
    Final CO / CC Issued; passed final-ish
    inspections; else Plans Coordination
    Revision Approved (Closed - Revision
    Approved shells only)                  → FINAL_DATE

Key-set variants (INFERRED_SCHEMA prefixes):
  - accela_full:  inspections / contacts / fees_details present
  - accela_basic: shell without those extras

Content suffixes further split by which canonical dates are recoverable
(``_issued_finaled``, ``_issued``, ``_finaled``, ``_applied``).

Known issues repaired:
  - Null STATUS_NORMALIZED for Response Received / File Validation
    Issues / Issued / Closed / Permit Renewal / Waiting on Applicant
    → FILLED (from DATA.status, not stale STATUS_ORIGINAL).
  - STATUS_ORIGINAL-driven mislabels: Closed kept as Active,
    Issued kept as In Review, Closed - Revision Approved kept as
    Inactive, Issuance / Sub Application kept as Active → FIXED.
  - Missing PERMIT_DATE on Issued / Closed / Permit Renewal rows
    that carry a Permit Issuance Issued event → FILLED.
  - FINAL_DATE earlier than Final Inspection Complete → FIXED.
  - Missing FINAL_DATE on Final filled from Final Inspection
    Complete / CO-CC / passed Final* inspections / Revision Approved.
  - Spurious FINAL_DATE on Expired (Inactive) → cleared.
  - Spurious PERMIT_DATE on In Review (none expected after status
    upgrades) cleared if present without an Issued event.

Not repairable from DATA:
  - FILE_DATE already matches DATA.date for every sample row.
  - Permit Complete / older Closed shells often lack Permit Issuance
    Issued → PERMIT_DATE stays missing on many Final rows.
  - Sub Application subordinate shells have almost no task history →
    reclassified In Review; no issuance/final dates available.
  - Some Final shells lack Final Inspection Complete, final
    inspections, and Revision Approved → FINAL_DATE stays missing.
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
    r"final|fnl|certificate|\bco\b|\bcc\b|\bcoc\b|cofo",
    re.IGNORECASE,
)

# Full pass only — Pass Partial on a Final* inspection is not a close-out.
_INSP_PASS = {
    "PASS",
    "PASSED",
    "APPROVED",
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
    """Parse a date value, returning pd.NaT on failure / sentinels."""
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


def _event_field(event: dict, *labels: str):
    """Read an Accela event field, tolerating leading/trailing spaces / NBSP."""
    for label in labels:
        for k, v in event.items():
            if not isinstance(k, str):
                continue
            if k.replace("\xa0", " ").strip().lower() == label.lower():
                if isinstance(v, str):
                    return v.replace("\xa0", " ").strip()
                return v
    return None


def _parse_event(event: dict):
    """Return (marked_as, on_date_str) from an Accela task event."""
    html = (event.get("html") or "").replace("\xa0", " ")
    m = re.search(
        r"Marked as\s*<span[^>]*>([^<]*)</span>\s*on\s*<span[^>]*>([^<]*)</span>",
        html,
        flags=re.I,
    )
    if m:
        return m.group(1).strip(), m.group(2).strip()

    marked = _event_field(event, "Marked as")
    on_val = _event_field(event, "on")
    return marked, on_val


def _iter_task_nodes(tasks: list):
    for t in tasks or []:
        if not isinstance(t, dict):
            continue
        yield (t.get("name") or "").replace("\xa0", " ").strip(), t
        for st in t.get("subtasks") or []:
            if isinstance(st, dict):
                yield (st.get("name") or "").replace("\xa0", " ").strip(), st


def _event_dates(tasks: list, task_names, marked_pred) -> list:
    if isinstance(task_names, str):
        task_names = {task_names}
    else:
        task_names = set(task_names)
    dates = []
    for name, t in _iter_task_nodes(tasks):
        if name not in task_names:
            continue
        for e in t.get("events") or []:
            if not isinstance(e, dict):
                continue
            marked, on_val = _parse_event(e)
            marked = (marked or "").strip() if isinstance(marked, str) else marked
            if not marked or not marked_pred(marked):
                continue
            dt = _safe_to_datetime(on_val)
            if _present(dt):
                dates.append(dt)
    return dates


# ── Schema classification ────────────────────────────────────────────────────

def _base_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    if not isinstance(data_dict, dict):
        return "unknown"

    keys = set(data_dict.keys())
    if "tasks" not in keys and "status" not in keys and "search_data" not in keys:
        return "unknown"

    inspections = data_dict.get("inspections")
    contacts = data_dict.get("contacts")
    fees = data_dict.get("fees_details")
    has_extras = (
        (isinstance(inspections, list) and len(inspections) > 0)
        or (isinstance(contacts, list) and len(contacts) > 0)
        or (isinstance(fees, list) and len(fees) > 0)
    )
    if "tasks" in keys or "status" in keys:
        return "accela_full" if has_extras else "accela_basic"
    if "search_data" in keys:
        return "search_only"
    return "unknown"


def _classify_schema(data_dict: Optional[dict]) -> str:
    base = _base_schema(data_dict)
    if base in {"missing", "unknown"} or data_dict is None:
        return base

    tasks = data_dict.get("tasks") or []
    issued = _permit_date_from_tasks(tasks)
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

_STATUS_MAP = {
    # Final — closed / completed / revision-closed
    "Closed": "Final",
    "Permit Complete": "Final",
    "Closed - Revision Approved": "Final",
    "Finaled": "Final",
    # Active — issued / renewed
    "Issued": "Active",
    "Permit Renewal": "Active",
    # In Review — pre-issuance / waiting / subordinate shells
    "In Review": "In Review",
    "Response Received": "In Review",
    "Waiting On Applicant": "In Review",
    "Waiting on Applicant": "In Review",
    "Submitted": "In Review",
    "Application": "In Review",
    "Incomplete": "In Review",
    "Plan Review": "In Review",
    "File Validation Issues": "In Review",
    "Issuance": "In Review",
    "Sub Application": "In Review",
    # Inactive
    "Canceled Permit": "Inactive",
    "Closed-Withdrawn": "Inactive",
    "Expired": "Inactive",
    "Voided": "Inactive",
}

_STATUS_MAP_LOWER = {k.lower(): v for k, v in _STATUS_MAP.items()}


def _raw_status(d: dict) -> str:
    status = d.get("status")
    if isinstance(status, str) and status.strip():
        return status.strip()
    sd = d.get("search_data") if isinstance(d.get("search_data"), dict) else {}
    sd_status = sd.get("Status")
    if isinstance(sd_status, str):
        return sd_status.strip()
    return ""


def _map_status(data_status: str) -> Optional[str]:
    if not data_status:
        return None
    return _STATUS_MAP.get(data_status) or _STATUS_MAP_LOWER.get(data_status.lower())


def _expected_status(d: dict, tasks: list) -> Optional[str]:
    """Map DATA.status, upgrading In Review → Active when Issued exists."""
    expected = _map_status(_raw_status(d))
    if expected == "In Review" and _present(_permit_date_from_tasks(tasks)):
        return "Active"
    return expected


# ── Date extractors ──────────────────────────────────────────────────────────

def _file_date_from_data(d: dict):
    """Best available application / file date from Accela payload."""
    sd = d.get("search_data") if isinstance(d.get("search_data"), dict) else {}
    dt = _safe_to_datetime(sd.get("Date"))
    if _present(dt):
        return dt

    dt = _safe_to_datetime(d.get("date"))
    if _present(dt):
        return dt

    tasks = d.get("tasks") or []
    intake = _event_dates(
        tasks,
        {"Application Submittal"},
        lambda m: (m or "").strip().lower()
        in {"accepted", "accepted-otc", "assigned", "plans received"},
    )
    if intake:
        return min(intake)
    return pd.NaT


def _permit_date_from_tasks(tasks: list):
    """Earliest Permit Issuance Issued date."""

    def _is_issued(m: str) -> bool:
        return (m or "").strip().lower() == "issued"

    issued = _event_dates(tasks, {"Permit Issuance"}, _is_issued)
    if issued:
        return min(issued)
    return pd.NaT


def _final_inspection_list_dates(d: dict) -> list:
    dates = []
    for insp in d.get("inspections") or []:
        if not isinstance(insp, dict):
            continue
        status = (insp.get("Status") or "").strip().upper()
        if status not in _INSP_PASS:
            continue
        title = insp.get("Title") or ""
        if not _FINAL_INSP_RE.search(title):
            continue
        dt = _safe_to_datetime(
            insp.get("Status Date") or insp.get("Last Update Date")
        )
        if _present(dt):
            dates.append(dt)
    return dates


def _final_date_from_data(d: dict):
    """Latest closure / final-inspection / certificate-adjacent mark."""
    tasks = d.get("tasks") or []
    dates: list = []

    dates.extend(
        _event_dates(
            tasks,
            {"Inspection"},
            lambda m: (m or "").strip().lower()
            in {"final inspection complete", "inspections complete"},
        )
    )
    dates.extend(
        _event_dates(
            tasks,
            {"Certificate of Occupancy"},
            lambda m: any(
                token in (m or "").strip().lower()
                for token in (
                    "final co issued",
                    "cc issued",
                    "c of o issued",
                    "c of c issued",
                )
            ),
        )
    )
    dates.extend(_final_inspection_list_dates(d))

    if dates:
        return max(dates)

    # Closed - Revision Approved shells often have no inspection final —
    # use Revision Approved as the administrative close mark.
    raw = _raw_status(d).lower()
    if raw == "closed - revision approved":
        rev = _event_dates(
            tasks,
            {"Plans Coordination"},
            lambda m: (m or "").strip().lower() == "revision approved",
        )
        if rev:
            return max(rev)
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
    tasks = d.get("tasks") or []
    expected = _expected_status(d, tasks)
    effective = _apply_status(repairs, row["STATUS_NORMALIZED"], expected)

    _apply_date(repairs, row, "FILE_DATE", _file_date_from_data(d))

    issued = _permit_date_from_tasks(tasks)
    if _present(issued):
        if effective in ("Active", "Final", "Inactive"):
            _apply_date(repairs, row, "PERMIT_DATE", issued, allow_fill=True)
        elif effective == "In Review":
            # Should be rare after Issued-event upgrade; correct bad stamps only.
            if not pd.isna(row["PERMIT_DATE"]):
                _apply_date(
                    repairs, row, "PERMIT_DATE", issued, allow_fill=False
                )
    else:
        if not pd.isna(row["PERMIT_DATE"]):
            _clear_date(repairs, row, "PERMIT_DATE")

    final_src = _final_date_from_data(d)
    if effective == "Final":
        _apply_date(repairs, row, "FINAL_DATE", final_src)
    else:
        _clear_date(repairs, row, "FINAL_DATE")


# ── Main entry point ─────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Weston permit records using information from the raw DATA JSON.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Weston".  Must contain
        columns STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, FINAL_DATE,
        and DATA.

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
        (df["JURISDICTION"] == "Weston") & (df["STATE"] == "FL")
    ].copy()

    print(f"Weston records: {len(city):,}\n")
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

    print("\nDATA.status → STATUS_NORMALIZED (after):")
    status_from_data = repaired["DATA"].map(
        lambda x: (_safe_parse(x) or {}).get("status")
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

    # Sanity: PERMIT_DATE should equal Issued when both exist
    issued_vals = []
    for x in repaired["DATA"]:
        d = _safe_parse(x) or {}
        issued_vals.append(_permit_date_from_tasks(d.get("tasks") or []))
    issued_s = pd.Series(
        pd.to_datetime(issued_vals, errors="coerce"), index=repaired.index
    )
    both = repaired["PERMIT_DATE"].notna() & issued_s.notna()
    match = int(
        (
            repaired.loc[both, "PERMIT_DATE"].dt.normalize()
            == issued_s.loc[both].dt.normalize()
        ).sum()
    )
    print(f"\nPERMIT_DATE == Issued event (both present): {match} / {int(both.sum())}")

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
        print("  by DATA.status:", dict(ps_counts))

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
        print("  by DATA.status:", dict(ps_counts))

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
        out_path = out_dir / "permits_fl_weston_repaired.parquet"
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote repaired sample → {out_path}")

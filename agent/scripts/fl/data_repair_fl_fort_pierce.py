"""Data repair for Fort Pierce (FL) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Fort Pierce DATA is the same city-portal family as Tamarac / Ormond Beach
/ St. Petersburg / Punta Gorda / Pompano Beach / Margate / North Port /
Lake Mary. This sample has two sub-schemas:

  - permit_status: detail/fees plus permit_status_detail,
                   insp_status / insp_status_detail
  - fees_detail:   detail + fees + fees_total only (no permit /
                   inspection blocks; STATUS_NORMALIZED null upstream)

Canonical mappings:
  - Status for Permit Number (permit_status), overridden to
    Inactive when Application Status is VOID / REJECTED / etc.
                                                     → STATUS_NORMALIZED
  - Application Status (fees_detail)                 → STATUS_NORMALIZED
  - Application Date                                 → FILE_DATE
  - Issue Date (not portal "Permit Date")            → PERMIT_DATE
  - Later of (a) successful FINAL/CO inspection or
    latest non-NOC success and (b) portal Permit Date
    when it is strictly after Issue Date on Final
    rows                                             → FINAL_DATE

INFERRED_SCHEMA is ``permit_status_{sp_slug}`` or
``fees_detail_{app_slug}``.

Known issues repaired:
  - 58 fees_detail rows with null STATUS_NORMALIZED filled from
    Application Status (VOID, IN PLAN CHECK, CLOSED, APPROVED).
  - One CLOSED permit_status row kept as Active because
    STATUS_ORIGINAL was stale ``permit printed`` → FIXED to Final.
  - VOID / REJECTED Application Status on permit_status rows that
    still show CLOSED / similar → FIXED to Inactive.
  - Upstream PERMIT_DATE copied portal "Permit Date", which is a
    close/final-adjacent stamp on most Final rows, not issuance →
    FIXED to Issue Date for Active / Final / Inactive.
  - Spurious PERMIT_DATE on In Review (and on rows with blank Issue
    Date) → cleared.
  - Final rows missing / wrong FINAL_DATE filled from inspections
    and/or Permit Date when it is strictly after Issue Date.

Not repairable from DATA:
  - Active/Final/Inactive with blank Issue Date → PERMIT_DATE
    cleared or left missing (cannot invent issuance from Permit Date).
  - fees_detail Finals with no Issue Date / inspections /
    Permit Date → PERMIT_DATE and FINAL_DATE stay missing.
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

_SUCCESS_RESULTS = {
    "APPROVED",
    "APPROVED WITH EXCEPTION",
    "PARTIALLY APPROVED",
    "SATISFACTORY",
    "WAIVED",
    "AD",  # administrative disposition / close marker in short insp rows
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


def _apply_status(repairs: dict, current, expected: Optional[str]) -> Optional[str]:
    """Apply expected STATUS_NORMALIZED; return effective status."""
    if expected is None:
        if pd.isna(current):
            return None
        return current

    if pd.isna(current):
        repairs["STATUS_NORMALIZED"] = expected
        repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"
    elif current != expected:
        repairs["STATUS_NORMALIZED"] = expected
        repairs["STATUS_NORMALIZED_FLAG"] = "FIXED"

    return repairs.get("STATUS_NORMALIZED", current)


def _apply_date(repairs: dict, row, field: str, candidate) -> None:
    """Fill or fix *field* from *candidate* datetime (pd.NaT = no candidate)."""
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
    """Clear a spurious date value."""
    current = repairs.get(field, row[field])
    if pd.isna(current):
        return
    repairs[field] = pd.NaT
    repairs[f"{field}_FLAG"] = "FIXED"


# ── Schema classification ────────────────────────────────────────────────────

def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    if not isinstance(data_dict, dict):
        return "unknown"
    if not data_dict:
        return "empty"

    keys = set(data_dict.keys())
    top_detail = data_dict.get("detail") if isinstance(data_dict.get("detail"), dict) else {}

    if "permit_status_detail" in keys:
        psd = data_dict.get("permit_status_detail") or {}
        sp = psd.get("Status for Permit Number") if isinstance(psd, dict) else None
        return f"permit_status_{_slug(sp)}"

    if "detail" in keys:
        app = top_detail.get("Application Status")
        return f"fees_detail_{_slug(app)}"

    return "unknown"


# ── Status maps ──────────────────────────────────────────────────────────────

# Portal "Status for Permit Number"
_SP_MAP = {
    "FINAL INSPECTION COMPLETE": "Final",
    "CLOSED": "Final",
    "C.O. ISSUED": "Final",
    "TEMPORARY C.O. ISSUED": "Final",
    "FINALED": "Final",
    "CERTIFICATE OF COMPLETION": "Final",
    "PERMIT PRINTED": "Active",
    "PERMIT ISSUED": "Active",
    "TO BE ISSUED": "In Review",
    "PLAN CHECK": "In Review",
    "PLANS BEING CHECKED": "In Review",
    "ON HOLD": "In Review",
    "PERMIT REVOKED": "Inactive",
    "PERMIT EXPIRED": "Inactive",
    "WITHDRAWN": "Inactive",
}

# Application Status (fees_detail / top-level detail)
_APP_MAP = {
    "CLOSED": "Final",
    "CLOSED BY REPORT": "Final",
    "CLOSED SPECIAL MAGISTRATE": "Final",
    "ADMINISTRATIVE CLOSURE": "Final",
    "ADMINISTRATIVELY CLOSED": "Final",
    "MANUALLY CLOSED": "Final",
    "COMPLETED": "Final",
    "CERTIFICATE ISSUED": "Final",
    "CERTIFICATE OF COMPLETION": "Final",
    "C/O ISSUED": "Final",
    "C.O. ISSUED": "Final",
    # APPROVED alone (no Status for Permit Number) is pre-issuance
    # plan approval, not an issued permit.
    "APPROVED": "In Review",
    "WEB APPROVED": "In Review",
    "APPROVED FOR PERMIT": "Active",
    "PERMIT PRINTED": "Active",
    "PERMIT ISSUED": "Active",
    "ISSUED": "Active",
    "IN PLAN CHECK": "In Review",
    "PLAN CHECK": "In Review",
    "IN APPROVAL": "In Review",
    "NOTICE RECEIVED": "In Review",
    "IN PROCESS": "In Review",
    "PENDING VERIFICATION": "In Review",
    "TO BE ISSUED": "In Review",
    "EXPIRED PERMIT": "Inactive",
    "PERMIT EXPIRED": "Inactive",
    "EXPIRED": "Inactive",
    "CANCELLED": "Inactive",
    "CANCELED": "Inactive",
    "REVOLKED PERMIT": "Inactive",  # portal spelling
    "REVOKED PERMIT": "Inactive",
    "REJECTED": "Inactive",
    "VOID": "Inactive",
    "NULL AND VOID": "Inactive",
    "DUPLICATE": "Inactive",
    "ABANDONED": "Inactive",
    "WITHDRAWN": "Inactive",
    "SUPERSEDED": "Inactive",
}

# Application Status values that terminate the permit even when
# Status for Permit Number still reads CLOSED / PERMIT PRINTED.
_INACTIVE_APP_OVERRIDE = {
    "VOID",
    "ABANDONED",
    "EXPIRED",
    "EXPIRED PERMIT",
    "PERMIT EXPIRED",
    "PERMITS EXPIRED",
    "WITHDRAWN",
    "SUPERSEDED",
    "NULL AND VOID",
    "CANCELLED",
    "CANCELED",
    "REVOLKED PERMIT",
    "REVOKED PERMIT",
    "REJECTED",
    "DUPLICATE",
}

# Completion evidence that should win over a later EXPIRED flag.
_COMPLETION_SP = {
    "FINAL INSPECTION COMPLETE",
    "C.O. ISSUED",
    "TEMPORARY C.O. ISSUED",
    "FINALED",
    "CERTIFICATE OF COMPLETION",
}


def _map_sp(raw: Optional[str]) -> Optional[str]:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    return _SP_MAP.get(text) or _SP_MAP.get(text.upper())


def _map_app(raw: Optional[str]) -> Optional[str]:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    return _APP_MAP.get(text) or _APP_MAP.get(text.upper())


def _legacy_expected_status(sp_raw, app_raw) -> Optional[str]:
    """Status for Permit Number, overridden by terminal Application Status."""
    app = (str(app_raw).strip() if app_raw is not None else "")
    sp = (str(sp_raw).strip() if sp_raw is not None else "")
    sp_upper = sp.upper()
    app_upper = app.upper()

    if app_upper in _INACTIVE_APP_OVERRIDE or app in _INACTIVE_APP_OVERRIDE:
        # Keep completed work as Final when SP shows a true completion
        # and APP only says EXPIRED (post-completion admin flag).
        if (
            app_upper in {"EXPIRED", "EXPIRED PERMIT", "PERMIT EXPIRED", "PERMITS EXPIRED"}
            and sp_upper in _COMPLETION_SP
        ):
            return _map_sp(sp_raw)
        return "Inactive"

    sp_expected = _map_sp(sp_raw)
    if sp_expected is not None:
        return sp_expected
    return _map_app(app_raw)


# ── Date extractors ──────────────────────────────────────────────────────────

def _is_final_inspection_name(name: str) -> bool:
    upper = str(name or "").upper()
    if "FINAL" in upper:
        return True
    if "CO SIGN" in upper or "C.O" in upper:
        return True
    if re.search(r"(^|[^A-Z])FNL([^A-Z]|$)", upper):
        return True
    if "CLOSEOUT" in upper:
        return True
    return False


def _is_noc_inspection_name(name: str) -> bool:
    return "NOC" in str(name or "").upper()


def _final_date_from_inspections(insp_detail) -> pd.Timestamp:
    """Latest successful FINAL/CO date; else latest non-NOC success."""
    if not isinstance(insp_detail, list):
        return pd.NaT

    final_dates = []
    approved_dates = []
    for row in insp_detail:
        if not isinstance(row, list) or len(row) < 3:
            continue
        name = str(row[0] or "")
        result = str(row[2] or "").strip().upper()
        if result not in _SUCCESS_RESULTS:
            continue
        dt = _safe_to_datetime(row[3] if len(row) > 3 else None)
        if not _present(dt):
            dt = _safe_to_datetime(row[1])
        if not _present(dt):
            continue
        if _is_final_inspection_name(name):
            final_dates.append(dt)
        elif not _is_noc_inspection_name(name):
            approved_dates.append(dt)

    if final_dates:
        return max(final_dates)
    if approved_dates:
        return max(approved_dates)
    return pd.NaT


def _final_date_from_permit_date(detail: dict) -> pd.Timestamp:
    """Portal Permit Date as Final close stamp when strictly after Issue Date.

    When Permit Date equals Issue Date it is just the issuance stamp, not a
    close. When Permit Date is *before* Issue Date (portal quirk on some
    older CLOSED rows) it is also not a usable completion stamp.
    """
    permit_date = _safe_to_datetime(detail.get("Permit Date"))
    if not _present(permit_date):
        return pd.NaT
    issue = _safe_to_datetime(detail.get("Issue Date"))
    if not _present(issue):
        # No Issue Date: Permit Date is the only close-adjacent stamp.
        return permit_date
    if pd.Timestamp(permit_date).normalize() <= pd.Timestamp(issue).normalize():
        return pd.NaT
    return permit_date


def _final_date_candidate(d: dict, detail: dict) -> pd.Timestamp:
    """Combine inspection and Permit-Date close stamps.

    Take the later of inspection-derived and Permit-Date candidates when
    both exist (Permit Date often carries the admin close / C.O. stamp
    when inspection lists are incomplete).
    """
    insp = _final_date_from_inspections(d.get("insp_status_detail"))
    close = _final_date_from_permit_date(detail)
    candidates = [dt for dt in (insp, close) if _present(dt)]
    if not candidates:
        return pd.NaT
    return max(candidates)


# ── Per-schema repair ────────────────────────────────────────────────────────

def _repair_permit_status(row, d: dict, repairs: dict) -> None:
    """Repair a legacy permit_status record."""
    detail = d.get("permit_status_detail") or {}
    if not isinstance(detail, dict):
        detail = {}
    top_detail = d.get("detail") or {}
    if not isinstance(top_detail, dict):
        top_detail = {}

    expected = _legacy_expected_status(
        detail.get("Status for Permit Number"),
        top_detail.get("Application Status"),
    )
    effective_status = _apply_status(repairs, row["STATUS_NORMALIZED"], expected)

    app_date = detail.get("Application Date") or top_detail.get("Application Date")
    _apply_date(repairs, row, "FILE_DATE", app_date)

    # FINAL_DATE for Final only; clear when remapped away from Final.
    final_src = _final_date_candidate(d, detail) if effective_status == "Final" else pd.NaT

    current_final = row["FINAL_DATE"]
    if effective_status == "Final":
        if _present(final_src):
            if pd.isna(current_final):
                repairs["FINAL_DATE"] = final_src
                repairs["FINAL_DATE_FLAG"] = "FILLED"
            elif not _dates_equal(current_final, final_src):
                repairs["FINAL_DATE"] = final_src
                repairs["FINAL_DATE_FLAG"] = "FIXED"
    elif not pd.isna(current_final):
        _clear_date(repairs, row, "FINAL_DATE")

    # PERMIT_DATE ← Issue Date (portal "Permit Date" is not issuance).
    issue = _safe_to_datetime(detail.get("Issue Date"))
    if _present(issue):
        if effective_status in ("Active", "Final", "Inactive"):
            _apply_date(repairs, row, "PERMIT_DATE", issue)
        elif effective_status == "In Review":
            _clear_date(repairs, row, "PERMIT_DATE")
    else:
        # No Issue Date: drop Permit-Date-as-issuance stamps.
        if effective_status in ("Active", "Final", "Inactive", "In Review"):
            _clear_date(repairs, row, "PERMIT_DATE")


def _repair_fees_detail(row, d: dict, repairs: dict) -> None:
    """Repair a sparse fees_detail record (no permit_status_detail)."""
    detail = d.get("detail") or {}
    if not isinstance(detail, dict):
        detail = {}

    app = (detail.get("Application Status") or "").strip()
    if app.upper() in _INACTIVE_APP_OVERRIDE or app in _INACTIVE_APP_OVERRIDE:
        expected = "Inactive"
    else:
        expected = _map_app(app)
    effective_status = _apply_status(repairs, row["STATUS_NORMALIZED"], expected)

    _apply_date(repairs, row, "FILE_DATE", detail.get("Application Date"))

    # No Issue Date / inspections on this schema.
    if effective_status == "In Review":
        _clear_date(repairs, row, "PERMIT_DATE")
    elif effective_status in ("Active", "Final", "Inactive") and not pd.isna(row["PERMIT_DATE"]):
        # fees_detail never carries Issue Date — clear unsupported stamps.
        _clear_date(repairs, row, "PERMIT_DATE")

    if effective_status != "Final" and not pd.isna(row["FINAL_DATE"]):
        _clear_date(repairs, row, "FINAL_DATE")


# ── Main entry point ─────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Fort Pierce permit records using information from the raw DATA JSON.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Fort Pierce". Must contain
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
        if d is None or schema in {"missing", "unknown", "empty"}:
            continue

        repairs: dict = {}
        if schema.startswith("permit_status"):
            _repair_permit_status(row, d, repairs)
        elif schema.startswith("fees_detail"):
            _repair_fees_detail(row, d, repairs)

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
        (df["JURISDICTION"] == "Fort Pierce") & (df["STATE"] == "FL")
    ].copy()

    print(f"Fort Pierce records: {len(city):,}\n")
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

    still_null = repaired[repaired["STATUS_NORMALIZED"].isna()]
    print(f"\nRemaining null STATUS_NORMALIZED: {len(still_null):,}")
    if len(still_null):
        print(still_null["INFERRED_SCHEMA"].value_counts().to_string())

    # Sanity: PERMIT_DATE should match Issue Date when present
    n_issue_mismatch = 0
    n_issue = 0
    for idx in repaired.index:
        d = _safe_parse(repaired.at[idx, "DATA"]) or {}
        psd = d.get("permit_status_detail") or {}
        if not isinstance(psd, dict):
            continue
        issue = _safe_to_datetime(psd.get("Issue Date"))
        if not _present(issue):
            continue
        n_issue += 1
        status = repaired.at[idx, "STATUS_NORMALIZED"]
        if status in ("Active", "Final", "Inactive"):
            if not _dates_equal(repaired.at[idx, "PERMIT_DATE"], issue):
                n_issue_mismatch += 1
    print(
        f"Active/Final/Inactive PERMIT_DATE != Issue Date: "
        f"{n_issue_mismatch} (of {n_issue} with Issue Date)"
    )

    print(f"\nAny missing FILE_DATE: {repaired['FILE_DATE'].isna().sum()}")
    active_final = repaired["STATUS_NORMALIZED"].isin(["Active", "Final"])
    final = repaired["STATUS_NORMALIZED"] == "Final"
    print(
        f"Active/Final missing PERMIT_DATE: "
        f"{(active_final & repaired['PERMIT_DATE'].isna()).sum()}"
    )
    print(f"Final missing FINAL_DATE: {(final & repaired['FINAL_DATE'].isna()).sum()}")

    # Residual FILE mismatches vs Application Date
    n_file_mm = 0
    for idx in repaired.index:
        d = _safe_parse(repaired.at[idx, "DATA"]) or {}
        psd = d.get("permit_status_detail") if isinstance(d.get("permit_status_detail"), dict) else {}
        top = d.get("detail") if isinstance(d.get("detail"), dict) else {}
        app_date = _safe_to_datetime(
            (psd or {}).get("Application Date") or (top or {}).get("Application Date")
        )
        if _present(app_date) and not pd.isna(repaired.at[idx, "FILE_DATE"]):
            if not _dates_equal(repaired.at[idx, "FILE_DATE"], app_date):
                n_file_mm += 1
    print(f"FILE_DATE != Application Date (when both present): {n_file_mm}")

    if agent_data_path:
        out_dir = Path(agent_data_path) / "repaired"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "permits_fl_fort_pierce_repaired.parquet"
        repaired.to_parquet(out_path, index=False)
        print(f"\nWrote repaired sample → {out_path}")

"""Data repair for Newark (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column when present. Creates {FIELD}_FLAG columns with
"FILLED" or "FIXED" annotations for every value that was changed.

Newark's Dewey / sample payload has **no usable DATA JSON** on any row
(confirmed in both ``permits_ca_sample.parquet`` and the upstream
``building-permits-united-states_2_0_12.snappy.parquet`` shard —
17,956 Newark CA rows, all with null DATA). All records therefore
receive ``INFERRED_SCHEMA = "missing"``.

Without agency JSON, date fields cannot be validated or filled from
source. The only structured agency signal available is
``STATUS_ORIGINAL`` (plus presence of ``PERMIT_DATE`` for blank-status
shells), which is used to correct / fill ``STATUS_NORMALIZED``:

  - ``under construction`` was normalized to ``In Review``; active
    construction means the permit was issued → ``Active``.
  - Blank ``STATUS_ORIGINAL`` / ``STATUS_NORMALIZED`` shells that
    already carry a ``PERMIT_DATE`` (fire/ops F13/F14 tents &
    operational permits) → ``Active``.

Canonical ``STATUS_ORIGINAL`` → ``STATUS_NORMALIZED`` map (for fill /
fix):

  - finaled, closed                 → Final
  - issued, approved,
    under construction              → Active
  - submitted                       → In Review
  - expired, withdrawn, void        → Inactive

Known issues repaired:
  - ``under construction`` left In Review → FIXED to Active.
  - 8 null-status shells with PERMIT_DATE → FILLED Active.

Not repairable / left as-is:
  - FILE_DATE missing on 55 ``closed`` / Final shells (no Applied /
    Submitted field and no DATA).
  - FINAL_DATE missing on every row, including all Final / finaled /
    closed shells (no Finaled / completion field and no DATA).
  - PERMIT_DATE already present on every sample row; without DATA it
    cannot be confirmed or corrected (including 3 FILE>PERMIT
    chronology inversions and In Review / Inactive rows that carry an
    issuance stamp).
  - Remaining STATUS_ORIGINAL values already match the map above.
"""

from __future__ import annotations

import json
import math
from typing import Optional

import numpy as np
import pandas as pd


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
        if not data.strip():
            return None
        return json.loads(data)
    return data


def _safe_to_datetime(val):
    """Parse a date value, returning pd.NaT on failure."""
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return pd.NaT
    if isinstance(val, str) and not str(val).strip():
        return pd.NaT
    try:
        dt = pd.to_datetime(val, utc=True, errors="coerce")
    except (ValueError, TypeError):
        return pd.NaT
    if dt is pd.NaT or pd.isna(dt):
        return pd.NaT
    return dt


def _classify_schema(data_dict: Optional[dict]) -> str:
    """Newark sample has no DATA; any future payload → unknown."""
    if data_dict is None:
        return "missing"
    if isinstance(data_dict, dict) and data_dict:
        return "unknown"
    return "missing"


# ── Status mapping from STATUS_ORIGINAL (DATA absent) ───────────────────────

_STATUS_ORIGINAL_MAP = {
    "finaled": "Final",
    "closed": "Final",
    "issued": "Active",
    "approved": "Active",
    "under construction": "Active",
    "submitted": "In Review",
    "expired": "Inactive",
    "withdrawn": "Inactive",
    "void": "Inactive",
}


def _normalize_original(raw) -> str:
    if raw is None or (isinstance(raw, float) and math.isnan(raw)):
        return ""
    return " ".join(str(raw).strip().lower().split())


def _expected_status_from_original(status_original) -> Optional[str]:
    key = _normalize_original(status_original)
    if not key:
        return None
    if key in _STATUS_ORIGINAL_MAP:
        return _STATUS_ORIGINAL_MAP[key]
    # Light fallbacks for variants not seen in the sample.
    if "final" in key or key in {"closed", "complete", "completed"}:
        return "Final"
    if key in {"issued", "approved", "active", "tco"} or "construction" in key:
        return "Active"
    if any(tok in key for tok in ("expired", "void", "withdrawn", "cancel", "denied")):
        return "Inactive"
    if any(tok in key for tok in ("review", "pending", "hold", "submitted")):
        return "In Review"
    return None


# ── Per-record repair logic ─────────────────────────────────────────────────

def _repair_record(row, d: Optional[dict], repairs: dict):
    """Populate *repairs* for a single Newark record.

    When DATA is present (not observed in the current sample), there are
    still no known field mappings; status repair falls back to
    STATUS_ORIGINAL (and PERMIT_DATE presence for blank shells). Date
    fields are only touched if DATA later exposes canonical keys (none
    known today).
    """
    current_status = row["STATUS_NORMALIZED"]
    expected = _expected_status_from_original(row.get("STATUS_ORIGINAL"))

    # Blank STATUS_ORIGINAL: if a permit issuance stamp exists, treat as
    # Active (Newark fire/ops F13/F14 shells).
    if expected is None and pd.isna(current_status):
        if _safe_to_datetime(row.get("PERMIT_DATE")) is not pd.NaT:
            expected = "Active"

    # -- STATUS_NORMALIZED --
    if expected is not None:
        if pd.isna(current_status):
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"
        elif current_status != expected:
            repairs["STATUS_NORMALIZED"] = expected
            repairs["STATUS_NORMALIZED_FLAG"] = "FIXED"

    # -- FILE_DATE / PERMIT_DATE / FINAL_DATE --
    # No agency date fields are available in DATA for Newark. Leave
    # existing values unchanged (including systematically missing
    # FINAL_DATE and the 55 closed shells missing FILE_DATE).
    _ = d  # reserved for future DATA-based date repair


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Newark permit records.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Newark".  Must contain
        columns STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, FINAL_DATE,
        STATUS_ORIGINAL, and DATA.

    Returns
    -------
    pd.DataFrame
        Copy of *df* with corrected field values, an INFERRED_SCHEMA
        column (``missing`` when DATA is absent), and flag columns:
        STATUS_NORMALIZED_FLAG, FILE_DATE_FLAG, PERMIT_DATE_FLAG,
        FINAL_DATE_FLAG.  Flag values are "FILLED" or "FIXED".
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
    city = df[
        (df["JURISDICTION"] == "Newark") & (df["STATE"] == "CA")
    ].copy()

    print(f"Newark records: {len(city):,}\n")
    print(f"DATA non-null: {city['DATA'].notna().sum():,} / {len(city):,}\n")

    repaired = data_repair(city)

    if AGENT_DATA_PATH:
        out_dir = Path(AGENT_DATA_PATH) / "repaired"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "permits_ca_newark_repaired.parquet"
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
                "original": city.loc[mask, "STATUS_ORIGINAL"].fillna("nan").astype(str),
            })
            .value_counts()
            .reset_index(name="n")
        )
        for _, trow in transitions.iterrows():
            print(
                f"  {trow['before']:15s} → {trow['after']:15s} "
                f"(STATUS_ORIGINAL={trow['original']}): {trow['n']:>4,}"
            )
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

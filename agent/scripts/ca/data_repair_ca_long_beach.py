"""Data repair for Long Beach (CA) permit records.

Repairs STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE using
the raw DATA JSON column. Creates {FIELD}_FLAG columns with "FILLED" or
"FIXED" annotations for every value that was changed.

Long Beach DATA is a flat project-listing payload with two sub-schemas:

  - project:  has Project Status, Status Date, Project Number, Address,
              Project Description, plus shared keys (Description,
              Final Date, Project Type, Situs).  Typical building /
              trade permits (Remodel, Electrical, Reroof, etc.).

  - listing:  only Description, Final Date, Project Type, Situs.  Mostly
              code-enforcement / admin / fire / health cases without a
              Project Status.

Important DATA quirks:
  - ``Final Date`` is usually a status token (Closed, Issued, Open,
    Void, …), not a calendar date.  Only ~6% of sample rows store an
    actual MM/DD/YYYY finaling date in that field.
  - ``Status Date`` is the only reliable timestamp on project rows; it
    reflects the last status change (close date when Closed; issuance-
    window date when Permit Issued), not an application/file date.

Known issues repaired:
  - STATUS_NORMALIZED missing on all listing rows and on one FeesDue
    project row.  Infer from Project Status (project) or from the
    Final Date token / parseable date (listing).
  - FINAL_DATE was bulk-copied from Status Date (or from a parseable
    Final Date) for Active / In Review / Inactive rows — clear those.
  - For Final (Closed) rows, prefer a parseable Final Date; otherwise
    use Status Date.  Fill the few Closed rows that still lack
    FINAL_DATE.
  - PERMIT_DATE is universally empty.  For Active (Permit Issued) rows,
    fill from Status Date (only available issuance proxy).

Not repairable from DATA:
  - FILE_DATE: no application / submittal date exists in either schema.
  - PERMIT_DATE for Final rows: no separate issuance date is stored;
    Status Date on Closed rows is the close/final date, not issuance.
  - FINAL_DATE for listing rows whose Final Date token is "Closed"
    (or empty) with no parseable date (~754 sample rows).
"""

import json
import math
import re
from typing import Optional

import pandas as pd
import numpy as np


_DATE_RE = re.compile(r"^\d{1,2}/\d{1,2}/\d{2,4}")


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
    """Parse a date value, returning pd.NaT on failure."""
    if val is None or (isinstance(val, str) and not val.strip()):
        return pd.NaT
    try:
        return pd.to_datetime(val)
    except (ValueError, TypeError):
        return pd.NaT


def _as_date(val):
    """Parse to a calendar date (datetime.date), or None on failure."""
    dt = _safe_to_datetime(val)
    if dt is pd.NaT or pd.isna(dt):
        return None
    return dt.date()


def _dates_equal(a, b) -> bool:
    da = _as_date(a)
    db = _as_date(b)
    if da is None or db is None:
        return False
    return da == db


def _parse_final_date_field(val):
    """Return (kind, date_or_None, token_or_None).

    kind is 'date', 'token', or 'empty'.
    """
    if val is None or (isinstance(val, str) and not str(val).strip()):
        return "empty", None, None
    s = str(val).strip()
    if _DATE_RE.match(s):
        d = _as_date(s)
        if d is not None:
            return "date", d, None
        return "empty", None, None
    return "token", None, s


def _classify_schema(data_dict: Optional[dict]) -> str:
    if data_dict is None:
        return "missing"
    if "Project Status" in data_dict:
        return "project"
    return "listing"


# ── Status mapping ───────────────────────────────────────────────────────────

_PROJECT_STATUS_MAP = {
    "Closed": "Final",
    "Permit Issued": "Active",
    "Review": "In Review",
    "Additional Information From Applicant Needed": "In Review",
    "Pre-App": "In Review",
    "FeesDue": "In Review",
    "Void": "Inactive",
    "Abandonned": "Inactive",  # agency spelling
    "Expired": "Inactive",
}

# listing schema: Final Date is usually a status token (or a real date).
_LISTING_FINAL_TOKEN_MAP = {
    "Closed": "Final",
    "Open": "In Review",
    "UnderRev": "In Review",
    "NeedsInfo": "In Review",
    "Pre-App": "In Review",
    "FeesDue": "In Review",
    "ClosedPend": "In Review",
    "Void": "Inactive",
    "Deleted": "Inactive",
    "Abandonned": "Inactive",
    "Expired": "Inactive",
    # "Issued" would map to Active but does not appear on listing rows.
}


def _set_status(row, expected: str, repairs: dict) -> None:
    current = row["STATUS_NORMALIZED"]
    if pd.isna(current):
        repairs["STATUS_NORMALIZED"] = expected
        repairs["STATUS_NORMALIZED_FLAG"] = "FILLED"
    elif current != expected:
        repairs["STATUS_NORMALIZED"] = expected
        repairs["STATUS_NORMALIZED_FLAG"] = "FIXED"


def _set_or_fix_final(row, final_d, repairs: dict) -> None:
    if final_d is None:
        return
    if pd.isna(row["FINAL_DATE"]):
        repairs["FINAL_DATE"] = final_d
        repairs["FINAL_DATE_FLAG"] = "FILLED"
    elif not _dates_equal(row["FINAL_DATE"], final_d):
        repairs["FINAL_DATE"] = final_d
        repairs["FINAL_DATE_FLAG"] = "FIXED"


# ── Per-schema repair logic ─────────────────────────────────────────────────

def _repair_project(row, d: dict, repairs: dict) -> None:
    """Repair a project-schema (Project Status present) record."""
    project_status = d.get("Project Status") or ""
    status_date = _as_date(d.get("Status Date"))
    fd_kind, fd_date, _fd_token = _parse_final_date_field(d.get("Final Date"))

    # -- STATUS_NORMALIZED --
    expected = _PROJECT_STATUS_MAP.get(project_status)
    if expected is not None:
        _set_status(row, expected, repairs)

    effective_status = repairs.get("STATUS_NORMALIZED", row["STATUS_NORMALIZED"])

    # -- FILE_DATE --
    # No application / submittal date in DATA.

    # -- PERMIT_DATE --
    # Only Active (Permit Issued) rows have Status Date as an issuance proxy.
    if pd.isna(row["PERMIT_DATE"]) and effective_status == "Active":
        if status_date is not None:
            repairs["PERMIT_DATE"] = status_date
            repairs["PERMIT_DATE_FLAG"] = "FILLED"
        elif fd_kind == "date":
            repairs["PERMIT_DATE"] = fd_date
            repairs["PERMIT_DATE_FLAG"] = "FILLED"

    # -- FINAL_DATE --
    if effective_status == "Final":
        # Prefer an actual date stored in Final Date; else Status Date.
        if fd_kind == "date":
            _set_or_fix_final(row, fd_date, repairs)
        elif status_date is not None:
            _set_or_fix_final(row, status_date, repairs)
    elif not pd.isna(row["FINAL_DATE"]):
        # Spurious FINAL_DATE copied from Status Date on non-Final rows.
        repairs["FINAL_DATE"] = pd.NaT
        repairs["FINAL_DATE_FLAG"] = "FIXED"


def _repair_listing(row, d: dict, repairs: dict) -> None:
    """Repair a listing-schema record (no Project Status)."""
    fd_kind, fd_date, fd_token = _parse_final_date_field(d.get("Final Date"))

    # -- STATUS_NORMALIZED --
    expected = None
    if fd_kind == "token":
        expected = _LISTING_FINAL_TOKEN_MAP.get(fd_token)
    elif fd_kind == "date":
        # A concrete Final Date on a listing row implies the case closed.
        expected = "Final"
    if expected is not None:
        _set_status(row, expected, repairs)

    effective_status = repairs.get("STATUS_NORMALIZED", row["STATUS_NORMALIZED"])

    # -- FILE_DATE / PERMIT_DATE --
    # No application or issuance timestamps in the listing payload.

    # -- FINAL_DATE --
    if effective_status == "Final":
        if fd_kind == "date":
            _set_or_fix_final(row, fd_date, repairs)
        # token "Closed" with no date: leave FINAL_DATE missing.
    elif not pd.isna(row["FINAL_DATE"]):
        # Non-Final listing rows should not carry a finaling date.
        # (Rare: a date in Final Date already maps status to Final above.)
        repairs["FINAL_DATE"] = pd.NaT
        repairs["FINAL_DATE_FLAG"] = "FIXED"


# ── Main entry point ────────────────────────────────────────────────────────

def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Repair STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for
    Long Beach permit records using information from the raw DATA JSON column.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Long Beach".  Must contain
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

        if schema == "project":
            _repair_project(row, d, repairs)
        elif schema == "listing":
            _repair_listing(row, d, repairs)

        for key, value in repairs.items():
            out.at[idx, key] = value

    return out


# ── CLI: run standalone to preview repair stats ─────────────────────────────

if __name__ == "__main__":
    import os
    from dotenv import load_dotenv

    load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))
    MY_DATA_PATH = os.getenv("MY_DATA_PATH")
    filepath = os.path.join(MY_DATA_PATH, "processed_data", "permits_la_sample.parquet")
    df = pd.read_parquet(filepath)
    lb = df[df["JURISDICTION"] == "Long Beach"].copy()

    print(f"Long Beach records: {len(lb):,}\n")

    repaired = data_repair(lb)

    print("INFERRED_SCHEMA:")
    for s, c in repaired["INFERRED_SCHEMA"].value_counts(dropna=False).items():
        print(f"  {str(s):20s}: {c:>4,}")
    print()

    for field in ["STATUS_NORMALIZED", "FILE_DATE", "PERMIT_DATE", "FINAL_DATE"]:
        flag_col = f"{field}_FLAG"
        n_filled = (repaired[flag_col] == "FILLED").sum()
        n_fixed = (repaired[flag_col] == "FIXED").sum()
        print(f"{field}:")
        print(f"  FILLED: {n_filled:>4,}   FIXED: {n_fixed:>4,}")

        before_missing = lb[field].isna().sum()
        after_missing = repaired[field].isna().sum()
        print(f"  Missing before: {before_missing:>4,}   Missing after: {after_missing:>4,}")
        print()

    print("STATUS_NORMALIZED distribution:")
    print("  Before:")
    for s, c in lb["STATUS_NORMALIZED"].value_counts(dropna=False).items():
        print(f"    {str(s):15s}: {c:>4,}")
    print("  After:")
    for s, c in repaired["STATUS_NORMALIZED"].value_counts(dropna=False).items():
        print(f"    {str(s):15s}: {c:>4,}")

    print("\nFINAL_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        if len(sub) == 0:
            continue
        n_has = sub["FINAL_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({n_has / len(sub):.1%})")

    print("\nPERMIT_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        if len(sub) == 0:
            continue
        n_has = sub["PERMIT_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({n_has / len(sub):.1%})")

    print("\nFILE_DATE by STATUS_NORMALIZED (after repair):")
    for status in ["Active", "Final", "In Review", "Inactive"]:
        sub = repaired[repaired["STATUS_NORMALIZED"] == status]
        if len(sub) == 0:
            continue
        n_has = sub["FILE_DATE"].notna().sum()
        print(f"  {status:15s}: {n_has:>4,} / {len(sub):>4,} ({n_has / len(sub):.1%})")

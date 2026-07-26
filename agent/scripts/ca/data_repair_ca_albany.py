"""Data repair for Albany (CA) permit records (pass-through).

Albany sample rows have no usable raw DATA JSON, so agency-source repair
of STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE is not
possible. This module still exposes the standard ``data_repair`` entry
point so Albany can follow the same call pattern as other jurisdictions.

The returned frame is an unchanged copy of the input plus null-valued
flag columns (and a null INFERRED_SCHEMA column) for schema compatibility.
"""

import pandas as pd
import numpy as np


def data_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Pass-through repair for Albany permit records.

    No field values are changed. Creates the standard flag columns with
    null values so downstream code can treat Albany like other repaired
    jurisdictions.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame filtered to JURISDICTION == "Albany".  Expected to
        contain columns STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE,
        FINAL_DATE, and DATA (DATA is unused here).

    Returns
    -------
    pd.DataFrame
        Copy of *df* with null-valued columns STATUS_NORMALIZED_FLAG,
        FILE_DATE_FLAG, PERMIT_DATE_FLAG, FINAL_DATE_FLAG, and
        INFERRED_SCHEMA.  Original field values are left unchanged.
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

    return out


# ── CLI: run standalone to preview repair stats ─────────────────────────────

if __name__ == "__main__":
    import os
    from dotenv import load_dotenv

    load_dotenv("/Users/ekung/projects/la-permits-data/.env")
    MY_DATA_PATH = os.getenv("MY_DATA_PATH")
    filepath = os.path.join(MY_DATA_PATH, "processed_data", "permits_ca_sample.parquet")
    df = pd.read_parquet(filepath)
    city = df[(df["JURISDICTION"] == "Albany") & (df["STATE"] == "CA")].copy()

    print(f"Albany records: {len(city):,}\n")
    print(f"DATA non-null: {city['DATA'].notna().sum():,} / {len(city):,}\n")

    repaired = data_repair(city)

    print("INFERRED_SCHEMA:")
    print(repaired["INFERRED_SCHEMA"].value_counts(dropna=False).to_string())
    print()

    for field in ["STATUS_NORMALIZED", "FILE_DATE", "PERMIT_DATE", "FINAL_DATE"]:
        flag_col = f"{field}_FLAG"
        n_filled = (repaired[flag_col] == "FILLED").sum()
        n_fixed = (repaired[flag_col] == "FIXED").sum()
        n_flag_null = repaired[flag_col].isna().sum()
        print(f"{field}:")
        print(f"  FILLED: {n_filled:>4,}   FIXED: {n_fixed:>4,}   FLAG null: {n_flag_null:>4,}")

        before_missing = city[field].isna().sum()
        after_missing = repaired[field].isna().sum()
        print(f"  Missing before: {before_missing:>4,}   Missing after: {after_missing:>4,}")
        print()

    # Confirm pass-through: core fields unchanged
    for field in ["STATUS_NORMALIZED", "FILE_DATE", "PERMIT_DATE", "FINAL_DATE"]:
        unchanged = city[field].equals(repaired[field])
        print(f"{field} unchanged: {unchanged}")

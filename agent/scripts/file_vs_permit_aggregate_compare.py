"""Compare aggregate monthly/annual permit counts under FILE_DATE vs PERMIT_DATE.

Uses all rows with each date (not only both), which is the relevant
interchangeability question for time-period aggregates.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from dotenv import load_dotenv

load_dotenv()

AGENT_DATA = Path(os.environ["AGENT_DATA_PATH"])
MY_DATA = Path(os.environ["MY_DATA_PATH"])
PARQUET = MY_DATA / "processed_data" / "dewey_ca_la_county_permits.parquet"
OUT_DIR = AGENT_DATA / "file_vs_permit_date"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def load() -> pd.DataFrame:
    df = pq.read_table(
        PARQUET, columns=["JURISDICTION", "FILE_DATE", "PERMIT_DATE"]
    ).to_pandas()
    for c in ("FILE_DATE", "PERMIT_DATE"):
        df[c] = pd.to_datetime(df[c], errors="coerce")
    return df


def series_compare(
    file_dt: pd.Series, permit_dt: pd.Series, freq: str
) -> dict:
    f = file_dt.dropna().dt.to_period(freq).value_counts().sort_index()
    p = permit_dt.dropna().dt.to_period(freq).value_counts().sort_index()
    # Restrict to overlapping calendar support where either has activity
    idx = f.index.union(p.index)
    if len(idx) == 0:
        return {
            f"{freq.lower()}_corr": None,
            f"{freq.lower()}_mape": None,
            f"{freq.lower()}_median_abs_pct_diff": None,
            f"{freq.lower()}_n_periods": 0,
            f"{freq.lower()}_total_file": 0,
            f"{freq.lower()}_total_permit": 0,
        }

    fc = f.reindex(idx, fill_value=0).astype(float)
    pc = p.reindex(idx, fill_value=0).astype(float)

    # Overlap periods where BOTH series have nonzero counts — more fair
    both_nz = (fc > 0) & (pc > 0)
    if both_nz.sum() >= 3 and fc[both_nz].std() > 0 and pc[both_nz].std() > 0:
        corr = float(fc[both_nz].corr(pc[both_nz]))
    else:
        corr = None

    # Relative difference on overlapping nonzero periods
    if both_nz.sum() > 0:
        rel = np.abs(pc[both_nz] - fc[both_nz]) / np.maximum(fc[both_nz], 1.0)
        mape = float(rel.mean())
        med_ape = float(rel.median())
    else:
        mape = None
        med_ape = None

    return {
        f"{freq.lower()}_corr": corr,
        f"{freq.lower()}_mape": mape,
        f"{freq.lower()}_median_abs_pct_diff": med_ape,
        f"{freq.lower()}_n_periods": int(both_nz.sum()),
        f"{freq.lower()}_total_file": int(fc.sum()),
        f"{freq.lower()}_total_permit": int(pc.sum()),
    }


def gap_distribution(file_dt: pd.Series, permit_dt: pd.Series) -> dict:
    both = file_dt.notna() & permit_dt.notna()
    gap = (permit_dt[both] - file_dt[both]).dt.days
    if len(gap) == 0:
        return {"gap_hist": {}, "n_both": 0}
    # Coarse bins for canvas
    bins = [
        (-np.inf, -1, "permit_before_file"),
        (0, 0, "same_day"),
        (1, 7, "1_7d"),
        (8, 30, "8_30d"),
        (31, 90, "31_90d"),
        (91, 365, "91_365d"),
        (366, np.inf, "over_1y"),
    ]
    hist = {}
    n = len(gap)
    for lo, hi, label in bins:
        if lo == hi:
            hist[label] = float(((gap == lo).sum()) / n)
        else:
            hist[label] = float((((gap >= lo) & (gap <= hi)).sum()) / n)
    return {"gap_hist": hist, "n_both": int(n)}


def analyze(df: pd.DataFrame, name: str) -> dict:
    out = {"jurisdiction": name}
    out.update(series_compare(df["FILE_DATE"], df["PERMIT_DATE"], "M"))
    out.update(series_compare(df["FILE_DATE"], df["PERMIT_DATE"], "Q"))
    out.update(series_compare(df["FILE_DATE"], df["PERMIT_DATE"], "Y"))
    out.update(gap_distribution(df["FILE_DATE"], df["PERMIT_DATE"]))

    # Coverage
    n = len(df)
    has_f = df["FILE_DATE"].notna()
    has_p = df["PERMIT_DATE"].notna()
    out["n_total"] = int(n)
    out["pct_file"] = float(has_f.mean())
    out["pct_permit"] = float(has_p.mean())
    out["pct_both"] = float((has_f & has_p).mean())
    out["pct_file_or_permit"] = float((has_f | has_p).mean())
    out["dating_pattern"] = (
        "both"
        if out["pct_both"] >= 0.5
        else "file_dominant"
        if out["pct_file"] > out["pct_permit"] + 0.2
        else "permit_dominant"
        if out["pct_permit"] > out["pct_file"] + 0.2
        else "mixed_sparse"
        if out["pct_file_or_permit"] < 0.5
        else "mixed"
    )
    return out


def overall_gap_percentiles(df: pd.DataFrame) -> dict:
    both = df["FILE_DATE"].notna() & df["PERMIT_DATE"].notna()
    gap = (df.loc[both, "PERMIT_DATE"] - df.loc[both, "FILE_DATE"]).dt.days
    qs = [0.01, 0.05, 0.1, 0.25, 0.5, 0.75, 0.9, 0.95, 0.99]
    return {f"p{int(q*100)}": float(gap.quantile(q)) for q in qs} | {
        "mean": float(gap.mean()),
        "n": int(len(gap)),
    }


def main() -> None:
    print("Loading...")
    df = load()
    print(f"{len(df):,} rows")

    rows = [analyze(df, "ALL")]
    for juri, g in df.groupby("JURISDICTION", dropna=False):
        name = str(juri) if pd.notna(juri) else "(missing)"
        rows.append(analyze(g, name))
        r = rows[-1]
        print(
            f"  {name}: pattern={r['dating_pattern']} "
            f"M_corr={r['m_corr']} M_medAPE={r['m_median_abs_pct_diff']} "
            f"same-day hist={r['gap_hist'].get('same_day')}"
        )

    # Round floats
    def clean(obj):
        if isinstance(obj, dict):
            return {k: clean(v) for k, v in obj.items()}
        if isinstance(obj, float):
            if np.isnan(obj):
                return None
            return round(obj, 4)
        return obj

    rows = [clean(r) for r in rows]
    gap_pct = clean(overall_gap_percentiles(df))

    out = {"jurisdictions": rows, "overall_gap_percentiles": gap_pct}
    path = OUT_DIR / "aggregate_interchangeability.json"
    with open(path, "w") as f:
        json.dump(out, f, indent=2)
    print(f"Wrote {path}")
    print("Overall gap percentiles:", gap_pct)
    all_row = rows[0]
    print("ALL aggregate:", {k: all_row[k] for k in all_row if k != "gap_hist"})


if __name__ == "__main__":
    main()

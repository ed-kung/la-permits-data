"""Compare FILE_DATE vs PERMIT_DATE gaps and period interchangeability by jurisdiction."""

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

COLS = ["JURISDICTION", "FILE_DATE", "PERMIT_DATE", "STATUS_NORMALIZED"]


def load_dates() -> pd.DataFrame:
    table = pq.read_table(PARQUET, columns=COLS)
    df = table.to_pandas()
    for c in ("FILE_DATE", "PERMIT_DATE"):
        df[c] = pd.to_datetime(df[c], errors="coerce")
    return df


def gap_stats(gap_days: pd.Series) -> dict:
    """gap_days = PERMIT_DATE - FILE_DATE in days (positive => permit after file)."""
    g = gap_days.dropna()
    if len(g) == 0:
        return {
            "n_both": 0,
            "mean_days": None,
            "median_days": None,
            "p25_days": None,
            "p75_days": None,
            "p90_days": None,
            "std_days": None,
            "pct_same_day": None,
            "pct_within_7d": None,
            "pct_within_30d": None,
            "pct_within_90d": None,
            "pct_permit_before_file": None,
            "pct_same_month": None,
            "pct_same_quarter": None,
            "pct_same_year": None,
        }
    abs_g = g.abs()
    return {
        "n_both": int(len(g)),
        "mean_days": float(g.mean()),
        "median_days": float(g.median()),
        "p25_days": float(g.quantile(0.25)),
        "p75_days": float(g.quantile(0.75)),
        "p90_days": float(g.quantile(0.90)),
        "std_days": float(g.std()),
        "pct_same_day": float((g == 0).mean()),
        "pct_within_7d": float((abs_g <= 7).mean()),
        "pct_within_30d": float((abs_g <= 30).mean()),
        "pct_within_90d": float((abs_g <= 90).mean()),
        "pct_permit_before_file": float((g < 0).mean()),
        "pct_same_month": None,  # filled by caller with calendar alignment
        "pct_same_quarter": None,
        "pct_same_year": None,
    }


def period_alignment(file_dt: pd.Series, permit_dt: pd.Series) -> dict:
    mask = file_dt.notna() & permit_dt.notna()
    f, p = file_dt[mask], permit_dt[mask]
    if len(f) == 0:
        return {
            "pct_same_month": None,
            "pct_same_quarter": None,
            "pct_same_year": None,
        }
    return {
        "pct_same_month": float(
            ((f.dt.year == p.dt.year) & (f.dt.month == p.dt.month)).mean()
        ),
        "pct_same_quarter": float(
            ((f.dt.year == p.dt.year) & (f.dt.quarter == p.dt.quarter)).mean()
        ),
        "pct_same_year": float((f.dt.year == p.dt.year).mean()),
    }


def monthly_count_correlation(file_dt: pd.Series, permit_dt: pd.Series) -> dict:
    """Correlate monthly permit counts under each dating convention (rows with both dates)."""
    mask = file_dt.notna() & permit_dt.notna()
    f, p = file_dt[mask], permit_dt[mask]
    if len(f) < 50:
        return {
            "monthly_corr_both": None,
            "monthly_mape_both": None,
            "n_months_both": 0,
        }

    f_counts = f.dt.to_period("M").value_counts().sort_index()
    p_counts = p.dt.to_period("M").value_counts().sort_index()
    idx = f_counts.index.union(p_counts.index)
    fc = f_counts.reindex(idx, fill_value=0).astype(float)
    pc = p_counts.reindex(idx, fill_value=0).astype(float)

    if fc.std() == 0 or pc.std() == 0:
        corr = None
    else:
        corr = float(fc.corr(pc))

    # MAPE of monthly counts (permit-dated vs file-dated), avoid /0
    denom = np.maximum(fc.values, 1.0)
    mape = float(np.mean(np.abs(pc.values - fc.values) / denom))

    return {
        "monthly_corr_both": corr,
        "monthly_mape_both": mape,
        "n_months_both": int(len(idx)),
    }


def coverage_stats(file_dt: pd.Series, permit_dt: pd.Series) -> dict:
    n = len(file_dt)
    has_f = file_dt.notna()
    has_p = permit_dt.notna()
    return {
        "n_total": int(n),
        "n_file": int(has_f.sum()),
        "n_permit": int(has_p.sum()),
        "n_both": int((has_f & has_p).sum()),
        "n_file_only": int((has_f & ~has_p).sum()),
        "n_permit_only": int((~has_f & has_p).sum()),
        "n_neither": int((~has_f & ~has_p).sum()),
        "pct_file": float(has_f.mean()) if n else None,
        "pct_permit": float(has_p.mean()) if n else None,
        "pct_both": float((has_f & has_p).mean()) if n else None,
        "pct_file_or_permit": float((has_f | has_p).mean()) if n else None,
    }


def analyze_subset(df: pd.DataFrame) -> dict:
    file_dt = df["FILE_DATE"]
    permit_dt = df["PERMIT_DATE"]
    both = file_dt.notna() & permit_dt.notna()
    gap = (permit_dt[both] - file_dt[both]).dt.days.astype(float)

    out = coverage_stats(file_dt, permit_dt)
    out.update(gap_stats(gap))
    # overwrite n_both with coverage version (same)
    align = period_alignment(file_dt, permit_dt)
    out.update(align)
    out.update(monthly_count_correlation(file_dt, permit_dt))
    return out


def main() -> None:
    print(f"Reading {PARQUET} ...")
    df = load_dates()
    print(f"Loaded {len(df):,} rows")

    rows = []
    overall = analyze_subset(df)
    overall["jurisdiction"] = "ALL"
    rows.append(overall)

    for juri, g in df.groupby("JURISDICTION", dropna=False):
        stats = analyze_subset(g)
        stats["jurisdiction"] = str(juri) if pd.notna(juri) else "(missing)"
        rows.append(stats)
        print(
            f"  {stats['jurisdiction']}: n_both={stats['n_both']:,} "
            f"median_gap={stats['median_days']} same_month={stats['pct_same_month']}"
        )

    result = pd.DataFrame(rows)
    # Prefer readable column order
    front = [
        "jurisdiction",
        "n_total",
        "n_file",
        "n_permit",
        "n_both",
        "n_file_only",
        "n_permit_only",
        "pct_file",
        "pct_permit",
        "pct_both",
        "pct_file_or_permit",
        "mean_days",
        "median_days",
        "p25_days",
        "p75_days",
        "p90_days",
        "std_days",
        "pct_same_day",
        "pct_within_7d",
        "pct_within_30d",
        "pct_within_90d",
        "pct_permit_before_file",
        "pct_same_month",
        "pct_same_quarter",
        "pct_same_year",
        "monthly_corr_both",
        "monthly_mape_both",
        "n_months_both",
    ]
    result = result[front].sort_values(
        by=["jurisdiction"],
        key=lambda s: s.map(lambda x: (x != "ALL", x)),
    )

    csv_path = OUT_DIR / "file_vs_permit_date_by_jurisdiction.csv"
    json_path = OUT_DIR / "file_vs_permit_date_by_jurisdiction.json"
    result.to_csv(csv_path, index=False)

    # JSON with rounded floats for canvas embedding
    records = []
    for rec in result.to_dict(orient="records"):
        clean = {}
        for k, v in rec.items():
            if isinstance(v, float):
                if np.isnan(v):
                    clean[k] = None
                else:
                    clean[k] = round(v, 4)
            elif isinstance(v, (np.integer,)):
                clean[k] = int(v)
            else:
                clean[k] = v
        records.append(clean)

    with open(json_path, "w") as f:
        json.dump(records, f, indent=2)

    print(f"Wrote {csv_path}")
    print(f"Wrote {json_path}")

    # Quick overall summary to stdout
    all_row = next(r for r in records if r["jurisdiction"] == "ALL")
    print("\n=== OVERALL (rows with both dates) ===")
    for k in (
        "n_both",
        "mean_days",
        "median_days",
        "pct_same_day",
        "pct_within_30d",
        "pct_same_month",
        "pct_same_quarter",
        "pct_same_year",
        "monthly_corr_both",
        "monthly_mape_both",
        "pct_permit_before_file",
    ):
        print(f"  {k}: {all_row[k]}")


if __name__ == "__main__":
    main()

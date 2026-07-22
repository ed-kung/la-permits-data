"""Explore the DATA JSON blob and its link to FILE/PERMIT/FINAL dates and status.

Reservoir-samples ~300 rows per JURISDICTION, parses DATA, and measures which
nested keys equal the top-level date/status columns.

Outputs under AGENT_DATA_PATH/data_json_explore/:
  - jurisdiction_summary.json
  - samples_by_jurisdiction.json
  - field_mapping_by_jurisdiction.csv
"""

from __future__ import annotations

import json
import os
import random
import re
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

MY_DATA = Path(os.environ["MY_DATA_PATH"])
AGENT_DATA = Path(os.environ["AGENT_DATA_PATH"])
PARQUET = MY_DATA / "processed_data" / "dewey_ca_la_county_permits.parquet"
OUT = AGENT_DATA / "data_json_explore"
OUT.mkdir(parents=True, exist_ok=True)

COLS = [
    "JURISDICTION",
    "DATA",
    "FILE_DATE",
    "PERMIT_DATE",
    "FINAL_DATE",
    "STATUS_NORMALIZED",
    "STATUS_ORIGINAL",
]
TARGET = 300
EXAMPLES = 4
SEED = 42

DATE_KEY_RE = re.compile(
    r"date|issued|filed|final|approved|applied|application|expire|complet|inspect|open.?date|close",
    re.I,
)
STATUS_KEY_RE = re.compile(r"status|state|result|disposition|outcome", re.I)


def to_date(v):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return None
    if isinstance(v, pd.Timestamp):
        return None if pd.isna(v) else v.date()
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        try:
            iv = int(v)
            if iv > 1e12:
                return datetime.utcfromtimestamp(iv / 1000).date()
            if iv > 1e9:
                return datetime.utcfromtimestamp(iv).date()
        except Exception:
            return None
        return None
    if isinstance(v, str):
        s = v.strip()
        if not s or len(s) < 6:
            return None
        if not re.search(r"\d{4}|\d{1,2}[/-]\d{1,2}", s):
            return None
        for fmt, n in (
            ("%Y-%m-%d", 10),
            ("%Y-%m-%dT%H:%M:%S", 19),
            ("%m/%d/%Y", 10),
            ("%m/%d/%Y %H:%M:%S", 19),
            ("%Y/%m/%d", 10),
            ("%d-%b-%Y", 11),
        ):
            try:
                return datetime.strptime(s[:n], fmt).date()
            except Exception:
                pass
        ts = pd.to_datetime(s, errors="coerce")
        if pd.notna(ts):
            return ts.date()
    return None


def walk(obj, prefix=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            path = f"{prefix}.{k}" if prefix else str(k)
            yield from walk(v, path)
    elif isinstance(obj, list):
        for v in obj[:8]:
            yield from walk(v, prefix + "[]")
    else:
        yield prefix, obj


def truncate(o, depth=0):
    if depth > 4:
        return "..."
    if isinstance(o, dict):
        return {k: truncate(v, depth + 1) for k, v in list(o.items())[:50]}
    if isinstance(o, list):
        return [truncate(v, depth + 1) for v in o[:4]]
    if isinstance(o, str) and len(o) > 240:
        return o[:240] + "…"
    return o


def rate(num, den):
    return round(num / den, 4) if den else None


def main() -> None:
    pf = pq.ParquetFile(PARQUET)
    rng = random.Random(SEED)
    reservoir: dict[str, list] = defaultdict(list)
    reservoir_w: dict[str, int] = defaultdict(int)
    null_data: Counter = Counter()
    total_seen: Counter = Counter()

    print("Sampling pass...", flush=True)
    for rg in range(pf.num_row_groups):
        df = pf.read_row_group(rg, columns=COLS).to_pandas()
        print(f"  RG {rg}: {len(df)}", flush=True)
        for jur, g in df.groupby("JURISDICTION", dropna=False):
            j = jur if pd.notna(jur) else "(null)"
            total_seen[j] += len(g)
            null_mask = g["DATA"].isna() | (g["DATA"].astype(str).str.len() == 0)
            null_data[j] += int(null_mask.sum())
            g2 = g.loc[~null_mask]
            if g2.empty:
                continue
            for rec in g2.itertuples(index=False):
                reservoir_w[j] += 1
                n = reservoir_w[j]
                item = {
                    "JURISDICTION": j,
                    "DATA": rec.DATA,
                    "FILE_DATE": rec.FILE_DATE,
                    "PERMIT_DATE": rec.PERMIT_DATE,
                    "FINAL_DATE": rec.FINAL_DATE,
                    "STATUS_NORMALIZED": rec.STATUS_NORMALIZED,
                    "STATUS_ORIGINAL": rec.STATUS_ORIGINAL,
                }
                if len(reservoir[j]) < TARGET:
                    reservoir[j].append(item)
                else:
                    k = rng.randint(1, n)
                    if k <= TARGET:
                        reservoir[j][k - 1] = item

    key_counts: dict = defaultdict(Counter)
    key_types: dict = defaultdict(lambda: defaultdict(Counter))
    n_parsed: Counter = Counter()
    n_fail: Counter = Counter()
    file_hits: dict = defaultdict(Counter)
    permit_hits: dict = defaultdict(Counter)
    final_hits: dict = defaultdict(Counter)
    status_n_hits: dict = defaultdict(Counter)
    status_o_hits: dict = defaultdict(Counter)
    dateish: dict = defaultdict(Counter)
    statusish: dict = defaultdict(Counter)
    file_match_n: Counter = Counter()
    permit_match_n: Counter = Counter()
    final_match_n: Counter = Counter()
    sn_match_n: Counter = Counter()
    so_match_n: Counter = Counter()
    file_col_n: Counter = Counter()
    permit_col_n: Counter = Counter()
    final_col_n: Counter = Counter()
    sn_col_n: Counter = Counter()
    so_col_n: Counter = Counter()
    examples: dict = defaultdict(list)

    print("Parsing samples...", flush=True)
    for jur, items in reservoir.items():
        for item in items:
            try:
                obj = json.loads(item["DATA"])
            except Exception:
                n_fail[jur] += 1
                continue
            if not isinstance(obj, dict):
                n_fail[jur] += 1
                continue
            n_parsed[jur] += 1
            for k, v in obj.items():
                key_counts[jur][k] += 1
                key_types[jur][k][type(v).__name__] += 1

            file_d = to_date(item["FILE_DATE"])
            permit_d = to_date(item["PERMIT_DATE"])
            final_d = to_date(item["FINAL_DATE"])
            sn = item["STATUS_NORMALIZED"] if isinstance(item["STATUS_NORMALIZED"], str) else None
            so = item["STATUS_ORIGINAL"] if isinstance(item["STATUS_ORIGINAL"], str) else None
            if file_d:
                file_col_n[jur] += 1
            if permit_d:
                permit_col_n[jur] += 1
            if final_d:
                final_col_n[jur] += 1
            if sn:
                sn_col_n[jur] += 1
            if so:
                so_col_n[jur] += 1

            mf: set = set()
            mp: set = set()
            mz: set = set()
            msn: set = set()
            mso: set = set()
            for path, val in walk(obj):
                if DATE_KEY_RE.search(path):
                    dateish[jur][path] += 1
                if STATUS_KEY_RE.search(path):
                    statusish[jur][path] += 1
                d = to_date(val)
                if d is not None:
                    if file_d and d == file_d:
                        mf.add(path)
                    if permit_d and d == permit_d:
                        mp.add(path)
                    if final_d and d == final_d:
                        mz.add(path)
                if isinstance(val, str) and val.strip():
                    vs = val.strip()
                    if sn and vs.lower() == sn.lower():
                        msn.add(path)
                    if so and vs.lower() == so.lower():
                        mso.add(path)

            for k in mf:
                file_hits[jur][k] += 1
            for k in mp:
                permit_hits[jur][k] += 1
            for k in mz:
                final_hits[jur][k] += 1
            for k in msn:
                status_n_hits[jur][k] += 1
            for k in mso:
                status_o_hits[jur][k] += 1
            if mf:
                file_match_n[jur] += 1
            if mp:
                permit_match_n[jur] += 1
            if mz:
                final_match_n[jur] += 1
            if msn:
                sn_match_n[jur] += 1
            if mso:
                so_match_n[jur] += 1

            if len(examples[jur]) < EXAMPLES:
                examples[jur].append(
                    {
                        "file_date": str(file_d) if file_d else None,
                        "permit_date": str(permit_d) if permit_d else None,
                        "final_date": str(final_d) if final_d else None,
                        "status_normalized": sn,
                        "status_original": so,
                        "matched_file_keys": sorted(mf),
                        "matched_permit_keys": sorted(mp),
                        "matched_final_keys": sorted(mz),
                        "matched_status_norm_keys": sorted(msn),
                        "matched_status_orig_keys": sorted(mso),
                        "top_level_keys": sorted(obj.keys()),
                        "data": truncate(obj),
                    }
                )

    summary = []
    for jur in sorted(n_parsed.keys(), key=lambda j: -total_seen[j]):
        n = n_parsed[jur]
        summary.append(
            {
                "jurisdiction": jur,
                "n_total_in_data": int(total_seen[jur]),
                "n_null_data": int(null_data[jur]),
                "null_data_pct": rate(null_data[jur], total_seen[jur]),
                "n_sample_parsed": n,
                "n_sample_fail": int(n_fail[jur]),
                "n_unique_top_keys": len(key_counts[jur]),
                "top_keys": [
                    {
                        "key": k,
                        "freq": int(c),
                        "pct": rate(c, n),
                        "types": dict(key_types[jur][k]),
                    }
                    for k, c in key_counts[jur].most_common(30)
                ],
                "file_date": {
                    "col_nonnull_in_sample": int(file_col_n[jur]),
                    "any_match_rate_given_col": rate(file_match_n[jur], file_col_n[jur]),
                    "best_keys": [
                        {
                            "key": k,
                            "hits": int(c),
                            "rate_given_col": rate(c, file_col_n[jur]),
                        }
                        for k, c in file_hits[jur].most_common(6)
                    ],
                },
                "permit_date": {
                    "col_nonnull_in_sample": int(permit_col_n[jur]),
                    "any_match_rate_given_col": rate(permit_match_n[jur], permit_col_n[jur]),
                    "best_keys": [
                        {
                            "key": k,
                            "hits": int(c),
                            "rate_given_col": rate(c, permit_col_n[jur]),
                        }
                        for k, c in permit_hits[jur].most_common(6)
                    ],
                },
                "final_date": {
                    "col_nonnull_in_sample": int(final_col_n[jur]),
                    "any_match_rate_given_col": rate(final_match_n[jur], final_col_n[jur]),
                    "best_keys": [
                        {
                            "key": k,
                            "hits": int(c),
                            "rate_given_col": rate(c, final_col_n[jur]),
                        }
                        for k, c in final_hits[jur].most_common(6)
                    ],
                },
                "status_normalized": {
                    "col_nonnull_in_sample": int(sn_col_n[jur]),
                    "any_match_rate_given_col": rate(sn_match_n[jur], sn_col_n[jur]),
                    "best_keys": [
                        {
                            "key": k,
                            "hits": int(c),
                            "rate_given_col": rate(c, sn_col_n[jur]),
                        }
                        for k, c in status_n_hits[jur].most_common(6)
                    ],
                },
                "status_original": {
                    "col_nonnull_in_sample": int(so_col_n[jur]),
                    "any_match_rate_given_col": rate(so_match_n[jur], so_col_n[jur]),
                    "best_keys": [
                        {
                            "key": k,
                            "hits": int(c),
                            "rate_given_col": rate(c, so_col_n[jur]),
                        }
                        for k, c in status_o_hits[jur].most_common(6)
                    ],
                },
                "dateish_keys": [
                    {"key": k, "freq": int(c)} for k, c in dateish[jur].most_common(20)
                ],
                "statusish_keys": [
                    {"key": k, "freq": int(c)} for k, c in statusish[jur].most_common(15)
                ],
            }
        )

    with open(OUT / "jurisdiction_summary.json", "w") as f:
        json.dump(summary, f, indent=2)
    with open(OUT / "samples_by_jurisdiction.json", "w") as f:
        json.dump(examples, f, indent=2, default=str)

    map_rows = []
    for s in summary:
        def top(block):
            if block["best_keys"]:
                b = block["best_keys"][0]
                return b["key"], b["rate_given_col"]
            return None, None

        fk, fr = top(s["file_date"])
        pk, pr = top(s["permit_date"])
        zk, zr = top(s["final_date"])
        nk, nr = top(s["status_normalized"])
        ok, o_r = top(s["status_original"])
        map_rows.append(
            {
                "jurisdiction": s["jurisdiction"],
                "n_total": s["n_total_in_data"],
                "null_data_pct": s["null_data_pct"],
                "n_sample": s["n_sample_parsed"],
                "n_top_keys": s["n_unique_top_keys"],
                "top_keys_preview": ", ".join(x["key"] for x in s["top_keys"][:10]),
                "FILE_DATE_src": fk,
                "FILE_DATE_match": fr,
                "PERMIT_DATE_src": pk,
                "PERMIT_DATE_match": pr,
                "FINAL_DATE_src": zk,
                "FINAL_DATE_match": zr,
                "STATUS_NORMALIZED_src": nk,
                "STATUS_NORMALIZED_match": nr,
                "STATUS_ORIGINAL_src": ok,
                "STATUS_ORIGINAL_match": o_r,
                "file_any_match": s["file_date"]["any_match_rate_given_col"],
                "permit_any_match": s["permit_date"]["any_match_rate_given_col"],
                "final_any_match": s["final_date"]["any_match_rate_given_col"],
                "status_n_any_match": s["status_normalized"]["any_match_rate_given_col"],
            }
        )
    pd.DataFrame(map_rows).to_csv(OUT / "field_mapping_by_jurisdiction.csv", index=False)
    print("Wrote", OUT)


if __name__ == "__main__":
    main()

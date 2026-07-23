"""
Thorough analysis of raw DATA JSON date fields — no truncation.
For each city, catalog ALL date-like fields and assess recovery potential.
Fixes truncation issue from v1 by printing all fields.
"""

import json
import os
import re
from collections import Counter, defaultdict

import pandas as pd
from dotenv import load_dotenv

load_dotenv()

MY_DATA_PATH = os.environ["MY_DATA_PATH"]
AGENT_DATA_PATH = os.environ["AGENT_DATA_PATH"]

df = pd.read_parquet(os.path.join(MY_DATA_PATH, "processed_data", "permits_top50_sample.parquet"))

DATE_VAL_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}"
    r"|^\d{1,2}/\d{1,2}/\d{2,4}"
)


def flatten_all(obj, prefix="", max_list=5):
    """Flatten JSON fully, sampling up to max_list items from arrays."""
    items = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            new_key = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict):
                items.update(flatten_all(v, new_key, max_list))
            elif isinstance(v, list):
                for i, item in enumerate(v[:max_list]):
                    if isinstance(item, dict):
                        items.update(flatten_all(item, f"{new_key}[{i}]", max_list))
                    else:
                        items[f"{new_key}[{i}]"] = item
            else:
                items[new_key] = v
    return items


def normalize_key(key):
    return re.sub(r"\[\d+\]", "[*]", key)


jurisdictions = sorted(df["JURISDICTION"].unique())

# Collect full results
all_results = {}

for jur in jurisdictions:
    jdf = df[df["JURISDICTION"] == jur]
    n_total = len(jdf)

    date_stats = {}
    for col in ["FILE_DATE", "PERMIT_DATE", "FINAL_DATE"]:
        n_present = jdf[col].notna().sum()
        date_stats[col] = {"present": int(n_present), "missing": int(n_total - n_present),
                           "pct": round(100 * n_present / n_total, 1)}

    field_date_count = Counter()
    field_total_count = Counter()
    field_examples = defaultdict(list)

    # Track which raw fields appear when each processed date is missing
    raw_when_file_missing = Counter()
    raw_when_permit_missing = Counter()
    raw_when_final_missing = Counter()
    n_file_miss_with_raw = 0
    n_permit_miss_with_raw = 0
    n_final_miss_with_raw = 0

    for idx, row in jdf.iterrows():
        data = row["DATA"]
        if pd.isna(data):
            continue
        try:
            obj = json.loads(data) if isinstance(data, str) else data
        except:
            continue

        flat = flatten_all(obj, max_list=3)

        row_date_fields = set()
        seen_canon = set()
        for key, val in flat.items():
            canon = normalize_key(key)
            if canon not in seen_canon:
                seen_canon.add(canon)
                field_total_count[canon] += 1

            if val is not None:
                val_str = str(val).strip()
                if DATE_VAL_RE.match(val_str):
                    field_date_count[canon] += 1
                    row_date_fields.add(canon)
                    if len(field_examples[canon]) < 2:
                        field_examples[canon].append(val_str)

        if pd.isna(row["FILE_DATE"]) and row_date_fields:
            n_file_miss_with_raw += 1
            for f in row_date_fields:
                raw_when_file_missing[f] += 1
        if pd.isna(row["PERMIT_DATE"]) and row_date_fields:
            n_permit_miss_with_raw += 1
            for f in row_date_fields:
                raw_when_permit_missing[f] += 1
        if pd.isna(row["FINAL_DATE"]) and row_date_fields:
            n_final_miss_with_raw += 1
            for f in row_date_fields:
                raw_when_final_missing[f] += 1

    all_results[jur] = {
        "date_stats": date_stats,
        "all_date_fields": {
            k: {"count": field_date_count[k], "total": field_total_count[k],
                "examples": field_examples.get(k, [])}
            for k in sorted(field_date_count.keys(), key=lambda x: -field_date_count[x])
        },
        "file_recovery": {
            "missing": date_stats["FILE_DATE"]["missing"],
            "rows_with_raw": n_file_miss_with_raw,
            "top_fields": dict(raw_when_file_missing.most_common(10))
        },
        "permit_recovery": {
            "missing": date_stats["PERMIT_DATE"]["missing"],
            "rows_with_raw": n_permit_miss_with_raw,
            "top_fields": dict(raw_when_permit_missing.most_common(10))
        },
        "final_recovery": {
            "missing": date_stats["FINAL_DATE"]["missing"],
            "rows_with_raw": n_final_miss_with_raw,
            "top_fields": dict(raw_when_final_missing.most_common(10))
        },
    }


# Now print focused output: for each city, show ALL date fields
# with a focus on fields relevant to PERMIT_DATE and FINAL_DATE recovery
print("=" * 100)
print("COMPLETE RAW DATA DATE FIELD CATALOG (NO TRUNCATION)")
print("=" * 100)

for jur in jurisdictions:
    r = all_results[jur]
    ds = r["date_stats"]
    print(f"\n{'=' * 80}")
    print(f"  {jur}")
    print(f"{'=' * 80}")
    print(f"  FILE_DATE: {ds['FILE_DATE']['present']}/{ds['FILE_DATE']['present']+ds['FILE_DATE']['missing']} ({ds['FILE_DATE']['pct']}%)")
    print(f"  PERMIT_DATE: {ds['PERMIT_DATE']['present']}/{ds['PERMIT_DATE']['present']+ds['PERMIT_DATE']['missing']} ({ds['PERMIT_DATE']['pct']}%)")
    print(f"  FINAL_DATE: {ds['FINAL_DATE']['present']}/{ds['FINAL_DATE']['present']+ds['FINAL_DATE']['missing']} ({ds['FINAL_DATE']['pct']}%)")

    print(f"\n  ALL date-like fields in DATA:")
    for field, info in r["all_date_fields"].items():
        n = ds['FILE_DATE']['present'] + ds['FILE_DATE']['missing']
        pct = 100 * info["count"] / n if n > 0 else 0
        print(f"    {field}: {info['count']}/{n} ({pct:.1f}%)  ex: {info['examples']}")

    # Recovery analysis
    for label, key in [("FILE_DATE", "file_recovery"), ("PERMIT_DATE", "permit_recovery"), ("FINAL_DATE", "final_recovery")]:
        rec = r[key]
        if rec["missing"] == 0:
            print(f"\n  {label}: fully populated")
        else:
            print(f"\n  {label} missing: {rec['missing']} rows, {rec['rows_with_raw']} have raw dates")
            if rec["top_fields"]:
                print(f"    Candidate fields: {dict(list(rec['top_fields'].items())[:8])}")

# Save to JSON
out_path = os.path.join(AGENT_DATA_PATH, "raw_data_date_analysis_v2.json")
with open(out_path, "w") as f:
    json.dump(all_results, f, indent=2, default=str)
print(f"\n\nSaved to: {out_path}")

"""
Explore the raw DATA JSON field in the permits sample to understand
what date information is available and could be extracted for each jurisdiction.

Outputs a detailed analysis to stdout and a summary JSON to AGENT_DATA_PATH.
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

DATE_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}"  # ISO date start
    r"|^\d{1,2}/\d{1,2}/\d{2,4}"  # US date format
    r"|^\d{1,2}-\d{1,2}-\d{2,4}"  # alt date format
)

DATE_NAME_PATTERN = re.compile(r"date|_dt$|_dt_|time|expir", re.IGNORECASE)


def flatten_json(obj, prefix=""):
    """Flatten nested JSON, returning {dotted_key: value} pairs."""
    items = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            new_key = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict):
                items.update(flatten_json(v, new_key))
            elif isinstance(v, list):
                if len(v) > 0 and isinstance(v[0], dict):
                    for i, item in enumerate(v[:3]):  # sample up to 3 list items
                        items.update(flatten_json(item, f"{new_key}[{i}]"))
                else:
                    items[new_key] = v
            else:
                items[new_key] = v
    return items


def looks_like_date(value):
    """Check if a string value looks like a date."""
    if not isinstance(value, str):
        return False
    return bool(DATE_PATTERN.match(value.strip()))


def normalize_field_name(name):
    """Strip list indices and prefixes to get a canonical field name."""
    return re.sub(r"\[\d+\]", "[*]", name)


jurisdictions = sorted(df["JURISDICTION"].unique())

results = {}

for jur in jurisdictions:
    jdf = df[df["JURISDICTION"] == jur]
    n_total = len(jdf)
    n_data_present = jdf["DATA"].notna().sum()

    # Date column stats for this jurisdiction
    date_stats = {}
    for col in ["FILE_DATE", "PERMIT_DATE", "FINAL_DATE"]:
        n_present = jdf[col].notna().sum()
        date_stats[col] = {"present": int(n_present), "missing": int(n_total - n_present)}

    # Parse all DATA JSONs and catalog fields
    date_field_counts = Counter()      # field_name -> count of rows where it appears
    date_field_nonempty = Counter()    # field_name -> count of rows where it has a date-like value
    date_field_examples = defaultdict(list)  # field_name -> sample values
    all_field_names = Counter()        # all flattened field names
    top_level_keys = Counter()         # top-level JSON keys

    # Also track: for rows where FILE_DATE/PERMIT_DATE/FINAL_DATE is missing,
    # how many have date-like fields in DATA?
    rows_missing_file_with_raw_dates = 0
    rows_missing_permit_with_raw_dates = 0
    rows_missing_final_with_raw_dates = 0
    
    raw_date_field_names_for_missing_file = Counter()
    raw_date_field_names_for_missing_permit = Counter()
    raw_date_field_names_for_missing_final = Counter()

    for idx, row in jdf.iterrows():
        data_raw = row["DATA"]
        if pd.isna(data_raw):
            continue

        try:
            data_json = json.loads(data_raw) if isinstance(data_raw, str) else data_raw
        except (json.JSONDecodeError, TypeError):
            continue

        if isinstance(data_json, dict):
            for k in data_json.keys():
                top_level_keys[k] += 1

        flat = flatten_json(data_json)
        
        # Find all date-like fields (by name or by value)
        row_date_fields = {}
        for field_name, value in flat.items():
            canon = normalize_field_name(field_name)
            all_field_names[canon] += 1
            
            is_date_name = bool(DATE_NAME_PATTERN.search(field_name))
            is_date_value = looks_like_date(str(value)) if value is not None else False
            
            if is_date_name or is_date_value:
                date_field_counts[canon] += 1
                if value is not None and str(value).strip() and str(value).strip().lower() not in ("", "none", "null", "nan"):
                    if is_date_value:
                        date_field_nonempty[canon] += 1
                        row_date_fields[canon] = str(value)
                        if len(date_field_examples[canon]) < 3:
                            date_field_examples[canon].append(str(value))

        # Check if this row has missing processed dates but has raw date fields
        if pd.isna(row["FILE_DATE"]) and row_date_fields:
            rows_missing_file_with_raw_dates += 1
            for f in row_date_fields:
                raw_date_field_names_for_missing_file[f] += 1
        if pd.isna(row["PERMIT_DATE"]) and row_date_fields:
            rows_missing_permit_with_raw_dates += 1
            for f in row_date_fields:
                raw_date_field_names_for_missing_permit[f] += 1
        if pd.isna(row["FINAL_DATE"]) and row_date_fields:
            rows_missing_final_with_raw_dates += 1
            for f in row_date_fields:
                raw_date_field_names_for_missing_final[f] += 1

    results[jur] = {
        "n_total": n_total,
        "n_data_present": int(n_data_present),
        "date_stats": date_stats,
        "top_level_keys": dict(top_level_keys.most_common(20)),
        "date_fields": {
            k: {
                "appears_in": date_field_counts[k],
                "has_date_value": date_field_nonempty[k],
                "examples": date_field_examples.get(k, [])
            }
            for k in sorted(date_field_counts.keys(), key=lambda x: -date_field_counts[x])
        },
        "rows_missing_file_with_raw_dates": rows_missing_file_with_raw_dates,
        "rows_missing_permit_with_raw_dates": rows_missing_permit_with_raw_dates,
        "rows_missing_final_with_raw_dates": rows_missing_final_with_raw_dates,
        "raw_fields_when_file_missing": dict(raw_date_field_names_for_missing_file.most_common(10)),
        "raw_fields_when_permit_missing": dict(raw_date_field_names_for_missing_permit.most_common(10)),
        "raw_fields_when_final_missing": dict(raw_date_field_names_for_missing_final.most_common(10)),
    }

# Print results
print("=" * 100)
print("RAW DATA DATE FIELD ANALYSIS BY JURISDICTION")
print("=" * 100)

for jur in jurisdictions:
    r = results[jur]
    print(f"\n{'=' * 80}")
    print(f"  {jur}")
    print(f"{'=' * 80}")
    print(f"  Records: {r['n_total']}, DATA present: {r['n_data_present']}")
    
    print(f"\n  Processed date availability:")
    for col, stats in r["date_stats"].items():
        pct = 100 * stats["present"] / r["n_total"] if r["n_total"] > 0 else 0
        print(f"    {col}: {stats['present']}/{r['n_total']} ({pct:.1f}%) present")
    
    print(f"\n  Top-level JSON keys: {list(r['top_level_keys'].keys())[:15]}")
    
    print(f"\n  Date-like fields found in DATA:")
    for field_name, info in list(r["date_fields"].items())[:15]:
        pct = 100 * info["has_date_value"] / r["n_data_present"] if r["n_data_present"] > 0 else 0
        print(f"    {field_name}: {info['has_date_value']}/{r['n_data_present']} ({pct:.1f}%) "
              f"  ex: {info['examples'][:2]}")
    
    print(f"\n  Recovery potential:")
    ds = r["date_stats"]
    
    if ds["FILE_DATE"]["missing"] > 0:
        print(f"    FILE_DATE missing: {ds['FILE_DATE']['missing']} rows")
        print(f"      Rows with any raw date: {r['rows_missing_file_with_raw_dates']}")
        if r["raw_fields_when_file_missing"]:
            print(f"      Candidate raw fields: {dict(list(r['raw_fields_when_file_missing'].items())[:5])}")
    else:
        print(f"    FILE_DATE: fully populated (no recovery needed)")
    
    if ds["PERMIT_DATE"]["missing"] > 0:
        print(f"    PERMIT_DATE missing: {ds['PERMIT_DATE']['missing']} rows")
        print(f"      Rows with any raw date: {r['rows_missing_permit_with_raw_dates']}")
        if r["raw_fields_when_permit_missing"]:
            print(f"      Candidate raw fields: {dict(list(r['raw_fields_when_permit_missing'].items())[:5])}")
    else:
        print(f"    PERMIT_DATE: fully populated (no recovery needed)")
    
    if ds["FINAL_DATE"]["missing"] > 0:
        print(f"    FINAL_DATE missing: {ds['FINAL_DATE']['missing']} rows")
        print(f"      Rows with any raw date: {r['rows_missing_final_with_raw_dates']}")
        if r["raw_fields_when_final_missing"]:
            print(f"      Candidate raw fields: {dict(list(r['raw_fields_when_final_missing'].items())[:5])}")
    else:
        print(f"    FINAL_DATE: fully populated (no recovery needed)")

# Save full results
os.makedirs(AGENT_DATA_PATH, exist_ok=True)
out_path = os.path.join(AGENT_DATA_PATH, "raw_data_date_analysis.json")
with open(out_path, "w") as f:
    json.dump(results, f, indent=2, default=str)
print(f"\n\nFull results saved to: {out_path}")

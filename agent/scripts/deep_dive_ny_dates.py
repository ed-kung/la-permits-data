"""
Deep dive into New York raw DATA to catalog ALL date-like fields
across all record schemas.
"""

import json
import os
import re
from collections import Counter, defaultdict

import pandas as pd
from dotenv import load_dotenv

load_dotenv()

MY_DATA_PATH = os.environ["MY_DATA_PATH"]

df = pd.read_parquet(os.path.join(MY_DATA_PATH, "processed_data", "permits_top50_sample.parquet"))
ny = df[df["JURISDICTION"] == "New York"].copy()

print(f"New York records: {len(ny)}")
print(f"DATA non-null: {ny['DATA'].notna().sum()}")

# For each record, parse the JSON and find ALL fields that contain date-like values
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
    """Strip array indices to get canonical field name."""
    return re.sub(r"\[\d+\]", "[*]", key)


# Pass 1: Identify all distinct top-level structures (record schemas)
schema_counter = Counter()
for idx, row in ny.iterrows():
    data = row["DATA"]
    if pd.isna(data):
        continue
    try:
        obj = json.loads(data) if isinstance(data, str) else data
    except:
        continue
    if isinstance(obj, dict):
        top_keys = tuple(sorted(obj.keys())[:10])
        schema_counter[top_keys] += 1

print(f"\n=== DISTINCT RECORD SCHEMAS (by top-level keys) ===")
for keys, count in schema_counter.most_common():
    print(f"  Count={count}: {list(keys)}")

# Pass 2: For every record, flatten and find ALL fields with date-like values
field_date_count = Counter()  # canonical field -> count of records with a date value
field_total_count = Counter()  # canonical field -> count of records where field exists
field_examples = defaultdict(list)

for idx, row in ny.iterrows():
    data = row["DATA"]
    if pd.isna(data):
        continue
    try:
        obj = json.loads(data) if isinstance(data, str) else data
    except:
        continue

    flat = flatten_all(obj, max_list=3)
    
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
                if len(field_examples[canon]) < 2:
                    field_examples[canon].append(val_str)

print(f"\n=== ALL FIELDS WITH DATE-LIKE VALUES (sorted by frequency) ===")
for field, count in sorted(field_date_count.items(), key=lambda x: -x[1]):
    total = field_total_count.get(field, 0)
    examples = field_examples.get(field, [])
    print(f"  {field}: {count}/{total} records have date values  ex: {examples}")

# Pass 3: Show a few full records to understand the schemas
print(f"\n\n=== SAMPLE RECORDS BY SCHEMA TYPE ===")
seen_schemas = set()
for idx, row in ny.iterrows():
    data = row["DATA"]
    if pd.isna(data):
        continue
    try:
        obj = json.loads(data) if isinstance(data, str) else data
    except:
        continue
    if isinstance(obj, dict):
        top_keys = tuple(sorted(obj.keys())[:10])
        if top_keys not in seen_schemas:
            seen_schemas.add(top_keys)
            print(f"\n--- Schema: {list(top_keys)[:8]}... ---")
            print(f"    FILE_DATE={row['FILE_DATE']}, PERMIT_DATE={row['PERMIT_DATE']}, FINAL_DATE={row['FINAL_DATE']}")
            
            # Show all date-like fields from this record
            flat = flatten_all(obj, max_list=2)
            date_fields = {}
            for key, val in flat.items():
                if val is not None:
                    val_str = str(val).strip()
                    if DATE_VAL_RE.match(val_str):
                        date_fields[key] = val_str
            
            print(f"    Date fields found:")
            for k, v in sorted(date_fields.items()):
                print(f"      {k} = {v}")
            
            if len(seen_schemas) >= 10:
                break

# Pass 4: Focus on completion_date, signoff_date, and other FINAL_DATE candidates
print(f"\n\n=== FINAL_DATE CANDIDATE FIELDS ===")
final_candidates = ["completion_date", "signoff_date", "final", "completed", "close", "expir"]
for field, count in sorted(field_date_count.items(), key=lambda x: -x[1]):
    field_lower = field.lower()
    if any(c in field_lower for c in final_candidates):
        total = field_total_count.get(field, 0)
        examples = field_examples.get(field, [])
        print(f"  {field}: {count}/{total} records  ex: {examples}")

# Pass 5: Check specifically for completion_date at top level
print(f"\n\n=== completion_date SPECIFICALLY ===")
n_has_completion = 0
n_completion_with_value = 0
completion_examples = []
for idx, row in ny.iterrows():
    data = row["DATA"]
    if pd.isna(data):
        continue
    try:
        obj = json.loads(data) if isinstance(data, str) else data
    except:
        continue
    if isinstance(obj, dict):
        if "completion_date" in obj:
            n_has_completion += 1
            val = obj["completion_date"]
            if val is not None and str(val).strip():
                val_str = str(val).strip()
                if DATE_VAL_RE.match(val_str):
                    n_completion_with_value += 1
                    if len(completion_examples) < 5:
                        completion_examples.append((val_str, str(row['FINAL_DATE'])))

print(f"  Records with 'completion_date' key: {n_has_completion}/{len(ny)}")
print(f"  Records with date value in completion_date: {n_completion_with_value}")
print(f"  Examples (completion_date, FINAL_DATE): {completion_examples}")

# Check other top-level date fields
print(f"\n=== ALL TOP-LEVEL DATE FIELDS ===")
top_level_date_fields = Counter()
top_level_date_values = Counter()
top_level_examples = defaultdict(list)

for idx, row in ny.iterrows():
    data = row["DATA"]
    if pd.isna(data):
        continue
    try:
        obj = json.loads(data) if isinstance(data, str) else data
    except:
        continue
    if isinstance(obj, dict):
        for k, v in obj.items():
            if v is not None and isinstance(v, str) and DATE_VAL_RE.match(v.strip()):
                top_level_date_fields[k] += 1
                if len(top_level_examples[k]) < 3:
                    top_level_examples[k].append(v.strip())
            elif isinstance(v, str) and ("date" in k.lower() or "time" in k.lower()):
                top_level_date_values[k] += 1

print("Fields with date values at top level:")
for field, count in top_level_date_fields.most_common():
    print(f"  {field}: {count} records  ex: {top_level_examples[field]}")

print("\nDate-named fields at top level WITHOUT date values:")
for field, count in top_level_date_values.most_common():
    print(f"  {field}: {count} records (field exists but no date value)")

"""Explore New York permits data to assess date fill-in potential from DATA column."""

import sys
import os
import json
import math
from collections import Counter

import pandas as pd
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from scripts.data_utils import extract_date_fields, detect_schema, _is_missing

from dotenv import load_dotenv, find_dotenv
load_dotenv(find_dotenv())

MY_DATA_PATH = os.getenv("MY_DATA_PATH")
AGENT_DATA_PATH = os.getenv("AGENT_DATA_PATH")

# ── Load data ────────────────────────────────────────────────────────────────
filepath = os.path.join(MY_DATA_PATH, "processed_data", "permits_top50_sample.parquet")
print(f"Loading data from: {filepath}")
df = pd.read_parquet(filepath)
print(f"Full dataset: {len(df):,} rows, {len(df.columns)} columns")
print(f"Columns: {list(df.columns)}")

# Filter to New York
ny = df[df['JURISDICTION'] == 'New York'].copy()
print(f"\nNew York records: {len(ny):,}")

# ── Missing value overview ───────────────────────────────────────────────────
print("\n" + "="*80)
print("MISSING VALUES FOR DATE COLUMNS")
print("="*80)
for col in ['FILE_DATE', 'PERMIT_DATE', 'FINAL_DATE']:
    n_total = len(ny)
    n_missing = ny[col].isna().sum()
    n_present = n_total - n_missing
    print(f"  {col:15s}: {n_present:>6,} present, {n_missing:>6,} missing ({n_missing/n_total:.1%})")

# Also check DATA column availability
n_data_missing = ny['DATA'].apply(lambda x: _is_missing(x)).sum()
print(f"\n  DATA column missing: {n_data_missing:,} ({n_data_missing/len(ny):.1%})")

# ── Schema distribution ─────────────────────────────────────────────────────
print("\n" + "="*80)
print("SCHEMA DISTRIBUTION")
print("="*80)
if 'SCHEMA' in ny.columns:
    print(ny['SCHEMA'].value_counts())
ny['_schema_detected'] = ny['DATA'].apply(detect_schema)
print("\nDetected schemas:")
print(ny['_schema_detected'].value_counts(dropna=False))

# ── STATUS distribution ─────────────────────────────────────────────────────
print("\n" + "="*80)
print("STATUS DISTRIBUTION")
print("="*80)
if 'STATUS_NORMALIZED' in ny.columns:
    print(ny['STATUS_NORMALIZED'].value_counts(dropna=False))

# ── Missing dates by status ─────────────────────────────────────────────────
print("\n" + "="*80)
print("MISSING DATES BY STATUS")
print("="*80)
if 'STATUS_NORMALIZED' in ny.columns:
    for status in ny['STATUS_NORMALIZED'].dropna().unique():
        sub = ny[ny['STATUS_NORMALIZED'] == status]
        print(f"\n  Status: {status} (n={len(sub):,})")
        for col in ['FILE_DATE', 'PERMIT_DATE', 'FINAL_DATE']:
            n_missing = sub[col].isna().sum()
            print(f"    {col:15s}: {n_missing:>6,} missing ({n_missing/len(sub):.1%})")

# ── Extract date fields from DATA column using extract_date_fields ───────────
print("\n" + "="*80)
print("EXTRACTING DATE FIELDS FROM DATA COLUMN (sample)")
print("="*80)

# Apply extract_date_fields to all NY records
print("Applying extract_date_fields to all New York records...")
ny['_date_fields'] = ny['DATA'].apply(extract_date_fields)
print("Done.")

# Show a few examples
for i, (idx, row) in enumerate(ny.iterrows()):
    if i >= 3:
        break
    print(f"\n--- Record {i+1} (index={idx}) ---")
    print(f"  FILE_DATE:   {row.get('FILE_DATE')}")
    print(f"  PERMIT_DATE: {row.get('PERMIT_DATE')}")
    print(f"  FINAL_DATE:  {row.get('FINAL_DATE')}")
    df_fields = row['_date_fields']
    print(f"  Date fields from DATA:")
    print(json.dumps(df_fields, indent=4, default=str)[:2000])

# ── Catalog all unique date-related keys ─────────────────────────────────────
print("\n" + "="*80)
print("ALL DATE-RELATED KEYS FOUND IN DATA COLUMN")
print("="*80)

def collect_keys(obj, prefix=""):
    """Recursively collect all keys with their paths."""
    keys = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            full_key = f"{prefix}.{k}" if prefix else k
            keys.append(full_key)
            if isinstance(v, dict):
                keys.extend(collect_keys(v, full_key))
            elif isinstance(v, list):
                for item in v:
                    if isinstance(item, dict):
                        keys.extend(collect_keys(item, full_key + "[]"))
    return keys

key_counter = Counter()
for df_fields in ny['_date_fields']:
    if df_fields:
        ks = collect_keys(df_fields)
        key_counter.update(ks)

print(f"\nUnique key paths: {len(key_counter)}")
print("\nKey path frequencies (top 50):")
for key, count in key_counter.most_common(50):
    print(f"  {count:>6,}  ({count/len(ny):.1%})  {key}")

# ── Detailed look at top-level date keys ─────────────────────────────────────
print("\n" + "="*80)
print("TOP-LEVEL DATE KEY VALUES (sample unique values)")
print("="*80)

# Collect top-level keys and sample values
top_level_keys = set()
for df_fields in ny['_date_fields']:
    if isinstance(df_fields, dict):
        for k in df_fields:
            if not isinstance(df_fields[k], (dict, list)):
                top_level_keys.add(k)

for key in sorted(top_level_keys):
    vals = []
    for df_fields in ny['_date_fields']:
        if isinstance(df_fields, dict) and key in df_fields:
            v = df_fields[key]
            if not isinstance(v, (dict, list)):
                vals.append(v)
    unique_vals = list(set(vals))[:10]
    n_with = len(vals)
    print(f"\n  {key} (present in {n_with:,} records, {n_with/len(ny):.1%}):")
    for v in unique_vals:
        print(f"    {v}")

# ── Look at nested keys to find filing/issued/final dates ───────────────────
print("\n" + "="*80)
print("NESTED DATE STRUCTURES (first 10 non-empty examples)")
print("="*80)

count = 0
for idx, row in ny.iterrows():
    df_fields = row['_date_fields']
    if df_fields and any(isinstance(v, (dict, list)) for v in df_fields.values()):
        print(f"\n--- index={idx} ---")
        print(json.dumps(df_fields, indent=2, default=str)[:3000])
        count += 1
        if count >= 10:
            break

# ── Focus: Which DATA keys can map to FILE_DATE, PERMIT_DATE, FINAL_DATE ────
print("\n" + "="*80)
print("MAPPING ANALYSIS: DATA date keys → FILE_DATE / PERMIT_DATE / FINAL_DATE")
print("="*80)

# Let's look at records where FILE_DATE is present and see what DATA date keys correlate
def get_flat_date_values(date_fields):
    """Flatten all scalar date values from extracted date fields."""
    result = {}
    def _flatten(obj, prefix=""):
        if isinstance(obj, dict):
            for k, v in obj.items():
                full_key = f"{prefix}.{k}" if prefix else k
                if isinstance(v, (dict)):
                    _flatten(v, full_key)
                elif isinstance(v, list):
                    for i, item in enumerate(v):
                        _flatten(item, f"{full_key}[{i}]")
                else:
                    result[full_key] = v
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                _flatten(item, f"{prefix}[{i}]")
    _flatten(date_fields)
    return result

# For records with known FILE_DATE, find DATA keys with matching values
print("\n--- Checking which DATA date values match FILE_DATE ---")
match_counter_file = Counter()
checked = 0
for idx, row in ny.iterrows():
    if pd.notna(row.get('FILE_DATE')) and row['_date_fields']:
        file_date = pd.to_datetime(row['FILE_DATE'])
        flat = get_flat_date_values(row['_date_fields'])
        for k, v in flat.items():
            try:
                v_date = pd.to_datetime(v)
                if v_date == file_date:
                    match_counter_file[k] += 1
            except:
                pass
        checked += 1
if checked > 0:
    print(f"  Checked {checked:,} records with FILE_DATE present")
    for k, c in match_counter_file.most_common(20):
        print(f"    {c:>6,}  ({c/checked:.1%})  {k}")

print("\n--- Checking which DATA date values match PERMIT_DATE ---")
match_counter_permit = Counter()
checked = 0
for idx, row in ny.iterrows():
    if pd.notna(row.get('PERMIT_DATE')) and row['_date_fields']:
        permit_date = pd.to_datetime(row['PERMIT_DATE'])
        flat = get_flat_date_values(row['_date_fields'])
        for k, v in flat.items():
            try:
                v_date = pd.to_datetime(v)
                if v_date == permit_date:
                    match_counter_permit[k] += 1
            except:
                pass
        checked += 1
if checked > 0:
    print(f"  Checked {checked:,} records with PERMIT_DATE present")
    for k, c in match_counter_permit.most_common(20):
        print(f"    {c:>6,}  ({c/checked:.1%})  {k}")

print("\n--- Checking which DATA date values match FINAL_DATE ---")
match_counter_final = Counter()
checked = 0
for idx, row in ny.iterrows():
    if pd.notna(row.get('FINAL_DATE')) and row['_date_fields']:
        final_date = pd.to_datetime(row['FINAL_DATE'])
        flat = get_flat_date_values(row['_date_fields'])
        for k, v in flat.items():
            try:
                v_date = pd.to_datetime(v)
                if v_date == final_date:
                    match_counter_final[k] += 1
            except:
                pass
        checked += 1
if checked > 0:
    print(f"  Checked {checked:,} records with FINAL_DATE present")
    for k, c in match_counter_final.most_common(20):
        print(f"    {c:>6,}  ({c/checked:.1%})  {k}")

# ── Check fill-in potential: records where date is MISSING but DATA has candidates
print("\n" + "="*80)
print("FILL-IN POTENTIAL: Records missing dates but with DATA candidates")
print("="*80)

# Identify the most promising key paths from the matching analysis above
# We'll check the top candidates for each date field

# First, let's see what keys are available across ALL records (not just those with dates)
print("\n--- All flat date key paths across ALL NY records ---")
all_key_counter = Counter()
for df_fields in ny['_date_fields']:
    if df_fields:
        flat = get_flat_date_values(df_fields)
        all_key_counter.update(flat.keys())

print(f"Total unique flat key paths: {len(all_key_counter)}")
for k, c in all_key_counter.most_common(40):
    print(f"  {c:>6,}  ({c/len(ny):.1%})  {k}")

# For records missing FILE_DATE, how many have each candidate key?
print("\n--- For records MISSING FILE_DATE, available DATA date keys ---")
ny_missing_file = ny[ny['FILE_DATE'].isna()]
missing_file_keys = Counter()
for idx, row in ny_missing_file.iterrows():
    if row['_date_fields']:
        flat = get_flat_date_values(row['_date_fields'])
        missing_file_keys.update(flat.keys())
print(f"Records missing FILE_DATE: {len(ny_missing_file):,}")
for k, c in missing_file_keys.most_common(30):
    print(f"  {c:>6,}  ({c/len(ny_missing_file):.1%})  {k}")

print("\n--- For records MISSING PERMIT_DATE, available DATA date keys ---")
ny_missing_permit = ny[ny['PERMIT_DATE'].isna()]
missing_permit_keys = Counter()
for idx, row in ny_missing_permit.iterrows():
    if row['_date_fields']:
        flat = get_flat_date_values(row['_date_fields'])
        missing_permit_keys.update(flat.keys())
print(f"Records missing PERMIT_DATE: {len(ny_missing_permit):,}")
for k, c in missing_permit_keys.most_common(30):
    print(f"  {c:>6,}  ({c/len(ny_missing_permit):.1%})  {k}")

print("\n--- For records MISSING FINAL_DATE, available DATA date keys ---")
ny_missing_final = ny[ny['FINAL_DATE'].isna()]
missing_final_keys = Counter()
for idx, row in ny_missing_final.iterrows():
    if row['_date_fields']:
        flat = get_flat_date_values(row['_date_fields'])
        missing_final_keys.update(flat.keys())
print(f"Records missing FINAL_DATE: {len(ny_missing_final):,}")
for k, c in missing_final_keys.most_common(30):
    print(f"  {c:>6,}  ({c/len(ny_missing_final):.1%})  {k}")

print("\n\nDone.")

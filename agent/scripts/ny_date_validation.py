"""Validate date mappings and quantify fill-in potential for New York permits."""

import sys
import os
import json
import math
from collections import Counter

import pandas as pd
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from scripts.data_utils import extract_date_fields, _is_missing

from dotenv import load_dotenv, find_dotenv
load_dotenv(find_dotenv())

MY_DATA_PATH = os.getenv("MY_DATA_PATH")

filepath = os.path.join(MY_DATA_PATH, "processed_data", "permits_top50_sample.parquet")
df = pd.read_parquet(filepath)
ny = df[df['JURISDICTION'] == 'New York'].copy()

print(f"New York records: {len(ny):,}")

# ── Identify the 4 DATA sub-schemas in New York ─────────────────────────────
# The DATA column is "custom" schema but has multiple sub-formats within NY.
# Let's classify by top-level keys.

def get_top_keys(data):
    if _is_missing(data):
        return frozenset()
    if isinstance(data, str):
        data = json.loads(data)
    return frozenset(data.keys())

ny['_top_keys'] = ny['DATA'].apply(get_top_keys)
key_groups = ny['_top_keys'].value_counts()
print("\n" + "="*80)
print("DATA SUB-SCHEMA GROUPS (by top-level keys)")
print("="*80)
for keys, count in key_groups.items():
    print(f"\n  n={count:>4,}: {sorted(keys)}")

# ── Define candidate extraction logic for each date field ────────────────────

def safe_parse(data):
    if _is_missing(data):
        return None
    if isinstance(data, str):
        return json.loads(data)
    return data

def extract_file_date_candidates(data_dict):
    """Extract FILE_DATE candidates from NY DATA JSON."""
    candidates = {}
    
    # Schema 1: filings[] → pre__filing_date from first INITIAL filing
    if 'filings' in data_dict and isinstance(data_dict['filings'], list):
        for f in data_dict['filings']:
            if isinstance(f, dict) and f.get('pre__filing_date'):
                candidates['filings[FIRST].pre__filing_date'] = f['pre__filing_date']
                break
    
    # Schema 2: filing → filing_date
    if 'filing' in data_dict and isinstance(data_dict['filing'], dict):
        if data_dict['filing'].get('filing_date'):
            candidates['filing.filing_date'] = data_dict['filing']['filing_date']
    
    # Schema 3: top-level filing_date
    if 'filing_date' in data_dict and not isinstance(data_dict['filing_date'], (dict, list)):
        candidates['filing_date'] = data_dict['filing_date']
    
    # Schema 4: issuances[] → first INITIAL filing_date
    if 'issuances' in data_dict and isinstance(data_dict['issuances'], list):
        initials = [i for i in data_dict['issuances'] if isinstance(i, dict) and i.get('filing_status') == 'INITIAL']
        if initials:
            # Sort by filing_date to get earliest
            try:
                initials_sorted = sorted(initials, key=lambda x: pd.to_datetime(x.get('filing_date', '9999')))
                candidates['issuances[INITIAL_earliest].filing_date'] = initials_sorted[0].get('filing_date')
            except:
                candidates['issuances[INITIAL_first].filing_date'] = initials[0].get('filing_date')
    
    return candidates


def extract_permit_date_candidates(data_dict):
    """Extract PERMIT_DATE candidates from NY DATA JSON."""
    candidates = {}
    
    # Schema 1: filings[] → fully_permitted from first filing
    if 'filings' in data_dict and isinstance(data_dict['filings'], list):
        for f in data_dict['filings']:
            if isinstance(f, dict) and f.get('fully_permitted'):
                candidates['filings[FIRST].fully_permitted'] = f['fully_permitted']
                break
    
    # Schema 2: filing → permit_issue_date
    if 'filing' in data_dict and isinstance(data_dict['filing'], dict):
        if data_dict['filing'].get('permit_issue_date'):
            candidates['filing.permit_issue_date'] = data_dict['filing']['permit_issue_date']
        if data_dict['filing'].get('first_permit_date'):
            candidates['filing.first_permit_date'] = data_dict['filing']['first_permit_date']
    
    # Schema 3: top-level permit_issued_date
    if 'permit_issued_date' in data_dict:
        candidates['permit_issued_date'] = data_dict['permit_issued_date']
    
    # Schema 4: issuances[] → first INITIAL issuance_date
    if 'issuances' in data_dict and isinstance(data_dict['issuances'], list):
        initials = [i for i in data_dict['issuances'] if isinstance(i, dict) and i.get('filing_status') == 'INITIAL']
        if initials:
            try:
                initials_sorted = sorted(initials, key=lambda x: pd.to_datetime(x.get('issuance_date', '9999')))
                candidates['issuances[INITIAL_earliest].issuance_date'] = initials_sorted[0].get('issuance_date')
            except:
                if initials[0].get('issuance_date'):
                    candidates['issuances[INITIAL_first].issuance_date'] = initials[0].get('issuance_date')
    
    # Schema 5: permits[] → first approved_date or issued_date
    if 'permits' in data_dict and isinstance(data_dict['permits'], list):
        for p in data_dict['permits']:
            if isinstance(p, dict):
                if p.get('issued_date'):
                    candidates['permits[FIRST].issued_date'] = p['issued_date']
                    break
                if p.get('approved_date'):
                    candidates['permits[FIRST].approved_date'] = p['approved_date']
                    break
    
    return candidates


def extract_final_date_candidates(data_dict):
    """Extract FINAL_DATE candidates from NY DATA JSON."""
    candidates = {}
    
    # Schema 1: filings[] → signoff_date from first filing with it
    if 'filings' in data_dict and isinstance(data_dict['filings'], list):
        for f in data_dict['filings']:
            if isinstance(f, dict) and f.get('signoff_date'):
                candidates['filings[FIRST].signoff_date'] = f['signoff_date']
                break
    
    # Schema 2: top-level completion_date
    if 'completion_date' in data_dict:
        candidates['completion_date'] = data_dict['completion_date']
    
    # Schema 3: filing → current_status_date (only if status is complete/signed-off)
    if 'filing' in data_dict and isinstance(data_dict['filing'], dict):
        filing = data_dict['filing']
        status = filing.get('filing_status', '')
        if status and 'complete' in str(status).lower():
            if filing.get('current_status_date'):
                candidates['filing.current_status_date (Complete)'] = filing['current_status_date']
    
    return candidates


# ── Validate extraction against known values ─────────────────────────────────
print("\n" + "="*80)
print("VALIDATION: Do extracted candidates match known date values?")
print("="*80)

def validate_mapping(ny, date_col, extract_fn, label):
    has_date = ny[ny[date_col].notna()].copy()
    n_total = len(has_date)
    
    match_counts = Counter()
    exact_matches = 0
    any_match = 0
    
    for idx, row in has_date.iterrows():
        data_dict = safe_parse(row['DATA'])
        if data_dict is None:
            continue
        known_date = pd.to_datetime(row[date_col])
        candidates = extract_fn(data_dict)
        
        found_match = False
        for key, val in candidates.items():
            try:
                cand_date = pd.to_datetime(val)
                if cand_date == known_date:
                    match_counts[key] += 1
                    found_match = True
            except:
                pass
        if found_match:
            any_match += 1
    
    print(f"\n  {label}")
    print(f"  Records with {date_col}: {n_total:,}")
    print(f"  Any candidate matches: {any_match:,} ({any_match/n_total:.1%})")
    print(f"  Match breakdown:")
    for key, count in match_counts.most_common():
        print(f"    {count:>6,} ({count/n_total:.1%})  {key}")
    
    return match_counts

file_matches = validate_mapping(ny, 'FILE_DATE', extract_file_date_candidates, "FILE_DATE validation")
permit_matches = validate_mapping(ny, 'PERMIT_DATE', extract_permit_date_candidates, "PERMIT_DATE validation")

# FINAL_DATE is always missing, so can't validate directly

# ── Quantify fill-in potential ───────────────────────────────────────────────
print("\n" + "="*80)
print("FILL-IN POTENTIAL: How many missing dates can be recovered?")
print("="*80)

def count_fillable(ny, date_col, extract_fn, label):
    missing = ny[ny[date_col].isna()].copy()
    n_missing = len(missing)
    
    fillable_counts = Counter()
    any_fillable = 0
    
    for idx, row in missing.iterrows():
        data_dict = safe_parse(row['DATA'])
        if data_dict is None:
            continue
        candidates = extract_fn(data_dict)
        
        valid_candidates = {}
        for key, val in candidates.items():
            try:
                pd.to_datetime(val)
                valid_candidates[key] = val
                fillable_counts[key] += 1
            except:
                pass
        if valid_candidates:
            any_fillable += 1
    
    print(f"\n  {label}")
    print(f"  Records missing {date_col}: {n_missing:,}")
    print(f"  Records fillable from DATA: {any_fillable:,} ({any_fillable/n_missing:.1%})")
    print(f"  Candidate breakdown:")
    for key, count in fillable_counts.most_common():
        print(f"    {count:>6,} ({count/n_missing:.1%})  {key}")

count_fillable(ny, 'FILE_DATE', extract_file_date_candidates, "FILE_DATE fill-in")
count_fillable(ny, 'PERMIT_DATE', extract_permit_date_candidates, "PERMIT_DATE fill-in")
count_fillable(ny, 'FINAL_DATE', extract_final_date_candidates, "FINAL_DATE fill-in")

# ── Check signoff_date vs STATUS ─────────────────────────────────────────────
print("\n" + "="*80)
print("SIGNOFF_DATE ANALYSIS (candidate for FINAL_DATE)")
print("="*80)

signoff_by_status = Counter()
has_signoff = 0
for idx, row in ny.iterrows():
    data_dict = safe_parse(row['DATA'])
    if data_dict is None:
        continue
    candidates = extract_final_date_candidates(data_dict)
    if candidates:
        has_signoff += 1
        status = row.get('STATUS_NORMALIZED', 'Unknown')
        signoff_by_status[status] += 1

print(f"\nRecords with FINAL_DATE candidates: {has_signoff:,} ({has_signoff/len(ny):.1%})")
print("\nBy STATUS_NORMALIZED:")
for status, count in signoff_by_status.most_common():
    n_status = len(ny[ny['STATUS_NORMALIZED'] == status]) if pd.notna(status) else ny['STATUS_NORMALIZED'].isna().sum()
    print(f"  {str(status):15s}: {count:>4,} / {n_status:>4,} ({count/n_status:.1%})")

# ── Cross-check: For Final status with signoff_date, what does job_status_descrp say? ──
print("\n" + "="*80)
print("JOB_STATUS_DESCRP for records with signoff_date")
print("="*80)
status_descrp_counter = Counter()
for idx, row in ny.iterrows():
    data_dict = safe_parse(row['DATA'])
    if data_dict is None:
        continue
    if 'filings' in data_dict and isinstance(data_dict['filings'], list):
        for f in data_dict['filings']:
            if isinstance(f, dict) and f.get('signoff_date'):
                descrp = f.get('job_status_descrp', 'N/A')
                status_descrp_counter[descrp] += 1
                break

print("job_status_descrp values for records with signoff_date:")
for descrp, count in status_descrp_counter.most_common():
    print(f"  {count:>4,}  {descrp}")

# ── Summary table ────────────────────────────────────────────────────────────
print("\n" + "="*80)
print("SUMMARY")
print("="*80)
for col in ['FILE_DATE', 'PERMIT_DATE', 'FINAL_DATE']:
    n_present = ny[col].notna().sum()
    n_missing = ny[col].isna().sum()
    print(f"\n{col}:")
    print(f"  Present: {n_present:>5,} ({n_present/len(ny):.1%})")
    print(f"  Missing: {n_missing:>5,} ({n_missing/len(ny):.1%})")

print("\nDone.")

"""Shared utilities for working with the permits dataset."""

import json
import math
import re
import numpy as np
import time
from typing import Optional, Union

import pandas as pd

import os
from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv())

ROOT_PATH = os.getenv("ROOT_PATH")
MY_DATA_PATH = os.getenv("MY_DATA_PATH")
RAW_DATA_PATH = os.getenv("RAW_DATA_PATH")
DEWEY_PATH = os.path.join(RAW_DATA_PATH, "dewey-downloads", "building-permits-united-states")

DEWEY_SUMMARY_FILEPATH = os.path.join(MY_DATA_PATH, "dewey_summary.parquet")

# -- Read data for one JURISDICTION/STATE -------------------------------------

def get_data_for_jurisdiction(jurisdiction, state, columns=None, n_records=None, rng=np.random.RandomState(42), verbose=True):
    summary_df = pd.read_parquet(DEWEY_SUMMARY_FILEPATH)
    files = summary_df.loc[(summary_df['JURISDICTION'] == jurisdiction) & (summary_df['STATE'] == state), 'FILENAME'].tolist()
    if len(files) == 0:
        return pd.DataFrame()
    total_records = summary_df.loc[(summary_df['JURISDICTION'] == jurisdiction) & (summary_df['STATE'] == state), 'COUNT'].sum()

    # Control sampling
    if n_records is None:
        frac = 1.0
    else:
        frac = min(1.0, n_records / total_records)

    t0 = time.time()
    dfs = []
    for i, f in enumerate(files):
        dt = time.time() - t0
        if verbose:
            print(f"\rRetrieving data for {jurisdiction} {state} ... {i + 1}/{len(files)} files ... elapsed time {dt:.2f} seconds              ", end="", flush=True)
        temp_df = pd.read_parquet(os.path.join(DEWEY_PATH, f), columns=columns)
        temp_df = temp_df.loc[(temp_df['JURISDICTION'] == jurisdiction) & (temp_df['STATE'] == state)]
        temp_df = temp_df.sample(frac=frac, random_state=rng)
        dfs.append(temp_df)
    df = pd.concat(dfs).reset_index(drop=True)
    if verbose:
        print("")
    return df

# -- Read data for multiple JURISDICTION/STATE pairs -------------------------------------

def get_data_for_jurisdictions(jurisdictions, states, columns=None, n_records=None, rng=np.random.RandomState(42), verbose=True):
    dfs = []
    t0 = time.time()
    i = 0
    for jurisdiction, state in zip(jurisdictions, states):
        df = get_data_for_jurisdiction(jurisdiction, state, columns=columns, n_records=n_records, rng=rng, verbose=verbose)
        dfs.append(df)
        if verbose:
            dt = time.time() - t0
            print(f"{i+1}/{len(jurisdictions)} retrieved ... elapsed time: {dt:.2f} seconds")
        i+=1
    if verbose:
        print("")
    return pd.concat(dfs).reset_index(drop=True)

# -- Data quality assessment ---------------------------------------------------

STATUSES = ['Active', 'Final', 'Inactive', 'In Review']
DATE_CONCEPTS = ['FILE_DATE', 'PERMIT_DATE', 'FINAL_DATE', 'PERMIT_OR_FILE_DATE']
QUALITY_CONCEPTS = {
    "Require FILE_DATE for all permits, PERMIT_DATE for Active and Final, FINAL_DATE for Final": {
        "FILE_DATE": ["Active", "Final", "Inactive", "In Review"],
        "PERMIT_DATE": ["Active", "Final"],
        "FINAL_DATE": ["Final"]
    },
    "Require PERMIT_OR_FILE_DATE for all permits, FINAL_DATE for Final": {
        "PERMIT_OR_FILE_DATE": ["Active", "Final", "Inactive", "In Review"],
        "FINAL_DATE": ["Final"]
    },
    "Require PERMIT_OR_FILE_DATE for all permits": {
        "PERMIT_OR_FILE_DATE": ["Active", "Final", "Inactive", "In Review"]
    }
}

def assess_data_quality(df):
    df['PERMIT_OR_FILE_DATE'] = df['PERMIT_DATE'].fillna(df['FILE_DATE'])
    result = {}
    n_total = len(df)
    n_status_ok = (df['STATUS_NORMALIZED'].notna()).sum()
    pct_status_ok = n_status_ok / (n_total + 1e-6)
    result['n_total'] = n_total
    result['n_status_ok'] = n_status_ok
    result['pct_status_ok'] = pct_status_ok
    for status in STATUSES:
        result[f'status__{status}'] = {}
        n_status = (df['STATUS_NORMALIZED'] == status).sum()
        pct_status = n_status / (n_status_ok + 1e-6)
        result[f'status__{status}']['n_status'] = n_status
        result[f'status__{status}']['pct_status'] = pct_status
        for dc in DATE_CONCEPTS:
            result[f'status__{status}'][f'{dc}'] = {}
            n_ok = ((df['STATUS_NORMALIZED'] == status) & (df[dc].notna())).sum()
            pct_ok = n_ok / (n_status + 1e-6)
            result[f'status__{status}'][f'{dc}']['n_ok'] = n_ok
            result[f'status__{status}'][f'{dc}']['pct_ok'] = pct_ok
    return result

def data_quality_report(df, threshold=0.85):

    jurs_df = df[['JURISDICTION', 'STATE']].drop_duplicates().reset_index(drop=True)
    jurisdictions = jurs_df['JURISDICTION'].tolist()
    states = jurs_df['STATE'].tolist()

    md = ""
    results = {}
    for jurisdiction, state in zip(jurisdictions, states):

        # Header and get data
        md += f"## {jurisdiction} {state} \n\n"
        sub_df = df.loc[(df['JURISDICTION'] == jurisdiction) & (df['STATE'] == state)]
        if len(sub_df) == 0:
            md += f"**No permits data found for {jurisdiction} {state}**.\n\n"
            continue

        result = assess_data_quality(sub_df)
        results[(jurisdiction, state)] = result

        # Total records
        md += f"- Total records: {result['n_total']:,}\n"

        # Schemas
        if 'SCHEMA' in sub_df.columns:
            schemas = sub_df['SCHEMA'].unique().tolist()
            md += "- Schemas: \n"
            for schema in schemas:
                n_schema = (sub_df['SCHEMA'] == schema).sum()
                pct_schema = n_schema / (len(sub_df) + 1e-6)
                md += f"    - {schema}: {n_schema:,} ({pct_schema:.1%})\n"

        # STATUS_NORMALIZED
        okfail = "*OK*" if result['pct_status_ok'] >= threshold else "**FAIL**"
        md += f"- STATUS_NORMALIZED not missing: {result['n_status_ok']:,} ({result['pct_status_ok']:.1%})  {okfail}\n"

        # Date concepts by status
        for status in STATUSES:
            md += f"    - {status}: {result[f'status__{status}']['n_status']:,} ({result[f'status__{status}']['pct_status']:.1%})\n"
            for dc in DATE_CONCEPTS:
                okfail = "*OK*" if result[f'status__{status}'][f'{dc}']['pct_ok'] >= threshold else "**FAIL**"
                md += f"        - {dc}: {result[f'status__{status}'][f'{dc}']['n_ok']:,} ({result[f'status__{status}'][f'{dc}']['pct_ok']:.1%})  {okfail}\n"
        
        md += "\n"
    
    # By data requirements
    md += "## By data requirements\n\n"
    for concept, reqs in QUALITY_CONCEPTS.items():
        md += f"- {concept}: "
        n_usable = 0
        for jurisdiction, state in results.keys():
            result = results[(jurisdiction, state)]
            usable = True
            for dc, statuses in reqs.items():
                for status in statuses:
                    if result[f'status__{status}'][f'{dc}']['pct_ok'] < threshold:
                        usable = False
                        break
            if usable:
                n_usable += 1
        md += f"{n_usable:,} / {len(jurisdictions)} meet criteria\n"

    md += "\n"
    return md


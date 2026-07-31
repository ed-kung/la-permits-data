"""Shared utilities for working with the permits dataset."""

import sys
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

sys.path.append(os.path.join(ROOT_PATH, "agent/scripts"))
from data_repair import data_repair, _slugify


# -- Deduplicate data -------------------------------------
def _deduplicate(df):
    n_original = len(df)

    # First pass: drop exact duplicates
    df = df.drop_duplicates(keep='first')

    # Second pass: keep most complete row per PERMIT_NUMBER
    has_key = df['PERMIT_NUMBER'].notna()
    df_keyed = df.loc[has_key].copy()
    df_nokey = df.loc[~has_key].copy()

    df_keyed['_non_null'] = df_keyed.notna().sum(axis=1)

    df_keyed = (
        df_keyed
        .sort_values(by='_non_null', ascending=False, kind='stable')
        .drop_duplicates(subset='PERMIT_NUMBER', keep='first')
        .drop(columns='_non_null')
    )

    df = pd.concat([df_keyed, df_nokey], ignore_index=True, sort=False)
    n_new = len(df)

    print(f"{n_original - n_new:,} duplicates dropped from {n_original:,} original records")

    return df



# -- Read data for one JURISDICTION/STATE -------------------------------------


def get_data_for_jurisdiction(
    jurisdiction, 
    state, 
    columns=None, 
    n_records=None, 
    repair=False,
    deduplicate=False,
    rng=np.random.RandomState(42), 
    verbose=True,
    save_to=None,
    replace=False,
    remove_raw_data_col=False
):
    if save_to is not None:
        if not replace and os.path.exists(save_to):
            df = pd.read_parquet(save_to)
            if (len(df)>0) and (set(columns).issubset(set(df.columns.tolist()))):
                return df
            df = None
        else:
            os.makedirs(os.path.dirname(save_to), exist_ok=True)

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
        temp_df = temp_df.loc[(temp_df['JURISDICTION'] == jurisdiction) & (temp_df['STATE'] == state)].reset_index(drop=True)
        temp_df = temp_df.sample(frac=frac, random_state=rng)
        if repair:
            temp_df = data_repair(temp_df, jurisdiction=jurisdiction, state=state)
            temp_df['FILE_DATE'] = pd.to_datetime(temp_df['FILE_DATE'], errors='coerce', utc=True)
            temp_df['PERMIT_DATE'] = pd.to_datetime(temp_df['PERMIT_DATE'], errors='coerce', utc=True)
            temp_df['FINAL_DATE'] = pd.to_datetime(temp_df['FINAL_DATE'], errors='coerce', utc=True)
        if remove_raw_data_col:
            temp_df = temp_df.drop(columns=['DATA'])
        dfs.append(temp_df)

    if verbose:
        print("")

    df = pd.concat(dfs).reset_index(drop=True)
    if deduplicate:
        df = _deduplicate(df)
    if save_to is not None:
        df.to_parquet(save_to)
        if verbose:
            print(f"Data saved to {save_to}")

    return df


# %%
# Compiles a summary of each of the raw Dewey permits data files
# with counts from each jurisdiction

import sys
import os
import time
from dotenv import load_dotenv, find_dotenv
import pandas as pd

load_dotenv(find_dotenv())

ROOT_PATH = os.getenv("ROOT_PATH")
MY_DATA_PATH = os.getenv("MY_DATA_PATH")
RAW_DATA_PATH = os.getenv("RAW_DATA_PATH")

# %%
# Create a list of all .parquet files in RAW_DATA_PATH

parquet_files = [f for f in os.listdir(RAW_DATA_PATH) if f.endswith('.parquet')]

# %%
# For each file, count the number of rows by STATE and JURISDICTION

summ_dfs = []
t0 = time.time()
for i, f in enumerate(parquet_files):
    dt = time.time() - t0
    print(f"\rProcessing {f}: ({i+1}/{len(parquet_files)}) ... elapsed time = {dt/60:,.2f} minutes", end="", flush=True)
    df = pd.read_parquet(os.path.join(RAW_DATA_PATH, f))
    dfg = df.groupby(['STATE', 'JURISDICTION']).agg(COUNT = ('JURISDICTION', 'count')).reset_index()
    dfg['FILENAME'] = f
    summ_dfs.append(dfg)

summ_df = pd.concat(summ_dfs)
summ_df = summ_df.sort_values(by=['STATE', 'JURISDICTION', 'FILENAME'], ascending=True).reset_index(drop=True)



# %%
# Output summary file

summ_df.to_csv(os.path.join(MY_DATA_PATH, "dewey_summary.csv"), index=False)
summ_df.to_parquet(os.path.join(MY_DATA_PATH, "dewey_summary.parquet"), index=False)




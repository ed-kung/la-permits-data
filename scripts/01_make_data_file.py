# %%
# Extract raw Dewey permits data for given jurisdictions

import sys
import os
from dotenv import load_dotenv, find_dotenv
import pandas as pd
import time

load_dotenv(find_dotenv())

ROOT_PATH = os.getenv("ROOT_PATH")
MY_DATA_PATH = os.getenv("MY_DATA_PATH")
DEWEY_PATH = os.getenv("DEWEY_PATH")

SUMMARY_FILEPATH = os.path.join(MY_DATA_PATH, "dewey_summary.parquet")
JURISDICTIONS_FILEPATH = os.path.join(MY_DATA_PATH, "raw_data", "dewey_la_county_jurisdictions.csv")
OUTPUT_FILEPATH = os.path.join(MY_DATA_PATH, "processed_data", "dewey_ca_la_county_permits.parquet")


# %%
# Get the jurisdictions and filenames to include

jurs_df = pd.read_csv(JURISDICTIONS_FILEPATH)
JURISDICTIONS = jurs_df['JURISDICTION'].unique().tolist()

summ_df = pd.read_parquet(SUMMARY_FILEPATH)
summ_df = summ_df.loc[summ_df['JURISDICTION'].isin(JURISDICTIONS)].reset_index(drop=True)

FILENAMES = summ_df['FILENAME'].unique().tolist()


# %%
# Compile the data

df_out = []
t0 = time.time()
for i, f in enumerate(FILENAMES):
    dt = time.time() - t0
    print(f"\rProcessing {f}: ({i+1}/{len(FILENAMES)}) ... elapsed time = {dt/60:,.2f} minutes", end="", flush=True)
    df = pd.read_parquet(os.path.join(DEWEY_PATH, f))
    df = df.loc[df['STATE'] == 'CA']
    df = df.loc[df['JURISDICTION'].isin(JURISDICTIONS)]
    df['FILE_DATE'] = pd.to_datetime(df['FILE_DATE'], errors='coerce')
    df['PERMIT_DATE'] = pd.to_datetime(df['PERMIT_DATE'], errors='coerce')
    df['FINAL_DATE'] = pd.to_datetime(df['FINAL_DATE'], errors='coerce')
    df_out.append(df)
print("")
df_out = pd.concat(df_out).reset_index(drop=True)

# %%
# Save the data

df_out.to_parquet(OUTPUT_FILEPATH)



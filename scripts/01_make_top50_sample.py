# %%
# Export random sample of top 50 US cities for data exploration

import sys
import os
from dotenv import load_dotenv, find_dotenv
import matplotlib.pyplot as plt
import time
import pandas as pd
import numpy as np

rng = np.random.RandomState(42)

load_dotenv(find_dotenv())

TARGET_RECORDS_PER_CITY = 2000

ROOT_PATH = os.getenv("ROOT_PATH")
MY_DATA_PATH = os.getenv("MY_DATA_PATH")
RAW_DATA_PATH = os.getenv("RAW_DATA_PATH")
DEWEY_PATH = os.path.join(RAW_DATA_PATH, "dewey-downloads", "building-permits-united-states")

SUMMARY_FILENAME = "dewey_summary"
SUMMARY_FILEPATH = os.path.join(MY_DATA_PATH, f"{SUMMARY_FILENAME}.parquet")
TOP_50_FILEPATH = os.path.join(MY_DATA_PATH, "raw_data", "top_50_us_cities.csv")

COLUMNS = [
    'JURISDICTION', 'STATE', 'FILE_DATE', 'PERMIT_DATE', 'FINAL_DATE', 'STATUS_NORMALIZED', 'STATUS_ORIGINAL', 'RECORD_TYPE_ORIGINAL', 'RECORD_SUBTYPE_ORIGINAL', 'APN', 'STREET', 'ZIPCODE', 'DATA', 'RESIDENTIAL'
]  # Columns to load from data file

OUTPUT_FILEPATH = os.path.join(MY_DATA_PATH, "processed_data", "permits_top50_sample.parquet")



# %%
# Load the data

summ_df = pd.read_parquet(SUMMARY_FILEPATH)
city_df = pd.read_csv(TOP_50_FILEPATH)
city_df = city_df.rename(columns={'CITY': 'JURISDICTION'})


# %%
# Notes:
# - In Dewey, the closest match for Las Vegas is "North Las Vegas"
# - In Dewey, the closest match for Louisville is "Louisville-Jefferson County"
# - In Dewey, the closest match for Colorado Springs is "El Paso County"
# - In Dewey, there does not appear to be a match for Wichita, KS

JURISDICTION_MAP = {}
for idx, row in city_df.iterrows():
    JURISDICTION_MAP[row['JURISDICTION']] = row['JURISDICTION']

JURISDICTION_MAP['Las Vegas'] = 'North Las Vegas'
JURISDICTION_MAP['Louisville'] = 'Louisville-Jefferson County'
JURISDICTION_MAP['Colorado Springs'] = 'El Paso County'

# %%
# Iterate over cities

dfs = []

t0 = time.time()
for idx, row in city_df.iterrows():
    j = row['JURISDICTION']
    jurisdiction = JURISDICTION_MAP[j]
    state = row['STATE']

    files = summ_df.loc[(summ_df['JURISDICTION'] == jurisdiction) & (summ_df['STATE'] == state), 'FILENAME'].tolist()

    n_records = summ_df.loc[(summ_df['JURISDICTION'] == jurisdiction) & (summ_df['STATE'] == state), 'COUNT'].sum()
    if n_records == 0:
        continue
    
    frac = TARGET_RECORDS_PER_CITY / n_records

    mydfs = []
    for jdx, f in enumerate(files):
        dt = time.time() - t0
        print(f"\rProcessing {j} {state} ({idx + 1}/{len(city_df)}) ... {jdx + 1}/{len(files)} files ... elapsed time {dt:.2f} seconds              ", end="", flush=True)

        temp_df = pd.read_parquet(os.path.join(DEWEY_PATH, f), columns=COLUMNS)
        temp_df = temp_df.loc[(temp_df['JURISDICTION'] == jurisdiction) & (temp_df['STATE'] == state)]
        temp_df = temp_df.sample(frac=frac, random_state=rng)

        mydfs.append(temp_df)
    mydf = pd.concat(mydfs)

    if len(mydf) == 0:
        continue
    
    mydf = mydf.sample(n=min(2000, len(mydf)), random_state=rng).reset_index(drop=True)
    dfs.append(mydf)

df = pd.concat(dfs)
print("\nDone!\n")
print(df["JURISDICTION"].value_counts())

# %%
# Clean date fields
df['FILE_DATE'] = pd.to_datetime(df['FILE_DATE'], errors='coerce')
df['PERMIT_DATE'] = pd.to_datetime(df['PERMIT_DATE'], errors='coerce')
df['FINAL_DATE'] = pd.to_datetime(df['FINAL_DATE'], errors='coerce')
df['PERMIT_OR_FILE_DATE'] = df['PERMIT_DATE'].fillna(df['FILE_DATE'])

# %%
# Save data
df.to_parquet(OUTPUT_FILEPATH)




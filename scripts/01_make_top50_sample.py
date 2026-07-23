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

sys.path.append(os.path.join(ROOT_PATH, "scripts"))
import data_utils as du

SUMMARY_FILENAME = "dewey_summary"
SUMMARY_FILEPATH = os.path.join(MY_DATA_PATH, f"{SUMMARY_FILENAME}.parquet")
TOP_50_FILEPATH = os.path.join(MY_DATA_PATH, "raw_data", "top_50_us_cities.csv")

COLUMNS = [
    'JURISDICTION', 'STATE', 'FILE_DATE', 'PERMIT_DATE', 'FINAL_DATE', 'STATUS_NORMALIZED', 'STATUS_ORIGINAL', 'RECORD_TYPE_ORIGINAL', 'RECORD_SUBTYPE_ORIGINAL', 'APN', 'STREET', 'ZIPCODE', 'DATA', 'RESIDENTIAL'
]  # Columns to load from data file

OUTPUT_FILEPATH = os.path.join(MY_DATA_PATH, "processed_data", "permits_top50_sample.parquet")



# %%
# Load the data

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
# Retrieve cities data

jurisdictions = [JURISDICTION_MAP[j] for j in city_df['JURISDICTION'].tolist()]
states = city_df['STATE'].tolist()

df = du.get_data_for_jurisdictions(jurisdictions, states, columns=COLUMNS, n_records=TARGET_RECORDS_PER_CITY, rng=rng)

print("\nDone!\n")
print(df["JURISDICTION"].value_counts())

# %%
# Save data
df.to_parquet(OUTPUT_FILEPATH)




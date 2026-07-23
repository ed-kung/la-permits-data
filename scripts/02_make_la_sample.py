# %%
# Export random sample of Los Angeles county permits for data exploration

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
LA_FILEPATH = os.path.join(MY_DATA_PATH, "raw_data", "dewey_la_county_jurisdictions.csv")

COLUMNS = [
    'JURISDICTION', 'STATE', 'FILE_DATE', 'PERMIT_DATE', 'FINAL_DATE', 'STATUS_NORMALIZED', 'STATUS_ORIGINAL', 'RECORD_TYPE_ORIGINAL', 'RECORD_SUBTYPE_ORIGINAL', 'APN', 'STREET', 'ZIPCODE', 'DATA', 'RESIDENTIAL'
]  # Columns to load from data file

OUTPUT_FILEPATH = os.path.join(MY_DATA_PATH, "processed_data", "permits_la_sample.parquet")



# %%
# Load the data

city_df = pd.read_csv(LA_FILEPATH)


# %%
# Retrieve cities data

jurisdictions = city_df['JURISDICTION'].tolist()
states = city_df['STATE'].tolist()

df = du.get_data_for_jurisdictions(jurisdictions, states, columns=COLUMNS, n_records=TARGET_RECORDS_PER_CITY, rng=rng)

print("\nDone!\n")
print(df["JURISDICTION"].value_counts())

# %%
# Save data
df.to_parquet(OUTPUT_FILEPATH)



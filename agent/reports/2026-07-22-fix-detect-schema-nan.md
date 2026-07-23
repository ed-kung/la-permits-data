# Fix detect_schema NaN handling

**Summary:** `notebooks/playground.ipynb` failed on `df['DATA'].apply(detect_schema)` because 309 rows have missing `DATA` (NaN floats). `detect_schema` (and `extract_date_fields`) in `scripts/data_utils.py` now return `None` / `{}` for missing values instead of raising.

## Cause

- Sample parquet: 97,936 rows; `DATA` is mostly JSON strings, with **309 NaNs**.
- `detect_schema` only accepted `dict` or `str`, so pandas `apply` hit `ValueError: Expected a JSON object (dict), got float`.

## Fix

- Added `_is_missing()` for `None` / NaN.
- `detect_schema`: returns `None` when data is missing.
- `extract_date_fields`: returns `{}` when data is missing (same robustness for later notebook cells).

## Artifacts

- Modified: `scripts/data_utils.py`

# FL sample: all jurisdictions have data repair scripts

**Summary:** Loaded `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` (423,887 rows, 217 unique `(JURISDICTION, STATE)` pairs). Walking pairs in first-appearance order and matching `agent/scripts/{state}/data_repair_{state}_{city}.py` (city slug = lowercased jurisdiction with non-alphanumerics → `_`), **every pair already has a non-stub repair script** containing `data_repair`. No new repair script was written this run.

## Method

1. Read distinct `(JURISDICTION, STATE)` in sample row order.
2. For each pair, check for `agent/scripts/fl/data_repair_fl_{slug}.py`.
3. Confirm each script defines `def data_repair` and is not trivially short.

## Results

| Check | Result |
| --- | --- |
| Unique pairs in sample | 217 |
| Matching FL repair scripts | 217 |
| Pairs missing a script | **0** |
| Scripts missing `data_repair` / stub-sized | **0** |
| Jurisdictions in data but not scripts | none |
| Scripts in `agent/scripts/fl/` not in sample | none |

Last pairs in sample order (all present): Eatonville, Orchid, Gadsden County. Recent reports include `2026-08-13-orchid-data-repair.md` and `2026-08-12-gadsden-county-data-repair.md`.

## Artifacts

- No new `agent/scripts/fl/data_repair_*.py` created.
- This report only.

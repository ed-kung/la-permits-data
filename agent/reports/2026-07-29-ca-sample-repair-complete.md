# CA sample data-repair coverage complete

**Summary:** Walked all `(JURISDICTION, STATE)` pairs in `MY_DATA_PATH/processed_data/permits_ca_sample.parquet` in first-appearance order and matched each to `agent/scripts/{state}/data_repair_{state}_{city}.py` (accent-normalized city slug, e.g. La Cañada Flintridge → `la_canada_flintridge`). All **250** pairs already have a non-stub `data_repair` script. There is no remaining CA sample jurisdiction to assess or repair under this workflow. The most recent addition is Williams (`agent/scripts/ca/data_repair_ca_williams.py`; report `2026-07-29-williams-data-repair.md`).

## Selection check

| Metric | Value |
| --- | ---: |
| Unique `(JURISDICTION, STATE)` in sample | 250 |
| Matching `agent/scripts/ca/data_repair_ca_*.py` files | 250 |
| Sample pairs missing a script | 0 |
| Scripts with no matching sample pair | 0 |
| Scripts missing `def data_repair` / stub-sized | 0 |

Slug rule used: NFKD accent strip, lowercase, non-alphanumeric → `_`.

## Implication

No new repair script or field assessment was produced in this run. Further work would require a different source file (e.g. `permits_top50_sample.parquet` for non-CA cities) or a re-audit of existing CA repairs.

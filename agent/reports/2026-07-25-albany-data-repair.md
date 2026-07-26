# Albany data repair (pass-through)

**Summary:** Implemented `agent/scripts/ca/data_repair_ca_albany.py` as a pass-through `data_repair` so Albany follows the same call pattern as other jurisdictions. No field values are repaired: Albany’s sample has null `DATA` on every row, so agency-JSON repair is impossible. The function returns a copy of the input with null-valued `STATUS_NORMALIZED_FLAG`, `FILE_DATE_FLAG`, `PERMIT_DATE_FLAG`, `FINAL_DATE_FLAG`, and `INFERRED_SCHEMA`.

## Why pass-through

Prior assessment (`2026-07-25-aliso-viejo-data-repair.md`) found all 2,000 Albany rows in `permits_ca_sample.parquet` have null `DATA`. Without raw agency JSON, `STATUS_NORMALIZED` / date fields cannot be validated or filled from source.

## Behavior

| Column | Behavior |
| --- | --- |
| `STATUS_NORMALIZED`, `FILE_DATE`, `PERMIT_DATE`, `FINAL_DATE` | Unchanged |
| `*_FLAG` columns | Created, all null |
| `INFERRED_SCHEMA` | Created, all null |

## Verification

CLI run against `permits_ca_sample.parquet` (`JURISDICTION == "Albany"`, `STATE == "CA"`):

- Records: 2,000; `DATA` non-null: 0
- All four flag columns null on every row; no FILLED/FIXED
- Core fields unchanged before vs after

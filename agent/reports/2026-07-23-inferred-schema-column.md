# Add INFERRED_SCHEMA to city data repair functions

**Summary:** Updated all six `{city}_data_repair.py` scripts under `agent/scripts/` so `data_repair()` also returns an `INFERRED_SCHEMA` string column identifying which raw `DATA` JSON schema was detected for each record. Multi-schema cities reuse their existing `_classify_schema` labels; single-schema cities gained a matching classifier.

## Changes

Each `data_repair()` now initializes `INFERRED_SCHEMA` and sets it for every row (including when `DATA` is missing → `"missing"`).

| Script | Schema values |
| --- | --- |
| `ny_data_repair.py` | `DOB_issuances`, `DOB_filing_single`, `other`, `unknown`, `missing` |
| `phi_data_repair.py` | `nested`, `flat_upper`, `flat_mixed`, `unknown`, `missing` |
| `culver_city_data_repair.py` | `tasks`, `flat`, `search_data_only`, `unknown`, `missing` |
| `calabasas_data_repair.py` | `standard`, `unknown`, `missing` (new `_classify_schema`) |
| `burbank_data_repair.py` | `flat`, `unknown`, `missing` (new `_classify_schema`) |
| `compton_data_repair.py` | `flat`, `unknown`, `missing` (new `_classify_schema`) |

## Artifacts

- Modified: `agent/scripts/ny_data_repair.py`
- Modified: `agent/scripts/phi_data_repair.py`
- Modified: `agent/scripts/culver_city_data_repair.py`
- Modified: `agent/scripts/calabasas_data_repair.py`
- Modified: `agent/scripts/burbank_data_repair.py`
- Modified: `agent/scripts/compton_data_repair.py`

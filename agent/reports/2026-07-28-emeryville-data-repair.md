# Emeryville (CA) data repair

**Summary:** Emeryville was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. All 2,000 sample rows (and all 4,933 upstream Dewey rows) have null `DATA`, so agency-JSON validation of dates is impossible. `STATUS_ORIGINAL` shows one systematic mis-map: 3 `tco` rows were left `In Review` → FIXED to `Active`. `FILE_DATE` and `FINAL_DATE` remain 100% missing with nothing to fill from; `PERMIT_DATE` is already complete (including on Active/Final). Script: `agent/scripts/ca/data_repair_ca_emeryville.py`.

## Jurisdiction selection

First `(JURISDICTION, STATE)` in sorted `permits_ca_sample.parquet` without `agent/scripts/{state}/data_repair_{state}_{city}.py`: **Emeryville, CA**.

## DATA schema

| Schema | N | Notes |
| --- | --- | --- |
| `missing` | 2,000 | `DATA` is null on every sample row |

Upstream Dewey shard `building-permits-united-states_0_5_0.snappy.parquet` also has null `DATA` for all 4,933 Emeryville jurisdiction rows. No Applied / Issued / Finaled JSON fields exist to recover dates.

## Findings by field

### STATUS_NORMALIZED

Before: Active 1,853 / Final 112 / In Review 20 / Inactive 15 / missing 0.

`STATUS_ORIGINAL` crosstab is otherwise consistent (`issued`→Active, `finaled`→Final, `under review`→In Review, `expired`/`withdrawn`→Inactive, `approved`→Active). The only incorrect mapping:

1. **`tco` (3 rows)** — Temporary Certificate of Occupancy is post-issuance occupancy, not plan review. Was `In Review` → should be `Active`.

Repair: **0 FILLED, 3 FIXED**; missing after: **0**.

After: Active 1,856 / Final 112 / In Review 17 / Inactive 15.

### FILE_DATE

Before: **2,000 / 2,000 missing**. No application/submittal date exists in structured columns or DATA.

Repair: **0 FILLED, 0 FIXED**. Coverage remains 0%.

### PERMIT_DATE

Before: **0 missing**. Present on every status, including In Review (17 under-review encroachment shells) and Inactive. Permit-number year vs `PERMIT_DATE` year aligns on ~90% of rows (most mismatches are issuance one year after the number’s year), consistent with a real issuance stamp — but without DATA this cannot be confirmed, so values are left unchanged.

Repair: **0 FILLED, 0 FIXED**. Active/Final coverage: **100%**.

### FINAL_DATE

Before: **2,000 / 2,000 missing**, including all 112 `finaled` / Final rows. No completion/finaled date exists in structured columns or DATA.

Repair: **0 FILLED, 0 FIXED**. Final coverage remains 0%.

## Repair script

`agent/scripts/ca/data_repair_ca_emeryville.py` — `data_repair(df)` overwrites incorrect/missing fields when possible, adds `{FIELD}_FLAG` (`FILLED` / `FIXED`) and `INFERRED_SCHEMA` (`missing` for every row). Status expected values are derived from `STATUS_ORIGINAL` because DATA is absent.

### Performance (n=2,000)

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | --- | --- | --- | --- |
| STATUS_NORMALIZED | 0 | 3 | 0 | 0 |
| FILE_DATE | 0 | 0 | 2,000 | 2,000 |
| PERMIT_DATE | 0 | 0 | 0 | 0 |
| FINAL_DATE | 0 | 0 | 2,000 | 2,000 |

### Coverage after repair

| Check | Result |
| --- | --- |
| FILE_DATE present | 0 / 2,000 (0%) |
| PERMIT_DATE on Active | 1,856 / 1,856 (100%) |
| PERMIT_DATE on Final | 112 / 112 (100%) |
| FINAL_DATE on Final | 0 / 112 (0%) |
| FINAL_DATE on non-Final | 0 |

Ideal-coverage gaps that cannot be closed without a richer agency feed: all `FILE_DATE`, and all Final `FINAL_DATE`.

## Artifacts

- Script: `agent/scripts/ca/data_repair_ca_emeryville.py`
- Repaired sample: `$AGENT_DATA_PATH/repaired/permits_ca_emeryville_repaired.parquet`

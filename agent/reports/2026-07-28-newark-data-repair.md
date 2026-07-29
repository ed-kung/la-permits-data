# Newark (CA) data repair

**Summary:** Newark was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. All 2,000 sample rows (and all 17,956 upstream Dewey rows in `building-permits-united-states_2_0_12.snappy.parquet`) have null `DATA`, so agency-JSON validation of dates is impossible. `STATUS_ORIGINAL` shows one systematic mis-map (`under construction` → In Review → FIXED to Active) and 8 blank-status fire/ops shells with `PERMIT_DATE` → FILLED Active. `FINAL_DATE` remains 100% missing; 55 `closed` Final shells still lack `FILE_DATE`; `PERMIT_DATE` is already complete on Active/Final. Script: `agent/scripts/ca/data_repair_ca_newark.py`.

## Jurisdiction selection

First `(JURISDICTION, STATE)` in `permits_ca_sample.parquet` appearance order without `agent/scripts/{state}/data_repair_{state}_{city}.py`: **Newark, CA**.

## DATA schema

| Schema | N | Notes |
| --- | --- | --- |
| `missing` | 2,000 | `DATA` is null on every sample row |

Upstream Dewey shard `building-permits-united-states_2_0_12.snappy.parquet` also has null `DATA` for all 17,956 Newark CA jurisdiction rows. No Applied / Issued / Finaled JSON fields exist to recover dates.

## Findings by field

### STATUS_NORMALIZED

Before: Final 1,425 / Active 466 / Inactive 99 / missing 8 / In Review 2.

`STATUS_ORIGINAL` crosstab is otherwise consistent (`finaled`/`closed`→Final, `issued`/`approved`→Active, `submitted`→In Review, `expired`/`withdrawn`/`void`→Inactive). Issues repaired:

1. **Blank status (8 rows)** — `STATUS_ORIGINAL` and `STATUS_NORMALIZED` both null (F13/F14 tents, operational, hazardous-materials permits). All already carry `PERMIT_DATE` → FILLED **Active**.
2. **`under construction` (1 row)** — post-issuance construction progress, not plan review. Was `In Review` → FIXED to **Active**.

`closed`→Final (58) is retained (same convention as Eastvale Closed→Final). Without DATA there is no finaled stamp to distinguish administrative close from completion.

Repair: **8 FILLED, 1 FIXED**; missing after: **0**.

After: Final 1,425 / Active 475 / Inactive 99 / In Review 1 (`submitted`).

### FILE_DATE

Before: **55 / 2,000 missing** (97.2% coverage). All 55 gaps are `STATUS_ORIGINAL=closed` / Final shells; the other 3 `closed` rows already have `FILE_DATE`. No application/submittal field exists in structured columns or DATA.

Three chronology inversions (`FILE_DATE` > `PERMIT_DATE`) exist on issued/finaled rows; without DATA they cannot be corrected.

Repair: **0 FILLED, 0 FIXED**. Coverage remains 97.2%.

### PERMIT_DATE

Before: **0 missing**. Present on every status, including the remaining In Review (`submitted`) shell and all Inactive rows. Active/Final coverage is already 100%. Without DATA values cannot be confirmed, so they are left unchanged.

Repair: **0 FILLED, 0 FIXED**. Active/Final coverage: **100%**.

### FINAL_DATE

Before: **2,000 / 2,000 missing**, including all 1,425 `finaled`/`closed` / Final rows. No completion/finaled date exists in structured columns or DATA.

Repair: **0 FILLED, 0 FIXED**. Final coverage remains 0%.

## Repair script

`agent/scripts/ca/data_repair_ca_newark.py` — `data_repair(df)` overwrites incorrect/missing fields when possible, adds `{FIELD}_FLAG` (`FILLED` / `FIXED`) and `INFERRED_SCHEMA` (`missing` for every row). Status expected values are derived from `STATUS_ORIGINAL` (and `PERMIT_DATE` presence for blank shells) because DATA is absent.

### Performance (n=2,000)

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | --- | --- | --- | --- |
| STATUS_NORMALIZED | 8 | 1 | 8 | 0 |
| FILE_DATE | 0 | 0 | 55 | 55 |
| PERMIT_DATE | 0 | 0 | 0 | 0 |
| FINAL_DATE | 0 | 0 | 2,000 | 2,000 |

### Coverage after repair

| Check | Result |
| --- | --- |
| FILE_DATE present | 1,945 / 2,000 (97.2%) |
| PERMIT_DATE on Active | 475 / 475 (100%) |
| PERMIT_DATE on Final | 1,425 / 1,425 (100%) |
| FINAL_DATE on Final | 0 / 1,425 (0%) |
| FINAL_DATE on non-Final | 0 |

Ideal-coverage gaps that cannot be closed without a richer agency feed: 55 `FILE_DATE` on closed shells, and all Final `FINAL_DATE`.

## Artifacts

- Script: `agent/scripts/ca/data_repair_ca_newark.py`
- Repaired sample: `$AGENT_DATA_PATH/repaired/permits_ca_newark_repaired.parquet`

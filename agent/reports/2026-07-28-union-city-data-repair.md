# Union City (CA) data repair

**Summary:** Union City was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. All 2,000 sample rows (and all 14,892 upstream Dewey Union City CA rows in shards `0_5_17` and `2_5_4`) have null `DATA`, null `STATUS_ORIGINAL`, null `FILE_DATE`, and null `FINAL_DATE`. Agency-JSON validation of dates is impossible. Every row already carries `PERMIT_DATE`; blank-status shells with an issuance stamp are filled to **Active** (2,000 FILLED). Date fields cannot be recovered. Script: `agent/scripts/ca/data_repair_ca_union_city.py`.

## Jurisdiction selection

First `(JURISDICTION, STATE)` in `permits_ca_sample.parquet` appearance order without `agent/scripts/{state}/data_repair_{state}_{city}.py`: **Union City, CA** (index 212, after Selma).

## DATA schema

| Schema | N | Notes |
| --- | --- | --- |
| `missing` | 2,000 | `DATA` is null on every sample row |

Upstream Dewey shards also have null `DATA` for all Union City CA jurisdiction rows (`building-permits-united-states_0_5_17.snappy.parquet`: 11,010; `building-permits-united-states_2_5_4.snappy.parquet`: 3,882). No Applied / Issued / Finaled JSON fields exist to recover dates. `STATUS_ORIGINAL` is likewise null upstream.

## Findings by field

### STATUS_NORMALIZED

Before: **2,000 / 2,000 missing**. `STATUS_ORIGINAL` is also entirely null, so there is no status string to map.

Only available signal: every row has a populated `PERMIT_DATE` (2010-01-06 … 2022-03-30). Following the Newark blank-shell convention (null status + issuance stamp → Active), all rows are filled to **Active**.

No rows can be labeled Final / In Review / Inactive without a terminal status, review-stage status, or finaling stamp in DATA.

Repair: **2,000 FILLED, 0 FIXED**; missing after: **0**.

After: Active 2,000.

### FILE_DATE

Before: **2,000 / 2,000 missing**. No application/submittal field exists in structured columns or DATA.

Permit numbers often encode a two-digit year (e.g. `BLDG-21-022404`) that matches `PERMIT_DATE`'s year on 1,824 / 1,908 parseable rows, or precedes it by one year on most disagreements — consistent with an application-year token — but this is not a calendar date and is not used as `FILE_DATE`.

Repair: **0 FILLED, 0 FIXED**. Coverage remains 0%.

### PERMIT_DATE

Before: **0 missing**. Present on every row. Active coverage after status fill is already 100%. Without DATA, values cannot be confirmed, so they are left unchanged.

Repair: **0 FILLED, 0 FIXED**. Active coverage: **100%**.

### FINAL_DATE

Before: **2,000 / 2,000 missing**. No completion/finaled date exists in structured columns or DATA. No rows are classified as Final, so the ideal Final/`FINAL_DATE` coverage target does not apply after repair.

Repair: **0 FILLED, 0 FIXED**.

## Repair script

`agent/scripts/ca/data_repair_ca_union_city.py` — `data_repair(df)` overwrites incorrect/missing fields when possible, adds `{FIELD}_FLAG` (`FILLED` / `FIXED`) and `INFERRED_SCHEMA` (`missing` for every row). Status expected values are derived from `STATUS_ORIGINAL` when present, else from `PERMIT_DATE` presence for blank shells, because DATA is absent.

### Performance (n=2,000)

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | ---: | ---: | ---: | ---: |
| STATUS_NORMALIZED | 2,000 | 0 | 2,000 | 0 |
| FILE_DATE | 0 | 0 | 2,000 | 2,000 |
| PERMIT_DATE | 0 | 0 | 0 | 0 |
| FINAL_DATE | 0 | 0 | 2,000 | 2,000 |

### Coverage after repair

| Check | Result |
| --- | --- |
| FILE_DATE present | 0 / 2,000 (0%) |
| PERMIT_DATE on Active | 2,000 / 2,000 (100%) |
| PERMIT_DATE on Final | n/a (0 Final rows) |
| FINAL_DATE on Final | n/a |
| FINAL_DATE on non-Final | 0 |

Ideal-coverage gaps that cannot be closed without a richer agency feed: all `FILE_DATE` values, and any Final/`FINAL_DATE` labeling (no terminal status or finaling stamp in the feed).

## Artifacts

- Script: `agent/scripts/ca/data_repair_ca_union_city.py`
- Repaired sample: `$AGENT_DATA_PATH/repaired/permits_ca_union_city_repaired.parquet`

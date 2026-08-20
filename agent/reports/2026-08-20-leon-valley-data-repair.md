# Leon Valley (TX) data repair

**Summary:** Among TX sample jurisdictions missing a repair script, Leon Valley was first. Its DATA is a MyGovernmentOnline project payload (`mgo_ppm` / `mgo_base`). `STATUS_NORMALIZED` and `FILE_DATE` are already correct for all 2,000 sample rows. `PERMIT_DATE` and `FINAL_DATE` are missing everywhere because the agency payload never stores a real issue or completion timestamp (`DateIssued` / `DateUpdated` are the .NET sentinel `0001-01-01`). The repair script encodes the correct mappings and will fill/fix when source fields become available, but on this sample it changes zero values.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_tx_sample.parquet` and walked `(JURISDICTION, STATE)` in group order. First pair without `agent/scripts/{state}/data_repair_{state}_{city}.py` was **Leon Valley, TX** (2,000 sample rows).

## DATA schema

Two near-identical top-level key sets (MGO project object):

| Schema | n | Distinguishing key |
| --- | ---: | --- |
| `mgo_ppm` | 1,943 | `PaymentProcessorModule == "MGO"` |
| `mgo_base` | 57 | same keys, no `PaymentProcessorModule` |

Relevant fields:

| DATA field | Role |
| --- | --- |
| `ProjectStatus` | Raw status |
| `DateCreated` | Application / create timestamp → `FILE_DATE` |
| `DateIssued` | Intended issue date → always sentinel in sample |
| `DateUpdated` | Always sentinel in sample |
| Other `*Date*` fields | Null; no CO / final / sign-off date |

## Field assessment

### STATUS_NORMALIZED

| `STATUS_ORIGINAL` | `ProjectStatus` | `STATUS_NORMALIZED` | n |
| --- | --- | --- | ---: |
| project closed/complete | Project Closed/Complete | Final | 1,413 |
| permit issued | Permit Issued | Active | 374 |
| pending payment | Pending Payment | In Review | 82 |
| pending (under review) | Pending (Under Review) | In Review | 55 |
| closed | Closed | Final | 50 |
| pending customer response | Pending Customer Response | In Review | 26 |

No missing statuses. Cross-check of `STATUS_NORMALIZED` vs `ProjectStatus` found **0 mismatches**. Mapping is correct; no fills or fixes needed in sample. No Inactive records in this sample.

### FILE_DATE

- Missing before repair: **0 / 2,000**
- Equals calendar day of `DateCreated` on every row
- Ideal coverage (all records populated) already met

### PERMIT_DATE

- Missing before repair: **2,000 / 2,000** (including all 374 Active + 1,463 Final)
- `DateIssued` is `0001-01-01T00:00:00` on every row → treated as missing
- No other usable issue/approval timestamp in DATA
- **Cannot fill** from available agency JSON; gap is a source-data limitation

### FINAL_DATE

- Missing before repair: **2,000 / 2,000** (including all 1,463 Final)
- `DateUpdated` is the same .NET sentinel; `ScheduledDueDate`, `RequestPermanentPowerDate`, and `RequestTemporaryPowerDate` are null
- **Cannot fill** for Final records from available agency JSON

## Repair script

- Path: `agent/scripts/tx/data_repair_tx_leon_valley.py`
- Entry point: `data_repair(df)`
- Sets `INFERRED_SCHEMA` (`mgo_ppm` / `mgo_base` / `missing` / `unknown`)
- Overwrites incorrect fields; adds `{FIELD}_FLAG` = `FILLED` or `FIXED` when changed
- Status map includes Leon Valley’s `Pending Payment`, `Pending Customer Response`, `Pending (Under Review)`, `Project Closed/Complete`, `Closed`, and `Permit Issued`
- `PERMIT_DATE` ← real `DateIssued` when present for Active/Final
- `FINAL_DATE` cleared only if present on a non-Final row (none in sample)

## Repair performance (TX sample, n=2,000)

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | ---: | ---: | ---: | ---: |
| STATUS_NORMALIZED | 0 | 0 | 0 | 0 |
| FILE_DATE | 0 | 0 | 0 | 0 |
| PERMIT_DATE | 0 | 0 | 2,000 | 2,000 |
| FINAL_DATE | 0 | 0 | 2,000 | 2,000 |

Post-repair coverage:

| Status | FILE_DATE | PERMIT_DATE | FINAL_DATE |
| --- | --- | --- | --- |
| Active (374) | 100% | 0% | 0% |
| Final (1,463) | 100% | 0% | 0% |
| In Review (163) | 100% | 0% | 0% |

Date-order violations after repair: none (no permit/final dates to compare).

## Artifact

- Repaired sample parquet: `AGENT_DATA_PATH/repaired/permits_tx_leon_valley_repaired.parquet`

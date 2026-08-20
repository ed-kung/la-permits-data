# Lampasas (TX) data repair

**Summary:** Among TX sample jurisdictions missing a repair script, Lampasas was first. Its DATA is a MyGovernmentOnline project payload (`mgo_ppm` / `mgo_base`). `STATUS_NORMALIZED` and `FILE_DATE` are already correct for all 2,000 sample rows. `PERMIT_DATE` and `FINAL_DATE` are missing everywhere because the agency payload never stores a real issue or completion timestamp (`DateIssued` / `DateUpdated` are the .NET sentinel `0001-01-01`). The repair script encodes the correct mappings and will fill/fix when source fields become available, but on this sample it changes zero values.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_tx_sample.parquet` and walked `(JURISDICTION, STATE)` in group order. First pair without `agent/scripts/{state}/data_repair_{state}_{city}.py` was **Lampasas, TX** (2,000 sample rows).

## DATA schema

Two near-identical top-level key sets (MGO project object):

| Schema | n | Distinguishing key |
| --- | ---: | --- |
| `mgo_ppm` | 1,996 | `PaymentProcessorModule == "MGO"` |
| `mgo_base` | 4 | same keys, no `PaymentProcessorModule` |

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
| permit issued | Permit Issued | Active | 1,417 |
| project closed/complete | Project Closed/Complete | Final | 484 |
| pending (under review) | Pending (Under Review) | In Review | 83 |
| withdrawn | Withdrawn | Inactive | 16 |

No missing statuses. Cross-check of `STATUS_NORMALIZED` vs `ProjectStatus` found **0 mismatches**. Mapping is correct; no fills or fixes needed in sample.

### FILE_DATE

- Missing before repair: **0 / 2,000**
- Equals calendar day of `DateCreated` on every row
- Ideal coverage (all records populated) already met

### PERMIT_DATE

- Missing before repair: **2,000 / 2,000** (including all 1,417 Active + 484 Final)
- `DateIssued` is `0001-01-01T00:00:00` on every row → treated as missing
- No other usable issue/approval timestamp in DATA
- **Cannot fill** from available agency JSON; gap is a source-data limitation

### FINAL_DATE

- Missing before repair: **2,000 / 2,000** (including all 484 Final)
- `DateUpdated` is the same .NET sentinel; `ScheduledDueDate` and related fields are null
- **Cannot fill** for Final records from available agency JSON

## Repair script

- Path: `agent/scripts/tx/data_repair_tx_lampasas.py`
- Entry point: `data_repair(df)`
- Sets `INFERRED_SCHEMA` (`mgo_ppm` / `mgo_base` / `missing` / `unknown`)
- Overwrites incorrect fields; adds `{FIELD}_FLAG` = `FILLED` or `FIXED` when changed
- Status map includes Lampasas’s `Pending (Under Review)` (with space), `Project Closed/Complete`, and `Withdrawn`
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
| Active (1,417) | 100% | 0% | 0% |
| Final (484) | 100% | 0% | 0% |
| In Review (83) | 100% | 0% | 0% |
| Inactive (16) | 100% | 0% | 0% |

Date-order violations after repair: none (no permit/final dates to compare).

## Artifact

- Repaired sample parquet: `AGENT_DATA_PATH/repaired/permits_tx_lampasas_repaired.parquet`

# West Lake Hills (TX) data repair

**Summary:** Among TX sample jurisdictions missing a repair script, West Lake Hills was first. Its DATA is a MyGovernmentOnline project payload (`mgo_ppm` / `mgo_base`). `STATUS_NORMALIZED` and `FILE_DATE` are already correct for all 2,000 sample rows. `PERMIT_DATE` and `FINAL_DATE` are missing everywhere because the agency payload never stores a real issue or completion timestamp (`DateIssued` / `DateUpdated` are the .NET sentinel `0001-01-01`). The repair script encodes the correct mappings and will fill/fix when source fields become available, but on this sample it changes zero values.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_tx_sample.parquet` and walked `(JURISDICTION, STATE)` pairs in appearance order. First pair without `agent/scripts/{state}/data_repair_{state}_{city}.py` was **West Lake Hills, TX** (2,000 sample rows).

## DATA schema

Two near-identical top-level key sets (MGO project object):

| Schema | n | Distinguishing key |
| --- | ---: | --- |
| `mgo_ppm` | 1,975 | `PaymentProcessorModule == "MGO"` |
| `mgo_base` | 25 | same keys, no `PaymentProcessorModule` |

Relevant fields:

| DATA field | Role |
| --- | --- |
| `ProjectStatus` | Raw status (strip whitespace before map) |
| `DateCreated` | Application / create timestamp → `FILE_DATE` |
| `DateIssued` | Intended issue date → always sentinel in sample |
| `DateUpdated` | Always sentinel in sample |
| Other `*Date*` fields | Null; no CO / final / sign-off date |

## Field assessment

### STATUS_NORMALIZED

| `STATUS_ORIGINAL` | `ProjectStatus` | `STATUS_NORMALIZED` | n |
| --- | --- | --- | ---: |
| project closed/complete | Project Closed/Complete | Final | 1,141 |
| permit issued | Permit Issued | Active | 564 |
| pending(under review) | Pending(Under Review) | In Review | 294 |
| stop work order | Stop Work Order | In Review | 1 |

No missing statuses. Cross-check of `STATUS_NORMALIZED` vs stripped `ProjectStatus` (using the standard MGO map, including `Stop Work Order` → `In Review`) found **0 mismatches**. Mapping is correct; no fills or fixes needed in sample.

### FILE_DATE

- 0 missing.
- Calendar-day match vs `DateCreated` on all 2,000 rows.
- No incorrect values to fix.

### PERMIT_DATE

- Missing on all 2,000 rows, including all 1,705 Active+Final records where it should ideally be populated.
- `DateIssued` is `0001-01-01T00:00:00` on every row (MGO/.NET empty-date sentinel).
- **Cannot fill** from DATA in this sample. Script will fill from a real `DateIssued` if present in future extracts.

### FINAL_DATE

- Missing on all 2,000 rows, including all 1,141 Final records where it should ideally be populated.
- `DateUpdated`, `ScheduledDueDate`, and power-request date fields are null or sentinel; no completion / CO / sign-off timestamp exists.
- **Cannot fill** from DATA in this sample. Script clears `FINAL_DATE` only if a non-Final row incorrectly carries one (none in sample).

## Repair script

- Path: `agent/scripts/tx/data_repair_tx_west_lake_hills.py`
- Entry point: `data_repair(df)`
- Adds `INFERRED_SCHEMA` and `{FIELD}_FLAG` (`FILLED` / `FIXED`) for status and the three date fields.
- Conventions follow `agent/scripts/ny/data_repair_ny_ny.py` and sibling TX MGO scripts.

## Repair performance (n=2,000)

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | ---: | ---: | ---: | ---: |
| STATUS_NORMALIZED | 0 | 0 | 0 | 0 |
| FILE_DATE | 0 | 0 | 0 | 0 |
| PERMIT_DATE | 0 | 0 | 2,000 | 2,000 |
| FINAL_DATE | 0 | 0 | 2,000 | 2,000 |

Coverage after repair (unchanged from before):

| Status | FILE_DATE | PERMIT_DATE | FINAL_DATE |
| --- | ---: | ---: | ---: |
| Active (564) | 100% | 0% | 0% |
| Final (1,141) | 100% | 0% | 0% |
| In Review (295) | 100% | 0% | 0% |

Date-order violations: none (no permit/final dates present).

## Artifacts

- Repair script: `agent/scripts/tx/data_repair_tx_west_lake_hills.py`
- Repaired sample parquet: `AGENT_DATA_PATH/repaired/permits_tx_west_lake_hills_repaired.parquet`

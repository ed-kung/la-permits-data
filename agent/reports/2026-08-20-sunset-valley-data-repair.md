# Sunset Valley (TX) data repair

**Summary:** Among TX sample jurisdictions missing a repair script, Sunset Valley was first. Its DATA is a MyGovernmentOnline project payload (`mgo_ppm` only in this sample). `STATUS_NORMALIZED` and `FILE_DATE` are already correct for all 570 sample rows. `PERMIT_DATE` and `FINAL_DATE` are missing everywhere because the agency payload never stores a real issue or completion timestamp (`DateIssued` / `DateUpdated` are the .NET sentinel `0001-01-01`). The repair script encodes the correct mappings and will fill/fix when source fields become available, but on this sample it changes zero values.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_tx_sample.parquet` and walked `(JURISDICTION, STATE)` pairs in sorted order. First pair without `agent/scripts/{state}/data_repair_{state}_{city}.py` was **Sunset Valley, TX** (570 sample rows). Remaining missing after this work: Uhland, TX.

## DATA schema

Single top-level key set (MGO project object):

| Schema | n | Distinguishing key |
| --- | ---: | --- |
| `mgo_ppm` | 570 | `PaymentProcessorModule == "MGO"` |

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
| permit issued | Permit Issued | Active | 294 |
| pending (under review) | Pending (Under Review) | In Review | 215 |
| pending payment | Pending Payment | In Review | 28 |
| project closed/complete | Project Closed/Complete | Final | 28 |
| expired | Expired | Inactive | 3 |
| pending review | Pending Review | In Review | 2 |

No missing statuses. Cross-check of `STATUS_NORMALIZED` vs stripped `ProjectStatus` (including `Pending Payment` / `Pending Review` → `In Review`) found **0 mismatches**. Mapping is correct; no fills or fixes needed in sample.

### FILE_DATE

- 0 missing.
- Calendar-day match vs `DateCreated` on all 570 rows.
- No incorrect values to fix.

### PERMIT_DATE

- Missing on all 570 rows, including all 322 Active+Final records where it should ideally be populated.
- `DateIssued` is `0001-01-01T00:00:00` on every row (MGO/.NET empty-date sentinel).
- **Cannot fill** from DATA in this sample. Script will fill from a real `DateIssued` if present in future extracts.

### FINAL_DATE

- Missing on all 570 rows, including all 28 Final records where it should ideally be populated.
- `DateUpdated`, `ScheduledDueDate`, and power-request date fields are null or sentinel; no completion / CO / sign-off timestamp exists.
- **Cannot fill** from DATA in this sample. Script clears `FINAL_DATE` only if a non-Final row incorrectly carries one (none in sample).

## Repair script

- Path: `agent/scripts/tx/data_repair_tx_sunset_valley.py`
- Entry point: `data_repair(df)`
- Adds `INFERRED_SCHEMA` and `{FIELD}_FLAG` (`FILLED` / `FIXED`) for status and the three date fields.
- Conventions follow `agent/scripts/ny/data_repair_ny_ny.py` and sibling TX MGO scripts (e.g. West Lake Hills, Rollingwood).

## Repair performance (n=570)

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | ---: | ---: | ---: | ---: |
| STATUS_NORMALIZED | 0 | 0 | 0 | 0 |
| FILE_DATE | 0 | 0 | 0 | 0 |
| PERMIT_DATE | 0 | 0 | 570 | 570 |
| FINAL_DATE | 0 | 0 | 570 | 570 |

Coverage after repair (unchanged from before):

| Status | FILE_DATE | PERMIT_DATE | FINAL_DATE |
| --- | ---: | ---: | ---: |
| Active (294) | 100% | 0% | 0% |
| Final (28) | 100% | 0% | 0% |
| In Review (245) | 100% | 0% | 0% |
| Inactive (3) | 100% | 0% | 0% |

Date-order violations after repair: none (`FILE>PERMIT=0`, `PERMIT>FINAL=0`, `FILE>FINAL=0`).

## Artifacts

- Script: `agent/scripts/tx/data_repair_tx_sunset_valley.py`
- Repaired sample parquet: `AGENT_DATA_PATH/repaired/permits_tx_sunset_valley_repaired.parquet`

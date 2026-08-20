# Uhland (TX) data repair

**Summary:** Among TX sample jurisdictions missing a repair script, Uhland was first (and last remaining). Its DATA is a MyGovernmentOnline project payload (`mgo_ppm` / `mgo_base`). `STATUS_NORMALIZED` and `FILE_DATE` are already correct for all 2,000 sample rows. `PERMIT_DATE` and `FINAL_DATE` are missing everywhere because the agency payload never stores a real issue or completion timestamp (`DateIssued` / `DateUpdated` are the .NET sentinel `0001-01-01`). The repair script encodes the correct mappings and will fill/fix when source fields become available, but on this sample it changes zero values.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_tx_sample.parquet` and walked `(JURISDICTION, STATE)` pairs in sorted order. First pair without `agent/scripts/{state}/data_repair_{state}_{city}.py` was **Uhland, TX** (2,000 sample rows). No other TX sample jurisdictions remain without a repair script after this work.

## DATA schema

Two near-identical top-level key sets (MGO project object):

| Schema | n | Distinguishing key |
| --- | ---: | --- |
| `mgo_ppm` | 1,997 | `PaymentProcessorModule == "MGO"` |
| `mgo_base` | 3 | same keys, no `PaymentProcessorModule` |

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
| permit issued | Permit Issued | Active | 1,766 |
| pending(under review) | Pending(Under Review) | In Review | 225 |
| project closed/complete | Project Closed/Complete | Final | 9 |

No missing statuses. Cross-check of `STATUS_NORMALIZED` vs stripped `ProjectStatus` found **0 mismatches**. Mapping is correct; no fills or fixes needed in sample. No `Inactive` rows appear in this sample.

### FILE_DATE

- 0 missing.
- Calendar-day match vs `DateCreated` on all 2,000 rows.
- No incorrect values to fix.
- Range: 2020-06-16 through 2025-09-24.

### PERMIT_DATE

- Missing on all 2,000 rows, including all 1,775 Active+Final records where it should ideally be populated.
- `DateIssued` is `0001-01-01T00:00:00` on every row (MGO/.NET empty-date sentinel).
- **Cannot fill** from DATA in this sample. Script will fill from a real `DateIssued` if present in future extracts.

### FINAL_DATE

- Missing on all 2,000 rows, including all 9 Final records where it should ideally be populated.
- `DateUpdated`, `ScheduledDueDate`, and power-request date fields are null or sentinel; no completion / CO / sign-off timestamp exists.
- **Cannot fill** from DATA in this sample. Script clears `FINAL_DATE` only if a non-Final row incorrectly carries one (none in sample).

## Repair script

- Path: `agent/scripts/tx/data_repair_tx_uhland.py`
- Entry point: `data_repair(df)`
- Adds `INFERRED_SCHEMA` and `{FIELD}_FLAG` (`FILLED` / `FIXED`) for status and the three date fields.
- Conventions follow `agent/scripts/ny/data_repair_ny_ny.py` and sibling TX MGO scripts (e.g. West Lake Hills, Sunset Valley).

## Repair performance (n=2000)

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | ---: | ---: | ---: | ---: |
| STATUS_NORMALIZED | 0 | 0 | 0 | 0 |
| FILE_DATE | 0 | 0 | 0 | 0 |
| PERMIT_DATE | 0 | 0 | 2,000 | 2,000 |
| FINAL_DATE | 0 | 0 | 2,000 | 2,000 |

Coverage after repair (unchanged from before):

| Status | FILE_DATE | PERMIT_DATE | FINAL_DATE |
| --- | ---: | ---: | ---: |
| Active (1,766) | 100% | 0% | 0% |
| Final (9) | 100% | 0% | 0% |
| In Review (225) | 100% | 0% | 0% |

Date-order violations after repair: none (`FILE>PERMIT=0`, `PERMIT>FINAL=0`, `FILE>FINAL=0`).

## Artifacts

- Script: `agent/scripts/tx/data_repair_tx_uhland.py`
- Repaired sample parquet: `AGENT_DATA_PATH/repaired/permits_tx_uhland_repaired.parquet`

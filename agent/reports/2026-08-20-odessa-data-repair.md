# Odessa (TX) data repair

**Summary:** Among TX sample jurisdictions missing a repair script, Odessa was first (after Nacogdoches). Its DATA is a MyGovernmentOnline project payload (`mgo_ppm` / `mgo_base`). `STATUS_NORMALIZED` and `FILE_DATE` are already correct for all 2,000 sample rows. `PERMIT_DATE` and `FINAL_DATE` are missing everywhere because the agency payload never stores a real issue or completion timestamp (`DateIssued` / `DateUpdated` are the .NET sentinel `0001-01-01`). The repair script encodes the correct mappings and will fill/fix when source fields become available, but on this sample it changes zero values.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_tx_sample.parquet` and walked `(JURISDICTION, STATE)` in first-appearance order. First pair without `agent/scripts/{state}/data_repair_{state}_{city}.py` was **Odessa, TX** (index 59 of 99 jurisdictions; 2,000 sample rows).

## DATA schema

Two near-identical top-level key sets (MGO project object):

| Schema | n | Distinguishing key |
| --- | ---: | --- |
| `mgo_ppm` | 1,978 | `PaymentProcessorModule == "MGO"` |
| `mgo_base` | 22 | same keys, no `PaymentProcessorModule` |

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
| project closed/complete | Project Closed/Complete | Final | 874 |
| permit issued | Permit Issued | Active | 761 |
| pending(under review) | Pending(Under Review) | In Review | 302 |
| stop work order | Stop Work Order | In Review | 23 |
| expired | Expired | Inactive | 40 |

No missing statuses. Cross-check of `STATUS_NORMALIZED` vs `ProjectStatus` found **0 mismatches**. Mapping is correct; no fills or fixes needed in sample.

### FILE_DATE

- Missing before repair: **0 / 2,000**
- Equals calendar day of `DateCreated` on every row
- Ideal coverage (all records populated) already met

### PERMIT_DATE

- Missing before repair: **2,000 / 2,000** (including all 761 Active + 874 Final)
- `DateIssued` is `0001-01-01T00:00:00` on every row → treated as missing
- No other usable issue/approval timestamp in DATA
- **Cannot fill** from available agency JSON; gap is a source-data limitation

### FINAL_DATE

- Missing before repair: **2,000 / 2,000** (including all 874 Final)
- `DateUpdated` is the same .NET sentinel; `ScheduledDueDate`, power-request dates are null
- **Cannot fill** for Final records from available agency JSON

## Repair script

- Path: `agent/scripts/tx/data_repair_tx_odessa.py`
- Entry point: `data_repair(df)`
- Sets `INFERRED_SCHEMA` (`mgo_ppm` / `mgo_base` / `missing` / `unknown`)
- Overwrites incorrect fields; adds `{FIELD}_FLAG` = `FILLED` or `FIXED` when changed
- Status map includes Odessa’s `Pending(Under Review)` (no space) and `Project Closed/Complete`
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
| Active (761) | 100% | 0% | 0% |
| Final (874) | 100% | 0% | 0% |
| In Review (325) | 100% | 0% | 0% |
| Inactive (40) | 100% | 0% | 0% |

Date-order violations after repair: none (no permit/final dates to compare).

## Artifact

- Repaired sample parquet: `AGENT_DATA_PATH/repaired/permits_tx_odessa_repaired.parquet`

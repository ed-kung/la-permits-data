# Manor (TX) data repair

**Summary:** Manor was the first `(JURISDICTION, STATE)` pair in `permits_tx_sample.parquet` without an existing repair script. Its DATA is a MyGovernmentOnline (MGO) project payload (`mgo_ppm` / `mgo_base`). `STATUS_NORMALIZED` and `FILE_DATE` are already correct for all 2,000 sample rows. `PERMIT_DATE` and `FINAL_DATE` are missing everywhere because the agency payload never stores a real issue or completion timestamp (`DateIssued` / `DateUpdated` are the .NET sentinel `0001-01-01`). The repair script encodes the correct mappings and will fill/fix when source fields become available, but on this sample it changes zero values.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_tx_sample.parquet` and walked `(JURISDICTION, STATE)` in first-appearance order. Existing TX scripts covered through Lago Vista; **Manor, TX** was the first missing (`agent/scripts/tx/data_repair_tx_manor.py`; index 69 of 99 jurisdictions; 2,000 sample rows).

## DATA schema

Two near-identical top-level key sets (MGO project object):

| Schema | n | Distinguishing key |
| --- | ---: | --- |
| `mgo_ppm` | 1,996 | `PaymentProcessorModule == "MGO"` |
| `mgo_base` | 4 | same keys, no `PaymentProcessorModule` |

All rows have `ProjectType == "Permit"` and `Jurisdiction == "Manor"`. Content varies by project type/use, but date/status fields share one flat schema.

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
| project closed/complete | Project Closed/Complete | Final | 1,456 |
| permit issued | Permit Issued | Active | 298 |
| pending (under review) | Pending (Under Review) | In Review | 181 |
| expired | Expired | Inactive | 53 |
| withdrawn | Withdrawn | Inactive | 12 |

No missing statuses. Cross-check of `STATUS_NORMALIZED` vs `ProjectStatus` found **0 mismatches**. Mapping is correct; no fills or fixes needed in sample.

### FILE_DATE

- Missing before repair: **0 / 2,000**
- Equals calendar day of `DateCreated` on every row (years 2016–2025)
- Ideal coverage (all records populated) already met

### PERMIT_DATE

- Missing before repair: **2,000 / 2,000** (including all 298 Active + 1,456 Final)
- `DateIssued` is `0001-01-01T00:00:00` on every row → treated as missing
- No other usable issue/approval timestamp in DATA
- **Cannot fill** from available agency JSON; gap is a source-data limitation

### FINAL_DATE

- Missing before repair: **2,000 / 2,000** (including all 1,456 Final)
- `DateUpdated` is the same .NET sentinel; power-request and scheduled-due dates are null
- **Cannot fill** for Final records from available agency JSON

## Repair script

- Path: `agent/scripts/tx/data_repair_tx_manor.py`
- Entry point: `data_repair(df)`
- Sets `INFERRED_SCHEMA` (`mgo_ppm` / `mgo_base` / `missing` / `unknown`)
- Overwrites incorrect fields; adds `{FIELD}_FLAG` = `FILLED` or `FIXED` when changed
- Status map covers Manor’s `Project Closed/Complete`, `Permit Issued`, `Pending (Under Review)`, `Expired`, and `Withdrawn` (plus common MGO variants)
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
| Active (298) | 100% | 0% | 0% |
| Final (1,456) | 100% | 0% | 0% |
| In Review (181) | 100% | 0% | 0% |
| Inactive (65) | 100% | 0% | 0% |

Date-order violations after repair: none (no permit/final dates to compare).

## Not repairable

- All Active/Final rows lack a real `DateIssued` → `PERMIT_DATE` stays missing.
- All Final rows lack a completion/sign-off timestamp → `FINAL_DATE` stays missing.

## Artifacts

- Script: `agent/scripts/tx/data_repair_tx_manor.py` (`data_repair`)
- Repaired sample: `$AGENT_DATA_PATH/repaired/permits_tx_manor_repaired.parquet`

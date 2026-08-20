# Marble Falls (TX) data repair

**Summary:** Among TX sample jurisdictions missing a repair script, Marble Falls was first. Its DATA is a MyGovernmentOnline project payload (`mgo_ppm` / `mgo_base`). `FILE_DATE` is already correct for all 2,000 sample rows. One row had missing `STATUS_NORMALIZED` for `Stop Work Order Issued`; the repair fills that as `In Review`. `PERMIT_DATE` and `FINAL_DATE` are missing everywhere because the agency payload never stores a real issue or completion timestamp (`DateIssued` / `DateUpdated` are the .NET sentinel `0001-01-01`).

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_tx_sample.parquet` and walked `(JURISDICTION, STATE)` in first-appearance order. First pair without `agent/scripts/{state}/data_repair_{state}_{city}.py` was **Marble Falls, TX** (2,000 sample rows).

## DATA schema

Two near-identical top-level key sets (MGO project object):

| Schema | n | Distinguishing key |
| --- | ---: | --- |
| `mgo_ppm` | 1,999 | includes `PaymentProcessorModule` |
| `mgo_base` | 1 | same keys, no `PaymentProcessorModule` |

Relevant fields:

| DATA field | Role |
| --- | --- |
| `ProjectStatus` | Raw status |
| `DateCreated` | Application / create timestamp → `FILE_DATE` |
| `DateIssued` | Intended issue date → always sentinel in sample |
| `DateUpdated` | Always sentinel in sample |
| Other `*Date*` fields | Null / sentinel; no CO / final / sign-off date |

## Field assessment

### STATUS_NORMALIZED

| `STATUS_ORIGINAL` | `ProjectStatus` | `STATUS_NORMALIZED` (before) | n |
| --- | --- | --- | ---: |
| closed | Closed | Final | 907 |
| issued (construction) | Issued (Construction) | Active | 837 |
| pending (under review) | Pending (Under Review) | In Review | 173 |
| pending (review complete) | Pending (Review Complete) | In Review | 40 |
| withdrawn | Withdrawn | Inactive | 41 |
| void | Void | Inactive | 1 |
| stop work order issued | Stop Work Order Issued | **missing** | 1 |

All populated statuses already matched `ProjectStatus`. The 1 missing row has `ProjectStatus == "Stop Work Order Issued"` — present in `STATUS_ORIGINAL` but never normalized. Mapped to **In Review** (consistent with other MGO “Stop Work Order*” mappings). No incorrect non-missing statuses found.

### FILE_DATE

- Missing before repair: **0 / 2,000**
- Equals calendar day of `DateCreated` on every row
- Ideal coverage (all records populated) already met

### PERMIT_DATE

- Missing before repair: **2,000 / 2,000** (including all 837 Active + 907 Final)
- `DateIssued` is `0001-01-01T00:00:00` on every row → treated as missing
- No other usable issue/approval timestamp in DATA
- **Cannot fill** from available agency JSON; gap is a source-data limitation

### FINAL_DATE

- Missing before repair: **2,000 / 2,000** (including all 907 Final)
- `DateUpdated` is the same .NET sentinel; `ScheduledDue` / `ScheduledDueDate` are also empty/sentinel
- **Cannot fill** for Final records from available agency JSON

## Repair script

- Path: `agent/scripts/tx/data_repair_tx_marble_falls.py`
- Entry point: `data_repair(df)`
- Sets `INFERRED_SCHEMA` (`mgo_ppm` / `mgo_base` / `missing` / `unknown`)
- Overwrites incorrect fields; adds `{FIELD}_FLAG` = `FILLED` or `FIXED` when changed
- Status map includes Marble Falls’s observed statuses, notably `Closed`, `Issued (Construction)`, `Pending (Under Review)`, `Pending (Review Complete)`, `Stop Work Order Issued`, `Withdrawn`, and `Void`
- `PERMIT_DATE` ← real `DateIssued` when present for Active/Final
- `FINAL_DATE` cleared only if present on a non-Final row (none in sample)

## Repair performance (TX sample, n=2,000)

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | ---: | ---: | ---: | ---: |
| STATUS_NORMALIZED | 1 | 0 | 1 | 0 |
| FILE_DATE | 0 | 0 | 0 | 0 |
| PERMIT_DATE | 0 | 0 | 2,000 | 2,000 |
| FINAL_DATE | 0 | 0 | 2,000 | 2,000 |

Post-repair status counts: Final 907, Active 837, In Review 214, Inactive 42.

Ideal date coverage still unmet for Active/Final `PERMIT_DATE` and Final `FINAL_DATE` because those timestamps are absent from the MGO JSON.

## Artifacts

- Repair script: `agent/scripts/tx/data_repair_tx_marble_falls.py`
- Repaired sample parquet: `AGENT_DATA_PATH/repaired/permits_tx_marble_falls_repaired.parquet`

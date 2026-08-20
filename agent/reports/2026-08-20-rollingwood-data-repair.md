# Rollingwood (TX) data repair

**Summary:** Among TX sample jurisdictions missing a repair script, Rollingwood was first. Its DATA is a MyGovernmentOnline project payload (`mgo_ppm` / `mgo_base`). `STATUS_NORMALIZED` and `FILE_DATE` are already correct for all 975 sample rows. `PERMIT_DATE` and `FINAL_DATE` are missing everywhere because the agency payload never stores a real issue or completion timestamp (`DateIssued` / `DateUpdated` are the .NET sentinel `0001-01-01`). The repair script encodes the correct mappings and will fill/fix when source fields become available, but on this sample it changes zero values.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_tx_sample.parquet` and walked `(JURISDICTION, STATE)` pairs in sorted order. First pair without `agent/scripts/{state}/data_repair_{state}_{city}.py` was **Rollingwood, TX** (975 sample rows). Remaining missing at selection time: Shavano Park, Sunset Valley, Uhland, Universal City, West Lake Hills, Windcrest.

## DATA schema

Two near-identical top-level key sets (MGO project object):

| Schema | n | Distinguishing key |
| --- | ---: | --- |
| `mgo_ppm` | 969 | `PaymentProcessorModule == "MGO"` |
| `mgo_base` | 6 | same keys, no `PaymentProcessorModule` |

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
| permit issued | Permit Issued | Active | 479 |
| project closed/complete | Project Closed/Complete | Final | 310 |
| closed | Closed | Final | 1 |
| pending (under review) | Pending (Under Review) | In Review | 148 |
| open | Open | In Review | 3 |
| pending customer response | Pending Customer Response | In Review | 2 |
| expired | Expired | Inactive | 29 |
| cancelled/withdrawn | Cancelled/Withdrawn | Inactive | 3 |

No missing statuses. Cross-check of `STATUS_NORMALIZED` vs stripped `ProjectStatus` found **0 mismatches**. Mapping is correct; no fills or fixes needed in sample.

### FILE_DATE

- Missing before repair: **0 / 975**
- Equals calendar day of `DateCreated` on every row
- Ideal coverage (all records populated) already met

### PERMIT_DATE

- Missing before repair: **975 / 975** (including all 479 Active + 311 Final)
- `DateIssued` is `0001-01-01T00:00:00` on every row → treated as missing
- No other usable issue/approval timestamp in DATA
- **Cannot fill** from available agency JSON; gap is a source-data limitation

### FINAL_DATE

- Missing before repair: **975 / 975** (including all 311 Final)
- `DateUpdated` is the same .NET sentinel; `ScheduledDueDate`, power-request dates are null
- **Cannot fill** for Final records from available agency JSON

## Repair script

- Path: `agent/scripts/tx/data_repair_tx_rollingwood.py`
- Entry point: `data_repair(df)`
- Sets `INFERRED_SCHEMA` (`mgo_ppm` / `mgo_base` / `missing` / `unknown`)
- Overwrites incorrect fields; adds `{FIELD}_FLAG` = `FILLED` or `FIXED` when changed
- Status map includes Rollingwood’s `Pending Customer Response`, `Open`, and `Closed`
- `PERMIT_DATE` ← real `DateIssued` when present for Active/Final
- `FINAL_DATE` cleared only if present on a non-Final row (none in sample)

## Repair performance (TX sample, n=975)

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | ---: | ---: | ---: | ---: |
| STATUS_NORMALIZED | 0 | 0 | 0 | 0 |
| FILE_DATE | 0 | 0 | 0 | 0 |
| PERMIT_DATE | 0 | 0 | 975 | 975 |
| FINAL_DATE | 0 | 0 | 975 | 975 |

Post-repair coverage:

| Status | n | FILE_DATE | PERMIT_DATE | FINAL_DATE |
| --- | ---: | ---: | ---: | ---: |
| Active | 479 | 100% | 0% | 0% |
| Final | 311 | 100% | 0% | 0% |
| In Review | 153 | 100% | 0% | 0% |
| Inactive | 32 | 100% | 0% | 0% |

Date-order violations after repair: none (no permit/final dates to compare).

## Artifacts

- Script: `agent/scripts/tx/data_repair_tx_rollingwood.py`
- Repaired sample parquet: `AGENT_DATA_PATH/repaired/permits_tx_rollingwood_repaired.parquet`

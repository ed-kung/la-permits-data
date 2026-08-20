# Taylor (TX) data repair

**Summary:** Among TX sample jurisdictions missing a repair script, Taylor was first. Its DATA is a MyGovernmentOnline project payload (`mgo_ppm` / `mgo_base`). `FILE_DATE` is already correct for all 2,000 sample rows. Four rows had missing `STATUS_NORMALIZED` for `Denied - Awaiting Revisions`; the repair fills those as `Inactive`. `PERMIT_DATE` and `FINAL_DATE` are missing everywhere because the agency payload never stores a real issue or completion timestamp (`DateIssued` / `DateUpdated` are the .NET sentinel `0001-01-01`).

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_tx_sample.parquet` and walked `(JURISDICTION, STATE)` in first-appearance order. First pair without `agent/scripts/{state}/data_repair_{state}_{city}.py` was **Taylor, TX** (2,000 sample rows).

## DATA schema

Two near-identical top-level key sets (MGO project object):

| Schema | n | Distinguishing key |
| --- | ---: | --- |
| `mgo_ppm` | 1,918 | `PaymentProcessorModule == "MGO"` |
| `mgo_base` | 82 | same keys, no `PaymentProcessorModule` |

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

| `STATUS_ORIGINAL` | `ProjectStatus` | `STATUS_NORMALIZED` (before) | n |
| --- | --- | --- | ---: |
| project closed/complete | Project Closed/Complete | Final | 1,240 |
| permit issued | Permit Issued | Active | 571 |
| in review | In Review | In Review | 109 |
| awaiting revisions | Awaiting Revisions | In Review | 29 |
| pending payment | Pending Payment | In Review | 17 |
| plan review completed | Plan Review Completed | In Review | 12 |
| withdrawn | Withdrawn | Inactive | 10 |
| expired | Expired | Inactive | 5 |
| denied - awaiting revisions | Denied - Awaiting Revisions | **missing** | 4 |
| ready to issue | Ready to Issue | In Review | 3 |

All populated statuses already matched `ProjectStatus`. The 4 missing rows share `ProjectStatus == "Denied - Awaiting Revisions"` — present in `STATUS_ORIGINAL` but never normalized. Mapped to **Inactive** (consistent with other MGO “Denied*” mappings). No incorrect non-missing statuses found.

### FILE_DATE

- Missing before repair: **0 / 2,000**
- Equals calendar day of `DateCreated` on every row
- Ideal coverage (all records populated) already met

### PERMIT_DATE

- Missing before repair: **2,000 / 2,000** (including all 571 Active + 1,240 Final)
- `DateIssued` is `0001-01-01T00:00:00` on every row → treated as missing
- No other usable issue/approval timestamp in DATA
- **Cannot fill** from available agency JSON; gap is a source-data limitation

### FINAL_DATE

- Missing before repair: **2,000 / 2,000** (including all 1,240 Final)
- `DateUpdated` is the same .NET sentinel; `ScheduledDueDate`, `RequestPermanentPowerDate`, and `RequestTemporaryPowerDate` are null
- **Cannot fill** for Final records from available agency JSON

## Repair script

- Path: `agent/scripts/tx/data_repair_tx_taylor.py`
- Entry point: `data_repair(df)`
- Sets `INFERRED_SCHEMA` (`mgo_ppm` / `mgo_base` / `missing` / `unknown`)
- Overwrites incorrect fields; adds `{FIELD}_FLAG` = `FILLED` or `FIXED` when changed
- Status map includes Taylor’s observed statuses, notably `Denied - Awaiting Revisions`, `Awaiting Revisions`, `Plan Review Completed`, and `Ready to Issue`
- `PERMIT_DATE` ← real `DateIssued` when present for Active/Final
- `FINAL_DATE` cleared only if present on a non-Final row (none in sample)

## Repair performance (TX sample, n=2,000)

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | ---: | ---: | ---: | ---: |
| STATUS_NORMALIZED | 4 | 0 | 4 | 0 |
| FILE_DATE | 0 | 0 | 0 | 0 |
| PERMIT_DATE | 0 | 0 | 2,000 | 2,000 |
| FINAL_DATE | 0 | 0 | 2,000 | 2,000 |

After repair, status counts: Final 1,240; Active 571; In Review 170; Inactive 19 (was 15). Filled permits: `2025-15205`, `2025-14878`, `2025-14968`, `2025-14684`.

Coverage after repair: `FILE_DATE` 100% for all statuses; `PERMIT_DATE` 0% for Active/Final; `FINAL_DATE` 0% for Final. No date-order violations (no permit/final dates to compare).

## Artifacts

- Script: `agent/scripts/tx/data_repair_tx_taylor.py`
- Repaired sample parquet: `AGENT_DATA_PATH/repaired/permits_tx_taylor_repaired.parquet`

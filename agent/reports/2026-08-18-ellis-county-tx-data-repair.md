# Ellis County (TX) data repair

**Summary:** Ellis County was the first TX jurisdiction in `permits_tx_sample.parquet` without a repair script (2,000 rows). DATA is a MyGovernmentOnline (MGO) flat project payload (`mgo_ppm` / `mgo_base`). The main defect is STATUS_NORMALIZED: 790 rows with `ProjectStatus` = `Permit Issued/Complete` were labeled Final; peer MGO TX cities map the equivalent `Permit Issued` state to Active, so these are FIXED to Active. FILE_DATE already equals `DateCreated` on every row. PERMIT_DATE and FINAL_DATE remain fully missing: `DateIssued` / `DateUpdated` are the .NET sentinel `0001-01-01T00:00:00` on all rows, and `RequestInspections` is a boolean with no inspection timestamps.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_tx_sample.parquet` and walked unique `(JURISDICTION, STATE)` pairs in sample order. Existing `agent/scripts/tx/data_repair_tx_*.py` scripts cover prior cities through Elgin. **Ellis County** was the first missing pair → `agent/scripts/tx/data_repair_tx_ellis_county.py`.

## DATA schema

| INFERRED_SCHEMA | n | Notes |
| --- | ---: | --- |
| `mgo_ppm` | 1,870 | Full MGO key set including `PaymentProcessorModule` (= `MGO`) |
| `mgo_base` | 130 | Same keys without `PaymentProcessorModule` |

Canonical sources:

| Target field | Primary source | Notes |
| --- | --- | --- |
| STATUS_NORMALIZED | `ProjectStatus` | Whitespace-stripped; Ellis-specific `Permit Issued/Complete` → Active |
| FILE_DATE | `DateCreated` | Matches FILE_DATE at calendar-day resolution on all rows |
| PERMIT_DATE | `DateIssued` | Always sentinel in sample → not fillable |
| FINAL_DATE | — | No completion / CO / inspection date in DATA |

## Field assessment

### STATUS_NORMALIZED

Before: Final 1,891 / In Review 105 / Inactive 4 / Active 0 / missing 0.

`ProjectStatus` → expected mapping:

| ProjectStatus | Before STATUS_NORMALIZED | Corrected | n |
| --- | --- | --- | ---: |
| Project Closed/Complete | Final | Final (unchanged) | 1,101 |
| Permit Issued/Complete | Final | **Active** (FIXED) | 790 |
| Pending (Under Review) | In Review | In Review (unchanged) | 105 |
| Withdrawn | Inactive | Inactive (unchanged) | 4 |

Reason for the 790 FIXED rows: upstream treated `permit issued/complete` as Final. In other TX MGO portals (Belton, Bulverde, Copperas Cove, etc.) the parallel status is `Permit Issued` → Active, while `Project Closed/Complete` is the true Final/closed state. Ellis’s `/Complete` suffix refers to completion of the issuance step, not project closeout. Zero Active rows before repair was the symptom.

After: Final 1,101 / Active 790 / In Review 105 / Inactive 4 / missing 0.

### FILE_DATE

Fully populated before repair (0 missing). Every row matches `DateCreated` at calendar-day resolution (809 `DateCreated` strings carry fractional seconds; day equality still holds). No FILLED/FIXED changes.

### PERMIT_DATE

Missing on all 2,000 rows (including all 790 Active + 1,101 Final after repair). `DateIssued` is present as a string on every record but always the .NET empty-date sentinel `0001-01-01T00:00:00`. No other issuance timestamp exists in DATA (`DateUpdated` is also sentinel; nested document/inspection payloads are boolean flags only). Cannot fill.

### FINAL_DATE

Missing on all 2,000 rows (including all 1,101 Final). No finaled / completion / certificate-of-occupancy date field in the MGO payload. `RequestInspections` is a boolean, not an inspection history. `RequestPermanentPowerDate`, `RequestTemporaryPowerDate`, and `ScheduledDueDate` are null on all sample rows. Cannot fill.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 0 | 790 | 0 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 0 | 0 | 2,000 → 2,000 |
| FINAL_DATE | 0 | 0 | 2,000 → 2,000 |

Post-repair coverage:

| Status | FILE_DATE | PERMIT_DATE | FINAL_DATE |
| --- | ---: | ---: | ---: |
| Active | 790 / 790 | 0 / 790 | 0 / 790 |
| Final | 1,101 / 1,101 | 0 / 1,101 | 0 / 1,101 |
| In Review | 105 / 105 | 0 / 105 | 0 / 105 |
| Inactive | 4 / 4 | 0 / 4 | 0 / 4 |

Date-order violations after repair: FILE>PERMIT=0, PERMIT>FINAL=0, FILE>FINAL=0.

## Artifacts

- Repair script: `agent/scripts/tx/data_repair_tx_ellis_county.py`
- Repaired sample parquet: `$AGENT_DATA_PATH/repaired/permits_tx_ellis_county_repaired.parquet`

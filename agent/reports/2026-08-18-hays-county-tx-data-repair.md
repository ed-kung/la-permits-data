# Hays County (TX) data repair

**Summary:** Hays County was the first TX jurisdiction in `permits_tx_sample.parquet` without a repair script (1,999 rows). DATA is a MyGovernmentOnline (MGO) flat project payload (`mgo_ppm` / `mgo_base`). STATUS_NORMALIZED was already correct for nearly all rows; the only change is 4 `Transferred` records remapped from In Review → Inactive. FILE_DATE already equals `DateCreated` on every row. PERMIT_DATE and FINAL_DATE remain fully missing: `DateIssued` / `DateUpdated` are the .NET sentinel `0001-01-01T00:00:00` on all rows, and no completion / inspection timestamps exist in DATA.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_tx_sample.parquet` and walked unique `(JURISDICTION, STATE)` pairs in sample order. Existing `agent/scripts/tx/data_repair_tx_*.py` scripts cover prior cities through Harker Heights / Harris County. **Hays County** was the first missing pair → `agent/scripts/tx/data_repair_tx_hays_county.py`.

## DATA schema

| INFERRED_SCHEMA | n | Notes |
| --- | ---: | --- |
| `mgo_ppm` | 1,926 | Full MGO key set including `PaymentProcessorModule` (= `MGO`) |
| `mgo_base` | 73 | Same keys without `PaymentProcessorModule` |

Canonical sources:

| Target field | Primary source | Notes |
| --- | --- | --- |
| STATUS_NORMALIZED | `ProjectStatus` | Whitespace-stripped; Hays-specific labels below |
| FILE_DATE | `DateCreated` | Matches FILE_DATE at calendar-day resolution on all rows |
| PERMIT_DATE | `DateIssued` | Always sentinel in sample → not fillable |
| FINAL_DATE | — | No completion / CO / inspection date in DATA |

## Field assessment

### STATUS_NORMALIZED

Before: Active 1,759 / In Review 208 / Inactive 27 / Final 5 / missing 0.

`ProjectStatus` → expected mapping:

| ProjectStatus | Before STATUS_NORMALIZED | Corrected | n |
| --- | --- | --- | ---: |
| Permitted | Active | Active (unchanged) | 1,752 |
| Pending | In Review | In Review (unchanged) | 204 |
| Expired | Inactive | Inactive (unchanged) | 21 |
| Active | Active | Active (unchanged) | 6 |
| Inactive | Inactive | Inactive (unchanged) | 6 |
| Closed | Final | Final (unchanged) | 5 |
| Transferred | In Review | **Inactive** (FIXED) | 4 |
| Permitted (No Maintenance | Active | Active (unchanged) | 1 |

Reason for the 4 FIXED rows: upstream mapped `Transferred` to In Review. A transfer out of this portal is a terminal / non-processing state for Hays County, not an application under review, so Inactive is the correct bucket (alongside Expired / Inactive).

After: Active 1,759 / In Review 204 / Inactive 31 / Final 5 / missing 0.

### FILE_DATE

Fully populated before repair (0 missing). Every row matches `DateCreated` at calendar-day resolution. No FILLED/FIXED changes.

### PERMIT_DATE

Missing on all 1,999 rows (including all 1,759 Active + 5 Final). `DateIssued` is present as a string on every record but always the .NET empty-date sentinel `0001-01-01T00:00:00`. No other issuance timestamp exists in DATA (`DateUpdated` is also sentinel; `TypeList` / photo / document fields are strings or booleans only). Cannot fill.

### FINAL_DATE

Missing on all 1,999 rows (including all 5 Final / `Closed`). No finaled / completion / certificate-of-occupancy date field in the MGO payload. `RequestInspections` is a boolean, not an inspection history. `RequestPermanentPowerDate`, `RequestTemporaryPowerDate`, and `ScheduledDueDate` are null on all sample rows. Cannot fill.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 0 | 4 | 0 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 0 | 0 | 1,999 → 1,999 |
| FINAL_DATE | 0 | 0 | 1,999 → 1,999 |

Post-repair coverage:

| Status | FILE_DATE | PERMIT_DATE | FINAL_DATE |
| --- | ---: | ---: | ---: |
| Active | 1,759 / 1,759 | 0 / 1,759 | 0 / 1,759 |
| Final | 5 / 5 | 0 / 5 | 0 / 5 |
| In Review | 204 / 204 | 0 / 204 | 0 / 204 |
| Inactive | 31 / 31 | 0 / 31 | 0 / 31 |

Date-order violations after repair: FILE>PERMIT=0, PERMIT>FINAL=0, FILE>FINAL=0.

## Artifacts

- Repair script: `agent/scripts/tx/data_repair_tx_hays_county.py`
- Repaired sample parquet: `$AGENT_DATA_PATH/repaired/permits_tx_hays_county_repaired.parquet`

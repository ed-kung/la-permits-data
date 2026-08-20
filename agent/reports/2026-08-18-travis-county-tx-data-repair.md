# Travis County (TX) data repair

**Summary:** Travis County was the first TX jurisdiction in `permits_tx_sample.parquet` without a repair script after La Porte (2,000 rows). DATA is a MyGovernmentOnline (MGO) flat project payload (`mgo_ppm` / `mgo_base`). STATUS_NORMALIZED was missing on 1 row (`Post Review`) and is now FILLED as In Review; all other statuses already matched `ProjectStatus`. FILE_DATE already equals `DateCreated` on every row. PERMIT_DATE and FINAL_DATE remain fully missing: `DateIssued` / `DateUpdated` are the .NET sentinel `0001-01-01T00:00:00` on all rows, and `RequestInspections` is a boolean with no inspection timestamps.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_tx_sample.parquet` and walked unique `(JURISDICTION, STATE)` pairs in sample order. Existing `agent/scripts/tx/data_repair_tx_*.py` scripts cover prior cities through La Porte. **Travis County** was the first missing pair → `agent/scripts/tx/data_repair_tx_travis_county.py`.

## DATA schema

| INFERRED_SCHEMA | n | Notes |
| --- | ---: | --- |
| `mgo_ppm` | 1,997 | Full MGO key set including `PaymentProcessorModule` (= `MGO`) |
| `mgo_base` | 3 | Same keys without `PaymentProcessorModule` |

Canonical sources:

| Target field | Primary source | Notes |
| --- | --- | --- |
| STATUS_NORMALIZED | `ProjectStatus` | Whitespace-stripped; Travis-specific values include `In-Review`, `Unpaid`, `Dormant`, `Post Review` |
| FILE_DATE | `DateCreated` | Matches FILE_DATE at calendar-day resolution on all rows |
| PERMIT_DATE | `DateIssued` | Always sentinel in sample → not fillable |
| FINAL_DATE | — | No completion / CO / inspection date in DATA |

## Field assessment

### STATUS_NORMALIZED

Before: Active 891 / Final 606 / In Review 346 / Inactive 156 / missing 1.

`ProjectStatus` → normalized mapping already correct for 1,999 rows:

| ProjectStatus | STATUS_NORMALIZED | n |
| --- | --- | ---: |
| Issued (Construction) | Active | 891 |
| Closed/Completed | Final | 606 |
| In-Review | In Review | 234 |
| Void | Inactive | 99 |
| Unpaid | In Review | 61 |
| Dormant | Inactive | 57 |
| Open | In Review | 51 |
| Post Review | *(missing)* | 1 |

The single missing row (`ProjectNumber` 23-44526, `ProjectStatus` = `Post Review`) had `STATUS_ORIGINAL` = `post review` but null `STATUS_NORMALIZED`. Mapped to **In Review** (FILLED).

After: Active 891 / Final 606 / In Review 347 / Inactive 156 / missing 0.

### FILE_DATE

Fully populated before repair (0 missing). Every row matches `DateCreated` at calendar-day resolution. No FILLED/FIXED changes.

### PERMIT_DATE

Missing on all 2,000 rows (including all 891 Active + 606 Final). `DateIssued` is present as a string on every record but always the .NET empty-date sentinel `0001-01-01T00:00:00`. No other issuance timestamp exists in DATA (`DateUpdated` is also sentinel; nested document/inspection payloads are boolean flags only). Cannot fill.

### FINAL_DATE

Missing on all 2,000 rows (including all 606 Final). No finaled / completion / certificate-of-occupancy date field in the MGO payload. `RequestInspections` is a boolean, not an inspection history. Cannot fill.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 1 | 0 | 1 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 0 | 0 | 2,000 → 2,000 |
| FINAL_DATE | 0 | 0 | 2,000 → 2,000 |

Post-repair coverage:

| Status | FILE_DATE | PERMIT_DATE | FINAL_DATE |
| --- | ---: | ---: | ---: |
| Active | 891 / 891 | 0 / 891 | 0 / 891 |
| Final | 606 / 606 | 0 / 606 | 0 / 606 |
| In Review | 347 / 347 | 0 / 347 | 0 / 347 |
| Inactive | 156 / 156 | 0 / 156 | 0 / 156 |

Date-order violations after repair: FILE>PERMIT=0, PERMIT>FINAL=0, FILE>FINAL=0.

## Artifacts

- Script: `agent/scripts/tx/data_repair_tx_travis_county.py` (`data_repair`)
- Repaired sample: `AGENT_DATA_PATH/repaired/permits_tx_travis_county_repaired.parquet`

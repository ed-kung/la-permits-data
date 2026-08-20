# Harker Heights (TX) data repair

**Summary:** Harker Heights was the first TX sample jurisdiction lacking a repair script (2,000 rows). DATA is a MyGovernmentOnline (MGO) flat project payload (`mgo_ppm` only in sample). `STATUS_NORMALIZED` and `FILE_DATE` are already correct against `ProjectStatus` and `DateCreated`. `PERMIT_DATE` and `FINAL_DATE` are missing on every row and cannot be filled: `DateIssued` / `DateUpdated` are the .NET sentinel `0001-01-01T00:00:00`, and no completion / CO / inspection timestamp exists in DATA despite 705 Final (`Closed`) rows. The repair script tags `INFERRED_SCHEMA` and will fill/fix when real `DateIssued` values appear.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_tx_sample.parquet` and walked `(JURISDICTION, STATE)` pairs in group order. Existing `agent/scripts/tx/data_repair_tx_*.py` scripts cover Austin through Grayson County / related cities through Pflugerville; **Harker Heights** is the first without a script (2,000 sample rows).

## DATA schema

| INFERRED_SCHEMA | n | Notes |
| --- | ---: | --- |
| `mgo_ppm` | 2,000 | Full MGO key set including `PaymentProcessorModule` (= `MGO`); single 89-key set |

Canonical sources:

| Target field | Primary source | Notes |
| --- | --- | --- |
| STATUS_NORMALIZED | `ProjectStatus` | Whitespace-stripped |
| FILE_DATE | `DateCreated` | Matches FILE_DATE at calendar-day resolution on all rows |
| PERMIT_DATE | `DateIssued` | Always sentinel in sample → not fillable |
| FINAL_DATE | — | No completion / CO / inspection date in DATA |

All sample rows are `ProjectType` = Permit. Date range for `FILE_DATE` / `DateCreated`: 2016-05-03 to 2025-10-01.

## Field assessment

### STATUS_NORMALIZED

Before: Active 1,097 / Final 705 / In Review 182 / Inactive 16 / missing 0.

`ProjectStatus` → expected mapping (all already correct):

| ProjectStatus | STATUS_ORIGINAL | STATUS_NORMALIZED | n |
| --- | --- | --- | ---: |
| Permit Issued | permit issued | Active | 1,097 |
| Closed | closed | Final | 705 |
| Pending (Under Review) | pending (under review) | In Review | 182 |
| Permit Expired | permit expired | Inactive | 11 |
| Withdrawn | withdrawn | Inactive | 5 |

No missing statuses and no mismatches vs `ProjectStatus`. **0 FILLED / 0 FIXED.**

### FILE_DATE

Fully populated before repair (0 missing). Every row matches `DateCreated` at calendar-day resolution. **0 FILLED / 0 FIXED.**

### PERMIT_DATE

Ideal: populated for Active and Final.

Missing on all 2,000 rows, including all 1,097 Active and 705 Final. `DateIssued` is present as a string on every record but always the .NET empty-date sentinel `0001-01-01T00:00:00`. `DateUpdated` is the same sentinel; power-request and scheduled-due dates are null; `RequestInspections` is a boolean only. Cannot fill from DATA. **0 FILLED / 0 FIXED.**

### FINAL_DATE

Ideal: populated for Final; absent otherwise.

Missing on all 2,000 rows. For the 1,295 non-Final rows this is correct. For the 705 Final rows (`Closed`) there is no recoverable finaled / completion / CO timestamp in the MGO payload. Cannot fill. **0 FILLED / 0 FIXED.**

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 0 | 0 | 0 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 0 | 0 | 2,000 → 2,000 |
| FINAL_DATE | 0 | 0 | 2,000 → 2,000 |

Post-repair coverage:

| Status | FILE_DATE | PERMIT_DATE | FINAL_DATE |
| --- | ---: | ---: | ---: |
| Active | 1,097 / 1,097 | 0 / 1,097 | 0 / 1,097 |
| Final | 705 / 705 | 0 / 705 | 0 / 705 |
| In Review | 182 / 182 | 0 / 182 | 0 / 182 |
| Inactive | 16 / 16 | 0 / 16 | 0 / 16 |

Date-order violations after repair: FILE>PERMIT=0, PERMIT>FINAL=0, FILE>FINAL=0.

## Artifacts

- Repair script: `agent/scripts/tx/data_repair_tx_harker_heights.py`
- Repaired sample parquet: `$AGENT_DATA_PATH/repaired/permits_tx_harker_heights_repaired.parquet`

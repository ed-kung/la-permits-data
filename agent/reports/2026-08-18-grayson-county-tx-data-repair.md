# Grayson County (TX) data repair

**Summary:** Grayson County was the first TX sample jurisdiction lacking a repair script (2,000 rows). DATA is a MyGovernmentOnline (MGO) flat project payload (`mgo_ppm` / `mgo_base`), almost entirely OSSF permits. `STATUS_NORMALIZED` and `FILE_DATE` are already correct against `ProjectStatus` and `DateCreated`. `PERMIT_DATE` and `FINAL_DATE` are missing on every row and cannot be filled: `DateIssued` / `DateUpdated` are the .NET sentinel `0001-01-01T00:00:00`, and no Final/closed status or completion timestamp exists in the sample. The repair script tags `INFERRED_SCHEMA` and is ready to fill/fix when real `DateIssued` values or additional statuses appear.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_tx_sample.parquet` and walked `(JURISDICTION, STATE)` pairs in order. Existing `agent/scripts/tx/data_repair_tx_*.py` scripts cover Abilene through Farmers Branch; **Grayson County** is the first without a script (2,000 sample rows).

## DATA schema

| INFERRED_SCHEMA | n | Notes |
| --- | ---: | --- |
| `mgo_ppm` | 1,794 | Full MGO key set including `PaymentProcessorModule` (= `MGO`) |
| `mgo_base` | 206 | Same keys without `PaymentProcessorModule` |

Canonical sources:

| Target field | Primary source | Notes |
| --- | --- | --- |
| STATUS_NORMALIZED | `ProjectStatus` | Whitespace-stripped; `Permitted` → Active |
| FILE_DATE | `DateCreated` | Matches FILE_DATE at calendar-day resolution on all rows |
| PERMIT_DATE | `DateIssued` | Always sentinel in sample → not fillable |
| FINAL_DATE | — | No completion / CO / inspection date in DATA; no Final rows |

Nearly all records are OSSF (`SpecificUse`: OSSF 1,955 / Not Assigned 34 / OSSF RV Parks 11).

## Field assessment

### STATUS_NORMALIZED

Before: Active 1,933 / In Review 50 / Inactive 17 / Final 0 / missing 0.

`ProjectStatus` → expected mapping (all already correct):

| ProjectStatus | STATUS_ORIGINAL | STATUS_NORMALIZED | n |
| --- | --- | --- | ---: |
| Permitted | permitted | Active | 1,613 |
| Active | active | Active | 320 |
| Pending | pending | In Review | 50 |
| Inactive | inactive | Inactive | 11 |
| Expired | expired | Inactive | 6 |

No missing statuses and no mismatches. Grayson has no closed/complete Final state in this sample (unlike Ellis County’s `Project Closed/Complete`). **0 FILLED / 0 FIXED.**

### FILE_DATE

Fully populated before repair (0 missing). Every row matches `DateCreated` at calendar-day resolution. **0 FILLED / 0 FIXED.**

### PERMIT_DATE

Ideal: populated for Active (and Final, if any).

Missing on all 2,000 rows, including all 1,933 Active. `DateIssued` is present as a string on every record but always the .NET empty-date sentinel `0001-01-01T00:00:00`. `DateUpdated` is the same sentinel; `RequestInspections` is a boolean; power-request and scheduled-due dates are null. Cannot fill from DATA. **0 FILLED / 0 FIXED.**

### FINAL_DATE

Ideal: populated for Final; absent otherwise.

No Final rows in the sample. `FINAL_DATE` is missing on all 2,000 rows (correct for non-Final). No finaled / completion / CO date field exists in the MGO payload. Cannot fill. **0 FILLED / 0 FIXED.**

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
| Active | 1,933 / 1,933 | 0 / 1,933 | 0 / 1,933 |
| In Review | 50 / 50 | 0 / 50 | 0 / 50 |
| Inactive | 17 / 17 | 0 / 17 | 0 / 17 |

Date-order violations after repair: FILE>PERMIT=0, PERMIT>FINAL=0, FILE>FINAL=0.

## Artifacts

- Repair script: `agent/scripts/tx/data_repair_tx_grayson_county.py`
- Repaired sample parquet: `$AGENT_DATA_PATH/repaired/permits_tx_grayson_county_repaired.parquet`

# Pflugerville (TX) data repair

**Summary:** Pflugerville was the first TX sample jurisdiction lacking a repair script (2,000 rows). DATA is a MyGovernmentOnline (MGO) flat project payload (`mgo_ppm` / `mgo_base`). `STATUS_NORMALIZED` and `FILE_DATE` are already correct against `ProjectStatus` and `DateCreated`. `PERMIT_DATE` and `FINAL_DATE` are missing on every row and cannot be filled: `DateIssued` / `DateUpdated` are the .NET sentinel `0001-01-01T00:00:00`, and no completion / CO / inspection timestamp exists in DATA despite 1,656 Final (`Closed` / `Finaled`) rows. The repair script tags `INFERRED_SCHEMA` and will fill/fix when real `DateIssued` values appear.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_tx_sample.parquet` and walked `(JURISDICTION, STATE)` pairs in first-appearance order. Existing `agent/scripts/tx/data_repair_tx_*.py` scripts cover Austin through Kyle; **Pflugerville** is the first without a script (2,000 sample rows).

## DATA schema

| INFERRED_SCHEMA | n | Notes |
| --- | ---: | --- |
| `mgo_ppm` | 1,962 | Full MGO key set including `PaymentProcessorModule` (= `MGO`) |
| `mgo_base` | 38 | Same keys without `PaymentProcessorModule` |

Canonical sources:

| Target field | Primary source | Notes |
| --- | --- | --- |
| STATUS_NORMALIZED | `ProjectStatus` | Whitespace-stripped |
| FILE_DATE | `DateCreated` | Matches FILE_DATE at calendar-day resolution on all rows |
| PERMIT_DATE | `DateIssued` | Always sentinel in sample → not fillable |
| FINAL_DATE | — | No completion / CO / inspection date in DATA |

All sample rows are `ProjectType` = Permit. Final rows mix ordinary closed permits (`Closed`, n=1,629) with explicitly finaled permits (`Finaled`, n=27).

## Field assessment

### STATUS_NORMALIZED

Before: Final 1,656 / Active 196 / Inactive 106 / In Review 42 / missing 0.

`ProjectStatus` → expected mapping (all already correct):

| ProjectStatus | STATUS_ORIGINAL | STATUS_NORMALIZED | n |
| --- | --- | --- | ---: |
| Closed | closed | Final | 1,629 |
| Issued | issued | Active | 196 |
| Expired | expired | Inactive | 106 |
| Pending (Under Review) | pending (under review) | In Review | 42 |
| Finaled | finaled | Final | 27 |

No missing statuses and no mismatches vs `ProjectStatus`. **0 FILLED / 0 FIXED.**

### FILE_DATE

Fully populated before repair (0 missing). Every row matches `DateCreated` at calendar-day resolution. **0 FILLED / 0 FIXED.**

### PERMIT_DATE

Ideal: populated for Active and Final.

Missing on all 2,000 rows, including all 196 Active and 1,656 Final. `DateIssued` is present as a string on every record but always the .NET empty-date sentinel `0001-01-01T00:00:00`. `DateUpdated` is the same sentinel; power-request and scheduled-due dates are null; `RequestInspections` is a boolean only. Cannot fill from DATA. **0 FILLED / 0 FIXED.**

### FINAL_DATE

Ideal: populated for Final; absent otherwise.

Missing on all 2,000 rows. For the 344 non-Final rows this is correct. For the 1,656 Final rows (`Closed` / `Finaled`) there is no recoverable finaled / completion / CO timestamp in the MGO payload. Cannot fill. **0 FILLED / 0 FIXED.**

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
| Active | 196 / 196 | 0 / 196 | 0 / 196 |
| Final | 1,656 / 1,656 | 0 / 1,656 | 0 / 1,656 |
| In Review | 42 / 42 | 0 / 42 | 0 / 42 |
| Inactive | 106 / 106 | 0 / 106 | 0 / 106 |

Date-order violations after repair: FILE>PERMIT=0, PERMIT>FINAL=0, FILE>FINAL=0.

## Artifacts

- Repair script: `agent/scripts/tx/data_repair_tx_pflugerville.py`
- Repaired sample parquet: `$AGENT_DATA_PATH/repaired/permits_tx_pflugerville_repaired.parquet`

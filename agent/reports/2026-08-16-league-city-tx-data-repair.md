# League City (TX) data repair

**Summary:** League City was the first TX jurisdiction in `permits_tx_sample.parquet` without a repair script (after Bellaire). All 2,001 rows are CivicPlus / EnerGov payloads (`entity_core` 1,823; `entity_rich` 178). STATUS_NORMALIZED had 47 missing values from unmapped portal statuses and 29 incorrect values from stale `STATUS_ORIGINAL` (CaseStatus had advanced). FILE_DATE already matched ApplyDate on every row. Repair filled 5 PERMIT_DATE values from IssueDate, filled 9 FINAL_DATE values on newly Final rows, and cleared 1,012 spurious FINAL_DATE values on non-Final rows (mostly Expired). After repair: Active PERMIT_DATE 100%; Final PERMIT_DATE 94.5%; Final FINAL_DATE 91.8%; non-Final FINAL_DATE empty.

## Scope

- Input: `MY_DATA_PATH/processed_data/permits_tx_sample.parquet`
- Jurisdiction: League City, TX (first pair lacking `agent/scripts/{state}/data_repair_{state}_{city}.py`)
- Script: `agent/scripts/tx/data_repair_tx_league_city.py`
- Artifact: `AGENT_DATA_PATH/repaired/permits_tx_league_city_repaired.parquet`

## DATA schema

EnerGov-style nested object. Two top-level key-set variants; both expose the same `entity` / `details` status and date fields:

| INFERRED_SCHEMA | n |
| --- | ---: |
| entity_core | 1,823 |
| entity_rich | 178 |

Canonical source fields:

| Target field | Primary source | Fallback |
| --- | --- | --- |
| STATUS_NORMALIZED | `details.PermitStatus` when Complete / Certificate of Occupancy Issued; else `entity.CaseStatus` | `details.PermitStatus` |
| FILE_DATE | `entity.ApplyDate` | — |
| PERMIT_DATE | `entity.IssueDate` | `details.IssueDate` |
| FINAL_DATE | `entity.FinalDate` | `details.FinalizeDate` |

`CaseStatus` and `PermitStatus` agree on 2,000 / 2,001 rows (one Submitted / Issued mismatch). `FinalDate` and `FinalizeDate` always agree when both are present (1,328 rows). Three ApplyDate entity/details pairs differ only by timezone offset; FILE_DATE already follows entity calendar day.

## Field assessment

### STATUS_NORMALIZED

47 missing + 29 incorrect before repair.

**Missing (FILLED 47):** portal statuses not mapped in the original normalize step:

| CaseStatus | Corrected | n |
| --- | --- | ---: |
| Comments Available Online | In Review | 21 |
| Pending Issuance of Permits | In Review | 12 |
| Pending Inspections | In Review | 11 |
| Active - FMO | Active | 2 |
| In Review | In Review | 1 |

**Incorrect (FIXED 29):** `STATUS_ORIGINAL` lagged behind portal `CaseStatus` (e.g. still `issued` after expiry or completion):

| CaseStatus | Prior STATUS_NORMALIZED | Corrected | n |
| --- | --- | --- | ---: |
| Expired | Active | Inactive | 15 |
| Complete | Active | Final | 6 |
| Certificate of Occupancy Issued | Active | Final | 3 |
| Issued | In Review | Active | 5 |

Root cause: original normalization used `STATUS_ORIGINAL`, which can disagree with live `entity.CaseStatus` / `details.PermitStatus` in DATA.

### FILE_DATE

Fully populated (0 missing). Every row matches `entity.ApplyDate` at calendar-day resolution (0 FILLED, 0 FIXED).

### PERMIT_DATE

293 missing before → 288 after (5 FILLED, 0 FIXED). Existing non-null values already matched IssueDate. The 5 fills are Issued (or details-only IssueDate) rows that previously lacked PERMIT_DATE, mostly while mislabeled In Review.

Unfillable gaps after repair:

- 18 Final rows with null IssueDate (mostly Certificate of Occupancy Issued)
- Remaining gaps are pre-issuance In Review or terminal Inactive without IssueDate

After repair: Active 396 / 396 (100%); Final 310 / 328 (94.5%).

### FINAL_DATE

697 missing before → 1,700 after. Issues:

1. **Spurious non-Final FINAL_DATE:** 1,012 non-Final rows (especially Expired / Inactive, plus 1 Active) carried portal FinalDate / FinalizeDate while status was not Complete / CO Issued → FIXED (cleared).
2. **Fillable Finals:** 9 rows (status-corrected Complete / CO Issued) had FinalDate in DATA but null FINAL_DATE → FILLED.
3. **Unfillable Finals:** 27 Certificate of Occupancy Issued rows have no FinalDate / FinalizeDate in DATA → FINAL_DATE stays missing.

After repair: Final 301 / 328 (91.8%); non-Final all empty.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 47 | 29 | 47 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 5 | 0 | 293 → 288 |
| FINAL_DATE | 9 | 1,012 | 697 → 1,700 |

STATUS_NORMALIZED after repair: Active 396; Final 328; Inactive 1,129; In Review 148.

Source date-order quirks remain on a small number of rows (FILE>PERMIT=4, PERMIT>FINAL=1) where portal ApplyDate / IssueDate / FinalDate themselves are out of order; the repair mirrors DATA rather than inventing chronology.

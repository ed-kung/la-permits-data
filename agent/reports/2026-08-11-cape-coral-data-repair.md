# Cape Coral (FL) data repair

Summary: Cape Coral was the first FL sample jurisdiction without a repair script after Jacksonville, Lee County, Sarasota County, Osceola County, Orlando, Charlotte County, Pasco County, and Miami-Dade County. The DATA payload is a Tyler EnerGov-style schema (`entity` / `details` / `fees`, optionally reviews). Upstream fields already match EnerGov dates almost perfectly: `FILE_DATE` = `ApplyDate` (100%), `PERMIT_DATE` = `IssueDate` whenever present, and Final `FINAL_DATE` = `FinalDate`. The repair fills the single null `STATUS_NORMALIZED` (`Awaiting Customer` → In Review) and clears **2** spurious `FINAL_DATE` values on Void/Denied rows where `FinalDate` is a case-closure stamp. Remaining Active/Final date gaps have no issuance or finalization dates in DATA.

## Jurisdiction selected

- Sample file: `MY_DATA_PATH/processed_data/permits_fl_sample.parquet`
- First `(JURISDICTION, STATE)` without `agent/scripts/{state}/data_repair_{state}_{city}.py`: **Cape Coral, FL**
- Sample size: **1,999** records
- Script: `agent/scripts/fl/data_repair_fl_cape_coral.py` (`data_repair`)

## DATA schemas (`INFERRED_SCHEMA`)

| Schema | n | Notes |
| --- | ---: | --- |
| `entity_fees` | 1,938 | entity + details + fees (+ contacts, processing_status) |
| `entity_fees_reviews` | 60 | plus reviews / holds / attachments / more_info |
| `entity_basic` | 1 | entity + details without fees |

Canonical field sources:

- `entity.CaseStatus` / `details.PermitStatus` → `STATUS_NORMALIZED`
- `entity.ApplyDate` (fallback `details.ApplyDate`) → `FILE_DATE`
- `entity.IssueDate` (fallback `details.IssueDate`) → `PERMIT_DATE`
- `entity.FinalDate` (fallback `details.FinalizeDate`) → `FINAL_DATE`

`ExpireDate` is a validity window, not a completion date. `processing_status` holds inspection request/schedule rows and does not supply a reliable finaled date beyond `FinalDate` / `FinalizeDate`. `entity.CaseStatus` and `details.PermitStatus` always agree in this sample.

## Findings by field

### STATUS_NORMALIZED

- Before: Final 1,712; Active 111; In Review 96; Inactive 79; missing **1**.
- Upstream mapping from `STATUS_ORIGINAL` already matches `CaseStatus` for every populated row (`closed`→Final, `issued`/`approved`→Active, review-pipeline labels→In Review, `void`/`expired`/`denied`→Inactive).
- The single null is `CaseStatus == "Awaiting Customer"` (not in the upstream mapper).
- Repair: **1 FILLED** (`Awaiting Customer` → In Review); **0 FIXED**.
- After: Final 1,712; Active 111; In Review 97; Inactive 79; missing **0**.

### FILE_DATE

- Before: **0 missing**. All 1,999 values match `entity.ApplyDate` at UTC calendar-day resolution (including 4 rows where details.ApplyDate crosses midnight vs entity due to timezone offset — FILE_DATE correctly follows entity).
- Repair: **0 FILLED**, **0 FIXED**.
- After: 100% coverage for every status bucket.

### PERMIT_DATE

- Before: 140 missing. All 1,859 present values match `entity.IssueDate` exactly at day resolution; whenever IssueDate exists, PERMIT_DATE is already filled.
- Remaining Active/Final gaps (not fillable — `Issued=False`, null IssueDate, no approval-date field elsewhere in DATA):
  - Active: **8** (7 `Approved`, 1 `Issued` shell `WEB19-05002`)
  - Final: **5** Closed shells (3 also lack FinalDate; 2 have FinalDate but never recorded IssueDate)
- Repair: **0 FILLED**, **0 FIXED**.
- After: Active **103/111 (92.8%)**; Final **1,707/1,712 (99.7%)**.

### FINAL_DATE

- Before: 289 missing. Among Final rows with a date, all **1,708** match `entity.FinalDate` / `details.FinalizeDate`.
- Four Closed Final rows lack FinalDate/FinalizeDate (one has an undetermined "Roof Final" inspection — not used as sign-off).
- Spurious `FINAL_DATE` on non-Final: **2** Inactive rows (`Void`, `Denied`) where EnerGov stamped `FinalDate` as case closure.
- Repair: **0 FILLED**; **2 FIXED** (cleared Void/Denied closure stamps).
- After: Final **1,708/1,712 (99.8%)**; Active / In Review / Inactive have **0**.

## Repair performance

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | ---: | ---: | ---: | ---: |
| STATUS_NORMALIZED | 1 | 0 | 1 | 0 |
| FILE_DATE | 0 | 0 | 0 | 0 |
| PERMIT_DATE | 0 | 0 | 140 | 140 |
| FINAL_DATE | 0 | 2 | 289 | 291 |

Coverage after repair (share non-null):

| Status | n | FILE_DATE | PERMIT_DATE | FINAL_DATE |
| --- | ---: | ---: | ---: | ---: |
| Active | 111 | 100% | 92.8% | 0% |
| Final | 1,712 | 100% | 99.7% | 99.8% |
| In Review | 97 | 100% | 3.1% | 0% |
| Inactive | 79 | 100% | 58.2% | 0% |

## Artifacts

- Repair script: `agent/scripts/fl/data_repair_fl_cape_coral.py`
- Repaired sample parquet: `AGENT_DATA_PATH/cape_coral_repaired_sample.parquet`

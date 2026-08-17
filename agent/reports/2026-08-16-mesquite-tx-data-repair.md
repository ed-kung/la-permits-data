# Mesquite (TX) data repair

**Summary:** Mesquite was the first TX jurisdiction in `permits_tx_sample.parquet` without a repair script (after Fort Bend County). All 1,999 rows are CivicPlus / EnerGov case payloads (`entity_core` 1,832; `entity_rich` 164; `entity_minimal` 3). STATUS_NORMALIZED lagged `entity.CaseStatus` on 71 rows (mostly Expired/Finaled still labeled Active, and CO In Review labeled Final). FILE_DATE already matches `ApplyDate` on every row. Repair filled 6 missing PERMIT_DATE values from `IssueDate` and 17 missing FINAL_DATE values from `FinalDate`/`FinalizeDate`, and cleared 4 spurious FINAL_DATE values on non-Final rows. Active PERMIT_DATE coverage is 100%; Final FINAL_DATE coverage is 99.3%.

## Scope

- Input: `MY_DATA_PATH/processed_data/permits_tx_sample.parquet`
- Jurisdiction: Mesquite, TX (first pair lacking `agent/scripts/{state}/data_repair_{state}_{city}.py`)
- Script: `agent/scripts/tx/data_repair_tx_mesquite.py`
- Artifact: `AGENT_DATA_PATH/repaired/permits_tx_mesquite_repaired.parquet`

## DATA schema

EnerGov-style nested object with `entity`, `details`, `contacts`, and `processing_status`. Variants differ only by optional fee / review extras:

| INFERRED_SCHEMA | n |
| --- | ---: |
| entity_core | 1,832 |
| entity_rich | 164 |
| entity_minimal | 3 |

Canonical source fields:

| Target field | Primary source | Fallback |
| --- | --- | --- |
| STATUS_NORMALIZED | `entity.CaseStatus` | — |
| FILE_DATE | `entity.ApplyDate` | — |
| PERMIT_DATE | `entity.IssueDate` | — |
| FINAL_DATE | `entity.FinalDate` | `details.FinalizeDate` |

`entity.CaseStatus` and `details.PermitStatus` agree on 1,994 / 1,999 rows; the 5 disagreements are `Issued` vs `Finaled` with no `FinalDate`, so CaseStatus is treated as authoritative.

## Field assessment

### STATUS_NORMALIZED

No missing values. Normalized status was built from lagged `STATUS_ORIGINAL`, so 71 rows disagree with live `CaseStatus`:

| CaseStatus | Prior STATUS_NORMALIZED | Corrected | n |
| --- | --- | --- | ---: |
| CO In Review | Final | In Review | 24 |
| Expired | Active / Final | Inactive | 19 |
| Finaled | Active / In Review | Final | 17 |
| Issued | In Review | Active | 4 |
| Void | In Review | Inactive | 4 |
| Awaiting Payment | Active | In Review | 1 |
| Denied | In Review | Inactive | 1 |
| Warranty | In Review | Final | 1 |

`Warranty` is treated as Final because the row already carries a completion `FinalDate`. `CO In Review` is In Review (CO process still open), not Final.

### FILE_DATE

Fully populated (0 missing). Every row matches `entity.ApplyDate` at calendar-day resolution (0 FILLED, 0 FIXED). Eighteen rows have an ApplyDate that differs by one calendar day between `entity` and `details` due to UTC offset; FILE_DATE follows `entity.ApplyDate`.

### PERMIT_DATE

294 missing before repair. Six Issued/Finaled rows whose `STATUS_ORIGINAL` lagged (`awaiting payment` / `in review` / `resubmission required`) had `IssueDate` available → FILLED. Remaining gaps: 7 Finaled rows with null `IssueDate`, plus pre-issuance In Review / Inactive rows. After status repair, Active has 308/308 (100%) and Final has 1,014/1,021 (99.3%).

### FINAL_DATE

998 missing before repair. Seventeen Finaled rows with `FinalDate`/`FinalizeDate` were FILLED. Four non-Final rows carried a spurious FINAL_DATE (2 Void, 1 Issued, 1 CO In Review remapped from Final) → FIXED (cleared). Seven legacy Finaled FDP stubs have empty final dates and empty `processing_status` → unfillable. After repair: Final 1,014/1,021 (99.3%); non-Final all empty.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 0 | 71 | 0 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 6 | 0 | 294 → 288 |
| FINAL_DATE | 17 | 4 | 998 → 985 |

STATUS_NORMALIZED after repair: Final 1,021; Inactive 530; Active 308; In Review 140.

After repair, by status:

- **FILE_DATE:** 100% for all statuses
- **PERMIT_DATE:** Active 308/308 (100%); Final 1,014/1,021 (99.3%)
- **FINAL_DATE:** Final 1,014/1,021 (99.3%); non-Final remain empty

Date-order violations after repair: FILE>PERMIT=8 (source ApplyDate after IssueDate by one day when late-UTC apply timestamps cross midnight vs midnight IssueDate); PERMIT>FINAL=0; FILE>FINAL=0.

## Not repairable

- 7 Finaled rows lack `IssueDate` → PERMIT_DATE stays missing.
- 7 Finaled rows lack `FinalDate`/`FinalizeDate` and have empty `processing_status` → FINAL_DATE stays missing.
- 8 FILE>PERMIT calendar-day inversions are present in the agency timestamps themselves and are left as-is.

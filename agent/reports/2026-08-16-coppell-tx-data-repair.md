# Coppell (TX) data repair

**Summary:** Coppell was the first TX jurisdiction in `permits_tx_sample.parquet` without a repair script (after Southlake). All 2,000 rows are CivicPlus / EnerGov payloads (`entity_core` 1,960; `entity_rich` 40). STATUS_NORMALIZED was missing only for `Comments Entered - Awaiting Re-submission` (10) → FILLED as In Review; all other rows already matched CaseStatus / PermitStatus. FILE_DATE and existing PERMIT_DATE / FINAL_DATE already matched portal ApplyDate / IssueDate / FinalDate. Repair cleared 6 spurious FINAL_DATE values on non-Final rows (2 Active Issued, 4 Inactive Void). After repair: Active PERMIT_DATE 99.2%; Final PERMIT_DATE 95.7%; Final FINAL_DATE 100%; non-Final FINAL_DATE empty.

## Scope

- Input: `MY_DATA_PATH/processed_data/permits_tx_sample.parquet`
- Jurisdiction: Coppell, TX (first pair lacking `agent/scripts/{state}/data_repair_{state}_{city}.py`)
- Script: `agent/scripts/tx/data_repair_tx_coppell.py`
- Artifact: `AGENT_DATA_PATH/repaired/permits_tx_coppell_repaired.parquet`

## DATA schema

EnerGov-style nested object. Two top-level key-set variants; both expose the same `entity` / `details` status and date fields:

| INFERRED_SCHEMA | n |
| --- | ---: |
| entity_core | 1,960 |
| entity_rich | 40 |

Canonical source fields:

| Target field | Primary source | Fallback |
| --- | --- | --- |
| STATUS_NORMALIZED | `details.PermitStatus` when Complete; else `entity.CaseStatus` | — |
| FILE_DATE | `entity.ApplyDate` | — |
| PERMIT_DATE | `entity.IssueDate` | — |
| FINAL_DATE | `entity.FinalDate` | `details.FinalizeDate` |

`CaseStatus` and `PermitStatus` agree on every sample row. `FinalDate` and `FinalizeDate` always agree at calendar-day resolution when both are present (1,019 rows).

## Field assessment

### STATUS_NORMALIZED

10 missing values, all with portal status `Comments Entered - Awaiting Re-submission` (unmapped in the original normalize step) → FILLED as In Review. No incorrect non-null values (0 FIXED).

| CaseStatus / PermitStatus | Prior STATUS_NORMALIZED | Corrected | n |
| --- | --- | --- | ---: |
| Comments Entered - Awaiting Re-submission | (missing) | In Review | 10 |

Other mappings already correct: Complete→Final, Issued→Active, Expired / Void / Denied→Inactive, In Review / Submitted / Submitted - Online / Pending Payment / On Hold / Stop Work Order→In Review.

### FILE_DATE

Fully populated (0 missing). Every row matches `entity.ApplyDate` at calendar-day resolution (0 FILLED, 0 FIXED).

### PERMIT_DATE

275 missing before and after repair (0 FILLED, 0 FIXED). Existing non-null PERMIT_DATE values already match `entity.IssueDate`. Unfillable gaps:

- 4 Active (`Issued`) rows with null IssueDate and `details.Issued=False`
- 44 Final (`Complete`) rows with null IssueDate and `details.Issued=False` (often contractor / registration cases that still carry FinalDate)
- Remaining gaps are pre-issuance In Review (120 of 122 before status fill; 130 of 132 after) or terminal Inactive without IssueDate

After repair: Active 515 / 519 (99.2%); Final 969 / 1,013 (95.7%).

### FINAL_DATE

981 missing before repair. Issues:

1. **Spurious non-Final FINAL_DATE:** 2 Active (Issued) and 4 Inactive (Void) rows carried portal FinalDate / FinalizeDate while status was not Complete → FIXED (cleared). Several are temporary food-event / rental registrations where FinalDate equals or follows IssueDate without a Complete status.
2. **Final already complete:** all 1,013 Complete rows already had FINAL_DATE matching FinalDate (0 FILLED needed).

After repair: Final 1,013 / 1,013 (100%); non-Final all empty. Missing count rises 981 → 987 solely from clearing the 6 spurious values.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 10 | 0 | 10 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 0 | 0 | 275 → 275 |
| FINAL_DATE | 0 | 6 | 981 → 987 |

STATUS_NORMALIZED after repair: Active 519; Final 1,013; Inactive 336; In Review 132.

Source date-order quirks remain on a small number of rows (FILE>PERMIT=10, PERMIT>FINAL=5, FILE>FINAL=2) where portal ApplyDate / IssueDate / FinalDate themselves are out of order; the repair mirrors DATA rather than inventing chronology.

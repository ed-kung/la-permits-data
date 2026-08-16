# Baytown (TX) data repair

Assessed Baytown permit sample fields against the EnerGov-style DATA JSON and wrote `agent/scripts/tx/data_repair_tx_baytown.py`. Status gaps for Requires Re-submit / Legacy Issued are fully filled; one Complete-as-Active mislabel is fixed; FILE_DATE was already complete; remaining Active/Final date gaps have no IssueDate or FinalDate in DATA.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_tx_sample.parquet` and walked (JURISDICTION, STATE) in order. Existing TX repair scripts covered Abilene through Bastrop County (plus several later cities). **Baytown** was the first pair without `agent/scripts/tx/data_repair_tx_baytown.py`.

Sample size: 2,000 rows.

## DATA schemas

Two top-level key-sets (same repairable `entity` / `details` fields):

| Schema | Keys | n |
| --- | --- | ---: |
| `entity_core` | contacts, details, entity, fees, processing_status | 1,951 |
| `entity_rich` | core + attachments, holds, more_info, reviews | 49 |

Canonical sources:

- `entity.CaseStatus` → `STATUS_NORMALIZED`
- `entity.ApplyDate` → `FILE_DATE`
- `entity.IssueDate` → `PERMIT_DATE`
- `entity.FinalDate` (else `details.FinalizeDate`) → `FINAL_DATE` (Final only)

## Field assessment

### STATUS_NORMALIZED

Before: Final 1,793; Inactive 87; Active 53; In Review 43; **missing 24**.

Missing rows were `Requires Re-submit` (15 → In Review) and `Legacy Issued` (9 → Active), both present in `CaseStatus` but unmapped upstream.

One incorrect value: STATUS_ORIGINAL `issued` / STATUS_NORMALIZED `Active` while `CaseStatus` / `PermitStatus` are `Complete` with a `FinalDate` → should be **Final**.

A few STATUS_ORIGINAL labels lag DATA (`requires re-submit` vs Issued; `issued` vs Under Inspection / Complete); repair trusts `CaseStatus`.

### FILE_DATE

Already populated for all 2,000 rows; every value matches `ApplyDate` at day resolution. No fills or fixes.

### PERMIT_DATE

Missing on 173 rows before repair. Ideal: populated for Active and Final.

- Fillable from `IssueDate`: 1 row (STATUS_ORIGINAL `requires re-submit` but `CaseStatus` Issued; status filled to Active).
- Legacy Issued (9) already had matching `PERMIT_DATE`.
- Remaining Active/Final gaps (53 Complete / Closed / Legacy Complete with `Issued=false` and null `IssueDate`) are not recoverable from DATA.

### FINAL_DATE

Missing on 234 rows before; 5 non-Final rows incorrectly carried a date (4 Void, 1 Incomplete Submittal) matching agency `FinalizeDate` stamps.

- 1 Final fill after status fix (Complete row above).
- 5 clears on non-Final.
- 32 Final rows still lack FINAL_DATE; DATA also has null `FinalDate` / `FinalizeDate` (mostly Legacy Complete).

## Repair performance

Script: `agent/scripts/tx/data_repair_tx_baytown.py`  
Artifact: `$AGENT_DATA_PATH/repaired/permits_tx_baytown_repaired.parquet`

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 24 | 1 | 24 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 1 | 0 | 173 → 172 |
| FINAL_DATE | 1 | 5 | 234 → 238 |

After repair:

- Status: Final 1,794; Active 62; In Review 57; Inactive 87 (no nulls).
- FILE_DATE: 2,000 / 2,000.
- PERMIT_DATE: Active 62/62 (100%); Final 1,741/1,794 (97.0%).
- FINAL_DATE: Final 1,762/1,794 (98.2%); 0 on non-Final.

Missing after rises for FINAL_DATE because five spurious non-Final dates were cleared and only one new Final date was filled.

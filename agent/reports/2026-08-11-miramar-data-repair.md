# Miramar (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script (parquet encounter order after Boca Raton) was Miramar (2,002 records). DATA splits into Tyler EnerGov `entity_fees_reviews` (1,451) and an older `legacy_application` portal (551). STATUS_NORMALIZED was already correct on all EnerGov rows; 248 legacy nulls were FILLED from application status labels (0 remaining nulls). FILE_DATE was already complete and matched ApplyDate / Application Received Date (0 changes). PERMIT_DATE already matched IssueDate wherever present; legacy rows and 146 Complete shells have no issuance timestamp (0 fills). FINAL_DATE gained **1,111 FILLED** from FinalDate or Passed final inspections (legacy PASS FINAL inspections included), raising Final coverage from 28.9% (454/1,573) to 89.1% (1,565/1,756).

## Scope

- Input: `MY_DATA_PATH/processed_data/permits_fl_sample.parquet`
- Jurisdiction: Miramar, FL (first `(JURISDICTION, STATE)` lacking `agent/scripts/{state}/data_repair_{state}_{city}.py` in parquet encounter order)
- Script: `agent/scripts/fl/data_repair_fl_miramar.py`
- Artifact: `AGENT_DATA_PATH/miramar_repaired_sample.parquet`

## DATA schemas (`INFERRED_SCHEMA`)

| Schema | Count | Distinguishing feature |
| --- | ---: | --- |
| `entity_fees_reviews` | 1,451 | EnerGov `entity` + `details` + `fees` + `processing_status` + reviews bundle |
| `legacy_application` | 551 | `application` / `application information` / `permit` / `inspection` |

## Field assessment

### STATUS_NORMALIZED

- Before: Final 1,573; null 248; Inactive 124; Active 37; In Review 20
- `entity_fees_reviews`: `CaseStatus` maps 1:1 to current STATUS_NORMALIZED (Complete→Final, Issued→Active, In Review / Submitted - Online→In Review, Withdrawn / Expired / Denied→Inactive). No incorrect values among these 1,451.
- `legacy_application`: upstream only normalized a subset of labels (e.g. COMPLETE / CLOSED sometimes Final, ACTIVE / OPEN→Active). **248 nulls FILLED** from `application information.general.Status` (fallback reference / application Status), including 180 COMPLETE / CLOSED→Final, review-pipeline ACTIVE subtypes→In Review / Active, and WITHDRAWN / EXPIRED / DENIED / ENTERED IN ERROR→Inactive.
- After: Final 1,756; Inactive 171; Active 41; In Review 34; null 0

### FILE_DATE

- Ideal: populated for all records.
- Sources: `entity.ApplyDate` / `details.ApplyDate`; legacy `Application Received Date`.
- All 2,002 rows already had FILE_DATE matching those sources at calendar-day resolution.
- 0 FILLED / 0 FIXED. After repair: 100% FILE_DATE for every STATUS_NORMALIZED class.

### PERMIT_DATE

- Ideal: populated for Active and Final.
- EnerGov: PERMIT_DATE already equals `IssueDate` on all 1,269 rows with an IssueDate (0 mismatches). Remaining Active/Final gaps are 146 Complete rows with `Issued=False` / null IssueDate — not fillable from DATA.
- Legacy: permit block exposes Status (FEE / COMPLETED / ISSUED / …) but **no issuance date** → all 551 PERMIT_DATE values stay null (22 Active + 462 Final after status repair).
- **0 FILLED + 0 FIXED.** After: Active 19/41 (46.3%); Final 1,148/1,756 (65.4%); In Review 0/34.

### FINAL_DATE

- Ideal: populated for Final.
- Before: 454/1,573 Final (28.9%); exclusively EnerGov rows whose `FinalDate` / `FinalizeDate` was populated. Legacy FINAL_DATE was entirely null.
- Repair: prefer FinalDate/FinalizeDate; else latest Passed `processing_status` description matching FINAL / FNL / CLOSEOUT (skip if before IssueDate); on legacy, latest PASS inspection whose type matches the same pattern.
- **1,111 FILLED + 0 FIXED** (753 EnerGov inspection fills + 359 legacy inspection fills; one inspection candidate predated IssueDate and was rejected).
- Not repairable: 87 EnerGov Final + 103 legacy Final with empty / non-final inspection history and no FinalDate.
- After: Final 1,565/1,756 (89.1%); non-Final FINAL_DATE all null. Chronology: PERMIT&lt;FILE 0; FINAL&lt;PERMIT 0.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 248 | 0 | 248 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 0 | 0 | 733 → 733 |
| FINAL_DATE | 1,111 | 0 | 1,548 → 437 |

Ideal-field coverage after repair (among non-null STATUS_NORMALIZED):

- FILE_DATE: 100% of Active / Final / In Review / Inactive
- PERMIT_DATE: 46.3% of Active; 65.4% of Final; 0% of In Review (no IssueDate)
- FINAL_DATE: 89.1% of Final

Post-repair checks: all STATUS_NORMALIZED non-null; FILE_DATE complete; FINAL_DATE only on Final; no PERMIT&lt;FILE or FINAL&lt;PERMIT inversions; remaining PERMIT gaps are legacy portal rows and Complete shells without IssueDate.

## Artifacts

- `agent/scripts/fl/data_repair_fl_miramar.py`
- `AGENT_DATA_PATH/miramar_repaired_sample.parquet`

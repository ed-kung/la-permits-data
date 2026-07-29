# Moorpark (CA) data repair

**Summary:** For the first sample jurisdiction lacking a repair script (Moorpark, CA; 2,000 rows), CaseStatus already mapped cleanly onto STATUS_NORMALIZED; 10 status corrections came from date overrides (9 issued-but-still-In-Review shells → Active; 1 Issued shell with a later FinalDate → Final). FILE_DATE already matched ApplyDate everywhere. PERMIT_DATE gained 5 fills from IssueDate; FINAL_DATE had 3 junk non-Final stamps cleared. After repair, FILE_DATE is 100%, Active PERMIT_DATE is 100%, Final PERMIT_DATE is 99.8% (1 Retaining Wall shell lacks IssueDate), and Final FINAL_DATE is 100%.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_ca_sample.parquet` and walked `(JURISDICTION, STATE)` in first-appearance order (unicode-normalized slugs). The first pair without `agent/scripts/{state}/data_repair_{state}_{city}.py` was **Moorpark, CA**.

## DATA schemas (`INFERRED_SCHEMA`)

Tyler EnerGov-style JSON under top-level `entity` / `details` / `contacts` / `fees` / `processing_status`, with an optional reviews bundle:

| Schema | n | Keys |
| --- | ---: | --- |
| `entity_fees` | 1,759 | entity, details, contacts, fees, processing_status |
| `entity_fees_reviews` | 236 | above + reviews, holds, attachments, more_info |
| `entity_basic` | 5 | entity, details, contacts, processing_status |

Canonical fields: `entity.CaseStatus` / `details.PermitStatus`, `ApplyDate`, `IssueDate`, `FinalDate` (fallback `details.FinalizeDate`). `processing_status` is empty for every sample row.

## Field assessment

### STATUS_NORMALIZED

Before: Active 827 / Final 510 / Inactive 519 / In Review 144 / missing 0.

`CaseStatus` × `STATUS_NORMALIZED` was a perfect 1:1 map (Issued→Active, Finaled→Final, Expired/Void/Withdrawn/Denied→Inactive, In Review/Submitted/Submitted-Online/On Hold→In Review). Corrections come only from date overrides:

- **In Review with IssueDate → Active (9):** CaseStatus still `In Review` / `Submitted` / `On Hold` while IssueDate is populated (STATUS_ORIGINAL lagged).
- **Issued with FinalDate strictly after IssueDate → Final (1):** BLR2023-1308 photovoltaic; CaseStatus still Issued but FinalDate 2023-08-08 after IssueDate 2023-04-05.

### FILE_DATE

Fully populated. Calendar-day match to `entity.ApplyDate` for all 2,000 rows. No fills/fixes.

### PERMIT_DATE

Missing on 221 rows. Of Active/Final-eligible shells, 5 had fillable IssueDate (3 Issued Active, 1 Finaled with IssueDate after FinalDate, 1 Submitted promoted to Active). Where both present, PERMIT_DATE already matched IssueDate at day resolution (1,779 / 1,779). One Finaled Retaining Wall row (BLR2022-0735) has FinalDate but null IssueDate → not fillable.

### FINAL_DATE

Missing on 1,486 rows. All 510 Finaled rows already had FINAL_DATE matching FinalDate/FinalizeDate. Four non-Final rows carried FINAL_DATE: one Issued shell with credible later FinalDate (promoted to Final, stamp retained); two Issued shells with same-day or inverted FinalDate and one Void closure stamp → cleared as junk.

## Repair performance

Script: `agent/scripts/ca/data_repair_ca_moorpark.py` (`data_repair`).

Artifact: `AGENT_DATA_PATH/repaired/permits_ca_moorpark_repaired.parquet`

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 0 | 10 | 0 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 5 | 0 | 221 → 216 |
| FINAL_DATE | 0 | 3 | 1,486 → 1,489 |

Status transitions: In Review→Active 9; Active→Final 1.

After repair:

- FILE_DATE: 2,000 / 2,000 (100%)
- PERMIT_DATE: Active 835 / 835 (100%); Final 510 / 511 (99.8%)
- FINAL_DATE: Final 511 / 511 (100%); cleared on non-Final
- Remaining ideal gaps: 1 Final missing PERMIT_DATE (Finaled Retaining Wall, no IssueDate); 0 Final missing FINAL_DATE

Source chronology quirks left as-is (ApplyDate after IssueDate on 24 rows; IssueDate after FinalDate on 2 Finaled rows; one parking IssueDate in 2028).

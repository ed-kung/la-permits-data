# Murrieta (CA) data repair

**Summary:** For the first sample jurisdiction lacking a repair script (Murrieta, CA; 2,000 rows), STATUS_NORMALIZED largely tracked `STATUS_ORIGINAL` / `CaseStatus` but mis-mapped all 13 `Estimate` shells to Final and left 42 issued review-pipeline shells as In Review. FILE_DATE already matched `ApplyDate` everywhere. After repair: 58 status fixes, 2 PERMIT_DATE fills, 1 FINAL_DATE fill and 6 junk FINAL_DATE clears. FILE_DATE is 100%, Active PERMIT_DATE is 100%, Final FINAL_DATE is 100%; 12 Final shells (mostly Complete occupancy/fire records) still lack IssueDate so PERMIT_DATE stays missing.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_ca_sample.parquet` and walked `(JURISDICTION, STATE)` in first-appearance order. The first pair without `agent/scripts/{state}/data_repair_{state}_{city}.py` was **Murrieta, CA** (after normalizing accented names such as La Cañada Flintridge).

## DATA schemas (`INFERRED_SCHEMA`)

Tyler EnerGov-style JSON under top-level `entity` / `details` / `contacts` / `fees` / `processing_status`, with an optional reviews bundle:

| Schema | n | Keys |
| --- | ---: | --- |
| `entity_fees` | 1,583 | entity, details, contacts, fees, processing_status |
| `entity_fees_reviews` | 417 | above + reviews, holds, attachments, more_info |

Canonical fields: `entity.CaseStatus` / `details.PermitStatus`, `ApplyDate`, `IssueDate`, `FinalDate` (fallback `details.FinalizeDate`). Unlike Simi Valley, Murrieta populates `processing_status` on 787 rows (inspection outcomes use `Pass` / `Failed` / etc.). Trade-specific final inspection Pass without `FinalDate` is not treated as permit completion.

## Field assessment

### STATUS_NORMALIZED

Before: Active 593 / Final 576 / In Review 452 / Inactive 379 / missing 0.

`CaseStatus` equals `PermitStatus` on 1,999 / 2,000 rows. Main errors:

- **Estimate → Final (13):** `STATUS_ORIGINAL=estimate` mapped to Final. Twelve have no IssueDate → In Review; one has IssueDate → Active.
- **Applied / Applied Online / In Plancheck with IssueDate left In Review (42):** IssueDate present (and `details.Issued=true`) while CaseStatus still in the review pipeline → Active.
- **Issued left Active despite completion evidence (3):** one with `PermitStatus=Finaled` and FinalizeDate; two with FinalDate strictly after IssueDate → Final.

Inactive labels (Expired, Expired - Plan Check, Void, Cancel) were already correct and sticky even when FinalDate is present as a closure stamp.

### FILE_DATE

Fully populated. Calendar-day match to `entity.ApplyDate` for all 2,000 rows. No fills/fixes.

### PERMIT_DATE

Missing on 600 rows. Two Active/Final-eligible shells had `IssueDate` but null PERMIT_DATE (one Issued, one Applied that becomes Active) → fillable. After status repair, Active PERMIT_DATE is complete. Where both present, PERMIT_DATE already matched IssueDate at calendar-day resolution. Twelve Final shells remain without IssueDate (11 Complete occupancy/fire, 1 Finaled occupancy inspection) → not fillable.

### FINAL_DATE

Missing on 1,429 rows. One Issued→Final shell had FinalizeDate but null FINAL_DATE → fillable. Five Expired and one Issued (FinalDate before IssueDate) carried junk FINAL_DATE → cleared. All Finaled / Complete shells already had FinalDate. Prefer `entity.FinalDate` over `details.FinalizeDate` (68 rows differ by timezone offset only).

## Repair performance

Script: `agent/scripts/ca/data_repair_ca_murrieta.py` (`data_repair`).

Artifact: `AGENT_DATA_PATH/repaired/permits_ca_murrieta_repaired.parquet`

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 0 | 58 | 0 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 2 | 0 | 600 → 598 |
| FINAL_DATE | 1 | 6 | 1,429 → 1,434 |

Status transitions: In Review→Active 42; Final→In Review 12; Active→Final 3; Final→Active 1.

After repair:

- FILE_DATE: 2,000 / 2,000 (100%)
- PERMIT_DATE: Active 633 / 633 (100%); Final 554 / 566 (97.9%)
- FINAL_DATE: Final 566 / 566 (100%); cleared on non-Final
- Remaining ideal gaps: 12 Active/Final missing PERMIT_DATE (Complete×11, Finaled×1, no IssueDate); 0 Final missing FINAL_DATE

Source chronology quirks left as-is (8 rows with FILE_DATE after PERMIT_DATE; 1 Final with PERMIT_DATE after FINAL_DATE).

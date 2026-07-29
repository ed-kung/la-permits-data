# Simi Valley (CA) data repair

**Summary:** For the first sample jurisdiction lacking a repair script (Simi Valley, CA; 2,000 rows), STATUS_NORMALIZED was driven by lagged `STATUS_ORIGINAL` rather than EnerGov `CaseStatus`, producing 104 status corrections (notably 28 `Estimate`→Final and 62 unissued `Approved`→Active). FILE_DATE already matched `ApplyDate` everywhere. PERMIT_DATE gained 9 fills from `IssueDate`; FINAL_DATE gained 6 fills and 6 fixes (including clearing junk closure stamps). After repair, FILE_DATE is 100%, Active/Final PERMIT_DATE is 99.9% (2 Will-Serve shells lack IssueDate), and Final FINAL_DATE is 100%.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_ca_sample.parquet` and walked `(JURISDICTION, STATE)` in first-appearance order. The first pair without `agent/scripts/{state}/data_repair_{state}_{city}.py` was **Simi Valley, CA**.

## DATA schemas (`INFERRED_SCHEMA`)

Tyler EnerGov-style JSON under top-level `entity` / `details` / `contacts` / `fees` / `processing_status`, with an optional reviews bundle:

| Schema | n | Keys |
| --- | ---: | --- |
| `entity_fees` | 1,905 | entity, details, contacts, fees, processing_status |
| `entity_fees_reviews` | 89 | above + reviews, holds, attachments, more_info |
| `entity_basic` | 6 | entity, details, contacts, processing_status |

Canonical fields: `entity.CaseStatus` / `details.PermitStatus`, `ApplyDate`, `IssueDate`, `FinalDate` (fallback `details.FinalizeDate`). `processing_status` is empty for every sample row.

## Field assessment

### STATUS_NORMALIZED

Before: Active 1,027 / Final 731 / Inactive 134 / In Review 107 / missing 1.

Main errors (CaseStatus vs normalized status):

- **Estimate → Final (28):** `STATUS_ORIGINAL=estimate` was mapped to Final despite no IssueDate/FinalDate. Should be In Review.
- **Approved without IssueDate → Active (62):** plan approval, not issuance. Should be In Review; 5 Approved with IssueDate correctly stay Active.
- **Finaled left Active/In Review (6):** CaseStatus already Finaled (and FinalDate present) while STATUS_ORIGINAL lagged (`issued` / `submitted online`).
- **Issued left In Review (5):** IssueDate present; STATUS_ORIGINAL still `submitted` / `submitted online`.
- **Expired left Active (1):** CaseStatus Expired, STATUS_ORIGINAL still `issued`.
- **Case Opened missing (1):** IssueDate present → Active.

### FILE_DATE

Fully populated. Calendar-day match to `entity.ApplyDate` / `details.ApplyDate` for all 2,000 rows. No fills/fixes.

### PERMIT_DATE

Missing on 277 rows. Of Active/Final-eligible shells, 9 had `IssueDate` but null PERMIT_DATE (5 Issued, 3 Approved, 1 Finaled) → fillable. Two Finaled Water Will-Serve Letter rows have FinalDate but null IssueDate → not fillable. Where both present, PERMIT_DATE already matched IssueDate.

### FINAL_DATE

Missing on 1,291 rows. Six Finaled rows had FinalDate/FinalizeDate but null FINAL_DATE → fillable. One Finaled row had FINAL_DATE one day earlier than FinalDate → fix to agency stamp. Four Inactive (Expired/Void) and one same-day Issued FinalDate carried junk FINAL_DATE → cleared. One Issued shell with FinalDate strictly after IssueDate was promoted to Final (stamp retained).

## Repair performance

Script: `agent/scripts/ca/data_repair_ca_simi_valley.py` (`data_repair`).

Artifact: `AGENT_DATA_PATH/repaired/permits_ca_simi_valley_repaired.parquet`

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 1 | 103 | 1 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 9 | 0 | 277 → 268 |
| FINAL_DATE | 6 | 6 | 1,291 → 1,290 |

Status transitions: Active→In Review 62; Final→In Review 28; Active→Final 6; In Review→Active 5; nan→Active 1; In Review→Final 1; Active→Inactive 1.

After repair:

- FILE_DATE: 2,000 / 2,000 (100%)
- PERMIT_DATE: Active 100%; Final 708 / 710 (99.7%)
- FINAL_DATE: Final 710 / 710 (100%); cleared on non-Final
- Remaining ideal gaps: 2 Active/Final missing PERMIT_DATE (Finaled Will-Serve, no IssueDate); 0 Final missing FINAL_DATE

Source chronology quirks left as-is (agency ApplyDate after IssueDate on 17 rows; IssueDate after FinalDate on 54 Finaled rows).

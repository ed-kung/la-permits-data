# Healdsburg (CA) data repair

**Summary:** Healdsburg was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. Its 2,000 Tyler EnerGov rows are driven by `entity.CaseStatus`, but online finaled shells (`Finaled - Online`) were left Active and unissued `Approved` shells were left Active. Repair corrects 260 statuses, fills 8 permit dates from `IssueDate`, and fills/fixes 45 final dates (including clearing Void/Expired closure stamps). After repair: FILE_DATE 100%, Active PERMIT_DATE 100%, Final PERMIT_DATE 95.9%, Final FINAL_DATE 99.6%.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_ca_sample.parquet` and walked `(JURISDICTION, STATE)` in first-appearance order. The first pair without `agent/scripts/{state}/data_repair_{state}_{city}.py` was **Healdsburg, CA**.

## DATA schemas (`INFERRED_SCHEMA`)

Tyler EnerGov-style JSON under top-level `entity` / `details` / `contacts` / `fees` / `processing_status`, with an optional reviews bundle:

| Schema | n | Keys |
| --- | ---: | --- |
| `entity_fees` | 1,855 | entity, details, contacts, fees, processing_status |
| `entity_fees_reviews` | 144 | above + reviews, holds, attachments, more_info |
| `entity_basic` | 1 | entity, details, contacts, processing_status |

Canonical fields: `entity.CaseStatus` / `details.PermitStatus`, `ApplyDate`, `IssueDate`, `FinalDate` (fallback `details.FinalizeDate`). `processing_status` is null/empty on 1,999 rows; one Finaled row has inspections (no Final* completion fallback needed beyond FinalDate).

Healdsburg CaseStatus labels (sample): Finaled 924, Issued 274, Finaled - Online 222, Issued - Online 212, Expired 136, Void 100, plus In Review / Approved / Requires Re-submittal online variants, On Hold, Withdrawn, Submitted - Online, Stop Work Order.

## Field assessment

### STATUS_NORMALIZED

Before: Final 919 / Active 735 / Inactive 240 / In Review 106 / missing 0.

Main errors (CaseStatus vs normalized status):

- **Finaled - Online → Active (222):** online finaled labels were never mapped to Final (`STATUS_ORIGINAL` often `finaled - online` or lagged `issued - online`). FinalDate present on all 222.
- **Finaled → Active (5):** CaseStatus already Finaled (FinalDate present) while `STATUS_ORIGINAL` lagged as `issued`.
- **Approved without IssueDate → Active (18):** plan approval, not issuance. Should be In Review.
- **Approved with FinalDate after IssueDate → Active (1):** credible completion stamp → Final.
- **Issued with FinalDate after IssueDate → Active (1):** stale Issued shell → Final.
- **Expired → Active (1):** CaseStatus Expired, `STATUS_ORIGINAL` still `issued`.
- **In Review / On Hold / Stop Work / Requires Re-submittal / Issued - Online with IssueDate → In Review (12):** IssueDate present → Active (issuance overrides review-pipeline labels).

### FILE_DATE

Fully populated. Calendar-day match to `entity.ApplyDate` / `details.ApplyDate` for all 2,000 rows. No fills/fixes.

### PERMIT_DATE

Missing on 270 rows. Where both present, PERMIT_DATE already matched IssueDate (1,730/1,730). Gaps:

- 8 rows with IssueDate but null PERMIT_DATE (2 Issued Active; 5 In Review→Active; 1 Issued - Online→Active) → fillable.
- 47 Active/Final after repair still lack IssueDate (45 Finaled + 2 Finaled - Online) → not fillable.
- In Review rows that carried PERMIT_DATE without staying In Review were promoted to Active (IssueDate present); unissued Approved rows keep PERMIT missing.

### FINAL_DATE

Missing on 848 rows. Final rows: 914/919 already matched FinalDate; 5 Finaled have null FinalDate → not fillable. Errors:

- 13 Finaled - Online and 4 Finaled (mislabeled Active) had FinalDate but null FINAL_DATE → fill after status fix.
- One Final row had `FINAL_DATE=2022-11-09` vs FinalDate `2022-11-07` → fix to agency stamp.
- One Finaled→Final row had `FINAL_DATE=2021-07-02` vs FinalDate `2024-07-22` → fix.
- 25 Inactive (23 Void / 2 Expired) and 1 Issued - Online Active carried junk FINAL_DATE closure/same-day stamps → cleared.

## Repair performance

Script: `agent/scripts/ca/data_repair_ca_healdsburg.py` (`data_repair`).

Artifact: `AGENT_DATA_PATH/repaired/permits_ca_healdsburg_repaired.parquet`

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 0 | 260 | 0 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 8 | 0 | 270 → 262 |
| FINAL_DATE | 17 | 28 | 848 → 857 |

Status after: Final 1,148 / Active 499 / Inactive 241 / In Review 112.

Status transitions: Active→Final 229; Active→In Review 18; In Review→Active 12; Active→Inactive 1.

After repair:

- FILE_DATE: 2,000 / 2,000 (100%)
- PERMIT_DATE: Active 499 / 499 (100%); Final 1,101 / 1,148 (95.9%)
- FINAL_DATE: Final 1,143 / 1,148 (99.6%); none on non-Final
- Remaining ideal gaps: 47 Active/Final missing PERMIT_DATE (Finaled/Finaled-Online, no IssueDate); 5 Final missing FINAL_DATE (Finaled, no FinalDate)

Source chronology quirks left as-is (agency ApplyDate after IssueDate on 108 rows; IssueDate after FinalDate on 1 Final row).

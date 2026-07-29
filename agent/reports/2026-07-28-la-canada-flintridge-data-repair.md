# La Cañada Flintridge (CA) data repair

**Summary:** La Cañada Flintridge was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. Its 2,000 Tyler EnerGov rows are driven by `entity.CaseStatus`, but five review-pipeline labels were never mapped into `STATUS_NORMALIZED` (145 nulls). Repair fills those as In Review, promotes 3 stale Issued/On Hold shells with credible FinalDate stamps to Final, and clears 240 junk FINAL_DATE closure stamps on non-Final rows. After repair: FILE_DATE 100%, Active/Final PERMIT_DATE 100%, Final FINAL_DATE 100%; no remaining ideal-coverage gaps.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_ca_sample.parquet` and walked `(JURISDICTION, STATE)` in first-appearance order. The first pair without `agent/scripts/{state}/data_repair_{state}_{city}.py` was **La Cañada Flintridge, CA** (slug `la_canada_flintridge`, ASCII-normalized ñ→n).

## DATA schemas (`INFERRED_SCHEMA`)

Tyler EnerGov-style JSON under top-level `entity` / `details` / `contacts` / `fees` / `processing_status`, with an optional reviews bundle:

| Schema | n | Keys |
| --- | ---: | --- |
| `entity_fees` | 1,816 | entity, details, contacts, fees, processing_status |
| `entity_fees_reviews` | 184 | above + reviews, holds, attachments, more_info |

Canonical fields: `entity.CaseStatus` / `details.PermitStatus`, `ApplyDate`, `IssueDate`, `FinalDate` (fallback `details.FinalizeDate`). `processing_status` is null/empty on all 2,000 rows.

CaseStatus labels (sample): Complete 905, Expired 298, Issued 213, Void 170, Pending Submittal of Requested Documents 72, Withdrawn 60, In Review 50, Submitted - Online 48, Plan Approval Expired 40, In Plan Check 33, Pending Invoice Payment 30, Pending Building Approval 26, In Screening 23, Requires Resubmittal 22, On Hold 7, Approved Pending Agency Clearances 2, Denied 1.

## Field assessment

### STATUS_NORMALIZED

Before: Final 905 / Inactive 569 / Active 213 / In Review 168 / missing 145.

Where CaseStatus was already mapped, STATUS_NORMALIZED matched exactly (no wrong non-null values). Gaps and overrides:

- **Unmapped → null (145):** `Pending Submittal of Requested Documents` (72), `Pending Building Approval` (26), `In Screening` (23), `Requires Resubmittal` (22), `Approved Pending Agency Clearances` (2). All are pre-issuance review pipeline → In Review.
- **Issued with FinalDate after IssueDate → Active (2):** credible completion stamp → Final.
- **On Hold with IssueDate and FinalDate after IssueDate → In Review (1):** same override → Final.

### FILE_DATE

Fully populated. Calendar-day match to `entity.ApplyDate` for all 2,000 rows. No fills/fixes.

### PERMIT_DATE

Missing on 595 rows (all In Review / Inactive / previously-null review statuses without IssueDate). Where both present, PERMIT_DATE already matched IssueDate (1,405/1,405). Active (213) and Final (905) already had 100% IssueDate coverage. After promoting the On Hold / Issued shells to Final, no Active/Final PERMIT fills were needed.

### FINAL_DATE

Missing on 852 rows. All 905 Complete→Final rows already matched FinalDate. Errors were junk stamps on non-Final rows:

- 236 Inactive (157 Void / 60 Withdrawn / 17 Plan Approval Expired / 2 Expired) carried case-closure FinalDate → clear.
- 5 Active Issued rows carried FinalDate (2 credible → status becomes Final and stamp kept; 3 same-day/inverted → clear).
- 1 In Review On Hold row had FinalDate after IssueDate → becomes Final (stamp kept).
- 1 Requires Resubmittal (null status) row had FinalDate without IssueDate → stays In Review; stamp cleared.

## Repair performance

Script: `agent/scripts/ca/data_repair_ca_la_canada_flintridge.py` (`data_repair`).

Artifact: `AGENT_DATA_PATH/repaired/permits_ca_la_canada_flintridge_repaired.parquet`

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 145 | 3 | 145 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 0 | 0 | 595 → 595 |
| FINAL_DATE | 0 | 240 | 852 → 1,092 |

Status after: Final 908 / Inactive 569 / In Review 312 / Active 211.

Status transitions: null→In Review 145; Active→Final 2; In Review→Final 1.

After repair:

- FILE_DATE: 2,000 / 2,000 (100%)
- PERMIT_DATE: Active 211 / 211 (100%); Final 908 / 908 (100%)
- FINAL_DATE: Final 908 / 908 (100%); none on non-Final
- Remaining ideal gaps: none

Source chronology quirks left as-is (agency ApplyDate after IssueDate on 3 rows; IssueDate after FinalDate on 1 Final row promoted from Issued).

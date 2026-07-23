# Philadelphia Data Repair Assessment

## Summary

Assessed the correctness of STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for 1,998 Philadelphia permit records by comparing field values against the raw DATA JSON column. Identified three distinct data schemas within the DATA column, with varying degrees of date and status information available. Wrote a repair function that fixes 84 STATUS_NORMALIZED values (71 filled, 13 fixed), fills 62 missing PERMIT_DATE values, and fills 6 missing FINAL_DATE values. FILE_DATE could not be repaired due to lack of source data in the DATA column for the affected records.

## Data Schemas

The Philadelphia DATA column contains three sub-schemas:

| Schema | Records | Description |
|--------|---------|-------------|
| **flat_upper** | 1,574 | Flat structure, uppercase keys (STATUS, PERMITISSUEDATE, PERMITCOMPLETEDDATE). No filing/creation date. |
| **nested** | 355 | Hierarchical with Status, Created Date, Issued Date, Completed Date, and nested Other Information. |
| **flat_mixed** | 69 | Mixed-case keys (StatusDescription, IssueDate, CompletedDate). No created date field. |

## Findings by Field

### STATUS_NORMALIZED

| Issue | Records | Resolution |
|-------|---------|------------|
| flat_mixed: all 69 records have NaN status | 69 | FILLED from parsed StatusDescription (Issued→Active, Completed→Final, Expired→Inactive, Ready For Issue→In Review, Withdrawn→Inactive) |
| nested: STATUS_NORMALIZED=Active but DATA.Status=Completed | 6 | FIXED to Final |
| nested: STATUS_NORMALIZED=Active but DATA.Status=Expired | 3 | FIXED to Inactive |
| nested: STATUS_NORMALIZED=Active, Status=Issued but Completed Date exists | 4 | FIXED to Final |
| flat_upper: "Amendment Application Incomplete" unmapped | 1 | FILLED as In Review |
| nested: "Amendment Applicant Revisions" unmapped | 1 | FILLED as In Review |

**Root cause**: The flat_mixed schema records were never processed for status normalization during initial data loading. The 13 fixed nested records had stale STATUS_ORIGINAL values (from the original data pull) that were not updated when the source system status changed.

### FILE_DATE

- **1,644 records missing** (1,574 flat_upper + 69 flat_mixed + 1 nested)
- **No repairs possible**: The flat_upper and flat_mixed schemas do not contain an application/filing date field. The single nested record (10057) has whitespace in all date fields.
- **Note**: The flat_upper schema has no application creation date — only PERMITISSUEDATE and PERMITCOMPLETEDDATE. This is a fundamental data gap from the source.

### PERMIT_DATE

| Issue | Records | Resolution |
|-------|---------|------------|
| flat_mixed Active/Final records with IssueDate available | 62 | FILLED from IssueDate |
| Remaining missing (In Review/Inactive, no issue date) | 16 | Cannot repair (appropriate to be missing) |

The 16 unfilled records are either permits not yet issued (In Review), inactive permits without issuance dates (Expired/Withdrawn), or a single Active record with corrupt whitespace data (10057).

### FINAL_DATE

| Issue | Records | Resolution |
|-------|---------|------------|
| nested records fixed to Final with Completed Date available | 6 | FILLED from Completed Date |
| Remaining missing Final records | 37 | No source available in DATA |
| Inactive records with FINAL_DATE populated | 157 | Left as-is (see note) |

**Note on Inactive records with FINAL_DATE**: 157 Inactive (Expired/Cancelled/Revoked) records have FINAL_DATE populated from PERMITCOMPLETEDDATE, which in this context represents the date the permit record was closed in the system, not construction completion. These are left unchanged as they reflect the source data.

## Repair Summary

| Field | FILLED | FIXED | Missing Before | Missing After |
|-------|--------|-------|----------------|---------------|
| STATUS_NORMALIZED | 71 | 13 | 71 | 0 |
| FILE_DATE | 0 | 0 | 1,644 | 1,644 |
| PERMIT_DATE | 62 | 0 | 78 | 16 |
| FINAL_DATE | 6 | 0 | 361 | 355 |

## Artifacts

- Repair script: `agent/scripts/phi_data_repair.py`

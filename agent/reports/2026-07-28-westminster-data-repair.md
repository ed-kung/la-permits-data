# Westminster (CA) data repair

**Summary:** Assessed Westminster's 2,000-row sample and wrote `agent/scripts/ca/data_repair_ca_westminster.py`. Westminster uses a Tyler EnerGov portal payload (`entity` + `details`). The repair fixes 53 stale statuses (28 Approved-without-issue Active→In Review; 16 issued Submitted/On Hold/Stop Work In Review→Active; 9 Issued/Approved with credible FinalDate Active→Final) and clears 1 spurious FINAL_DATE on an Expired row. FILE_DATE was already 100% correct. After repair, Active has 99.7% PERMIT_DATE, Final has 98.3% PERMIT_DATE and 99.4% FINAL_DATE. Remaining gaps are null/sentinel IssueDate or FinalDate in DATA.

## Jurisdiction selection

First `(JURISDICTION, STATE)` in `permits_ca_sample.parquet` without an existing `agent/scripts/{state}/data_repair_{state}_{city}.py`: **Westminster, CA**.

## DATA schema

All 2,000 rows have DATA. Inferred schemas:

| Schema | N | Notes |
| --- | --- | --- |
| `entity_fees` | 1,913 | `entity` + `details` + `contacts` + `fees` + `processing_status` |
| `entity_fees_reviews` | 86 | Above plus `reviews` / `holds` / `attachments` / `more_info` |
| `entity_basic` | 1 | Same as `entity_fees` but no `fees` key |

Canonical mappings from DATA:

- `entity.CaseStatus` / `details.PermitStatus` → `STATUS_NORMALIZED` (with IssueDate / credible FinalDate overrides)
- `entity.ApplyDate` (fallback `details.ApplyDate`) → `FILE_DATE`
- `entity.IssueDate` (fallback `details.IssueDate`) → `PERMIT_DATE`
- `entity.FinalDate` (fallback `details.FinalizeDate`) → `FINAL_DATE`

`CaseStatus` and `PermitStatus` always agree in this sample. `ExpireDate` is a validity window, not a completion date. `CompleteDate` / `ClosedDate` are unused (always null). Two IssueDate values use sentinel years (3017, 9018) and are treated as missing.

## Findings by field

### STATUS_NORMALIZED

Before: Final 1,009 / Inactive 488 / Active 375 / In Review 128 / missing 0.

Upstream CaseStatus→status mapping is mostly consistent (`Complete`→Final, `Issued`→Active, `Expired`/`Void`/`Withdrawn`→Inactive, review-pipeline labels→In Review). Issues:

1. **Approved without IssueDate (28):** coded Active despite `Issued=false` and null IssueDate. These are plan approvals, not issued permits → In Review.
2. **Issued/Approved with FinalDate > IssueDate (9):** CaseStatus still Issued/Approved while FinalizeDate is present → Final.
3. **Submitted / On Hold / Stop Work Order with IssueDate (16):** left In Review despite issuance → Active.

`Legacy` (3) correctly stays Final. Inactive labels remain sticky even when FinalDate is present.

### FILE_DATE

Already populated for all 2,000 rows and matches `entity.ApplyDate` at calendar-day resolution. No fills or fixes. 19 FILE>PERMIT chronology inversions exist in source DATA (ApplyDate after IssueDate) and are left as-is.

### PERMIT_DATE

When present, always matches IssueDate (after discarding sentinel years). No incorrect values to overwrite. Missing count stays 227: genuine null IssueDate in DATA (plus 2 sentinel years). Ideal-coverage gaps after status repair: 18 Active/Final rows (16 Complete, 1 Legacy, 1 Issued) with no usable IssueDate.

### FINAL_DATE

When present on Final rows, matches FinalDate/FinalizeDate. Issues:

1. **1 Expired row** carried FINAL_DATE from a case-closure FinalDate stamp → cleared (status stays Inactive).
2. **9 Active rows** already had FINAL_DATE matching a credible FinalDate; status promotion to Final makes those dates valid (no FINAL_DATE flag change).
3. **6 Final rows** (4 Complete, 2 Legacy) have null FinalDate/FinalizeDate → cannot fill.

6 PERMIT>FINAL inversions are present in source DATA and left as-is.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | --- | --- | --- |
| STATUS_NORMALIZED | 0 | 53 | 0 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 0 | 0 | 227 → 227 |
| FINAL_DATE | 0 | 1 | 987 → 988 |

Status transitions: Active→In Review 28; In Review→Active 16; Active→Final 9.

After repair coverage:

| Status | PERMIT_DATE | FINAL_DATE |
| --- | --- | --- |
| Active | 353 / 354 (99.7%) | 0 / 354 |
| Final | 1,001 / 1,018 (98.3%) | 1,012 / 1,018 (99.4%) |
| In Review | 0 / 140 | 0 / 140 |
| Inactive | 419 / 488 | 0 / 488 |

FILE_DATE: 2,000 / 2,000 (100%).

## Artifacts

- Script: `agent/scripts/ca/data_repair_ca_westminster.py` (`data_repair`)
- Repaired sample: `$AGENT_DATA_PATH/repaired/permits_ca_westminster_repaired.parquet`

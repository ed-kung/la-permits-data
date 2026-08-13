# New Smyrna Beach (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script was New Smyrna Beach. Its DATA is a Tyler EnerGov payload (`entity` / `details` / `fees` / `contacts` / `processing_status`, optionally `reviews` / `holds` / `attachments` / `more_info`). Repair fixed 27 stale `STATUS_NORMALIZED` values (25 Issued shells whose `PermitStatus` was already Complete with `FinalizeDate`, plus 2 `fees due` rows that had already been Issued), filled 25 missing Final dates from `details.FinalizeDate`, filled 2 missing `PERMIT_DATE` values on the newly Active rows, and cleared incorrect `PERMIT_DATE` / `FINAL_DATE` from In Review and other non-Final rows. `FILE_DATE` was already complete and correct. Two Active/Final rows still lack `PERMIT_DATE` because DATA has no `IssueDate`.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` and walked `(JURISDICTION, STATE)` in first-appearance order. New Smyrna Beach was the first pair without `agent/scripts/fl/data_repair_fl_new_smyrna_beach.py`.

## DATA shape

1,999 rows. Two top-level keysets (EnerGov base vs full):

| Schema | n | Notes |
| --- | ---: | --- |
| `energov_issued_finaled` | 1,176 | base keyset; issued + final |
| `energov_issued` | 305 | base; issued, no final |
| `energov_applied` | 169 | base; applied only |
| `energov_finaled` | 124 | base; final, no issued |
| `energov_full_issued` | 95 | full keyset; issued |
| `energov_full_applied` | 90 | full; applied only |
| `energov_full_issued_finaled` | 35 | full; issued + final |
| `energov_full_finaled` | 5 | full; final only |

Canonical sources:

| Field | DATA source |
| --- | --- |
| STATUS_NORMALIZED | `entity.CaseStatus` (fallback `details.PermitStatus`); Issued + Complete + final date → Final |
| FILE_DATE | `entity.ApplyDate` (fallback `details.ApplyDate`) |
| PERMIT_DATE | `entity.IssueDate` / `details.IssueDate` |
| FINAL_DATE | `entity.FinalDate` else `details.FinalizeDate` else passed final-ish `processing_status` inspection |

## Field assessments

### STATUS_NORMALIZED

Before: Final 1,142; Active 358; In Review 247; Inactive 252; **0 null**.

Incorrect values:
- **25** `CaseStatus=Issued` / `PermitStatus=Complete` with `details.FinalizeDate` still labeled Active (entity lagged details; `entity.FinalDate` blank so upstream never wrote `FINAL_DATE`).
- **2** `STATUS_ORIGINAL=fees due` while `CaseStatus=Issued` (and `IssueDate` set) still labeled In Review.

After: Final 1,167; Active 335; In Review 245; Inactive 252; **0 null**. Flags: **0 FILLED, 27 FIXED**.

### FILE_DATE

Before: **0 missing**. Every value equals `entity.ApplyDate` at day resolution (1,999/1,999). No fills or fixes. (`details.ApplyDate` can be +1 calendar day from UTC offset; entity is canonical.)

After coverage: 100% for all status classes.

### PERMIT_DATE

Before: 391 missing. When present, values matched `IssueDate` (1,608/1,608, 0 mismatches).

Repairs:
- **2 FILLED** — the fees-due→Active rows that already had `IssueDate`.
- **12 FIXED** — cleared leftover `PERMIT_DATE` on remaining In Review rows (Fees Due / On Hold / Resubmittal Required / Stop Work Order) that still carried an IssueDate stamp.

Not fillable: 1 Active (`ELER-00250-2024`, CaseStatus Issued but `Issued=false` and no IssueDate) and 1 Final (`TREE22-0252`, Complete with FinalDate but no IssueDate).

Flags: **2 FILLED, 12 FIXED**. After: Active 334/335 (99.7%); Final 1,166/1,167 (99.9%); In Review 0/245.

One pre-existing `FILE_DATE` > `PERMIT_DATE` day inversion remains (agency stamp); not rewritten.

### FINAL_DATE

Among Final rows, all 1,142 Complete rows already matched `entity.FinalDate` (== `details.FinalizeDate`).

Repairs:
- **25 FILLED** — Issued→Final upgrades filled from `details.FinalizeDate`.
- **150 FIXED** — cleared `FINAL_DATE` on non-Final rows (9 Active Issued shells with FinalDate, 4 In Review Fees Due, 137 Inactive Void/Withdrawn).

After: Final 1,167/1,167 (100%); non-Final 0%. Four `PERMIT_DATE` > `FINAL_DATE` day inversions remain on agency stamps; not rewritten.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 0 | 27 | 0 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 2 | 12 | 391 → 401 |
| FINAL_DATE | 25 | 150 | 707 → 832 |

Ideal-coverage gaps remaining:

- FILE_DATE: **none**
- Active/Final missing PERMIT_DATE: **2** (no IssueDate in DATA)
- Final missing FINAL_DATE: **none**
- STATUS_NORMALIZED: **none**

(`PERMIT_DATE` / `FINAL_DATE` missing counts rose because incorrect non-Final values were cleared.)

## Artifacts

- Repair script: `agent/scripts/fl/data_repair_fl_new_smyrna_beach.py`
- Repaired sample: `$AGENT_DATA_PATH/repaired/permits_fl_new_smyrna_beach_repaired.parquet`

# Oakland Park (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script was Oakland Park. DATA is a Tyler EnerGov payload (`entity` / `details` / `fees` / `processing_status`, optionally `reviews`/`holds`/`attachments`/`more_info`). Repair filled 32 null `STATUS_NORMALIZED` values (`Issued- COED` / `Issued - CC` → Final), upgraded 1 lagged Issued→Final shell, cleared 8 spurious In Review `PERMIT_DATE` values and 65 spurious non-Final `FINAL_DATE` values, and filled 1 Final `FINAL_DATE` from `FinalizeDate`. `FILE_DATE` was already correct on every row. Fifteen Active/Final shells still lack `PERMIT_DATE` because DATA has no `IssueDate`.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` and walked `(JURISDICTION, STATE)` pairs in first-seen order. Oakland Park was the first pair without `agent/scripts/fl/data_repair_fl_oakland_park.py`.

## DATA shape

| Schema | n |
| --- | ---: |
| `energov_issued_finaled` | 1,122 |
| `energov_applied` | 426 |
| `energov_issued` | 217 |
| `energov_full_applied` | 120 |
| `energov_full_issued` | 55 |
| `energov_finaled` | 43 |
| `energov_full_issued_finaled` | 14 |
| `energov_full_finaled` | 3 |

Canonical sources:

| Field | DATA source |
| --- | --- |
| STATUS_NORMALIZED | `entity.CaseStatus` (fallback `details.PermitStatus`) |
| FILE_DATE | `entity.ApplyDate` (fallback `details.ApplyDate`) |
| PERMIT_DATE | `entity.IssueDate` (fallback `details.IssueDate`) |
| FINAL_DATE | `entity.FinalDate` / `details.FinalizeDate`; else passed FINAL-ish `processing_status` inspection |

## Field assessments

### STATUS_NORMALIZED

Before: Final 817; In Review 449; Inactive 358; Active 344; null 32.

Cause of nulls: upstream never mapped certificate statuses `Issued- COED` (28) and `Issued - CC` (4). Both always carry `IssueDate` + `FinalDate` / `FinalizeDate` in DATA → Final.

One additional lag: `CaseStatus=Issued` while `PermitStatus=Final` and `FinalizeDate` present → FIXED Active→Final.

Other CaseStatus values already matched the intended map (`Final`→Final, `Issued`→Active, `In Review`/`Submitted*`/`On Hold`/`Stop Work Order`→In Review, `Expired`/`Void`/`Denied`→Inactive).

After: Final 850; In Review 449; Inactive 358; Active 343; **0 null**. Flags: **32 FILLED, 1 FIXED**.

### FILE_DATE

Missing on 0/2,000. Every row matches `entity.ApplyDate` at UTC calendar-day resolution (`str[:10]`). Flags: **0 FILLED, 0 FIXED**.

### PERMIT_DATE

Before: missing 592. Present values already matched `entity.IssueDate` / `details.IssueDate`.

Repairs:

- **8** In Review rows with leftover `IssueDate` → FIXED clear (status not yet issued in the normalized sense).

Not filled: Inactive gaps (136) have no `IssueDate` in DATA; 14 Final + 1 Active shells have `Issued=False` and blank `IssueDate`.

After: missing 600. Ideal Active/Final coverage 1,178/1,193 (98.7%). Flags: **0 FILLED, 8 FIXED**.

### FINAL_DATE

Before: present on all 817 Final + 32 COED/CC null-status shells; also spuriously present on 33 Active, 24 Inactive, and 8 In Review.

Repairs:

- **1** Issued→Final lag shell → FILLED from `details.FinalizeDate`
- **65** non-Final shells → FIXED clear of `FinalDate` / `FinalizeDate` copies (Active FinalDate often precedes IssueDate — not a true finalization)

After: Final 850/850 (100%); non-Final 0. Flags: **1 FILLED, 65 FIXED**.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 32 | 1 | 32 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 0 | 8 | 592 → 600 |
| FINAL_DATE | 1 | 65 | 1,086 → 1,150 |

## Artifacts

- Repair script: `agent/scripts/fl/data_repair_fl_oakland_park.py` (`data_repair`)
- Repaired sample: `AGENT_DATA_PATH/repaired/permits_fl_oakland_park_repaired.parquet`

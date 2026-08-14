# Southwest Ranches-Lauderdale-by-the-Sea (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script was **Southwest Ranches-Lauderdale-by-the-Sea**. DATA is a CitizenServe-style portal payload (`Status:`, `Permit Details`, `Reviews`, `Inspections`) shared by both towns. Upstream left 54 `STATUS_NORMALIZED` null for on-hold / pending / abandoned labels (53 filled; 1 blank shell stays null) and promoted 8 issued pending rows to Active. `FILE_DATE` usually stored the latest Review Completion instead of the earliest Review Start (997 rewritten, 14 post-issue cleared, 11 filled). `PERMIT_DATE` already matched `Permit Details["Issue Date:"]` wherever present (0 changes). `FINAL_DATE` was missing on every row; filled from latest Approved/Passed inspection for Closed/Final rows (1,179/1,197 = 98.5%). After repair: FILE_DATE 58.6%; Active/Final PERMIT_DATE 1,569/1,583 (99.1%); Final FINAL_DATE 98.5%.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` and walked `(JURISDICTION, STATE)` pairs in first-seen order. Southwest Ranches-Lauderdale-by-the-Sea was the first pair without `agent/scripts/fl/data_repair_fl_southwest_ranches_lauderdale_by_the_sea.py`.

## DATA shape

All 2,000 rows share the same CitizenServe portal shell. Two key-set variants:

| Schema prefix | n | Role |
| --- | ---: | --- |
| `portal_form` | 1,660 | Contractor / building-type extras (`Builder`, `Electrician`, `Square Feet`, …) |
| `portal_core` | 340 | Minimal colon-key shell |

Suffixes (`_issued_finaled`, `_issued`, `_finaled`, `_applied`, `_status_only`) mark which canonical dates are recoverable. Dominant schema: `portal_form_issued_finaled` (1,168).

Canonical sources:

| Field | DATA source |
| --- | --- |
| STATUS_NORMALIZED | `Status:` (`Closed`→Final, `Issued`/`Approved`→Active, review/on-hold/pending→In Review unless Issue Date present→Active, `Voided`/`Expired`/`Cancelled`/`Withdrawn`/`Abandoned/ Voided Permit`→Inactive) |
| FILE_DATE | Earliest Review Start ≤ Issue; else earliest Review Completion ≤ Issue (no Application Intake tasks in sample) |
| PERMIT_DATE | `Permit Details["Issue Date:"]` (top-level `Issue Date` always null; no `01/01/2000` sentinels) |
| FINAL_DATE | Latest Approved/Passed inspection date (any trade type), floored at Issue when present |

## Field assessments

### STATUS_NORMALIZED

Before: Final 1,197; Active 378; Inactive 294; In Review 77; **54 null**.

| Status: | n | Upstream STATUS_NORMALIZED | Assessment |
| --- | ---: | --- | --- |
| Closed | 1,197 | Final | Correct |
| Issued | 360 | Active | Correct |
| Voided | 146 | Inactive | Correct |
| Expired | 89 | Inactive | Correct |
| Cancelled | 57 | Inactive | Correct |
| Online Application Received | 50 | In Review | Correct |
| Under Review | 27 | In Review | Correct |
| Approved | 18 | Active | Correct |
| On hold due to missing paperwork | 25 | null | Fill → In Review |
| On hold due to missing payment | 17 | null | Fill → In Review (2 with Issue Date → Active) |
| Pending Zoning/Engineering Final | 6 | null | Fill → Active (all issued) |
| Pending Engineering / Zoning | 2 / 2 | null | Fill → In Review |
| Abandoned/ Voided Permit | 1 | null | Fill → Inactive |
| Withdrawn | 2 | Inactive | Correct |
| (blank) | 1 | null | No workflow / no Issue → stays null |

Flags: **53 FILLED, 0 FIXED**. After: Final 1,197; Active 386; Inactive 295; In Review 121; **1 null**.

### FILE_DATE

Missing on 825/2,000 before. When present, calendar day usually matched latest Review Completion (~900 of rewritten rows), not earliest Review Start. No Application Intake review tasks exist.

| Repair action | n |
| --- | ---: |
| FIXED to earliest Review Start/Completion (≤ Issue) | 997 |
| Cleared post-issue FILE with no application source | 14 |
| FILLED from Reviews | 11 |
| Still missing (empty / undated Reviews) | 828 |

After: **1,172/2,000 (58.6%)** populated; 0 `FILE_DATE > PERMIT_DATE` inversions. Coverage is moderate because many Voided/Cancelled/Online Application shells have empty Reviews.

### PERMIT_DATE

Missing on 312/2,000 before. Every populated `PERMIT_DATE` already matched `Permit Details["Issue Date:"]`. Top-level `Issue Date` is null on all rows. No sentinel Issue Dates in this sample.

Still missing after repair: 312 rows — Inactive/In Review shells without Issue Date (expected), plus **10 Approved Active** and **4 Closed Final** shells with blank Issue Date (not recoverable from DATA). Active/Final coverage: **1,569/1,583 (99.1%)**. Flags: **0 FILLED, 0 FIXED**.

### FINAL_DATE

Missing on 2,000/2,000 before. Portal inspection types are only trade labels (`Structural`, `Electrical`, `Plumbing`, …) with no Final*/CO types; Closed rows with inspections end in Approved.

| Repair action | n |
| --- | ---: |
| FILLED from latest Approved/Passed inspection (Final only; floored at Issue) | 1,179 |

Final rows still missing FINAL_DATE (18): Closed shells with empty Inspections or no Approved/Passed stamp. Ideal Final coverage: **1,179/1,197 (98.5%)**. Non-Final rows keep FINAL_DATE cleared. 0 `PERMIT_DATE > FINAL_DATE` inversions.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 53 | 0 | 54 → 1 |
| FILE_DATE | 11 | 1,011 | 825 → 828 |
| PERMIT_DATE | 0 | 0 | 312 → 312 |
| FINAL_DATE | 1,179 | 0 | 2,000 → 821 |

Coverage after repair: FILE_DATE 58.6% all statuses; Active/Final PERMIT_DATE 1,569/1,583 (99.1%); Final FINAL_DATE 1,179/1,197 (98.5%).

## Artifacts

- Repair script: `agent/scripts/fl/data_repair_fl_southwest_ranches_lauderdale_by_the_sea.py` (`data_repair`)
- Repaired sample: `$AGENT_DATA_PATH/repaired/permits_fl_southwest_ranches_lauderdale_by_the_sea_repaired.parquet`

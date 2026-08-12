# Manatee County (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script (parquet encounter order after Deerfield Beach / prior FL batch) was **Manatee County** (1,997 records). DATA is Accela Citizen Access (`accela` 1,990; blank-status `accela_shell` 7). STATUS_NORMALIZED: 80 FILLED + 160 FIXED (nulls 87→7). FILE_DATE already matched `DATA.date` on every row (0 changes). PERMIT_DATE: 778 FILLED from Permit Issuance / Application Issue Permit / more_details Permit Issued Date (Active 100%; Final 89.3%). FINAL_DATE: 1,248 FILLED + 3 FIXED (Final coverage 0.8%→99.9%).

## Scope

- Input: `MY_DATA_PATH/processed_data/permits_fl_sample.parquet`
- Jurisdiction: Manatee County, FL (first `(JURISDICTION, STATE)` lacking `agent/scripts/{state}/data_repair_{state}_{city}.py` in parquet encounter order)
- Script: `agent/scripts/fl/data_repair_fl_manatee_county.py`
- Artifact: `AGENT_DATA_PATH/manatee_county_repaired_sample.parquet`

## DATA schemas (`INFERRED_SCHEMA`)

| Schema | Count | Distinguishing feature |
| --- | ---: | --- |
| `accela` | 1,990 | Top-level `status`, `date`, `tasks`, `search_data`, `more_details`, `inspections` (always null in sample) |
| `accela_shell` | 7 | Same key set, but blank `status` / `search_data.Status` (misc shells) |

Task event keys use trailing spaces (`"Marked as "`, `" on "`); repair parses via normalized key match and HTML fallback.

## Field assessment

### STATUS_NORMALIZED

- Before: Final 1,141; Active 387; In Review 229; Inactive 153; null 87
- Canonical source: `DATA.status` (fallback `search_data.Status`). Upstream `STATUS_ORIGINAL` is often a stale earlier Accela state (e.g. `permit issued` while current status is `Closed`).
- **FILLED (80):** Pre-Acceptance Review→In Review (35); Review Verification→In Review (12); Awaiting Required Documents→In Review (11); Canceled→Inactive (6); Closed→Final (6); More Info Required w/ issuance→Active (4); Inspection Passed→Active (3); plus Permit Issued / Work Started / Pending Closure (3).
- **FIXED (160):** Active→Final on Closed (86) and related completion states; In Review→Active on Permit Issued (33) / Inspection Passed (2); In Review→Final on Closed/Complete (22); mislabeled Canceled/Expired→Inactive (13); Approved extensions Active→In Review (2).
- Post-issuance `More Info Required` upgraded to Active when a `Permit Issuance`/`Issued` event exists.
- After: Final 1,258; Active 336; In Review 224; Inactive 172; null 7 (blank-status shells)

### FILE_DATE

- Ideal: populated for all records.
- Source: top-level `date` (equals `search_data.Date`).
- Already correct on all 1,997 rows. **0 FILLED / 0 FIXED.**
- After: 100% coverage for every status (including shells).

### PERMIT_DATE

- Ideal: populated for Active and Final; not for unissued In Review.
- Before: missing on 1,252 / 1,997 (62.7%), including 238 Active and 580 Final.
- Sources (priority): earliest `Permit Issuance` marked `Issued`; else `Application` marked `Issue Permit`; else earliest `Permit Issued Date*` under `more_details.Application Information` (excluding expiration fields).
- **778 FILLED + 0 FIXED.** Existing populated PERMIT_DATE values already matched task/md sources.
- After: Active 336/336 (100%); Final 1,124/1,258 (89.3%); In Review 0/224; Inactive 63/172.
- Not repairable: 133 `Complete` Permit Re-Review rows and 1 `Complete - Sent to Clerk` have no issuance fields (workflow completes plan re-review, not a new issuance).

### FINAL_DATE

- Ideal: populated for Final.
- Before: missing on 1,988 / 1,997 (99.5%); only 9 Final rows had a value, and 3 of those were earlier than the Closure task date.
- Sources: latest of Closure (`Certificate of Completion Issued` / `Issue Certificate of Occupancy` / `Issue Certificate of Completion` / `Closed`); Inspection (`Inspection Passed and CofC Issued` / `Final Inspection Passed` / pending-closure variants); Construction (`Work Completed`); else Plan Re-Review Verification `Re-Review Complete`; else Fiscal Processing Complete.
- **1,248 FILLED + 3 FIXED** (stale Closed FINAL_DATE overwritten from Closure/Inspection events).
- After: Final 1,257/1,258 (99.9%); non-Final FINAL_DATE all null.
- Not repairable: 1 Closed Temporary Certificate of Occupancy with no dated completion event.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 80 | 160 | 87 → 7 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 778 | 0 | 1,252 → 474 |
| FINAL_DATE | 1,248 | 3 | 1,988 → 740 |

Ideal-field coverage after repair:

- FILE_DATE: 100% of all statuses
- PERMIT_DATE: 100% of Active; 89.3% of Final; 0% of In Review
- FINAL_DATE: 99.9% of Final; 0% of non-Final

Post-repair checks: PERMIT_DATE > FINAL_DATE inversions = 0; In Review carries no PERMIT_DATE; only remaining STATUS nulls are the 7 blank-status shells.

## Artifacts

- `agent/scripts/fl/data_repair_fl_manatee_county.py`
- `AGENT_DATA_PATH/manatee_county_repaired_sample.parquet`

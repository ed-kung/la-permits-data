# Farmers Branch (TX) data repair

**Summary:** Farmers Branch was the first TX sample jurisdiction lacking a repair script. Its CivicPlus/EnerGov `DATA` JSON has two key-set variants (`entity_core`, `entity_rich`) sharing the same `entity`/`details` fields. Repairing from `CaseStatus`, `ApplyDate`, `IssueDate`, and `FinalDate`/`FinalizeDate` filled all 126 missing statuses, fixed 32 stale statuses, filled 9 missing permit dates and 32 missing final dates, corrected 1 wrong final date, and cleared 139 spurious `FINAL_DATE` values on non-Final rows. `FILE_DATE` was already complete and correct. Remaining gaps are structural: 30 Complete CO/utility-release rows with no `IssueDate`, 5 Complete rows with no final timestamp, and 1 Active inspection-code rental with no `IssueDate`.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_tx_sample.parquet` and walked `(JURISDICTION, STATE)` pairs in order. Existing `agent/scripts/tx/data_repair_tx_*.py` scripts cover Abilene through Ellis County; **Farmers Branch** is the first without a script (2,000 sample rows).

## DATA schema

| INFERRED_SCHEMA | n |
| --- | ---: |
| `entity_core` (contacts, details, entity, fees, processing_status) | 1,836 |
| `entity_rich` (+ attachments, holds, more_info, reviews) | 164 |

Canonical sources:

| Field | Source |
| --- | --- |
| `STATUS_NORMALIZED` | `entity.CaseStatus` |
| `FILE_DATE` | `entity.ApplyDate` |
| `PERMIT_DATE` | `entity.IssueDate` |
| `FINAL_DATE` (Final only) | `entity.FinalDate`, else `details.FinalizeDate` |

`processing_status` is null on every sample row (no inspection-date fallback).

## Findings by field

### STATUS_NORMALIZED

Before repair: Final 1,380 / Active 231 / Inactive 160 / In Review 103 / **missing 126**.

Missing statuses were unmapped `STATUS_ORIGINAL` values that already appear cleanly in `CaseStatus`:

| STATUS_ORIGINAL | Expected | n |
| --- | --- | ---: |
| closed - nir | Final | 86 |
| requires resubmittal | In Review (or Active if CaseStatus advanced) | 36 |
| pending - mep contractors | In Review | 2 |
| pending - escalated to code enforcement | In Review | 1 |
| inspection - code | Active | 1 |

Additionally, 39 rows had `STATUS_ORIGINAL` lagging `CaseStatus` (e.g. `issued`/`expired`/`in review` while portal status is already `Complete`, `Canceled`, or `Issued`). That produced 32 incorrect `STATUS_NORMALIZED` values.

**After repair:** Final 1,490 / Active 223 / In Review 133 / Inactive 154 / missing 0. Flags: **126 FILLED**, **32 FIXED**.

### FILE_DATE

All 2,000 rows already had `FILE_DATE`, and every value matched `entity.ApplyDate` at calendar-day resolution. **0 FILLED / 0 FIXED.**

### PERMIT_DATE

Ideal: populated for Active and Final.

- Active/Final rows with `IssueDate` already matched `PERMIT_DATE` when both were present (0 day mismatches).
- 9 rows gained a `PERMIT_DATE` once status was corrected to Active/Final (or CaseStatus already carried an `IssueDate` under a previously null/In Review label) → **9 FILLED**.
- **30 Final** rows remain without `PERMIT_DATE`: Complete Certificate of Occupancy / Temporary Release of Utilities / Clean & Show Utility Release cases with `Issued=False` and null `IssueDate` (no issuance timestamp in DATA).
- **1 Active** row (`CEP24-0606`, Inspection - Code / Single-Family Rental) has no `IssueDate`.

After repair: Active 222/223 (99.6%), Final 1,460/1,490 (98.0%).

### FINAL_DATE

Ideal: populated for Final; absent otherwise.

- 15 Complete rows had missing `FINAL_DATE` despite a portal final timestamp; after status remaps (esp. Closed - NIR → Final and Complete lag fixes), **32 FILLED**.
- **1 FIXED** overwrite: `PW-ROW2401-0005` had `FINAL_DATE=2024-02-28` while `FinalDate`/`FinalizeDate` were `2024-07-23` (row also reclassified to Final).
- **139 FIXED** clears of spurious `FINAL_DATE` on non-Final rows (Void/Expired/Canceled/Issued/etc.).
- **5 Final** rows still lack a final timestamp (3 Right-of-Way utilities, 1 residential re-roof, 1 banner/temporary sign) — both `FinalDate` and `FinalizeDate` null.

After repair: Final 1,485/1,490 (99.7%); Active/In Review/Inactive all 0%.

## Repair script

- Script: `agent/scripts/tx/data_repair_tx_farmers_branch.py`
- Entry point: `data_repair(df)`
- Artifact: `AGENT_DATA_PATH/repaired/permits_tx_farmers_branch_repaired.parquet`

### Performance (sample n=2,000)

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 126 | 32 | 126 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 9 | 0 | 271 → 262 |
| FINAL_DATE | 32 | 140 | 408 → 515 |

`FINAL_DATE` missing count rises because clearing invalid non-Final dates outweighs fills; that is intentional.

## Not repairable from DATA

1. Complete CO / utility-release shells with no `IssueDate` (~30) — no permit issuance date exists.
2. Five Complete permits with null `FinalDate`/`FinalizeDate`.
3. One Active inspection-code rental with null `IssueDate`.

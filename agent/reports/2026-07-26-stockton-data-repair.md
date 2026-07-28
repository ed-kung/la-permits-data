# Stockton (CA) data repair

**Summary:** Stockton was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. Assessed and repaired `STATUS_NORMALIZED`, `FILE_DATE`, `PERMIT_DATE`, and `FINAL_DATE` from the Accela Citizen Access `DATA` JSON. Status is now fully populated (**FILLED 5 · FIXED 28**): mis-normalized Estimate / expired / Finaled / Issued rows were corrected, and five null-status Over Time Inspection Request rows were filled from task marks. `FILE_DATE` already matched `DATA.date` for all 2,001 rows (no changes). `PERMIT_DATE` missingness fell from **1,819 → 516** (**FILLED 1,303**) using Issued / Re-Issued task events and legacy `PERMIT MASTER` Issue / Reissue dates. `FINAL_DATE` missingness fell from **1,469 → 847** (**FILLED 627 · FIXED 9**), filling from Inspections / Finaled, Closed / Closed, and `Permit Status Date`, and clearing spurious finals on Active rows. Remaining gaps are mostly pre-~2015 Accela shells with empty task events and no `PERMIT MASTER` dates.

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_ca_sample.parquet`
- Jurisdiction: **Stockton, CA** (n=2,001)
- Script: `agent/scripts/ca/data_repair_ca_stockton.py` (`data_repair`)

## DATA schema (`INFERRED_SCHEMA`)

All records are Accela Civic Access scrapes with top-level keys `status`, `date`, `tasks`, `more_details`, `search_data`, etc. Sub-schemas reflect which date sources are populated:

| Schema | n | Description |
| --- | ---: | --- |
| `accela_legacy_master` | 915 | Empty task shells; usable dates in `more_details` → `PERMIT MASTER` |
| `accela_tasks` | 845 | Dated workflow events under `tasks` |
| `accela_shell` | 235 | Tasks present but no dated events and no usable master dates |
| `accela_tasks_and_master` | 5 | Both task events and `PERMIT MASTER` dates |
| `accela_partial` | 1 | Missing inspections / conditions / fees_details keys |

Canonical fields:

| Field | Source |
| --- | --- |
| `STATUS_NORMALIZED` | `DATA.status`; if null, task `Marked as` (Void / Approved / …) |
| `FILE_DATE` | `DATA.date` (fallback: `search_data['Date']`) |
| `PERMIT_DATE` | `Ready to Issue` / `Application Review` / `Application Submittal` → Issued\|Re-Issued; else `PERMIT MASTER` Permit Issue Date / Last Reissue Date |
| `FINAL_DATE` | `Inspections` / Finaled; `Closed` / Closed; else `PERMIT MASTER` Permit Status Date (Finaled/Closed or code `CL`/`FI`) |

## Field assessment

### STATUS_NORMALIZED

**Before:** Final 1,634 · Active 145 · In Review 109 · Inactive 108 · missing 5

Issues:
1. **28 mis-normalized rows** relative to `DATA.status`:
   - Estimate → Final (11) — fee estimates, not completed permits → In Review
   - Finaled → Active (7) → Final
   - Permit Expired / Expired Permit → Active (6) → Inactive
   - Issued → In Review (2) → Active
   - Application Expired → In Review (1) → Inactive
   - Resubmittal Required → Inactive (1) → In Review
2. **5 null `DATA.status`** Over Time Inspection Request rows with null `STATUS_NORMALIZED`. Task marks still present: Approved → Active (2), Void → Inactive (3).

When present, `DATA.status` maps cleanly:

| `DATA.status` | `STATUS_NORMALIZED` |
| --- | --- |
| Finaled, Closed | Final |
| Issued, Re-Issued, Approved, Final Pending | Active |
| Applied, Pending Review, Ready to Issue, Resubmittal Required, Scheduled, Estimate, Template | In Review |
| Expired Permit, Permit Expired, Expired Application, Application Expired, Void, Withdrawn | Inactive |

**After:** Final 1,630 · Active 136 · In Review 118 · Inactive 117 · missing 0  
Flags: **FILLED 5 · FIXED 28**

### FILE_DATE

**Before:** 0 missing (100%).

- Every row’s `FILE_DATE` equals `DATA.date` (string ISO date).
- `search_data['Date']` mirrors the same calendar day when present.

**After:** still 0 missing.  
Flags: **FILLED 0 · FIXED 0**

### PERMIT_DATE

**Before:** 1,819 missing (90.9%). Among Active/Final: 1,613 / 1,779 missing.

Root cause: upstream only populated issuance when a `Ready to Issue` / Issued event existed (182 rows). Most Issued marks live on `Application Review` / `Application Submittal`, and legacy rows store Issue / Reissue under `PERMIT MASTER` instead.

Repairs (Active / Final only):
1. Prefer earliest `Ready to Issue` → Issued|Re-Issued.
2. Else earliest Issued|Re-Issued on Application Review / Submittal / Processing (or any task).
3. Else `PERMIT MASTER` Permit Issue Date, then Permit Last Reissue Date.

**After:** 516 missing (25.8%). Active 95.6% populated · Final 82.0%.  
Flags: **FILLED 1,303 · FIXED 0**

Not repairable: 299 Active/Final rows (mostly Finaled/Closed `accela_shell` / empty-master legacy) have neither Issued events nor master issue dates.

### FINAL_DATE

**Before:** 1,469 missing (73.4%). Among Final: 1,107 / 1,634 missing. Five Active rows incorrectly carried a FINAL_DATE from Inspections / Final Pending.

Root cause: upstream used Inspections / Finaled when present (and sometimes Final Pending). Closed events and legacy `Permit Status Date` (code `CL`) were unused. ~109 Finaled rows still only have Final Pending as a completion mark — left as-is (best available proxy).

Repairs:
1. Fill / correct from latest Inspections / Finaled, then Closed / Closed, then C of O Issued.
2. Else fill from `PERMIT MASTER` Permit Status Date when status is Finaled/Closed or code is `CL`/`FI`.
3. Clear FINAL_DATE when effective status is not Final (**FIXED** to null).

**After:** 847 missing (42.3%). Final 70.8% populated · Active/In Review/Inactive 0%.  
Flags: **FILLED 627 · FIXED 9** (5 clears on Active + 4 date corrections to Finaled/Closed events)

Not repairable: 476 Final rows (largely `accela_legacy_master` without Status Date, plus `accela_shell`) have no finaling event or master status date.

## Repair performance (sample)

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | ---: | ---: | ---: | ---: |
| STATUS_NORMALIZED | 5 | 28 | 5 | 0 |
| FILE_DATE | 0 | 0 | 0 | 0 |
| PERMIT_DATE | 1,303 | 0 | 1,819 | 516 |
| FINAL_DATE | 627 | 9 | 1,469 | 847 |

## Artifacts

- Repair script: `agent/scripts/ca/data_repair_ca_stockton.py`

# Riverside (CA) data repair

**Summary:** Riverside was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. Assessed and repaired `STATUS_NORMALIZED`, `FILE_DATE`, `PERMIT_DATE`, and `FINAL_DATE` from the flat agency-portal `DATA` JSON. Status is now fully populated (**FILLED 39 · FIXED 0**): unmapped revision/amendment statuses (Applicant Revisions, Plans Resubmitted, Amendment*, Planning Clearance Incomplete) were filled; the 15 Applicant Revisions rows already labeled In Review were left unchanged. `FILE_DATE` already matched `Created Date` for all 1,999 rows (no changes). `PERMIT_DATE` already matched `Issued Date` whenever present; Active/Final remain **100%** populated after status fills (amendment rows already carried Issued dates). `FINAL_DATE` on Final (Completed) rows was already complete; **99 FIXED** cleared spurious finals on Inactive Cancelled/Expired/Withdrawn and a handful of Issued / Stop Work rows where `Completed Date` is a close/cancel stamp, not a finalization.

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_ca_sample.parquet`
- Jurisdiction: **Riverside, CA** (n=1,999)
- Script: `agent/scripts/ca/data_repair_ca_riverside.py` (`data_repair`)

## DATA schema (`INFERRED_SCHEMA`)

All records are flat portal scrapes with core keys `Status`, `Created Date`, `Issued Date`, `Completed Date`, `Other Information`, etc. Variants differ by optional keys:

| Schema | n | Optional keys |
| --- | ---: | --- |
| `riverside_core` | 500 | (none) |
| `riverside_related` | 443 | `related_information` |
| `riverside_parcel_related` | 319 | `Parcel`, `related_information` |
| `riverside_parcel` | 257 | `Parcel` |
| `riverside_parcel_contractors_related` | 224 | `Parcel`, `Contractors`, `related_information` |
| `riverside_parcel_contractors` | 180 | `Parcel`, `Contractors` |
| `riverside_contractors` | 42 | `Contractors` |
| `riverside_contractors_related` | 34 | `Contractors`, `related_information` |

Canonical fields:

| Field | Source |
| --- | --- |
| `STATUS_NORMALIZED` | `DATA.Status` |
| `FILE_DATE` | `Created Date` (fallback: `Other Information.CreatedDate`) |
| `PERMIT_DATE` | `Issued Date` (fallback: `Other Information.IssueDate`) |
| `FINAL_DATE` | `Completed Date` when status is Final / Completed (fallback: OI `CompletedDate`, then `Construction Completed Date`) |

`Construction Completed Date` is always empty in this sample. OI date fields, when present, agree with top-level dates.

## Field assessment

### STATUS_NORMALIZED

**Before:** In Review 1,213 · Final 378 · Inactive 198 · Active 171 · missing 39

When present, `DATA.Status` maps cleanly for the common statuses:

| `DATA.Status` | `STATUS_NORMALIZED` |
| --- | --- |
| Completed | Final |
| Issued | Active |
| Draft, In Review, Application Incomplete, Ready For Issue, Submitted, Stop Work | In Review |
| Expired, Cancelled, Withdrawn | Inactive |

Issues:
1. **39 null `STATUS_NORMALIZED`** from statuses missing (or inconsistently applied) in the upstream map:
   - Applicant Revisions → missing (31) vs already In Review (15) → fill remaining as In Review
   - Plans Resubmitted → In Review (2)
   - Planning Clearance Incomplete → In Review (1)
   - Amendment Applicant Revisions / Amendment Review / Amendment Requested → Active (5 total; all have `Issued Date`, so the underlying permit is issued)

**After:** In Review 1,247 · Final 378 · Inactive 198 · Active 176 · missing 0  
Flags: **FILLED 39 · FIXED 0**

### FILE_DATE

**Before:** 0 missing (100%).

- Every row’s `FILE_DATE` equals `Created Date` (e.g. `Jan 14, 2021`).
- No disagreements with OI `CreatedDate` when that field is populated.

**After:** still 0 missing.  
Flags: **FILLED 0 · FIXED 0**

### PERMIT_DATE

**Before:** 1,327 missing (66.4%). Among Active/Final: **0 / 549** missing.

- Whenever `Issued Date` is non-empty, `PERMIT_DATE` already matches it exactly (672/672).
- Missing `PERMIT_DATE` coincides with empty `Issued Date` (Draft / In Review / pre-issuance rows) — nothing further to fill from DATA.
- Amendment rows with null status already carried `PERMIT_DATE` from `Issued Date`; after status fill they remain Active with dates intact.

**After:** still 1,327 missing overall; Active 176/176 and Final 378/378 populated.  
Flags: **FILLED 0 · FIXED 0**

### FINAL_DATE

**Before:** 1,522 missing. Final (Completed): 0 / 378 missing — all match `Completed Date`.

Issues:
1. **99 non-Final rows carried `FINAL_DATE`** copied from `Completed Date`, which for these statuses is a cancel/close/stop stamp, not a finalization:
   - Inactive Cancelled 49 · Expired 31 · Withdrawn 16
   - Active Issued 2 (Completed Date equals Issued Date; status still Issued)
   - In Review Stop Work 1 (Completed Date before Issued Date)

Repairs: clear `FINAL_DATE` when effective status ≠ Final.

**After:** Final 378/378 (100%); Active / In Review / Inactive 0 with FINAL_DATE.  
Flags: **FILLED 0 · FIXED 99**  
Missing: 1,522 → 1,621 (increase from clearing spurious values)

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| `STATUS_NORMALIZED` | 39 | 0 | 39 → 0 |
| `FILE_DATE` | 0 | 0 | 0 → 0 |
| `PERMIT_DATE` | 0 | 0 | 1,327 → 1,327 |
| `FINAL_DATE` | 0 | 99 | 1,522 → 1,621 |

Ideal coverage after repair:
- `FILE_DATE`: 1,999 / 1,999 (100%)
- `PERMIT_DATE` for Active/Final: 554 / 554 (100%)
- `FINAL_DATE` for Final: 378 / 378 (100%)

## Artifacts

- Script: `agent/scripts/ca/data_repair_ca_riverside.py`
- Repaired sample: `AGENT_DATA_PATH/repaired/permits_ca_riverside_repaired.parquet`

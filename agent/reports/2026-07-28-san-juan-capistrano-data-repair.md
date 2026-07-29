# San Juan Capistrano (CA) data repair

**Summary:** San Juan Capistrano was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. Assessed and repaired `STATUS_NORMALIZED`, `FILE_DATE`, `PERMIT_DATE`, and `FINAL_DATE` from the civic-portal `DATA` JSON (`permit_info` / `inspections`). Status: **FILLED 2 · FIXED 27** (blank GRADING shells → In Review; stale `STATUS_ORIGINAL`-driven labels corrected from `PermitStatus` + FinaledDate). `FILE_DATE` already matched `PermitAppliedDate` wherever both exist (**FILLED/FIXED 0**; 74 remain blank with no AppliedDate). `PERMIT_DATE` missingness fell **220 → 202** (**FILLED 18**). `FINAL_DATE`: **FILLED 5 · FIXED 6** (cleared Inactive closure stamps); after repair every non-Final row has null `FINAL_DATE`, and Final coverage is 983/985 (99.8%).

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_ca_sample.parquet`
- Jurisdiction: **San Juan Capistrano, CA** (n=2,000)
- Script: `agent/scripts/ca/data_repair_ca_san_juan_capistrano.py` (`data_repair`)
- Artifact: `AGENT_DATA_PATH/repaired/permits_ca_san_juan_capistrano_repaired.parquet`

## DATA schema (`INFERRED_SCHEMA`)

All records share top-level keys `fees`, `contacts`, `site_info`, `inspections`, `permit_info`, `search_data`. Variants differ by which `permit_info` dates are populated:

| Schema | n | Description |
| --- | ---: | --- |
| `permit_info_issued_finaled` | 982 | Issued + Finaled present |
| `permit_info_issued` | 803 | Issued present, Finaled blank |
| `permit_info_applied_only` | 99 | Only Applied populated |
| `permit_info_empty` | 67 | Empty CONVERTED shells (no status/dates) |
| `permit_info_approved_only` | 36 | Approved present, Issued/Finaled blank |
| `permit_info_finaled_only` | 6 | Finaled present, Issued blank |
| `permit_info_empty_dates` | 5 | Status text, no usable dates |
| `legacy_no_status` | 2 | Blank PermitStatus but AppliedDate present |

Canonical fields:

| Field | Source |
| --- | --- |
| `STATUS_NORMALIZED` | `permit_info.PermitStatus`, with Final upgrade from `PermitFinaledDate` |
| `FILE_DATE` | `permit_info.PermitAppliedDate` |
| `PERMIT_DATE` | `PermitIssuedDate`; else `PermitApprovedDate` |
| `FINAL_DATE` | `PermitFinaledDate`; else latest final / C of O inspection |

`search_data` APPLIED/ISSUED/FINALED never disagree with `permit_info` and never supply dates that `permit_info` lacks.

## Field assessment

### STATUS_NORMALIZED

**Before:** Final 979 · Inactive 613 · Active 266 · In Review 73 · missing 69

Most rows already match a PermitStatus map (`FINALED`→Final, `ACTIVE`/`ISSUED`/`APPROVED`→Active, `EXPIRED`/`VOID`/`CANCELLED`/`WITHDRAWN`/`DENIED`/`WAIVED`→Inactive, `UNDER REVIEW`/`PENDING`→In Review). Repairable problems:

1. **Blank PermitStatus with AppliedDate (2 GRADING).** → **FILLED** as In Review.
2. **67 empty CONVERTED shells** (blank status and all dates) → not repairable; remain missing.
3. **Stale labels vs live PermitStatus / FinaledDate (27 FIXED):**
   - Active → Inactive (16): `EXPIRED` left Active because `STATUS_ORIGINAL` was `issued`.
   - Active → Final (6): `FINALED` left Active (4, ORIG=`issued`) or `APPROVED`/`ACTIVE` with `PermitFinaledDate` (2).
   - In Review → Active (3): `ISSUED` left In Review (ORIG=`under review`); IssueDate present.
   - In Review → Inactive (2): `EXPIRED` (1) and `WAIVED` (1).

Inactive terminal labels are sticky even when FinaledDate is present as a closure stamp.

**After:** Final 985 · Inactive 631 · Active 247 · In Review 70 · missing 67  
Flags: **FILLED 2 · FIXED 27**

### FILE_DATE

**Before:** 74 missing (3.7%).

- Every populated `FILE_DATE` already equals `PermitAppliedDate` at day resolution (1,926 matches; 0 mismatches).
- Remaining gaps have blank AppliedDate (67 empty CONVERTED + 7 other shells with status but no application stamp). ApprovedDate / IssuedDate are not used as FILE substitutes.

**After:** still 74 missing.  
Flags: **FILLED 0 · FIXED 0**

### PERMIT_DATE

**Before:** 220 missing (11.0%).

Root causes repaired:
1. Three `ISSUED` shells mislabeled In Review had IssueDate but null `PERMIT_DATE` → status FIXED to Active and **FILLED**.
2. Active/Final rows with blank IssueDate but usable ApprovedDate (and a few Issued shells after promotion) → **FILLED 18** total.
3. Wherever IssueDate was present and `PERMIT_DATE` populated, dates already matched (0 day mismatches).

**After:** 202 missing. Active 245/247 (99.2%); Final 983/985 (99.8%); In Review 15/70 (upstream IssueDate retained on review rows).

Remaining Active/Final gaps by PermitStatus: FINALED 2 · APPROVED 2 (no Issued or Approved date in DATA).

Flags: **FILLED 18 · FIXED 0**

### FINAL_DATE

**Before:** 1,016 missing (50.8%). Among Final: 3 missing; among non-Final: 8 had FinaledDate stamps.

Root causes:
1. Four `FINALED` left Active had FinaledDate but null `FINAL_DATE` → status FIXED to Final and **FILLED 4**.
2. One Final row with blank FinaledDate but a `BUILDING FINAL**` inspection → **FILLED 1**.
3. Spurious `FINAL_DATE` on Inactive `EXPIRED` shells (parking/filming/encroachment closure stamps) → **FIXED 6** (cleared).
4. Two Final rows still lack FinaledDate and final inspections → not repairable.

Wherever FinaledDate was present and `FINAL_DATE` populated, dates already matched. `PermitExpirationDate` is not used.

**After:** 1,017 missing (net +1 from clearing 6 and filling 5). Final 983/985 (99.8%); Active / In Review / Inactive all 0%.  
Flags: **FILLED 5 · FIXED 6**

## Chronology

After repair, agency-sourced date inversions remain in DATA (not introduced by repair):

- `PERMIT < FILE`: 61 (Issued/Approved before Applied on various permit types)
- `FINAL < PERMIT`: 3

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| `STATUS_NORMALIZED` | 2 | 27 | 69 → 67 |
| `FILE_DATE` | 0 | 0 | 74 → 74 |
| `PERMIT_DATE` | 18 | 0 | 220 → 202 |
| `FINAL_DATE` | 5 | 6 | 1,016 → 1,017 |

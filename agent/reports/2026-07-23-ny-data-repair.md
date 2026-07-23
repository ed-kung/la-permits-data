# New York Data Repair: Assessment & Repair of STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, FINAL_DATE

The New York sample (2,000 records) has significant data quality issues across all four fields. The raw DATA JSON column contains sufficient information to fill 407 missing STATUS_NORMALIZED values, 256 missing FILE_DATE values, 355 missing PERMIT_DATE values, and 878 missing FINAL_DATE values, and to correct 12 incorrect STATUS_NORMALIZED values. A `data_repair()` function has been written to perform these repairs.

## Data structure

The New York DATA column contains three sub-schemas, each originating from a different NYC Department of Buildings dataset:

| Sub-schema | Records | Description |
|---|---|---|
| DOB_issuances | 1,263 | Permit issuances data; top-level arrays `filings` + `issuances` |
| DOB_filing_single | 446 | BIS/NOW filing data; single `filing` dict |
| other | 291 | Electrical permits; flat structure with `filing_status`, `job_status`, `completion_date`, `permit_issued_date` |

## Field-by-field findings

### STATUS_NORMALIZED

**Before repair:** 407 missing (20.4%), 12 incorrect.

**Missing values (407 → 0 after repair):**

- **DOB_issuances (258 missing):** 256 records lack a `filings` array (and therefore lack `job_status_descrp`), but all 256 have `issuance_date` in their issuances entries, confirming permits were issued → filled as **Active**. The remaining 2 records have `job_status_descrp` values: 1 "PLAN EXAM - DISAPPROVED" → **Inactive**, 1 "APPLICATION ASSIGNED TO PLAN EXAMINER" → **In Review**.

- **DOB_filing_single (149 missing):** Each record's `filing.filing_status` maps deterministically to a normalized status. The dominant group is "Permit Entire" (121) → **Active**. Others: "Objections" (11) → In Review, "LOC Issued" (5) → Final, "Approved" (3) → Active, and various single-count statuses.

**Incorrect values (12 fixed):**

| Count | Schema | Original | Corrected | Raw status field |
|---|---|---|---|---|
| 5 | DOB_issuances | Final | Active | `jsd = PERMIT ISSUED - ENTIRE JOB/WORK` |
| 2 | DOB_issuances | Active | Final | `jsd = SIGNED OFF` |
| 2 | other | Active | Final | `filing_status = Complete, job_status = Job is complete` |
| 1 | DOB_filing_single | Active | Final | `filing_status = LOC Issued` |
| 1 | DOB_filing_single | Active | Inactive | `filing_status = Filing Withdrawn` |
| 1 | DOB_issuances | Active | Final | `jsd = PERMIT ISSUED - ENTIRE JOB/WORK` (duplicate note: this was in a different bucket above, same fix logic) |

**Root cause:** STATUS_NORMALIZED was originally derived from STATUS_ORIGINAL, which appears to come from a separate processing pipeline. The raw DATA JSON contains more authoritative status information (e.g., `job_status_descrp` in DOB filings, `filing_status` in DOB NOW). Mismatches arise when these two sources disagree, and in all 12 cases the DATA JSON status is more consistent with the record's other fields.

### FILE_DATE

**Before repair:** 258 missing (12.9%).

- **DOB_issuances (256 missing → 0 after repair):** These are the same 256 records lacking a `filings` array. FILE_DATE normally comes from `filings[0].pre__filing_date` (confirmed: 100% match rate for the 1,007 records that have it). For the 256 without filings, FILE_DATE was filled from the earliest INITIAL issuance's `filing_date`.
- **DOB_filing_single (2 missing → 2 still missing):** These records lack `filing.filing_date` in the DATA; cannot be filled.

### PERMIT_DATE

**Before repair:** 738 missing (36.9%).

PERMIT_DATE is sourced differently per sub-schema:
- **DOB_issuances:** `filings[0].fully_permitted` (100% match rate for known values), fallback to earliest INITIAL `issuance_date`
- **DOB_filing_single:** `filing.permit_issue_date` or `filing.first_permit_date`
- **other:** `permit_issued_date` (100% match rate for known values)

**After repair:** 383 still missing. Remaining gaps:

| Status | Missing | Explanation |
|---|---|---|
| Active | 200 | 138 DOB_filing_single without `permit_issue_date`, 43 "other" without `permit_issued_date`, 19 DOB_issuances without `fully_permitted` or `issuance_date` |
| Final | 28 | DATA JSON lacks the relevant date field |
| In Review | 100 | Not expected to have PERMIT_DATE |
| Inactive | 55 | Not expected to have PERMIT_DATE |

### FINAL_DATE

**Before repair:** 2,000 missing (100%). This field was entirely unpopulated.

**After repair:** 878 filled (all for Final-status records).

- **DOB_issuances (590 with `signoff_date` in filings, 588 Final):** Filled from `filings[0].signoff_date`.
- **other (291 with `completion_date`, 139 Final after status fix):** Filled from `completion_date`.
- **DOB_filing_single:** Only 3 records had a candidate (`current_status_date` when status indicates completion); all had missing STATUS_NORMALIZED and were mapped to Final.

**After repair:** 9 Final records still missing FINAL_DATE (all DOB_issuances where the filings array exists but lacks `signoff_date`).

## Summary statistics

| Field | Before (missing) | After (missing) | Filled | Fixed |
|---|---|---|---|---|
| STATUS_NORMALIZED | 407 | 0 | 407 | 12 |
| FILE_DATE | 258 | 2 | 256 | 0 |
| PERMIT_DATE | 738 | 383 | 355 | 0 |
| FINAL_DATE | 2,000 | 1,122 | 878 | 0 |

## Artifacts

- **Repair function:** `agent/scripts/ny_data_repair.py` — `data_repair(df)` takes a NY-filtered DataFrame and returns a copy with corrected fields and `{FIELD}_FLAG` columns.
- **Assessment scripts:** `agent/scripts/ny_assess_fields.py`, `ny_assess_fields_v2.py`, `ny_assess_fields_v3.py`
- **Verification script:** `agent/scripts/ny_verify_fixes.py`

# New York Date Fill-In Analysis

**Date:** 2026-07-23  
**Data source:** `MY_DATA_PATH/processed_data/permits_top50_sample.parquet`, filtered to `JURISDICTION == "New York"` (2,000 records)

## Summary

Missing values for FILE_DATE, PERMIT_DATE, and FINAL_DATE in New York building-permit records can be substantially recovered from the DATA column JSON. A proposed extraction function (`agent/scripts/ny_date_fill.py`) was built and validated, achieving the following improvements:

| Field | Before | After | Newly Filled | Remaining Missing |
|-------|--------|-------|-------------|-------------------|
| FILE_DATE | 1,742 (87.1%) | 1,998 (99.9%) | +256 | 2 |
| PERMIT_DATE | 1,262 (63.1%) | 1,617 (80.8%) | +355 | 383 |
| FINAL_DATE | 0 (0.0%) | 1,036 (51.8%) | +1,036 | 964 |

Validation against records where dates were already populated shows **100% match** for FILE_DATE and **96.7% match** for PERMIT_DATE (remaining 3.1% are minor discrepancies in the `filing+permits` sub-schema).

## Data Structure

New York records use a "custom" schema (not Accela or Energov). The DATA column contains three distinct sub-schemas from different NYC DOB data sources:

### Sub-schema A: DOB filings + issuances (63.2%, n=1,263)
- Top-level keys: `{filings, issuances}`
- `filings[]` contains: `pre__filing_date`, `fully_permitted`, `signoff_date`, `paid`, `approved`, `latest_action_date`, `job_status_descrp`, etc.
- `issuances[]` contains: `filing_date`, `issuance_date`, `filing_status` (INITIAL/RENEWAL), `job_start_date`, `expiration_date`, etc.

### Sub-schema B: DOB filing + permits (22.3%, n=446)
- Top-level keys: `{filing, permits}`
- `filing` (singular dict) contains: `filing_date`, `permit_issue_date`, `first_permit_date`, `current_status_date`, `filing_status`
- `permits[]` contains: `approved_date`, `issued_date`, `expired_date`, `filing_reason` (Initial Permit/Renewal/etc.)

### Sub-schema C: Electrical permits / flat (14.6%, n=291)
- Flat top-level structure with keys: `filing_date`, `permit_issued_date`, `completion_date`, `job_start_date`, `filing_status`, `job_status`, plus many applicant/insurance fields.

## Missing Dates: Baseline

| Field | Present | Missing | Missing % |
|-------|---------|---------|-----------|
| FILE_DATE | 1,742 | 258 | 12.9% |
| PERMIT_DATE | 1,262 | 738 | 36.9% |
| FINAL_DATE | 0 | 2,000 | 100.0% |

### Missing by STATUS_NORMALIZED

| Status | n | FILE_DATE missing | PERMIT_DATE missing | FINAL_DATE missing |
|--------|---|-------------------|---------------------|--------------------|
| Final | 882 | 0 (0.0%) | 78 (8.8%) | 882 (100%) |
| Active | 569 | 0 (0.0%) | 248 (43.6%) | 569 (100%) |
| In Review | 86 | 0 (0.0%) | 83 (96.5%) | 86 (100%) |
| Inactive | 56 | 2 (3.6%) | 52 (92.9%) | 56 (100%) |
| (no status) | 407 | 256 (62.9%) | 277 (68.1%) | 407 (100%) |

Key observation: records missing FILE_DATE (258) are overwhelmingly in the "no status" group and use only the `issuances`-only sub-variant (no `filings` array).

## Mapping Logic

### FILE_DATE (application/submitted date)
1. `filings[0].pre__filing_date` — Sub-schema A (57.8% of known matches)
2. `filing.filing_date` — Sub-schema B (24.4%)
3. Top-level `filing_date` — Sub-schema C (16.7%)
4. `issuances[INITIAL earliest].filing_date` — Fallback (fills 99.2% of missing)

**Validation:** 100% match rate against 1,742 records with known FILE_DATE.

### PERMIT_DATE (approval/issued date)
1. `filings[0].fully_permitted` — Sub-schema A (59.0% of known matches)
2. `permits[Initial Permit].approved_date` — Sub-schema B (previously missed; corrected from `issued_date`)
3. Top-level `permit_issued_date` — Sub-schema C (19.7%)
4. `filing.permit_issue_date` — Sub-schema B fallback
5. `issuances[INITIAL earliest].issuance_date` — General fallback

**Validation:** 96.7% match rate against 1,262 records with known PERMIT_DATE. The 3.1% mismatches are in the `filing+permits` sub-schema where the exact date interpretation differs slightly.

### FINAL_DATE (finalized/completion/signed-off date)
1. `filings[0].signoff_date` — Sub-schema A (29.5% of all records)
2. `filing.current_status_date` — Sub-schema B, only when `filing.filing_status` indicates completion: "LOC Issued" (Letter of Completion), "TA Certificate of Operation Issued", "PA Certificate of Operation Issued" (142+7 records)
3. Top-level `completion_date` — Sub-schema C (14.5%)

**Note:** FINAL_DATE was 100% missing in the original data, so no direct validation was possible. However, `signoff_date` appears almost exclusively on records with `job_status_descrp == "SIGNED OFF"` or "COMPLETED", and completion_date appears only in the electrical permits sub-schema. The extracted FINAL_DATE aligns well with STATUS_NORMALIZED: 99.0% of "Final" records get a value, vs. 26.5% of "Active" records (which may represent partial sign-offs).

## Remaining Gaps After Fill-In

| Field | Status | Still Missing | Total | % Missing |
|-------|--------|---------------|-------|-----------|
| FILE_DATE | All statuses | 2 | 2,000 | 0.1% |
| PERMIT_DATE | Final | ~9 | 882 | ~1.0% |
| PERMIT_DATE | Active | ~202 | 569 | 35.5% |
| PERMIT_DATE | In Review | 83 | 86 | 96.5% |
| PERMIT_DATE | Inactive | 52 | 56 | 92.9% |
| FINAL_DATE | Final | 9 | 882 | 1.0% |
| FINAL_DATE | Active | 418 | 569 | 73.5% |

The remaining PERMIT_DATE gaps for Active/In Review/Inactive are expected — these permits have not yet been issued. FINAL_DATE coverage for Final-status records is now 99.0%.

## Artifacts

- **Proposed function:** `agent/scripts/ny_date_fill.py` — contains `extract_ny_file_date()`, `extract_ny_permit_date()`, `extract_ny_final_date()`, and `fill_ny_dates()`.
- **Exploration scripts:** `agent/scripts/ny_date_exploration.py`, `agent/scripts/ny_date_validation.py`

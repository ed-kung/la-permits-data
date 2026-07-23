# Chicago DATA Column Repair Assessment

**Date:** 2026-07-23  
**Source:** `MY_DATA_PATH/processed_data/permits_top50_sample.parquet`, filtered to `JURISDICTION == "Chicago"` (1,998 records)

## Summary

Chicago's DATA column uses a **custom** (flat key-value) JSON schema. It contains two date fields and one status field that can partially fill missing values. The main limitation is that **94% of records lack a PERMIT_STATUS value** (from an older Chicago open-data format), and **no completion/finalization date exists anywhere in the DATA column**, so FINAL_DATE cannot be recovered.

## Missingness Before Repair

| Field              | Present | Missing | % Missing |
|--------------------|--------:|--------:|----------:|
| STATUS_NORMALIZED  |       0 |   1,998 |    100.0% |
| FILE_DATE          |   1,997 |       1 |      0.1% |
| PERMIT_DATE        |   1,998 |       0 |      0.0% |
| FINAL_DATE         |       0 |   1,998 |    100.0% |

## DATA Column Fields Available

Using `extract_date_fields` from `scripts/data_utils.py`, the following relevant keys were identified across all 1,998 records:

| DATA Key                | Count  | Maps To           |
|-------------------------|-------:|-------------------|
| `ISSUE_DATE`            | 1,998  | PERMIT_DATE       |
| `APPLICATION_START_DATE`| 1,998  | FILE_DATE         |
| `PERMIT_STATUS`         | 1,989* | STATUS_NORMALIZED |
| `PERMIT_MILESTONE`      | 1,989* | (supplementary)   |

*\*1,989 records have the key present, but only 113 have a non-empty value.*

## Field-by-Field Assessment

### 1. STATUS_NORMALIZED (100% missing → 94.3% missing after repair)

**PERMIT_STATUS** in the DATA column has non-empty values for **113 of 1,998 records (5.7%)**. The remaining 1,885 records have an empty string — these come from an older Chicago data format that predates the status field.

**Proposed mapping:**

| PERMIT_STATUS | → STATUS_NORMALIZED | Count |
|---------------|---------------------|------:|
| `ACTIVE`      | Active              |    97 |
| `COMPLETE`    | Final               |    11 |
| `EXPIRED`     | Inactive            |     2 |
| `CANCELLED`   | Inactive            |     1 |
| `OPEN`        | In Review           |     2 |
| *(empty)*     | *(cannot determine)*| 1,876 |
| *(NaN/missing)*| *(cannot determine)*|    9 |

**For the 1,885 undetermined records:** All have an `ISSUE_DATE`, confirming these permits were issued. Without further information (e.g., inspection records, expiration rules), we cannot reliably distinguish Active from Final or Inactive. A conservative approach would be to leave these as missing rather than assume a status.

**Cross-tab of PERMIT_STATUS × PERMIT_MILESTONE** shows clean alignment — e.g., `COMPLETE` status always pairs with `INSPECTION ELIGIBLE` milestone, `ACTIVE` always pairs with inspection-stage milestones. PERMIT_MILESTONE does not add independent status information beyond PERMIT_STATUS.

### 2. FILE_DATE (0.1% missing → 0.1% missing, unchanged)

Only **1 record** is missing FILE_DATE. Unfortunately, its `APPLICATION_START_DATE` in DATA is also an empty string, so the gap **cannot be filled**.

Cross-validation: For the 1,997 records where both FILE_DATE and APPLICATION_START_DATE are present, **1,996 match exactly** (1 mismatch on record 5532, which appears to have been re-filed with updated dates in DATA).

### 3. PERMIT_DATE (0% missing, no action needed)

PERMIT_DATE is fully populated. Cross-validation confirms `ISSUE_DATE` in DATA matches PERMIT_DATE for **1,997 of 1,998 records** (same record 5532 has a discrepancy — likely a re-issuance reflected in the DATA column but not in the main field).

### 4. FINAL_DATE (100% missing → 100% missing, cannot repair)

**No completion, finalization, or close date key exists in the Chicago DATA column.** A thorough search for keys containing "final", "complete", "close", "expire", "end", or "finish" found zero matches.

The `PERMIT_MILESTONE = "COMPLETE"` flag (11 records) confirms some permits reached completion, but no associated date is recorded. FINAL_DATE **cannot be recovered from the DATA column**.

## After Repair

| Field              | Present | Missing | % Missing | Change      |
|--------------------|--------:|--------:|----------:|-------------|
| STATUS_NORMALIZED  |     113 |   1,885 |     94.3% | ↓ from 100% |
| FILE_DATE          |   1,997 |       1 |      0.1% | unchanged   |
| PERMIT_DATE        |   1,998 |       0 |      0.0% | unchanged   |
| FINAL_DATE         |       0 |   1,998 |    100.0% | unchanged   |

## Artifacts

- **`agent/scripts/chi_data_repair.py`** — Proposed repair functions:
  - `chi_extract_status(data)` — extract STATUS_NORMALIZED from a single DATA cell
  - `chi_extract_file_date(data)` — extract FILE_DATE from a single DATA cell
  - `chi_extract_permit_date(data)` — extract PERMIT_DATE from a single DATA cell
  - `chi_repair_missing_fields(df)` — batch repair all three fields on a Chicago DataFrame

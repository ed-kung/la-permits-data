# Philadelphia DATA Column Repair Assessment

## Summary

Assessed the degree to which missing values for STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE can be recovered from the raw JSON in the DATA column for 1,998 Philadelphia building-permit records. **STATUS_NORMALIZED** can be fully recovered (71/71 missing values, 100%). **PERMIT_DATE** can be largely recovered (67/78 missing, 85.9%). **FINAL_DATE** has limited recovery (9/361, 2.5%). **FILE_DATE** cannot be recovered at all (0/1,644) because the dominant data source lacks an application date field.

## Data Structure

Philadelphia records come from two underlying city systems and appear in three distinct DATA sub-schemas:

| Schema | System | Records | % | Identifying keys |
|--------|--------|---------|---|------------------|
| POSSE | HANSEN/ECLIPSE | 1,574 | 78.8% | `PERMITISSUEDATE` (any case) |
| Eclipse detailed | Eclipse | 355 | 17.8% | `Status` + `Created Date` |
| Flat detail | Eclipse | 69 | 3.5% | `IssueDate` or `StatusDescription`, no `Status` |

## Missing Values Before Repair

| Field | Present | Missing | Missing % |
|-------|---------|---------|-----------|
| STATUS_NORMALIZED | 1,927 | 71 | 3.6% |
| FILE_DATE | 354 | 1,644 | 82.3% |
| PERMIT_DATE | 1,920 | 78 | 3.9% |
| FINAL_DATE | 1,637 | 361 | 18.1% |

## Field Mappings and Validation

### FILE_DATE (application/submitted date)

| Schema | DATA field | Overlap | Match rate | Fill potential |
|--------|-----------|---------|------------|----------------|
| POSSE | (none) | — | — | 0 / 1,574 |
| Eclipse | `Created Date` | 354 | 100.0% | 0 / 1 (empty value) |
| Flat detail | (none) | — | — | 0 / 69 |

**Result: 0 / 1,644 missing values fillable (0%).** The POSSE system (79% of records) and flat detail schema (3%) do not contain any application or submission date. The single Eclipse record with missing FILE_DATE also has an empty `Created Date`.

### PERMIT_DATE (approval/issued date)

| Schema | DATA field | Overlap | Match rate | Fill potential |
|--------|-----------|---------|------------|----------------|
| POSSE | `PERMITISSUEDATE` | 1,573 | 100.0% | 0 / 1 |
| Eclipse | `Issued Date` | 347 | 100.0% | 0 / 8 (all empty) |
| Flat detail | `IssueDate` | 0 (all missing) | — | **67 / 69** |

**Result: 67 / 78 missing values fillable (85.9%).** Nearly all fillable values come from the flat detail schema, where all 69 records have missing PERMIT_DATE but 67 have a usable `IssueDate`.

### FINAL_DATE (finalized/completion date)

| Schema | DATA field | Overlap | Match rate | Fill potential |
|--------|-----------|---------|------------|----------------|
| POSSE | `PERMITCOMPLETEDDATE` | 1,348 | 100.0% | 0 / 226 (all empty) |
| Eclipse | `Completed Date` | 255 | 100.0% | **9 / 100** |
| Flat detail | `CompletedDate` | 34 | 100.0% | 0 / 35 (all empty) |

**Result: 9 / 361 missing values fillable (2.5%).** Most records missing FINAL_DATE simply have no completion date in the raw data either — the permit has not been finalized.

### STATUS_NORMALIZED

**POSSE status mapping** (validated: 1,573/1,573 = 100% match):

| DATA.STATUS | STATUS_NORMALIZED |
|-------------|-------------------|
| COMPLETED / Completed | Final |
| Issued | Active |
| EXPIRED / Expired | Inactive |
| CLOSED | Final |
| ABANDONED | Inactive |
| REVOKED | Inactive |
| Cancelled | Inactive |
| Denied | Inactive |
| Amendment Application Incomplete | In Review (tentative) |

**Eclipse status mapping** (validated: 344/354 = 97.2% match):

| DATA.Status | STATUS_NORMALIZED |
|-------------|-------------------|
| Completed | Final |
| Issued | Active |
| Expired | Inactive |
| Ready For Issue | In Review |
| Stop Work | In Review |
| Withdrawn | Inactive |
| Amendment Applicant Revisions | In Review (tentative) |

The 10 Eclipse mismatches (2.8%) are records where the existing STATUS_NORMALIZED is "Active" but DATA.Status shows "Completed" or "Expired" — likely cases where the data source was updated after the normalized status was set.

**Flat detail status mapping** (no ground truth — all 69 have missing STATUS_NORMALIZED):

Status is extracted from the first word of `StatusDescription` (e.g., "Completed \n May 26, 2020" → "Completed"). Mapping follows the same vocabulary as Eclipse.

**Result: 71 / 71 missing values fillable (100%).**

## Overall Fill Summary

| Field | Missing | Fillable | Fill rate | Still missing |
|-------|---------|----------|-----------|---------------|
| FILE_DATE | 1,644 | 0 | 0% | 1,644 |
| PERMIT_DATE | 78 | 67 | 85.9% | 11 |
| FINAL_DATE | 361 | 9 | 2.5% | 352 |
| STATUS_NORMALIZED | 71 | 71 | 100% | 0 |

## Artifacts

- **`agent/scripts/phi_data_repair.py`** — Philadelphia-specific extraction functions:
  - `extract_phi_file_date(data)` — extracts FILE_DATE (Eclipse "Created Date" only)
  - `extract_phi_permit_date(data)` — extracts PERMIT_DATE from all three schemas
  - `extract_phi_final_date(data)` — extracts FINAL_DATE from all three schemas
  - `extract_phi_status(data)` — extracts STATUS_NORMALIZED from all three schemas
  - `fill_phi_dates(df)` — batch fill function operating on a Philadelphia-filtered DataFrame

## Validation Results

Running `fill_phi_dates` on the 1,998-record sample and comparing extracted values against existing (non-missing) ground truth:

| Field | Extracted | Matched | Match rate |
|-------|-----------|---------|------------|
| PERMIT_DATE | 1,920 | 1,920 | 100.0% |
| FINAL_DATE | 1,637 | 1,637 | 100.0% |
| STATUS_NORMALIZED | 1,927 | 1,918 | 99.5% |

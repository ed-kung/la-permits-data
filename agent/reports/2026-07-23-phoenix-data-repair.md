# Phoenix DATA Column Repair Assessment

## Summary

Assessed the degree to which missing values for STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE can be recovered from the DATA column for Phoenix, AZ permit records (1,992 records in sample). Phoenix uses a "custom" schema with flat permit data and a nested inspections list. **FILE_DATE cannot be filled** (no source exists). PERMIT_DATE can be partially filled (113/214 = 52.8%), STATUS_NORMALIZED fully filled (75/75 = 100%, tentative), and FINAL_DATE minimally filled (18/90 eligible = 20.0%).

## Data Structure

Phoenix records contain a flat JSON with these date/status-relevant fields:

| Field | Format | Coverage | Role |
|-------|--------|----------|------|
| `issued` | DD-MMM-YYYY (e.g. "20-AUG-2008") | 1,770/1,992 (88.9%) | Permit issuance date |
| `expires` | DD-MMM-YYYY | 1,695/1,992 (85.1%) | Permit expiration date |
| `status` | Short code (DONE/OPEN/EXPR/VOID/CNCL/SHAP) | 1,992/1,992 (100%) | Permit status |
| `permit.IssuedDate` | /Date(ms)/ Microsoft format | 1,445/1,992 (72.5%) | Permit issuance (alt format) |
| `inspections[].CompletedDate` | /Date(ms)/ | 1,461/1,992 (73.3%) | Inspection completion dates |
| `inspections[].Result` | PASS/FAIL/PROGRESS/etc. | — | Inspection outcome |

No application/submitted date field exists anywhere in the Phoenix data structure (no `filing_date`, `submitted_date`, `application_date`, or equivalent).

## Baseline Missing Values

| Field | Missing | Present | % Missing |
|-------|---------|---------|-----------|
| FILE_DATE | 1,992 | 0 | 100.0% |
| PERMIT_DATE | 214 | 1,778 | 10.7% |
| FINAL_DATE | 632 | 1,360 | 31.7% |
| STATUS_NORMALIZED | 75 | 1,917 | 3.8% |

## Fill Assessment by Field

### FILE_DATE — NOT FILLABLE

No application or submission date exists in the Phoenix DATA structure. The `DataSubmitted` field in the `permit` sub-object is always null. No other date field pre-dates the issuance date. **0% fillable.**

### PERMIT_DATE — Partially Fillable (52.8%)

- **Source 1:** `issued` (DD-MMM-YYYY) — matches 100% of known PERMIT_DATE values (1,768/1,768 overlaps)
- **Source 2:** `permit.IssuedDate` (/Date(ms)/) — matches 100% of known values (1,332/1,332 overlaps); provides coverage for 111 records lacking the `issued` field

**Result:** 113 of 214 missing values filled. 101 records have neither source available.

### FINAL_DATE — Minimally Fillable (20.0% of eligible)

Strategy: latest `CompletedDate` among inspections with `Result == "PASS"`, falling back to latest `CompletedDate` from any inspection.

- Validated on known values: **88.4% accuracy** (latest PASS matches 1,185/1,341)
- Only applicable to DONE-status records (non-DONE records are not expected to have a final date)
- Of 632 records with missing FINAL_DATE:
  - 258 are EXPR (expired) — not expected to have FINAL_DATE
  - 197 are OPEN — not expected to have FINAL_DATE
  - 90 are DONE — **these are the fill targets**
  - 58 are VOID, 28 SHAP, 1 CNCL — not expected to have FINAL_DATE
- Of 90 DONE records with missing FINAL_DATE, only 18 have inspection data available

**Result:** 18 of 90 eligible records filled. Remaining 72 DONE records lack inspection data entirely.

### STATUS_NORMALIZED — Fully Fillable (100%, tentative)

All 75 missing STATUS_NORMALIZED records have `DATA.status = "SHAP"`. The mapping is validated by cross-tabulation with existing STATUS_NORMALIZED values:

| DATA.status | STATUS_NORMALIZED | Confidence |
|-------------|-------------------|------------|
| DONE | In Review | 99.9% (1,268/1,269) |
| OPEN | In Review | 100% (209/209) |
| EXPR | Inactive | 99.7% (372/373) |
| VOID | Inactive | 98.5% (64/65) |
| CNCL | Inactive | 100% (1/1) |
| **SHAP** | **Active** (tentative) | No ground truth |

The SHAP → "Active" mapping is tentative. SHAP records have issued permits (55/75 have PERMIT_DATE) and many have inspection histories and FINAL_DATEs (47/75), suggesting active or completed work. Without documentation of what "SHAP" means in Phoenix's system, this requires domain confirmation.

**Result:** 75/75 filled. Mapping needs domain validation.

## Post-Fill Summary

| Field | Missing Before | Missing After | Filled | Remaining Gap |
|-------|---------------|---------------|--------|---------------|
| FILE_DATE | 1,992 (100%) | 1,992 (100%) | 0 | Cannot recover |
| PERMIT_DATE | 214 (10.7%) | 101 (5.1%) | 113 | No source data for 101 |
| FINAL_DATE | 632 (31.7%) | 614 (30.8%) | 18 | 72 DONE lack inspections; 542 non-DONE expected |
| STATUS_NORMALIZED | 75 (3.8%) | 0 (0%) | 75 | — |

## Artifacts

- **`agent/scripts/pho_data_repair.py`** — Phoenix-specific extraction functions following `ny_date_fill.py` conventions. Contains:
  - `extract_pho_permit_date(data)` — extracts PERMIT_DATE from `issued` or `permit.IssuedDate`
  - `extract_pho_final_date(data)` — extracts FINAL_DATE from latest PASS inspection CompletedDate
  - `extract_pho_status(data)` — maps DATA.status codes to STATUS_NORMALIZED
  - `fill_pho_dates(df)` — batch function that fills all three fields on a Phoenix DataFrame

## Notes

- The notable asymmetry (DONE mapping to "In Review" rather than "Final" or "Active") reflects the existing upstream normalization in the sample data — the repair function preserves this convention.
- The 88.4% accuracy of the FINAL_DATE strategy means ~12% of filled values may be off by a few days or weeks (typically matching an earlier or later inspection in the same permit lifecycle). This is a known limitation.

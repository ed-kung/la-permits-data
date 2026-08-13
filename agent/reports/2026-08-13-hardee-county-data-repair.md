# Hardee County (FL) data repair

Assessed and repaired `STATUS_NORMALIZED`, `FILE_DATE`, `PERMIT_DATE`, and `FINAL_DATE` for Hardee County permits in `permits_fl_sample.parquet` (2,000 rows). First `(JURISDICTION, STATE)` pair without an existing repair script was **Hardee County / FL**. DATA is a city portal JSON with shared permit fields plus nested `inspections` / `fees` / `payments` / `reviews`; key-set variants add `plan_reviews` and optionally `record_type_from_contractor_box`. Status nulls from unmapped originals (`c.o issued`, `problem file`, pre-issuance / department holds) were the main STATUS issue. FILE_DATE was already correct aside from one empty shell. PERMIT_DATE had unsupported / `01/01/1900` values cleared. FINAL_DATE gained 120 fills from passed final inspections, with sentinel and non-Final values cleared.

## Artifacts

- Repair script: `agent/scripts/fl/data_repair_fl_hardee_county.py`
- Function: `data_repair(df)`
- Repaired sample: `$AGENT_DATA_PATH/hardee_county_repaired_sample.parquet`

## DATA schemas (`INFERRED_SCHEMA`)

| Schema | Count |
| --- | ---: |
| `city_portal_issued_finaled` | 900 |
| `city_portal_issued` | 561 |
| `city_portal_applied` | 454 |
| `city_portal_finaled` | 33 |
| `city_portal_record_type_issued` | 24 |
| `city_portal_plan_reviews_issued` | 10 |
| `city_portal_record_type_applied` | 9 |
| `city_portal_plan_reviews_applied` | 5 |
| `city_portal_record_type_issued_finaled` | 3 |
| `city_portal_record_type_status_only` | 1 |

Canonical mappings:

- **Status** (fallback `STATUS_ORIGINAL`) → `STATUS_NORMALIZED`
- `Permit Date` → `FILE_DATE`
- `Issued Date` → `PERMIT_DATE`
- `Date of CO, CC, or Closed Date` → `FINAL_DATE`, else latest passed final-ish inspection `completed_date`

## Field findings

### STATUS_NORMALIZED

- Before: Final 1,311 / Active 283 / Inactive 88 / In Review 32 / **null 286**
- After: Final 1,408 / Active 283 / Inactive 112 / In Review 52 / null 145
- **FILLED 141**: unmapped originals mapped from DATA `Status` — `c.o issued`→Final (97); `contacted and ready for issuance` / `waiting on fire department` / `zoning department`→In Review (20); `problem file`→Inactive (24).
- **FIXED 0**: already-mapped Closed / Certificate of Completion / Issued / Plan Review / Open / Voided / Expired were already correct.
- **Remaining null 145**: blank `Status` shells with no Issued/Closed dates — mostly `MILTON Damage Assessment` (138) plus a few other empty-lifecycle rows. Not repairable from DATA.

### FILE_DATE

- Before/after missing: **1** (empty shell; blank `Permit Date`).
- **FILLED 0 / FIXED 0**: all 1,999 populated rows already matched DATA `Permit Date`.
- Coverage after repair: 100% for Active / Final / In Review / Inactive.

### PERMIT_DATE

- Before missing: 429 (plus 58 `01/01/1900` sentinels counted as present).
- After missing: 502.
- **FILLED 0**: no Active/Final row had a usable Issued Date that was previously missing.
- **FIXED 73**: cleared 58 sentinel `01/01/1900` values and 15 non-Issued dates (PERMIT_DATE set while DATA `Issued Date` blank — common on Problem file / Contacted-and-ready / some Closed shells).
- Ideal coverage after repair: Active 281/283 (99.3%); Final 1,171/1,408 (83.2%). Remaining Active/Final gaps have blank Issued Date in DATA.

### FINAL_DATE

- Before missing: 1,217; After missing: 1,103.
- **FILLED 120**: Final shells with blank `Date of CO, CC, or Closed Date` filled from passed final / CO inspections.
- **FIXED 6**: cleared 3 sentinel `01/01/1900` values; cleared FINAL_DATE on 1 Active (Issued shell with same-day Closed date but Status still Issued), 2 Voided Inactive, leaving non-Final shells without FINAL_DATE.
- Ideal coverage after repair: Final 897/1,408 (63.7%). Remaining Final gaps have blank Closed/CO date and no passed final inspection in DATA.

## Repair performance summary

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 141 | 0 | 286 → 145 |
| FILE_DATE | 0 | 0 | 1 → 1 |
| PERMIT_DATE | 0 | 73 | 429 → 502 |
| FINAL_DATE | 120 | 6 | 1,217 → 1,103 |

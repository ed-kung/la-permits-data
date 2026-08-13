# Haines City (FL) data repair

Assessed and repaired `STATUS_NORMALIZED`, `FILE_DATE`, `PERMIT_DATE`, and `FINAL_DATE` for Haines City permits in `permits_fl_sample.parquet` (2,000 rows). First `(JURISDICTION, STATE)` pair without an existing repair script was **Haines City / FL**. DATA is a city portal JSON with shared permit fields plus nested `inspections` / `fees` / `payments`; three key-set variants differ by `plan_reviews` and `record_type_from_contractor_box`. Status nulls and lag (especially approved/issued shells that are already Finaled, or issued shells still UNDER REVIEW / ON/HOLD) were the main STATUS issues. FILE_DATE was already correct. PERMIT_DATE had unsupported / `01/01/1900` values cleared. FINAL_DATE gained 259 fills from close-out / CO / passed final inspections, with sentinel and non-Final values cleared.

## Artifacts

- Repair script: `agent/scripts/fl/data_repair_fl_haines_city.py`
- Function: `data_repair(df)`

## DATA schemas (`INFERRED_SCHEMA`)

| Schema | Count |
| --- | ---: |
| `city_portal_issued_finaled` | 1,176 |
| `city_portal_issued` | 540 |
| `city_portal_applied` | 186 |
| `city_portal_record_type_applied` | 36 |
| `city_portal_record_type_issued` | 23 |
| `city_portal_finaled` | 15 |
| `city_portal_plan_reviews_applied` | 13 |
| `city_portal_plan_reviews_issued` | 7 |
| `city_portal_record_type_issued_finaled` | 4 |

Canonical mappings:

- **Status** (plus BPR / Application Status / `STATUS_ORIGINAL` fallbacks) → `STATUS_NORMALIZED`
- `Permit Date` → `FILE_DATE`
- `Permit Issued Date` → `PERMIT_DATE`
- `Final Inspection Date` → `FINAL_DATE`, else `Permit Close Out Date`, else `NSFR CO Issued Date`, else latest approved final inspection `completed_date`

## Field findings

### STATUS_NORMALIZED

- Before: Final 1,061 / Active 784 / In Review 111 / Inactive 20 / **null 24**
- After: Final 1,137 / Active 703 / In Review 138 / Inactive 22 / null 0
- **FILLED 24**: unmapped originals (`on/hold`, under building/planning review, planning/building approval, denied/*, priority violations) mapped from DATA `Status` / BPR.
- **FIXED 84**: 75 Active→Final (BPR Finaled/Closed or `STATUS_ORIGINAL` finaled* while Status lagged as APPROVED/ISSUED/blank); 9 Active→In Review (Status UNDER REVIEW / ON/HOLD).

### FILE_DATE

- Already populated for all 2,000 rows; every value matches DATA `Permit Date`.
- **FILLED 0 / FIXED 0**

### PERMIT_DATE

- Canonical source is `Permit Issued Date` only (reject `01/01/1900`).
- **FIXED 83**: cleared dates with blank/sentinel Issued (including 5 sentinel years). No Issued-present rows were missing PERMIT_DATE, so **FILLED 0**.
- Missing rose 167 → 250 because unsupported values were removed.
- After repair: Active 88.3% and Final 97.8% have PERMIT_DATE. Remaining Active/Final gaps (107) have blank Issued in DATA (mostly APPROVED / Building or Planning Approval pre-issuance; some Closed shells).

### FINAL_DATE

- Upstream FINAL_DATE matched `Final Inspection Date` when that field was set; many Final shells lacked it but had close-out, CO, or passed final inspections.
- **FILLED 259** on Final rows from those fallbacks.
- **FIXED 117**: cleared `01/01/1900` sentinels, FINAL_DATE on non-Final rows, and a few Final rows whose FINAL_DATE had no supporting DATA date.
- After repair: 950 / 1,137 Final rows (83.6%) have FINAL_DATE; non-Final rows have none. 187 Final rows still lack any usable final date in DATA.

## Repair performance (sample)

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 24 | 84 | 24 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 0 | 83 | 167 → 250 |
| FINAL_DATE | 259 | 117 | 1,204 → 1,050 |

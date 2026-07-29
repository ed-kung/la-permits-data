# Marina (CA) data repair

**Summary:** Assessed Marina's 2,000-row sample and wrote `agent/scripts/ca/data_repair_ca_marina.py`. Marina uses a civic portal scrape with list-page and detail-page JSON under `DATA`. Status mapping from `Status` / `Status:` is already correct for 1,989 rows; the repair fixes 26 stale statuses (21 Issued/Approved with passed Final* inspections → Final; 5 review-pipeline rows with Issue Date → Active). FILE_DATE was usually Issue Date or a mid-stream review Completion rather than earliest `Reviews[].Start` (286 FIXED, 6 FILLED). FINAL_DATE was missing on every row; 394 Final rows are filled from passed Final* or Residential Property Inspection Pass dates. PERMIT_DATE already matched parseable Issue Date wherever both existed (0 changes). Residual gaps lack Reviews / Issue Date / final inspection evidence in DATA.

## Jurisdiction selection

First `(JURISDICTION, STATE)` in `permits_ca_sample.parquet` without an existing `agent/scripts/{state}/data_repair_{state}_{city}.py`: **Marina, CA**.

## DATA schema

All 2,000 rows have DATA. Two payload families:

1. **List page** (`Status`, `Permit#`, top-level `Issue Date`) — often no nested Reviews/Inspections; top-level Issue Date is frequently work-description text from a column shift.
2. **Detail page** (`Status:`, `Permit Details`, optional `Reviews` / `Inspections` / form fields).

Inferred schemas:

| Schema | N | Notes |
| --- | ---: | --- |
| `list_with_work` | 931 | List page + Work Description |
| `portal_inspections` | 291 | Nonempty Inspections, no Reviews |
| `portal_reviews_inspections` | 225 | Nonempty Reviews + Inspections |
| `portal_form` | 209 | Building form fields, no Reviews/Inspections |
| `portal_basic` | 161 | Status: / Permit Details shell only |
| `list_simple` | 96 | List page, no Work Description |
| `portal_reviews` | 79 | Nonempty Reviews only |
| `portal_rpir` | 8 | RPI request form, no Reviews/Inspections |

Canonical mappings from DATA:

- `Status` / `Status:` → `STATUS_NORMALIZED` (with Final* inspection and Issue Date overrides)
- Earliest `Reviews[].Start` → `FILE_DATE`
- `Permit Details['Issue Date:']` (fallback: parseable top-level `Issue Date`) → `PERMIT_DATE`
- Latest passed inspection with type containing `Final` (fallback: Residential Property Inspection Pass) → `FINAL_DATE`

`Expiration Date:` is a validity window, not a completion date. Final Review Completion is a plan-review milestone (often coincides with issuance), not a building final.

## Findings by field

### STATUS_NORMALIZED

Before: Final 1,309 / Active 491 / Inactive 153 / In Review 36 / missing 11.

Raw status map is already correct when populated: Complete/Closed→Final, Issued/Approved→Active, Expired/Void/Withdrawn→Inactive, Under Review/Online Application Received/Pending/Continued→In Review.

Issues:

1. **Missing (11):** 3 garbage `Status` values (`Type: Project Description: Purpose:` column-shift junk); 8 blank `Status:` shells (mostly RPI / form detail pages). No mappable label in DATA → left missing.
2. **Stale Active (21):** Issued (20) / Approved (1) with a dated passed Final* inspection still Active → FIXED to Final.
3. **Stale In Review (5):** Online Application Received (2), Continued (2), Pending (1) with a real Issue Date → FIXED to Active.

Repair performance: **0 FILLED, 26 FIXED**; missing after: **11**.

After: Final 1,330 / Active 475 / Inactive 153 / In Review 31 / missing 11.

### FILE_DATE

Before: 1,702 missing (85.1%). Only 304 rows have any `Reviews[].Start`.

When present, FILE_DATE usually matched Issue Date or a mid-stream review Completion / Final Review Start rather than the earliest Start (286 of 298 disagree).

Repair: set to earliest `Reviews[].Start` → **6 FILLED, 286 FIXED**. Missing after: **1,696**. Coverage: **304 / 2,000 (15.2%)**.

Remaining gaps are almost all list_simple / list_with_work / portal shells with no Reviews — DATA has no application/submittal date. Four FILE > PERMIT inversions remain where agency Reviews Start after Issue Date (reopenings / revisions); repair mirrors DATA.

### PERMIT_DATE

Before: 171 missing. Where both present, every PERMIT_DATE matches a parseable Issue Date (1,821/1,821). Top-level Issue Date rejects ~91 work-description garbage strings.

Repair: **0 FILLED, 0 FIXED**. Active/Final gaps (52) are Approved/Complete/Closed shells with no parseable Issue Date in DATA. After status promotion, Active coverage **441 / 475 (92.8%)**; Final **1,312 / 1,330 (98.6%)**. In Review PERMIT_DATE coverage is 0% (review-pipeline rows with Issue Date were promoted to Active).

### FINAL_DATE

Before: 2,000 / 2,000 missing (100%).

Repair: **394 FILLED, 0 FIXED** from passed Final* inspections (362) or Residential Property Inspection Pass (32) on Final rows. Missing after: **1,606**.

Final coverage after repair: **394 / 1,330 (29.6%)**. No spurious FINAL_DATE on Active / In Review / Inactive. Remaining Final gaps are mostly Complete list_with_work shells (656) and portal_form shells (184) with empty Inspections.

## Repair script

`agent/scripts/ca/data_repair_ca_marina.py` — `data_repair(df)` overwrites incorrect/missing fields, adds `{FIELD}_FLAG` (`FILLED` / `FIXED`) and `INFERRED_SCHEMA`.

Status logic: Expired/Void/Withdrawn sticky Inactive; passed Final* inspection → Final; Complete/Closed → Final; Issue Date on In Review labels → Active; else Status/Status: map.

### Performance (n=2,000)

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | ---: | ---: | ---: | ---: |
| STATUS_NORMALIZED | 0 | 26 | 11 | 11 |
| FILE_DATE | 6 | 286 | 1,702 | 1,696 |
| PERMIT_DATE | 0 | 0 | 171 | 171 |
| FINAL_DATE | 394 | 0 | 2,000 | 1,606 |

### Artifact

`AGENT_DATA_PATH/repaired/permits_ca_marina_repaired.parquet`

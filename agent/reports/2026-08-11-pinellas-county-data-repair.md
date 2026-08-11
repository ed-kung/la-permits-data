# Pinellas County (FL) data repair

Summary: Pinellas County was the first FL sample jurisdiction without a repair script after Jacksonville, Lee County, Sarasota County, Osceola County, Orlando, Charlotte County, Pasco County, Miami-Dade County, and Cape Coral. Accela Citizen Access payloads expose status under `DATA.status` and dates under `DATA.date`, with issuance on `Permit Issuance` or (for Express permits) `Permit Review` Marked as Issued, and finalization from CO/COC Verification, Inspections task closeout, or approved Final inspection Status Dates. The repair remaps **68** lagged statuses and fills **17** previously null ones; leaves `FILE_DATE` unchanged (already 100% correct); recovers **251** missing `PERMIT_DATE` values (mostly Express `Permit Review` Issued); and recovers **1,394** missing `FINAL_DATE` values. After repair, Active rows have **100%** `PERMIT_DATE` coverage and Final rows have **95.9%** `FINAL_DATE` coverage. Remaining gaps are mostly legacy `accela_shell` Finaled rows with no issuance events, plus Administrative Close / Closed - Supp-Rev Approved rows without dated finalization signals, and 13 empty-status POS/registration stubs.

## Jurisdiction selected

- Sample file: `MY_DATA_PATH/processed_data/permits_fl_sample.parquet`
- First `(JURISDICTION, STATE)` without `agent/scripts/{state}/data_repair_{state}_{city}.py`: **Pinellas County, FL**
- Sample size: **2,002** records
- Script: `agent/scripts/fl/data_repair_fl_pinellas_county.py` (`data_repair`)

## DATA schemas (`INFERRED_SCHEMA`)

| Schema | n | Notes |
| --- | ---: | --- |
| `accela_shell` | 1,591 | Tasks present but no dated events (legacy / migrated histories; often still have `inspections`) |
| `accela_full` | 409 | Accela payload with `inspections` and at least one dated task event |
| `accela_basic` | 2 | Dated task events without an `inspections` array |

Canonical field sources:

- `DATA.status` (fallback: workflow marks when status is empty) → `STATUS_NORMALIZED`
- `DATA.date` / `search_data.Date` → `FILE_DATE`
- Earliest `Permit Issuance` Marked as Issued; else `Permit Review` Marked as Issued → `PERMIT_DATE`
- `CO/COC Verification` certificate issued; else `Inspections` Marked as Final Inspection Complete / Finaled; else approved Final inspection `Status Date` → `FINAL_DATE`

## Findings by field

### STATUS_NORMALIZED

- Before: Final 1,604; Inactive 192; Active 118; In Review 58; missing 30.
- Upstream `STATUS_NORMALIZED` follows `STATUS_ORIGINAL`, which lags `DATA.status` on **68** rows (e.g. ORIG=`issued` while Accela shows `Finaled` / `Expired` / `Closed - Finaled`).
- Of 30 null statuses, **16** were fillable from `DATA.status` (`Closed - Supp-Rev Approved`, `Missing Documents`, `Verified`, `Phase I Required`) and **1** empty-status revision was inferred as In Review from Application Intake marks. **13** empty-status POS Building / Milestone Inspection Registration stubs remain unmapped.
- Repair using `DATA.status`:
  - **17 FILLED** — Closed - Supp-Rev Approved→Final (7); Missing Documents / Verified / Phase I Required / empty-with-intake→In Review (10)
  - **68 FIXED** — mainly Active→Final on Finaled / Closed - Finaled / CofO / Administrative Close (38); Active→Inactive on Expired / Closed - Expired (16); In Review→Active on Issued (5); In Review→Inactive on Closed - Withdrawn / Expired (5); other Closed-* lags (4)
- After repair: Final 1,653; Inactive 212; Active 69; In Review 55; missing **13**.

### FILE_DATE

- Before: **0 missing (0.0%)**. All 2,002 values already matched parseable `DATA.date` (and `search_data.Date`) at day resolution.
- Repair: **0 FILLED**, **0 FIXED**.
- After: still fully populated for every non-null status bucket (100%).

### PERMIT_DATE

- Before: 1,932 missing (96.5%). Among Active/Final, coverage was weak (Active 40/118; Final 28/1,604). All **70** existing values already matched `Permit Issuance` Marked as Issued.
- Accela issuance signals: `Permit Issuance` Issued (77 rows) and Express-style `Permit Review` Issued (253 rows; disjoint from Permit Issuance).
- Repair: **251 FILLED** for Active/Final rows (244 from Permit Review, 7 from Permit Issuance); **0 FIXED**.
- After repair: Active **69/69 (100%)**; Final **241/1,653 (14.6%)**.
- Remaining Active/Final gaps (**1,412**, all Final): almost all `accela_shell` Finaled/CofO rows with empty task event histories, plus 25 `accela_full` Administrative Close / Closed - Supp-Rev Approved / Closed rows that never received an Issued mark. Not fillable from DATA.

### FINAL_DATE

- Before: 1,811 missing (90.5%). All **191** populated values were on Final rows and matched Inspections task Final Inspection Complete / Finaled (no spurious non-Final finals).
- Stronger / alternate finalization signals: CO/COC Verification certificate issued (rare); Inspections task closeout; approved Final inspection `Status Date` (dominant for shells).
- Repair: **1,394 FILLED** (1,346 from approved Final inspection Status Date; 38 from Inspections task closeout; 9 from other approved inspections; 1 from CO); **0 FIXED** (existing values already agreed with the preferred Accela source).
- After: Final **1,585/1,653 (95.9%)**; Active / In Review / Inactive have **0**.
- Remaining Final gaps (**68**): mostly Administrative Close (58) and Closed - Supp-Rev Approved (8) without CO / Inspections closeout or a passed Final inspection, plus 1 Finaled and 1 Closed shell.

## Repair performance

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | ---: | ---: | ---: | ---: |
| STATUS_NORMALIZED | 17 | 68 | 30 | 13 |
| FILE_DATE | 0 | 0 | 0 | 0 |
| PERMIT_DATE | 251 | 0 | 1,932 | 1,681 |
| FINAL_DATE | 1,394 | 0 | 1,811 | 417 |

Coverage after repair (share non-null):

| Status | n | FILE_DATE | PERMIT_DATE | FINAL_DATE |
| --- | ---: | ---: | ---: | ---: |
| Active | 69 | 100% | 100% | 0% |
| Final | 1,653 | 100% | 14.6% | 95.9% |
| In Review | 55 | 100% | 0% | 0% |
| Inactive | 212 | 100% | 5.2% | 0% |

## Artifacts

- Repair script: `agent/scripts/fl/data_repair_fl_pinellas_county.py`
- Summary JSON: `AGENT_DATA_PATH/pinellas_county/repair_summary.json`

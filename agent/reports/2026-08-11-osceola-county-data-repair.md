# Osceola County (FL) data repair

Summary: Osceola County was the first FL sample jurisdiction without a repair script after Jacksonville, Lee County, Sarasota County, and Alachua County. Accela Citizen Access payloads expose status under `DATA.status` and dates under `DATA.date`, Permit Issuance / CO Issuance task events, and inspection Status Dates. The repair fills all 81 missing `FILE_DATE` values, remaps 66 statuses (35 FILLED, 31 FIXED) where `STATUS_ORIGINAL` lagged Accela, adds 16 `PERMIT_DATE` values from Permit Issuance Issued, and recovers 504 missing `FINAL_DATE` values (plus 16 FIXED) from CO Issuance, Finaled tasks, and Final-titled inspections. Remaining Active/Final date gaps are mostly legacy `accela_shell` historical records and Closed/Complete code-enforcement rows with empty issuance or finalization history.

## Jurisdiction selected

- Sample file: `MY_DATA_PATH/processed_data/permits_fl_sample.parquet`
- First `(JURISDICTION, STATE)` without `agent/scripts/{state}/data_repair_{state}_{city}.py`: **Osceola County, FL**
- Sample size: **2,001** records

## DATA schemas (`INFERRED_SCHEMA`)

| Schema | n | Notes |
| --- | ---: | --- |
| `accela_full` | 1,232 | Accela payload with `inspections` and at least one dated task event |
| `accela_shell` | 768 | Tasks present but no dated events (legacy AA CONV / thin histories) |
| `accela_basic` | 1 | Dated task events without an `inspections` array |

Canonical field sources:

- `DATA.status` → `STATUS_NORMALIZED`
- `DATA.date` / `search_data.Date` → `FILE_DATE`
- Earliest Permit Issuance / Issuance Marked as Issued → `PERMIT_DATE`
- CO Issuance Approved/Issued; else Inspections Finaled/Final; else max(Final-titled inspection Status Date, Inspections Approved task) → `FINAL_DATE`

## Findings by field

### STATUS_NORMALIZED

- Before: Final 1,161; Active 515; missing 163; In Review 85; Inactive 77.
- Upstream `STATUS_NORMALIZED` follows `STATUS_ORIGINAL`, which lags `DATA.status` on **30** rows (e.g. ORIG=`issued` while Accela shows `Final` / `CO` / `Expired`).
- Missing statuses were mostly empty-status Historical Building rows (128) plus unmapped enforcement / administrative codes (Collections, Citation, Adjudicated, RELEASED, etc.).
- Repair using `DATA.status`:
  - **35 FILLED** (Active - About to Expire, Adjudicated, Citation, Collections, CO, Closed disaster assessments, RELEASED bonds, etc.)
  - **31 FIXED** — mainly Active/In Review → Final when Accela shows `Final` / `CO` / `Finaled` / `Complied`; Active → Inactive for lagged `Expired`; In Review → Active for `Over the Counter` / `Issued` / `Approved with Conditions`
- After repair: Final 1,194; Active 501; missing **128**; Inactive 96; In Review 82.
- Remaining missing: all 128 are Historical Building with empty `DATA.status` and empty `search_data.Status` → not fillable from DATA.

### FILE_DATE

- Before: 81 missing (4.0%). Every row has a parseable `DATA.date`; existing non-null values already matched at day resolution (0 mismatches).
- Repair: **81 FILLED**, **0 FIXED**. After repair: **0 missing**; 100% coverage for every non-null status bucket.

### PERMIT_DATE

- Before: 1,679 missing (83.9%). Among Active/Final, 1,362 missing.
- Only **323** rows have a Permit Issuance / Issuance Marked as Issued event; 316 of those already matched the existing `PERMIT_DATE`.
- Repair: **16 FILLED** for Active/Final rows with Issued but null permit; **0 FIXED** (no calendar mismatches vs Issued).
- After repair: Active **53/501 (10.6%)**; Final **276/1,194 (23.1%)**.
- Remaining gaps: Historical Building / Historical Fire / Historical Enforcement `accela_shell` Approvals with empty task events; Closed code violations and Complete lien/BAC requests (not true issued building permits); Building/trade permits whose Permit Issuance task exists but has an empty event list (legacy conversion).

### FINAL_DATE

- Before: 1,862 missing; among status=Final, 1,022/1,161 missing (88.0%). All 139 existing finals were already on Final rows (none on Active/In Review/Inactive).
- Upstream finals usually matched Inspections Approved / Approved Unconditionally Status Dates; CO Issuance Approved was present but unused on many CO-status building permits.
- Repair: **504 FILLED** from CO Issuance, Inspections Finaled/Final, Final-titled inspection Status Dates, and Inspections Approved task dates; **16 FIXED** where a later Final inspection / Finaled event superseded an earlier partial closeout date.
- Avoided Accela conversion noise by excluding Partial* inspection statuses (some carry `Status Date` = 2018-02-10 migration timestamps).
- After repair: Final **643/1,194 (53.9%)**; non-Final statuses have 0 `FINAL_DATE`.
- Remaining Final gaps: Closed/Complete Code Violation, Lien Verification Request, BAC Request, Parking Violation, and similar non-building workflows with no CO / Final inspection evidence; a handful of Finaled building/trade permits with empty inspections and empty finalization tasks.

## Repair performance

Script: `agent/scripts/fl/data_repair_fl_osceola_county.py` (`data_repair`)

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | ---: | ---: | ---: | ---: |
| STATUS_NORMALIZED | 35 | 31 | 163 | 128 |
| FILE_DATE | 81 | 0 | 81 | 0 |
| PERMIT_DATE | 16 | 0 | 1,679 | 1,663 |
| FINAL_DATE | 504 | 16 | 1,862 | 1,358 |

Coverage after repair (share non-null):

| Status | n | FILE_DATE | PERMIT_DATE | FINAL_DATE |
| --- | ---: | ---: | ---: | ---: |
| Active | 501 | 100% | 10.6% | 0% |
| Final | 1,194 | 100% | 23.1% | 53.9% |
| In Review | 82 | 100% | 0% | 0% |
| Inactive | 96 | 100% | 9.4% | 0% |

## Not repairable from DATA

- 128 Historical Building rows with blank `DATA.status` → `STATUS_NORMALIZED` stays missing.
- `accela_shell` historical Approvals and legacy Permit Issuance shells with empty events → no `PERMIT_DATE`.
- Closed/Complete code-enforcement, lien verification, and BAC rows → typically no issuance or building finalization dates in DATA.
- Finaled building/trade permits with neither CO Issuance nor Final-titled / Approved inspection evidence → `FINAL_DATE` stays missing.

## Artifacts

- Repair script: `agent/scripts/fl/data_repair_fl_osceola_county.py`
- No derived parquet written; run the script’s `__main__` block for live stats.

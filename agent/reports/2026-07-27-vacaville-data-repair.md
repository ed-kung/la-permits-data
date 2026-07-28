# Vacaville (CA) data repair

**Summary:** Vacaville was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. Assessed and repaired `STATUS_NORMALIZED`, `FILE_DATE`, `PERMIT_DATE`, and `FINAL_DATE` from the civic-portal `DATA` JSON (`permit_info` / `search_data`). Status is now fully populated (**FILLED 1 · FIXED 7**): stale `STATUS_ORIGINAL` lags behind `PermitStatus` (FINALED still labeled issued; ISSUED still labeled ready-to-issue/applied), plus ONLINE SUBMITTAL null and FEE ESTIMATE mis-mapped to Inactive. `FILE_DATE` already matched `PermitAppliedDate` for all 2,000 rows (no changes). `PERMIT_DATE` missingness fell from **81 → 76** (**FILLED 5**), using Issued and Approved for Active/Final rows. `FINAL_DATE` missingness fell from **659 → 652** (**FILLED 8 · FIXED 1**), filling from `PermitFinaledDate` / passed FINAL inspections and clearing a spurious CANCELED close date. Remaining gaps are mostly legacy admin-fee / interim-development shells with blank finaling dates.

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_ca_sample.parquet`
- Jurisdiction: **Vacaville, CA** (n=2,000)
- Script: `agent/scripts/ca/data_repair_ca_vacaville.py` (`data_repair`)
- Artifact: `AGENT_DATA_PATH/vacaville_repaired_sample.parquet`

## DATA schema (`INFERRED_SCHEMA`)

All records share top-level keys `fees`, `contacts`, `site_info`, `inspections`, `permit_info`, `search_data`. Sub-schemas reflect which `permit_info` dates are populated:

| Schema | n | Description |
| --- | ---: | --- |
| `permit_info_issued_finaled` | 1,341 | Issued + Finaled present |
| `permit_info_issued` | 580 | Issued present, Finaled blank |
| `permit_info_applied_only` | 66 | Only Applied populated |
| `permit_info_approved_only` | 10 | Approved present, Issued/Finaled blank |
| `permit_info_finaled_only` | 3 | Finaled present, Issued blank |

Canonical fields:

| Field | Source |
| --- | --- |
| `STATUS_NORMALIZED` | `permit_info.PermitStatus` (prefer Final when non-inactive and `PermitFinaledDate` present) |
| `FILE_DATE` | `PermitAppliedDate` |
| `PERMIT_DATE` | `PermitIssuedDate`; else `search_data.ISSUED`; else `PermitApprovedDate` |
| `FINAL_DATE` | `PermitFinaledDate`; else `search_data.FINALED`; else latest passed FINAL inspection `Completed` |

## Field assessment

### STATUS_NORMALIZED

**Before:** Final 1,385 · Active 501 · Inactive 83 · In Review 30 · missing 1

`PermitStatus` maps cleanly for nearly all rows. Issues were concentration of stale `STATUS_ORIGINAL` vs current `PermitStatus`, plus two mapping gaps:

| Change | n | Reason |
| --- | ---: | --- |
| FINALED: Active → Final | 3 | `STATUS_ORIGINAL=issued` lagged `PermitStatus=FINALED` (and `PermitFinaledDate` present) |
| ISSUED: In Review → Active | 2 | `STATUS_ORIGINAL` still ready-to-issue / applied |
| INSPECTION PHASE: Active → Final | 1 | Non-inactive row with `PermitFinaledDate` |
| FEE ESTIMATE: Inactive → In Review | 1 | Fee estimate is not a terminal inactive status |
| ONLINE SUBMITTAL: null → In Review | 1 | Unmapped original status |

**After:** Final 1,389 · Active 499 · Inactive 82 · In Review 30 · missing 0  
Flags: **FILLED 1 · FIXED 7**

### FILE_DATE

**Before:** 0 missing (100%).

- Every row’s `FILE_DATE` equals `PermitAppliedDate`.

**After:** still 0 missing.  
Flags: **FILLED 0 · FIXED 0**

### PERMIT_DATE

**Before:** 81 missing (4.0%). Among Active/Final: 5 / 1,886 missing.

Root cause: upstream skipped rows where `PermitIssuedDate` was blank even when `PermitApprovedDate` (or a later ISSUED status) was available; also two ISSUED rows kept In Review (so issuance was ignored).

Repairs (Active / Final only):
1. Prefer `PermitIssuedDate` / `search_data.ISSUED`.
2. Else `PermitApprovedDate`.

**After:** 76 missing. Active 499/499 (100%); Final 1,387/1,389 (99.9%).  
Flags: **FILLED 5 · FIXED 0**

Not repairable: 2 Final FINALED attic-insulation rows with blank Issued and Approved.

### FINAL_DATE

**Before:** 659 missing. Among Final: 46 / 1,385 missing. Two non-Final rows carried a `FINAL_DATE` (CANCELED close timestamp; INSPECTION PHASE with finaled date).

Repairs:
1. Remap finaled Active/INSPECTION rows to Final, then FILL from `PermitFinaledDate` (3 + keep 1 already present).
2. FILL 5 legacy Final rows from passed `FINAL INSPECTION` `Completed`.
3. Clear spurious FINAL on Inactive CANCELED (FIXED).

**After:** 652 missing. Final 1,348 / 1,389 (97.0%); Active/In Review/Inactive all 0%.  
Flags: **FILLED 8 · FIXED 1**

Not repairable: 41 Final rows — mostly `ADMINISTRATIVE PLAN CHECK FEE` (22) and `INTERIM DEVELOPMENT FEES` (13) — with blank `PermitFinaledDate` and no dated final inspection.

## Performance summary

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| `STATUS_NORMALIZED` | 1 | 7 | 1 → 0 |
| `FILE_DATE` | 0 | 0 | 0 → 0 |
| `PERMIT_DATE` | 5 | 0 | 81 → 76 |
| `FINAL_DATE` | 8 | 1 | 659 → 652 |

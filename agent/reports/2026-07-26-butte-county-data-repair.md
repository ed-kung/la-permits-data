# Butte County (CA) data repair

**Summary:** Butte County was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. Assessed and repaired `STATUS_NORMALIZED`, `FILE_DATE`, `PERMIT_DATE`, and `FINAL_DATE` from the GIS / open-data portal `DATA` JSON (`permit_info` + `inspections`). Status changes were small (**FILLED 6 · FIXED 1**): six blank-status shells with only an Applied date became In Review, and one `ISSUED CWIF DUE` row moved from In Review → Active. `FILE_DATE` missingness fell from **651 → 27** (**FILLED 624**) by using `PermitIssuedDate` when legacy rows lack `PermitAppliedDate`. `PERMIT_DATE` missingness fell from **214 → 181** (**FILLED 33**), mainly Approved / Issued fills on Active and Final rows. `FINAL_DATE` gained **7** inspection-based fills on Final rows and cleared **17** spurious finals on EXPIRED (Inactive) rows. Remaining gaps are mostly CLOSED / COMPLETED shells with no Finaled date or final inspection, plus empty archive stubs.

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_ca_sample.parquet`
- Jurisdiction: **Butte County, CA** (n=1,999)
- Script: `agent/scripts/ca/data_repair_ca_butte_county.py` (`data_repair`)
- Artifact: `AGENT_DATA_PATH/butte_county_repaired_sample.parquet`

## DATA schema (`INFERRED_SCHEMA`)

All records share top-level keys `contacts`, `fees`, `inspections`, `permit_info`, `search_data`, `site_info` (same family as Shasta County). Sub-schemas reflect which date sources are populated:

| Schema | n | Description |
| --- | ---: | --- |
| `permit_info_dates_only` | 1,114 | Empty inspections; Issued / Approved / Finaled present |
| `permit_info_with_inspections` | 734 | Non-empty `inspections` list |
| `permit_info_applied_only` | 125 | Only `PermitAppliedDate` |
| `permit_info_empty` | 26 | No usable applied / issued / approved / finaled dates |

Canonical fields:

| Field | Source |
| --- | --- |
| `STATUS_NORMALIZED` | `permit_info.PermitStatus` (date fallback when blank) |
| `FILE_DATE` | `PermitAppliedDate`; else `PermitIssuedDate` (legacy) |
| `PERMIT_DATE` | `PermitIssuedDate`; else `PermitApprovedDate` |
| `FINAL_DATE` | `PermitFinaledDate`; else latest passed final-type inspection |

## Field assessment

### STATUS_NORMALIZED

**Before:** Final 1,291 · Active 319 · Inactive 320 · In Review 40 · missing 29

Upstream mapping from `PermitStatus` was already consistent for nearly every labeled row:

| `PermitStatus` | Upstream `STATUS_NORMALIZED` | Repair mapping |
| --- | --- | --- |
| FINALED, CLOSED, COMPLETED/Completed | Final | Final |
| ISSUED, APPROVED, RECEIPT ISSUED | Active | Active |
| ISSUED CWIF DUE | In Review | **Active** (has Issued date) |
| APPLIED, UNDER REVIEW, WAITING ON CUSTOMER, RENEWABLE | In Review | In Review |
| EXPIRED, VOID, CANCELLED, REFUND REQ RECD | Inactive | Inactive |
| (blank) | missing | In Review if Applied only; else leave missing |

Issues repaired:
1. **1 FIXED:** `ISSUED CWIF DUE` was In Review despite `PermitIssuedDate` → Active.
2. **6 FILLED:** blank `PermitStatus` with only `PermitAppliedDate` → In Review.
3. **23 blank shells** remain missing (no status, no usable dates).

**After:** Final 1,291 · Active 320 · Inactive 320 · In Review 45 · missing 23  
Flags: **FILLED 6 · FIXED 1**

### FILE_DATE

**Before:** 651 missing (32.6%).

- When `PermitAppliedDate` is present, `FILE_DATE` already matched it (0 mismatches).
- All 651 missing rows have empty Applied; **624** have `PermitIssuedDate` (mostly 1979–2002 legacy CRW records).
- Remaining 27 lack Applied and Issued (26 empty stubs + 1 FINALED with only FinaledDate).

Repairs: fill from Applied when present; else Issued.

**After:** 27 missing (98.6% coverage).  
Flags: **FILLED 624 · FIXED 0**

### PERMIT_DATE

**Before:** 214 missing (10.7%). Among Active/Final: 103 / 1,610 missing.

Root cause: upstream populated Issued when present, but skipped Approved-only Active rows (APPROVED) and a handful of Final shells with Approved but empty Issued. One ISSUED row also had Issued present but null `PERMIT_DATE`.

Repairs (Active / Final only): prefer Issued, else Approved.

**After:** 181 missing. Active 317/320 (99.1%); Final 1,224/1,291 (94.8%).  
Flags: **FILLED 33 · FIXED 0**

Remaining Active/Final gaps (70) are mostly CLOSED / COMPLETED / FINALED / RECEIPT ISSUED shells with neither Issued nor Approved in `permit_info`.

### FINAL_DATE

**Before:** 929 missing (46.5%). Among Final: 238 / 1,291 missing. Inactive had 17 spurious finals.

Issues:
1. **238 Final rows** lack `PermitFinaledDate`. Almost all are CLOSED (205), Completed/COMPLETED (25), or FINALED (8). Only **7** have a usable passed final-type inspection (`PERMIT FINAL`, `BUILDING FINAL`, `ELECTRICAL FINAL`, `PW FINAL`, etc.).
2. **17 EXPIRED (Inactive)** rows carried `PermitFinaledDate` / `FINAL_DATE`. Treated as expire/close timestamps, not completion → cleared; status stays Inactive.

**After:** Final 1,060/1,291 (82.1%) have FINAL_DATE; Active / In Review / Inactive all 0. Missing overall 939 (net rise from clearing Inactive).  
Flags: **FILLED 7 · FIXED 17**

## Repair performance summary

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 6 | 1 | 29 → 23 |
| FILE_DATE | 624 | 0 | 651 → 27 |
| PERMIT_DATE | 33 | 0 | 214 → 181 |
| FINAL_DATE | 7 | 17 | 929 → 939 |

## Not repairable from DATA

- ~231 Final CLOSED / COMPLETED / FINALED shells: no FinaledDate and no usable final inspection.
- ~70 Active/Final rows: no Issued or Approved date (especially CLOSED fee-estimate / admin shells).
- 23–26 empty `PermitStatus` archive stubs with no dates.
- 1 FINALED row with only FinaledDate (no Applied/Issued for FILE_DATE).

# St. Cloud (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script was St. Cloud. Its DATA is an Accela/eTRAKiT-style portal payload (`fees` / `contacts` / `site_info` / `inspections` / `permit_info` / `search_data`) with canonical status and dates under `permit_info`. Repair filled all 32 null `STATUS_NORMALIZED` values, fixed 3 Active rows that already had `PermitFinaledDate` to Final, filled 121 missing `PERMIT_DATE` values from `PermitApprovedDate` when Issued was blank, and cleared `FINAL_DATE` from 14 Inactive rows. `FILE_DATE` was already complete and correct. Remaining gaps are CLOSED Finals that omit issuance and/or finaled stamps in DATA.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` and walked `(JURISDICTION, STATE)` in first-appearance order. St. Cloud was the first pair without `agent/scripts/fl/data_repair_fl_st_cloud.py`.

## DATA shape

All 2,000 rows share the same top-level Accela keyset. `INFERRED_SCHEMA` variants reflect which `permit_info` dates are populated:

| Schema | n | Notes |
| --- | ---: | --- |
| `accela_finaled` | 1,596 | `PermitFinaledDate`, no issued |
| `accela_issued` | 175 | issued, no finaled |
| `accela_issued_finaled` | 124 | issued + finaled |
| `accela_approved` | 71 | approved only (no issued/finaled) |
| `accela_applied` | 34 | applied only |

Canonical sources:

| Field | DATA source |
| --- | --- |
| STATUS_NORMALIZED | `permit_info.PermitStatus`; blank status inferred from dates; Active-family + `PermitFinaledDate` → Final |
| FILE_DATE | `PermitAppliedDate` |
| PERMIT_DATE | `PermitIssuedDate`; else `PermitApprovedDate` (Active/Final) |
| FINAL_DATE | `PermitFinaledDate`; else (Final only) latest passed final-ish / passed inspection |

## Field assessments

### STATUS_NORMALIZED

Before: Final 1,804; Active 125; In Review 26; Inactive 13; **32 null**.

Null causes:
- 28 blank `PermitStatus` (mostly RIGHT OF WAY with `PermitApprovedDate`, plus 1 garage-sale applied-only)
- 2 `IN APPROVAL` (unmapped upstream)
- 2 `ABANDONED APPLICATION` (unmapped upstream)

Also incorrect: 3 `PERMIT ISSUED` / `PERMIT PRINTED` rows labeled Active while `PermitFinaledDate` was set (and upstream `FINAL_DATE` already matched).

After: Final 1,807; Active 149; In Review 29; Inactive 15; **0 null**. Flags: **32 FILLED, 3 FIXED**.

### FILE_DATE

Before: **0 missing**. Every value equals `PermitAppliedDate` (2,000/2,000). No fills or fixes.

After coverage: 100% for all status classes.

### PERMIT_DATE

Before: 1,701 missing. When present, every value equals `PermitIssuedDate` (299/299, 0 mismatches).

Fillable gaps: 121 Active/Final rows with blank Issued but populated `PermitApprovedDate` (42 newly Active blank-status / APPROVED shells + 79 Final CLOSED/FINALED). No Issued stamps were left unused.

Not fillable: 1,540 Active/Final CLOSED rows with neither Issued nor Approved in DATA.

Flags: **121 FILLED, 0 FIXED**. After: Active 149/149 (100%); Final 267/1,807 (14.8%).

Six `FILE_DATE` > `PERMIT_DATE` day inversions remain (4 pre-existing Issued earlier than Applied; 2 from Approved-before-Applied agency stamps). Dates match DATA; not rewritten.

### FINAL_DATE

Among Final rows, 1,703 already matched `PermitFinaledDate`; 101 CLOSED Finals had blank `PermitFinaledDate` and no usable passed inspections → still missing.

Non-Final cleanup: 14 Inactive rows carried `FINAL_DATE` from void/revoked/abandoned closeout stamps → cleared (`FIXED`). The 3 Active→Final transitions kept their existing finaled dates (no flag).

Flags: **0 FILLED, 14 FIXED**. Final coverage after repair: 1,706/1,807 (94.4%).

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 32 | 3 | 32 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 121 | 0 | 1,701 → 1,580 |
| FINAL_DATE | 0 | 14 | 280 → 294 |

Ideal-coverage gaps remaining:

- FILE_DATE: **none**
- Active/Final missing PERMIT_DATE: **1,540** (CLOSED shells with no Issued/Approved in DATA)
- Final missing FINAL_DATE: **101** (CLOSED with blank `PermitFinaledDate` and no passed inspection)
- STATUS_NORMALIZED: **none**

## Artifacts

- Repair script: `agent/scripts/fl/data_repair_fl_st_cloud.py`
- Repaired sample: `$AGENT_DATA_PATH/repaired/permits_fl_st_cloud_repaired.parquet`

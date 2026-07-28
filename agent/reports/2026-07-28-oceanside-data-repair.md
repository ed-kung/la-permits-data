# Oceanside (CA) data repair — 2026-07-28

Oceanside was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. Civic-portal JSON under `DATA` already has correct `FILE_DATE` and, when populated, correct `PERMIT_DATE` / `FINAL_DATE` matching `permit_info`. Main issues were stale `STATUS_NORMALIZED` (STATUS_ORIGINAL lagged `PermitStatus`: FINALED still Active, ISSUED still In Review), missing `PERMIT_DATE` on Active/Final rows with Issued or Approved available, and missing `FINAL_DATE` on Final rows after status correction. Repair fills/fixes 21 statuses, 47 permit dates, and 10 final dates; residual gaps are empty RECEIVED shells and a few FINALED rows without issuance/finaled timestamps.

## Jurisdiction selection

Walked `(JURISDICTION, STATE)` pairs in sample order and compared against `agent/scripts/{state}/data_repair_{state}_{city}.py`. First missing: **Oceanside, CA** → `agent/scripts/ca/data_repair_ca_oceanside.py` (n=2,001).

## DATA schema

All rows share civic-portal top-level keys (`fees`, `contacts`, `site_info`, `inspections`, `permit_info`, `search_data`). Canonical dates/status live under `permit_info` (`PermitStatus`, `PermitAppliedDate`, `PermitIssuedDate`, `PermitApprovedDate`, `PermitFinaledDate`); `search_data.Status` / `Application` mirror status and applied date. Content variants recorded in `INFERRED_SCHEMA`:

| Schema | n | Description |
| --- | ---: | --- |
| `permit_info_issued_finaled` | 1,233 | Issued + Finaled present |
| `permit_info_issued` | 497 | Issued present, Finaled blank |
| `permit_info_applied_only` | 205 | Only Applied populated |
| `permit_info_approved_only` | 45 | Approved present, Issued/Finaled blank |
| `permit_info_finaled_only` | 16 | Finaled present, Issued blank |
| `permit_info_empty_dates` | 3 | Status/type text, no usable dates |
| `legacy_no_status` | 1 | Blank `PermitStatus`, Applied present |
| `permit_info_empty` | 1 | Blank `permit_info` shell |

## Field assessment

### STATUS_NORMALIZED

- Missing on 2 / 2,001: one blank-status CERT OF CORRECTION with Applied (`CA10-00005`); one empty FIRE shell (`FIRE13-0372`).
- When `STATUS_ORIGINAL` matches `DATA.permit_info.PermitStatus`, existing normalization is consistent (FINALED → Final; ISSUED/APPROVED → Active; RECEIVED/UNDER REVIEW/PAID/UNPAID/READY TO BILL/RTRND FOR CORRECTION/NSF-RTND CHECK → In Review; EXPIRED/WITHDRAWN/VOID/CANCELED/DENIED → Inactive).
- **Issue:** 20 rows where `STATUS_ORIGINAL` lagged `PermitStatus` (e.g. `issued` while DATA is `FINALED`; `received` while DATA is `ISSUED` or `APPROVED`; `under review` while DATA is `WITHDRAWN`), plus 2 ISSUED / 1 UNDER REVIEW rows carrying `PermitFinaledDate` that should be Final.
- **Repair:** map from `PermitStatus` (plus Final override when non-inactive `PermitFinaledDate` present; blank-status inference from Applied → In Review) → **1 FILLED**, **20 FIXED**. Missing after: 1 (empty FIRE shell).

Status transitions: Active→Final 10; In Review→Active 9; In Review→Inactive 1; null→In Review 1.

### FILE_DATE

- Missing on 4 / 2,001 (0.2%). Present values match `PermitAppliedDate` on all 1,997 rows with Applied populated (0 incorrect).
- The 4 gaps also lack `search_data.Application`; no safe application date in `DATA` (3 RECEIVED shells + 1 empty FIRE shell).
- **Repair:** no changes (0 FILLED / 0 FIXED). Coverage remains 99.8%.

### PERMIT_DATE

- Missing on 280 / 2,001 (14.0%). When present, every value matches `PermitIssuedDate` (0 incorrect).
- Among Active/Final before repair: Active 413/437 present, Final 1,226/1,245 present.
- Recoverable gaps: Active APPROVED rows with only `PermitApprovedDate`; Final FINALED rows with blank Issued but populated Approved; ISSUED rows whose status was corrected from In Review to Active (Issued was present but status gate blocked fill).
- **Repair:** **47 FILLED**, **0 FIXED**. Missing after: 233.
- Post-repair Active PERMIT coverage: 436/436 (100%); Final: 1,250/1,255 (99.6%). Remaining 5 Final gaps lack both Issued and Approved in `DATA`.

### FINAL_DATE

- Missing on 760 / 2,001 (38.0%). When present, every value matches `PermitFinaledDate` (0 incorrect vs that field).
- Among Final before repair: 1,238/1,245 had `FINAL_DATE`. Eight Final-after-repair rows had `PermitFinaledDate` but null `FINAL_DATE` because status was still Active from stale `STATUS_ORIGINAL`.
- One FINALED row (`BLDG12-1789`) lacked `PermitFinaledDate` but had a passed `**905 FINAL SFR` inspection → filled from inspection.
- One Inactive EXPIRED row carried a spurious `FINAL_DATE` → cleared.
- Two ISSUED rows with `PermitFinaledDate` were promoted to Final and keep their existing `FINAL_DATE`.
- **Repair:** **9 FILLED**, **1 FIXED** (clear). Missing after: 752.
- Post-repair Final FINAL coverage: 1,249/1,255 (99.5%). Remaining 6 Final gaps are FINALED without `PermitFinaledDate` or a usable final inspection.

## Repair performance

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | ---: | ---: | ---: | ---: |
| STATUS_NORMALIZED | 1 | 20 | 2 | 1 |
| FILE_DATE | 0 | 0 | 4 | 4 |
| PERMIT_DATE | 47 | 0 | 280 | 233 |
| FINAL_DATE | 9 | 1 | 760 | 752 |

Status distribution after repair: Final 1,255 · Active 436 · In Review 205 · Inactive 104 · missing 1.

Post-repair completeness by status:

| Status | FILE_DATE | PERMIT_DATE | FINAL_DATE |
| --- | ---: | ---: | ---: |
| Active | ~100% | 100% | 0% |
| Final | ~100% | 99.6% | 99.5% |
| In Review | ~98.5% | 18.0% | 0% |
| Inactive | ~100% | 43.3% | 0% |

Chronology: 6 `PERMIT < FILE` and 3 `FINAL < PERMIT` cases remain; all mirror inverted dates already present in `permit_info` (not introduced by repair).

## Artifacts

- Script: `agent/scripts/ca/data_repair_ca_oceanside.py` (`data_repair`)
- Repaired sample: `$AGENT_DATA_PATH/repaired/permits_ca_oceanside_repaired.parquet`

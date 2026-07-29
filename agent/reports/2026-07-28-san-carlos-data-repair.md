# San Carlos (CA) data repair — 2026-07-28

San Carlos was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. Civic-portal JSON under `DATA` already has correct `FILE_DATE` on all 2,000 rows (matches `PermitAppliedDate` / `search_data.Application`) and correct `PERMIT_DATE` / `FINAL_DATE` whenever those were populated from Issued / Finaled. Main issues were 26 blank-`PermitStatus` ENCROACHMENT shells with missing `STATUS_NORMALIZED`, stale `STATUS_ORIGINAL` lagging `PermitStatus` (FINALED still Active/In Review; ISSUED/APPROVED still In Review), non-inactive rows with `PermitFinaledDate` that should be Final (INSPECTION, F5, ISSUED), missing `PERMIT_DATE` on Active/Final when Issued or Approved is available, missing `FINAL_DATE` on Final rows fillable from Finaled or passed final inspections, and spurious `FINAL_DATE` on Inactive CANCELLED. Repair fills/fixes 54 statuses, 46 permit dates, and 41 final dates; residual gaps lack Issued / Approved / Finaled (or a passed final inspection) in `DATA`.

## Jurisdiction selection

Walked `(JURISDICTION, STATE)` pairs in sample order and compared against `agent/scripts/{state}/data_repair_{state}_{city}.py`. First missing: **San Carlos, CA** → `agent/scripts/ca/data_repair_ca_san_carlos.py` (n=2,000). Prior pairs (Los Altos, San Luis Obispo County) already had repair scripts.

## DATA schema

All rows share civic-portal top-level keys (`fees`, `contacts`, `site_info`, `inspections`, `permit_info`, `search_data`). Canonical dates/status live under `permit_info` (`PermitStatus`, `PermitAppliedDate`, `PermitIssuedDate`, `PermitApprovedDate`, `PermitFinaledDate`). `search_data` has Application / Issued / Permit Number / Site Address / RECORDID. Content variants recorded in `INFERRED_SCHEMA`:

| Schema | n | Description |
| --- | ---: | --- |
| `permit_info_issued_finaled` | 1,236 | Issued + Finaled present |
| `permit_info_issued` | 460 | Issued present, Finaled blank |
| `permit_info_applied_only` | 128 | Only Applied populated |
| `permit_info_finaled_only` | 121 | Finaled present, Issued blank |
| `permit_info_approved_only` | 29 | Approved present, Issued/Finaled blank |
| `legacy_no_status` | 26 | Blank `PermitStatus`, Applied present |

## Field assessment

### STATUS_NORMALIZED

- Missing on 26 / 2,000: blank `PermitStatus` and blank `STATUS_ORIGINAL` (ENCROACHMENT 21, PROPERTY CHANGE 2, MEP / commercial / residential 3). All have Applied only → In Review.
- When `STATUS_ORIGINAL` matches `PermitStatus`, mapping is already correct: `finaled`/`closed`→Final, `issued`/`approved`/`active`/`inspection`→Active, `under review`/`received`/`hold`/`f5`→In Review, `cancelled`/`expired`→Inactive.
- **Issue:** 18 rows where `STATUS_ORIGINAL` lagged `PermitStatus` (FINALED still Active/In Review; APPROVED/ISSUED still In Review). Separately, 26 non-inactive rows carry `PermitFinaledDate` while status is INSPECTION / F5 / ISSUED / FINALED-lag → should be Final.
- **Repair:** map from `PermitStatus` (including San Carlos labels ACTIVE, INSPECTION, F5, HOLD, CLOSED); promote non-inactive rows with `PermitFinaledDate` to Final; blank-status inferred from Applied → **26 FILLED**, **28 FIXED**. Missing after: 0.

Status transitions: null→In Review 26; Active→Final 20; In Review→Final 6; In Review→Active 2.

### FILE_DATE

- Missing on 0 / 2,000. Present values match `PermitAppliedDate` (and `search_data.Application`) on all rows (0 incorrect).
- **Repair:** no changes (0 FILLED / 0 FIXED). Coverage remains 100%.

### PERMIT_DATE

- Missing on 306 / 2,000 (15.3%). When present, every value matches `PermitIssuedDate` (0 incorrect vs Issued).
- Among Active/Final before repair: Active 408/467 present (87.4%), Final 1,231/1,348 present (91.3%). Recoverable: Active APPROVED with Approved (20); Active/Final with Issued missing `PERMIT_DATE` (2 ISSUED); Final FINALED with Approved only (18); status-promoted rows with Issued/Approved.
- **Repair:** **46 FILLED**, **0 FIXED**. Missing after: 260.
- Post-repair Active PERMIT coverage: 416/449 (92.7%); Final: 1,272/1,374 (92.6%). Remaining Active/Final gaps (135) lack both Issued and Approved (FINALED 101, ISSUED 21, ACTIVE 12, CLOSED 1).

### FINAL_DATE

- Missing on 658 / 2,000 (32.9%). When present, every value matches `PermitFinaledDate` (0 incorrect vs that field).
- Among Final before repair: 1,318/1,348 had `FINAL_DATE`. Thirty FINALED/CLOSED rows lacked Finaled; 13 are fillable from passed final inspections (`**FINAL BUILDING` PASS / Result `FIN`); 17 lack both Finaled and a usable passed final inspection. Fifteen status-promoted rows had Finaled with null `FINAL_DATE`. Thirteen Inactive CANCELLED carried spurious `FINAL_DATE` → cleared. Eleven other non-Final rows with Finaled already had `FINAL_DATE` and become Final via status promotion.
- **Repair:** **28 FILLED**, **13 FIXED** (clears). Missing after: 643.
- Post-repair Final FINAL coverage: 1,357/1,374 (98.8%). Remaining 17 Final gaps have blank Finaled and no passed final inspection.

## Repair performance

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | ---: | ---: | ---: | ---: |
| STATUS_NORMALIZED | 26 | 28 | 26 | 0 |
| FILE_DATE | 0 | 0 | 0 | 0 |
| PERMIT_DATE | 46 | 0 | 306 | 260 |
| FINAL_DATE | 28 | 13 | 658 | 643 |

Status distribution after repair: Final 1,374 · Active 449 · In Review 97 · Inactive 80 · missing 0.

Post-repair completeness by status:

| Status | n | FILE_DATE | PERMIT_DATE | FINAL_DATE |
| --- | ---: | ---: | ---: | ---: |
| Active | 449 | 100% | 92.7% | 0% |
| Final | 1,374 | 100% | 92.6% | 98.8% |
| In Review | 97 | 100% | 3.1% | 0% |
| Inactive | 80 | 100% | 61.3% | 0% |

Overall FILE_DATE coverage: 2,000 / 2,000 (100%). Active+Final PERMIT_DATE: 1,688 / 1,823 (92.6%).

Chronology: 13 `PERMIT < FILE` and 3 `FINAL < PERMIT` cases remain; these mirror inverted dates already present in `permit_info` before repair (not introduced by repair).

## Artifacts

- Repair script: `agent/scripts/ca/data_repair_ca_san_carlos.py`
- Repaired sample parquet: `/Users/ekung/Dropbox/projects/la-permits-data-bot/repaired/permits_ca_san_carlos_repaired.parquet`

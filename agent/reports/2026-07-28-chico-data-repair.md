# Chico (CA) data repair — 2026-07-28

Chico was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. Civic-portal JSON under `DATA` already has correct `FILE_DATE` (when Applied exists) and correct `PERMIT_DATE` / `FINAL_DATE` whenever those fields were populated from Issued / Finaled. Main issues were stale `STATUS_ORIGINAL` lagging `PermitStatus` (FINALED still Active/In Review; ISSUED still In Review; CERTIFICATE OF OCC still Active/Inactive), sewer `PAID`/`NOT PAID` shells carrying `PermitFinaledDate` but left In Review, `MASTER PLAN APPROVED` wrongly mapped to Final, missing `PERMIT_DATE` on Active/Final rows with Issued or Approved available, missing `FINAL_DATE` on Final rows after status correction, and one spurious `FINAL_DATE` on WITHDRAWN. Repair fills/fixes 68 statuses, 34 permit dates, and 22 final dates; residual gaps lack Applied / Issued / Finaled in `DATA`.

## Jurisdiction selection

Walked `(JURISDICTION, STATE)` pairs in sample order and compared against `agent/scripts/{state}/data_repair_{state}_{city}.py`. First missing: **Chico, CA** → `agent/scripts/ca/data_repair_ca_chico.py` (n=2,000).

## DATA schema

All rows share civic-portal top-level keys (`fees`, `contacts`, `site_info`, `inspections`, `permit_info`, `search_data`). Canonical dates/status live under `permit_info` (`PermitStatus`, `PermitAppliedDate`, `PermitIssuedDate`, `PermitApprovedDate`, `PermitFinaledDate`). Content variants recorded in `INFERRED_SCHEMA`:

| Schema | n | Description |
| --- | ---: | --- |
| `permit_info_issued_finaled` | 1,477 | Issued + Finaled present |
| `permit_info_issued` | 216 | Issued present, Finaled blank |
| `permit_info_applied_only` | 169 | Only Applied populated |
| `permit_info_approved_only` | 76 | Approved present, Issued/Finaled blank |
| `permit_info_finaled_only` | 51 | Finaled present, Issued blank |
| `permit_info_empty_dates` | 10 | Status text, no usable dates |
| `legacy_no_status` | 1 | Blank `PermitStatus`, Applied present |

## Field assessment

### STATUS_NORMALIZED

- Missing on 1 / 2,000: blank-status oversized-load shell with Applied only (`ENGADM19-00053`).
- Long-form `PermitStatus` values are mostly already correct when `STATUS_ORIGINAL` matches DATA (`FINALED`/`FINAL`/`CERTOFOC`→Final, `ISSUED`→Active, `APPLIED`/`UNDER REVIEW`/`PAID`→In Review, `EXPIRED`/`VOID`/`WITHDRAWN`→Inactive).
- **Issue:** 29 rows where `STATUS_ORIGINAL` lagged `PermitStatus` (e.g. FINALED still Active/In Review; ISSUED still In Review/Inactive; CERTIFICATE OF OCC still Active/Inactive; EXPIRED still Active). Separately, 34 sewer `PAID`/`NOT PAID` rows carry `PermitFinaledDate` but stayed In Review, and 4 `MASTER PLAN APPROVED` rows were Final despite Approved-only (no completion).
- **Repair:** map from `PermitStatus`; promote non-inactive rows with `PermitFinaledDate` to Final; map `MASTER PLAN APPROVED`→Active; blank-status Applied → In Review → **1 FILLED**, **67 FIXED**. Missing after: 0.

Status transitions: In Review→Final 42; Active→Final 11; In Review→Active 7; Final→Active 4; Active→Inactive 1; Inactive→Active 1; Inactive→Final 1; null→In Review 1.

### FILE_DATE

- Missing on 10 / 2,000 (0.5%). Present values match `PermitAppliedDate` on all 1,990 rows with Applied populated (0 incorrect).
- The 10 gaps (7 CLONE, 2 VOID, 1 APPLIED) also lack Applied / search Application; no safe application date in `DATA`.
- **Repair:** no changes (0 FILLED / 0 FIXED). Coverage remains 99.5%.

### PERMIT_DATE

- Missing on 322 / 2,000 (16.1%). When present, every value matches `PermitIssuedDate` (0 incorrect).
- Among Active/Final before repair: Active 125/130 present, Final 1,461/1,484 present.
- Recoverable gaps: oversized-load `ISSUED` Approved-only (4); `FINALED` Approved-only / Issued present but null `PERMIT_DATE`; `MASTER PLAN APPROVED` remapped to Active with Approved; status-promoted ISSUED/CERTIFICATE OF OCC rows.
- **Repair:** **34 FILLED**, **0 FIXED**. Missing after: 288.
- Post-repair Active PERMIT coverage: 129/130 (99.2%); Final: 1,493/1,534 (97.3%). Remaining Final gaps are mostly promoted sewer `PAID` shells with Finaled but no Issued/Approved (33), plus a few FINALED / SEWER IN-LIEU rows without issuance dates. One Active oversized load (`ENGADM19-00024`) has neither Issued nor Approved.

### FINAL_DATE

- Missing on 493 / 2,000 (24.7%). When present, every value matches `PermitFinaledDate` (0 incorrect vs that field).
- Among Final before repair: 1,472/1,484 had `FINAL_DATE`. Status-lagged FINALED / CERTIFICATE OF OCC rows had `PermitFinaledDate` with null `FINAL_DATE` because status lagged. One Inactive WITHDRAWN row carried spurious `FINAL_DATE` → cleared. After promoting `PAID`/`NOT PAID` with Finaled to Final, their existing `FINAL_DATE` values become valid.
- **Repair:** **21 FILLED**, **1 FIXED** (clear). Missing after: 473.
- Post-repair Final FINAL coverage: 1,527/1,534 (99.5%). Remaining 7 Final gaps are `FINAL`/`FINALED` rows with blank `PermitFinaledDate` and no completed final inspection.

## Repair performance

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | ---: | ---: | ---: | ---: |
| STATUS_NORMALIZED | 1 | 67 | 1 | 0 |
| FILE_DATE | 0 | 0 | 10 | 10 |
| PERMIT_DATE | 34 | 0 | 322 | 288 |
| FINAL_DATE | 21 | 1 | 493 | 473 |

Status distribution after repair: Final 1,534 · Inactive 197 · In Review 139 · Active 130.

Post-repair completeness by status:

| Status | FILE_DATE | PERMIT_DATE | FINAL_DATE |
| --- | ---: | ---: | ---: |
| Active | ~100% | 99.2% | 0% |
| Final | ~100% | 97.3% | 99.5% |
| In Review | ~94% | 3.6% | 0% |
| Inactive | ~99% | 43.1% | 0% |

Chronology: 4 `PERMIT < FILE` and 4 `FINAL < PERMIT` cases remain; all mirror inverted dates already present in `permit_info` (not introduced by repair).

## Artifacts

- Repair script: `agent/scripts/ca/data_repair_ca_chico.py`
- Repaired sample parquet: `$AGENT_DATA_PATH/repaired/permits_ca_chico_repaired.parquet`

# Saratoga (CA) data repair — 2026-07-28

Saratoga was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. Civic-portal JSON under `DATA` already has correct `FILE_DATE` (when Applied exists) and correct `PERMIT_DATE` / `FINAL_DATE` whenever those fields were populated from Issued / Finaled. Main issues were short-code statuses `AP` and `PP` wrongly mapped to Final, stale `STATUS_ORIGINAL` lagging `PermitStatus` (FINALED still Active; ISSUED still In Review), missing `PERMIT_DATE` on Active/Final rows with Issued or Approved available (especially closed `CL` Approved-only rows), and missing `FINAL_DATE` on Final rows after status correction or when only a passed final inspection exists. Repair fills/fixes 150 statuses, 350 permit dates, and 18 final dates; residual `FINAL_DATE` gaps are mostly legacy `CL`/`FI` closed records without a finaled timestamp.

## Jurisdiction selection

Walked `(JURISDICTION, STATE)` pairs in sample order and compared against `agent/scripts/{state}/data_repair_{state}_{city}.py`. First missing: **Saratoga, CA** → `agent/scripts/ca/data_repair_ca_saratoga.py` (n=2,000).

## DATA schema

All rows share civic-portal top-level keys (`fees`, `contacts`, `site_info`, `inspections`, `permit_info`, `search_data`). Canonical dates/status live under `permit_info` (`PermitStatus`, `PermitAppliedDate`, `PermitIssuedDate`, `PermitApprovedDate`, `PermitFinaledDate`). Content variants recorded in `INFERRED_SCHEMA`:

| Schema | n | Description |
| --- | ---: | --- |
| `permit_info_issued` | 891 | Issued present, Finaled blank |
| `permit_info_issued_finaled` | 676 | Issued + Finaled present |
| `permit_info_approved_only` | 335 | Approved present, Issued/Finaled blank |
| `permit_info_applied_only` | 57 | Only Applied populated |
| `permit_info_finaled_only` | 39 | Finaled present, Issued blank |
| `legacy_no_status` | 2 | Blank `PermitStatus`, Applied present |

## Field assessment

### STATUS_NORMALIZED

- Missing on 2 / 2,000: blank-status encroachment shells with Applied only (`10-1021`, `08-0045`).
- Long-form `PermitStatus` values are mostly already correct when `STATUS_ORIGINAL` matches DATA (`FINALED`→Final, `ISSUED`/`APPROVED`→Active, `APPLIED`/`E-APPLIED`/`UNDER REVIEW`→In Review, `EXPIRED`/`VOID`→Inactive, `CL`/`FI`→Final).
- **Issue:** short codes `AP` (n=25; Approved date, no Issued/Finaled) and `PP` (n=100; Issued present) were normalized to Final despite lacking finaling evidence. Also 23 Active rows whose DATA is FINALED or carries `PermitFinaledDate` (stale `STATUS_ORIGINAL` issued/approved), and 1 ISSUED row still In Review.
- **Repair:** map from `PermitStatus` (AP/PP→Active; promote to Final when non-inactive `PermitFinaledDate` present; blank-status Applied → In Review) → **2 FILLED**, **148 FIXED**. Missing after: 0.

Status transitions: Final→Active 124; Active→Final 23; In Review→Active 1; null→In Review 2.

### FILE_DATE

- Missing on 1 / 2,000 (0.05%). Present values match `PermitAppliedDate` on all 1,999 rows with Applied populated (0 incorrect).
- The 1 gap (`23-0296`, FINALED encroachment) also lacks Applied / search Application; no safe application date in `DATA`.
- **Repair:** no changes (0 FILLED / 0 FIXED). Coverage remains 99.95%.

### PERMIT_DATE

- Missing on 436 / 2,000 (21.8%). When present, every value matches `PermitIssuedDate` (0 incorrect).
- Among Active/Final before repair: Active 205/232 present, Final 1,277/1,611 present.
- Recoverable gaps: Final `CL` rows with Approved-only (270); `AP` remapped to Active with Approved; `APPROVED`/`ISSUED`/`FINALED` rows with Issued or Approved present but null `PERMIT_DATE`.
- **Repair:** **350 FILLED**, **0 FIXED**. Missing after: 86.
- Post-repair Active PERMIT coverage: 331/334 (99.1%); Final: 1,501/1,510 (99.4%). Remaining gaps lack both Issued and Approved in `DATA`.

### FINAL_DATE

- Missing on 1,291 / 2,000 (64.6%). When present, every value matches `PermitFinaledDate` (0 incorrect vs that field).
- Among Final before repair: only 691/1,611 had `FINAL_DATE`. Six Active-but-FINALED rows had `PermitFinaledDate` with null `FINAL_DATE` because status lagged. Ten Final FINALED rows lacked `PermitFinaledDate` but had a passed final inspection → filled from inspection. Two Inactive EXPIRED rows carried spurious `FINAL_DATE` → cleared.
- **Repair:** **16 FILLED**, **2 FIXED** (clear). Missing after: 1,277.
- Post-repair Final FINAL coverage: 723/1,510 (47.9%). Remaining gaps are almost entirely legacy `CL`/`FI` closed records without `PermitFinaledDate` or a titled final inspection (CL inspections use coded types like `B165` with result `AP`, not usable as final dates).

## Repair performance

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | ---: | ---: | ---: | ---: |
| STATUS_NORMALIZED | 2 | 148 | 2 | 0 |
| FILE_DATE | 0 | 0 | 1 | 1 |
| PERMIT_DATE | 350 | 0 | 436 | 86 |
| FINAL_DATE | 16 | 2 | 1,291 | 1,277 |

Status distribution after repair: Final 1,510 · Active 334 · Inactive 110 · In Review 46.

Post-repair completeness by status:

| Status | FILE_DATE | PERMIT_DATE | FINAL_DATE |
| --- | ---: | ---: | ---: |
| Active | ~100% | 99.1% | 0% |
| Final | ~100% | 99.4% | 47.9% |
| In Review | 100% | 4.3% | 0% |
| Inactive | 100% | 72.7% | 0% |

Chronology: 516 `PERMIT < FILE` and 2 `FINAL < PERMIT` cases remain; all mirror inverted dates already present in `permit_info` (mostly legacy `CL`/`FI` rows; not introduced by repair).

## Artifacts

- Repair script: `agent/scripts/ca/data_repair_ca_saratoga.py`
- Repaired sample parquet: `$AGENT_DATA_PATH/repaired/permits_ca_saratoga_repaired.parquet`

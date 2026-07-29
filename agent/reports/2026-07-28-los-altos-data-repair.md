# Los Altos (CA) data repair — 2026-07-28

Los Altos was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. Civic-portal JSON under `DATA` already has correct `FILE_DATE` whenever `PermitAppliedDate` is present, and correct `PERMIT_DATE` / `FINAL_DATE` whenever those were populated from Issued / Finaled. Main issues were 104 blank-`PermitStatus` shells (mostly EXCAVATION / ENCROACHMENT) with missing `STATUS_NORMALIZED`, stale `STATUS_ORIGINAL` lagging `PermitStatus` (FINALED still Active; ISSUED/APPROVED still In Review), one wrong `PERMIT_DATE` that did not match Issued, missing `PERMIT_DATE` on Active/Final rows with Issued or Approved available, missing `FINAL_DATE` on Final rows (including after status promotion) fillable from Finaled or passed `BUILDING FINAL**` inspections, and one spurious `FINAL_DATE` on Inactive CANCELED. Repair fills/fixes 119 statuses, 24 permit dates, and 13 final dates; residual gaps lack Applied / Issued / Approved / Finaled (or a passed final inspection) in `DATA`.

## Jurisdiction selection

Walked `(JURISDICTION, STATE)` pairs in sample order and compared against `agent/scripts/{state}/data_repair_{state}_{city}.py`. First missing: **Los Altos, CA** → `agent/scripts/ca/data_repair_ca_los_altos.py` (n=2,000). Prior pair (Chico) already had a repair script.

## DATA schema

All rows share civic-portal top-level keys (`fees`, `contacts`, `site_info`, `inspections`, `permit_info`, `search_data`). Canonical dates/status live under `permit_info` (`PermitStatus`, `PermitAppliedDate`, `PermitIssuedDate`, `PermitApprovedDate`, `PermitFinaledDate`). `search_data` has only Address / Contractor / Permit # / RECORDID (no Application date). Content variants recorded in `INFERRED_SCHEMA`:

| Schema | n | Description |
| --- | ---: | --- |
| `permit_info_issued_finaled` | 1,136 | Issued + Finaled present |
| `permit_info_issued` | 649 | Issued present, Finaled blank |
| `legacy_no_status` | 102 | Blank `PermitStatus`, dates present |
| `permit_info_applied_only` | 55 | Only Applied populated |
| `permit_info_finaled_only` | 31 | Finaled present, Issued blank |
| `permit_info_approved_only` | 24 | Approved present, Issued/Finaled blank |
| `permit_info_empty_dates` | 3 | Status text / blank, no usable dates |

## Field assessment

### STATUS_NORMALIZED

- Missing on 104 / 2,000: blank `PermitStatus` and blank `STATUS_ORIGINAL` (EXCAVATION 57, ENCROACHMENT 28, TEMPORARY LANE CLOSURE 11, etc.). Of these, 62 have Issued → Active, 40 have Applied only → In Review, 2 have no dates → remain missing.
- When `STATUS_ORIGINAL` matches `PermitStatus`, mapping is already correct: `finaled`→Final, `issued`/`approved`→Active, `submitted`/`fees paid`/`pending`/…→In Review, `canceled`/`abandoned`/`denied`/…→Inactive.
- **Issue:** 16 rows where `STATUS_ORIGINAL` lagged `PermitStatus` (9 `issued` still Active while DATA is FINALED; 6 submitted/received/site assessment still In Review while DATA is ISSUED; 1 site assessment still In Review while DATA is APPROVED). Separately, one Active APPROVED row carries `PermitFinaledDate` and should be Final.
- **Repair:** map from `PermitStatus`; promote non-inactive rows with `PermitFinaledDate` to Final; blank-status inferred from dates → **102 FILLED**, **17 FIXED**. Missing after: 2.

Status transitions: null→Active 62; null→In Review 40; Active→Final 10; In Review→Active 7.

### FILE_DATE

- Missing on 71 / 2,000 (3.5%). Present values match `PermitAppliedDate` on all 1,929 rows with Applied populated (0 incorrect).
- The 71 gaps also lack Applied; `search_data` has no Application key. Many have Issued (and some Finaled) but Issued is not used as an application/submittal date.
- **Repair:** no changes (0 FILLED / 0 FIXED). Coverage remains 96.5%.

### PERMIT_DATE

- Missing on 159 / 2,000 (8.0%). When present, nearly all match `PermitIssuedDate`; **1 incorrect** Active ISSUED row had `PERMIT_DATE=2024-07-30` while Issued/Approved were `2024-08-30` → FIXED.
- Among Active/Final before repair: Active 630/647 present, Final 1,131/1,160 present. Recoverable: Active APPROVED with Approved (14); status-promoted ISSUED rows; blank-status Issued shells missing `PERMIT_DATE`; a few Final with Approved.
- **Repair:** **23 FILLED**, **1 FIXED**. Missing after: 136.
- Post-repair Active PERMIT coverage: 704/706 (99.7%); Final: 1,142/1,170 (97.6%). Remaining Final gaps are mostly finaled-only rows with neither Issued nor Approved (28). Two Active shells lack both Issued and Approved.

### FINAL_DATE

- Missing on 842 / 2,000 (42.1%). When present, every value matches `PermitFinaledDate` (0 incorrect vs that field).
- Among Final before repair: 1,156/1,160 had `FINAL_DATE`. Four FINALED rows lacked Finaled; three are fillable from passed `BUILDING FINAL**` inspections; one has only CORRECTION NOTICE finals → left missing. Nine Active FINALED (status-lagged) had Finaled with null `FINAL_DATE`. One Inactive CANCELED carried spurious `FINAL_DATE` → cleared. One Active APPROVED with Finaled already had `FINAL_DATE` and becomes Final via status promotion.
- **Repair:** **12 FILLED**, **1 FIXED** (clear). Missing after: 831.
- Post-repair Final FINAL coverage: 1,169/1,170 (99.9%). Remaining 1 Final gap has blank Finaled and no passed final inspection.

## Repair performance

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | ---: | ---: | ---: | ---: |
| STATUS_NORMALIZED | 102 | 17 | 104 | 2 |
| FILE_DATE | 0 | 0 | 71 | 71 |
| PERMIT_DATE | 23 | 1 | 159 | 136 |
| FINAL_DATE | 12 | 1 | 842 | 831 |

Status distribution after repair: Final 1,170 · Active 706 · In Review 81 · Inactive 41 · missing 2.

Post-repair completeness by status:

| Status | n | FILE_DATE | PERMIT_DATE | FINAL_DATE |
| --- | ---: | ---: | ---: | ---: |
| Active | 706 | — | 99.7% | 0% |
| Final | 1,170 | — | 97.6% | 99.9% |
| In Review | 81 | — | 6.2% | 0% |
| Inactive | 41 | — | 31.7% | 0% |

Overall FILE_DATE coverage: 1,929 / 2,000 (96.5%). Active+Final PERMIT_DATE: 1,846 / 1,876 (98.4%).

Chronology: 87 `PERMIT < FILE` and 3 `FINAL < PERMIT` cases remain; all mirror inverted dates already present in `permit_info` before repair (not introduced by repair).

## Artifacts

- Repair script: `agent/scripts/ca/data_repair_ca_los_altos.py`
- Repaired sample parquet: `$AGENT_DATA_PATH/repaired/permits_ca_los_altos_repaired.parquet`

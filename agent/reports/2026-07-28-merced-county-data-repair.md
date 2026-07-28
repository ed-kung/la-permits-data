# Merced County (CA) data repair — 2026-07-28

Merced County was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. Civic-portal JSON under `DATA` already has correct `FILE_DATE` and, when populated, correct `PERMIT_DATE` / `FINAL_DATE` matching `permit_info`. Main issues were wrong `STATUS_NORMALIZED` mappings (ESTIMATE/RED TAG → Final, RETIRED → In Review), stale `STATUS_ORIGINAL` vs `PermitStatus` (FINALED still Active; ISSUED/ACTIVE with `PermitFinaledDate`), blank-status rows, one `PERMIT_DATE` set to Applied instead of Issued, and a few Final rows missing `FINAL_DATE` recoverable from `PermitFinaledDate` or final inspections. Repair fills/fixes 259 statuses, 8 permit dates, and 7 final dates.

## Jurisdiction selection

Walked `(JURISDICTION, STATE)` pairs in sample order and compared against `agent/scripts/{state}/data_repair_{state}_{city}.py`. First missing: **Merced County, CA** → `agent/scripts/ca/data_repair_ca_merced_county.py` (n=2,000).

## DATA schema

All rows share civic-portal top-level keys (`fees`, `contacts`, `site_info`, `inspections`, `permit_info`, `search_data`). Canonical dates/status live under `permit_info` (`PermitStatus`, `PermitAppliedDate`, `PermitIssuedDate`, `PermitApprovedDate`, `PermitFinaledDate`). Content variants recorded in `INFERRED_SCHEMA`:

| Schema | n | Description |
| --- | ---: | --- |
| `permit_info_issued_finaled` | 1,242 | Issued + Finaled present |
| `permit_info_issued` | 401 | Issued present, Finaled blank |
| `permit_info_applied_only` | 209 | Only Applied populated |
| `legacy_no_status` | 113 | Blank `PermitStatus`, Applied (and rarely Issued/Approved) present |
| `permit_info_approved_only` | 26 | Approved present, Issued/Finaled blank |
| `permit_info_finaled_only` | 7 | Finaled present, Issued blank |
| `permit_info_empty_dates` | 2 | Status/type text, no usable dates |

## Field assessment

### STATUS_NORMALIZED

- Missing on 113 / 2,000 (all blank `PermitStatus`).
- When `STATUS_ORIGINAL` matches `DATA.permit_info.PermitStatus`, most common mappings are consistent (FINALED → Final; ISSUED/ACTIVE/APPROVED → Active; APPLIED → In Review; PERMIT/APPLICATION EXPIRED / CANCELED → Inactive).
- **Issues:**
  - ESTIMATE (64) mapped to Final with no Issued/Approved/Finaled dates → should be In Review.
  - RED TAG (9) mapped to Final with almost no finaling evidence → Inactive (code-enforcement).
  - RETIRED (37) mapped to In Review → Inactive (archived).
  - 2 rows with `STATUS_ORIGINAL=issued` while `PermitStatus=FINALED` left as Active; 27 ISSUED + 2 ACTIVE rows carry `PermitFinaledDate` and should be Final.
  - 3 `30(+) DAYS PAST DUE` rows (issued) left as In Review → Active.
  - 113 blank-status shells (mostly encroachments / annual work with Applied only).
- **Repair:** map from `PermitStatus` (plus Final override when non-inactive `PermitFinaledDate` present; blank-status inference from dates) → **113 FILLED**, **146 FIXED**. Missing after: 0.

Status transitions: null→In Review 111; null→Active 2; Final→In Review 64 (ESTIMATE); Final→Inactive 9 (RED TAG); In Review→Inactive 37 (RETIRED); Active→Final 31; In Review→Final 2; In Review→Active 3.

### FILE_DATE

- Missing on 4 / 2,000 (0.2%). Present values match `PermitAppliedDate` on all 1,996 rows with Applied populated (0 incorrect).
- The 4 gaps also lack any application date in `search_data` (1 APPROVED fireworks OP with Issued only; 2 APPLIED shells; 1 RETIRED shell).
- **Repair:** no changes (0 FILLED / 0 FIXED). Coverage remains 99.8%.

### PERMIT_DATE

- Missing on 356 / 2,000 (17.8%). When present, nearly every value matches `PermitIssuedDate`; **1 incorrect**: `OP2019-0153` had `PERMIT_DATE` = Applied (2019-06-06) while `PermitIssuedDate` = 2024-02-23.
- Among Active/Final before repair: Active 285/290 present, Final 1,213/1,292 present (most Final gaps were ESTIMATE/RED TAG mislabels).
- Recoverable gaps: Active/Final rows with blank Issued but populated Approved; blank-status row with Approved promoted to Active.
- **Repair:** **7 FILLED**, **1 FIXED**. Missing after: 349.
- Post-repair Active PERMIT coverage: 261/264 (98.9%); Final: 1,249/1,252 (99.8%). Remaining gaps lack both Issued and Approved in `DATA`.

### FINAL_DATE

- Missing on 754 / 2,000 (37.7%). When present, every value matches `PermitFinaledDate` (0 incorrect vs that field).
- Among Final before repair: 1,212/1,292 had `FINAL_DATE`. Most of the 80 Final gaps were ESTIMATE (64) and RED TAG (9) mislabels; 7 true FINALED rows lacked `PermitFinaledDate`.
- After status repair, Final rows with `PermitFinaledDate` but null `FINAL_DATE` (stale Active→Final) are filled; one FINALED row (`BP2013-0573`) recovered from a passed `FINAL-FIRE` inspection.
- Spurious `FINAL_DATE` on 2 Inactive APPLICATION EXP rows and 1 RETIRED row → cleared.
- **Repair:** **4 FILLED**, **3 FIXED** (clears). Missing after: 753.
- Post-repair Final FINAL coverage: 1,247/1,252 (99.6%). Remaining 5 FINALED gaps lack `PermitFinaledDate` and only have non-final electrical inspections (or none).

## Repair performance

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | ---: | ---: | ---: | ---: |
| STATUS_NORMALIZED | 113 | 146 | 113 | 0 |
| FILE_DATE | 0 | 0 | 4 | 4 |
| PERMIT_DATE | 7 | 1 | 356 | 349 |
| FINAL_DATE | 4 | 3 | 754 | 753 |

Status distribution after repair: Final 1,252 · In Review 300 · Active 264 · Inactive 184 · missing 0.

Post-repair completeness by status:

| Status | FILE_DATE | PERMIT_DATE | FINAL_DATE |
| --- | ---: | ---: | ---: |
| Active | ~99% | 98.9% | 0% |
| Final | ~100% | 99.8% | 99.6% |
| In Review | ~99% | 5.0% | 0% |
| Inactive | ~100% | 68.5% | 0% |

Chronology: 7 `PERMIT < FILE` and 1 `FINAL < PERMIT` cases remain; all mirror inverted dates already present in `permit_info` (not introduced by repair).

## Artifacts

- Repair script: `agent/scripts/ca/data_repair_ca_merced_county.py`
- Repaired sample: `$AGENT_DATA_PATH/repaired/permits_ca_merced_county_repaired.parquet`

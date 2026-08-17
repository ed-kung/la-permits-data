# Flower Mound (TX) data repair

**Summary:** Flower Mound was the first TX jurisdiction in `permits_tx_sample.parquet` without a repair script. All 1,999 rows share one City portal payload (`permit_info` / `search_data` / `inspections` / …). STATUS_NORMALIZED was missing on 62 uncommon statuses and wrong on 1 APPROVED row; FILE_DATE already matched AppliedDate wherever Applied existed (5 empty shells remain); PERMIT_DATE gained 58 fills from Approved when Issued was blank; FINAL_DATE had 28 spurious non-Final values cleared. Active/Final coverage after repair: PERMIT_DATE 90.1% / 99.6%; FINAL_DATE on Final 99.2%.

## Scope

- Input: `MY_DATA_PATH/processed_data/permits_tx_sample.parquet`
- Jurisdiction: Flower Mound, TX (first pair lacking `agent/scripts/{state}/data_repair_{state}_{city}.py`)
- Script: `agent/scripts/tx/data_repair_tx_flower_mound.py`
- Artifact: `AGENT_DATA_PATH/repaired/permits_tx_flower_mound_repaired.parquet`

## DATA schema

Every record has top-level keys `contacts`, `fees`, `inspections`, `permit_info`, `search_data`, `site_info`. Dates and status live in `permit_info`. `search_data` has two key layouts:

| INFERRED_SCHEMA | n | Notes |
| --- | ---: | --- |
| permit_info | 1,990 | Application / Issued / Site Address / Permit Number |
| permit_info_econ_search | 9 | ADDRESS / PERMIT NUMBER / RECORDID (ECON/EPRS ids) |

Canonical source fields:

| Target field | Primary source | Fallback |
| --- | --- | --- |
| STATUS_NORMALIZED | `permit_info.PermitStatus` | date inference if blank |
| FILE_DATE | `PermitAppliedDate` | `search_data.Application`, then Issued / search Issued |
| PERMIT_DATE | `PermitIssuedDate` | `search_data.Issued`, then `PermitApprovedDate` |
| FINAL_DATE | `PermitFinaledDate` (Final only) | approved FINAL/CO inspection `Completed` |

## Field assessment

### STATUS_NORMALIZED

| PermitStatus | Prior STATUS_NORMALIZED | n |
| --- | --- | ---: |
| FINALED | Final | 1,492 |
| VOID | Inactive | 229 |
| ISSUED | Active | 77 |
| EXPIRED | Inactive | 45 |
| REPERMITTED | *(missing)* | 43 |
| DENIED | Inactive | 19 |
| ONGOING / Ongoing | *(missing)* | 18 |
| INACTIVE | Inactive | 14 |
| NOTIFIED | In Review | 14 |
| EXEMPT | In Review | 12 |
| UNDER REVIEW | In Review | 11 |
| WARRANTY | In Review | 6 |
| APPROVED | Active (4) / In Review (1) | 5 |
| WITHDRAWN | Inactive | 4 |
| ON HOLD | In Review | 3 |
| COMPLETED / CLOSED / COMPLETE | Final | 5 |
| ISSUED - REMOVE - BANNER | *(missing)* | 1 |
| PENDING | In Review | 1 |

- **62 missing:** pipeline had no mapping for REPERMITTED, ONGOING, and ISSUED - REMOVE - BANNER.
- **1 incorrect:** PermitStatus APPROVED with STATUS_ORIGINAL still `notified` → STATUS_NORMALIZED In Review (should be Active).
- Remaining mapped statuses already matched `PermitStatus`.

Repair mapping for previously unmapped values: REPERMITTED → Inactive (superseded; descriptions say “REPERMITTED AS …”); ONGOING → Active (long-lived OSSF); ISSUED - REMOVE - BANNER → Active.

### FILE_DATE

- 1,994 / 1,999 populated; all matched `PermitAppliedDate` at day resolution (0 mismatches).
- **5 missing** are converted WARRANTY (4) / COMPLETED drainage (1) shells with blank Applied, blank search Application/Issued, and no IssuedDate. One WARRANTY row has only `PermitApprovedDate` — not used as a file-date proxy.

### PERMIT_DATE

- When present, always matched `PermitIssuedDate` (1,701 / 1,701).
- **298 missing** before repair. Of those, **58** had `PermitApprovedDate` but blank Issued (Active APPROVED, some Final/Inactive/In Review) → FILLED from Approved.
- Remaining gaps on Active/Final: 10 Active ONGOING OSSF rows with neither Issued nor Approved; 6 Final rows (FINALED/COMPLETED/CLOSED) with FinaledDate but no Issued/Approved (plus one empty COMPLETED shell).

### FINAL_DATE

- When present, always matched `PermitFinaledDate` (1,513 / 1,513).
- **12 Final** rows are FINALED/COMPLETED with blank FinaledDate and empty `inspections` → cannot fill.
- **28 non-Final** rows carried FinaledDate (27 Inactive denied/inactive/withdrawn; 1 Active ISSUED) → cleared as spurious for non-Final status.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 62 | 1 | 62 → 0 |
| FILE_DATE | 0 | 0 | 5 → 5 |
| PERMIT_DATE | 58 | 0 | 298 → 240 |
| FINAL_DATE | 0 | 28 | 486 → 514 |

After repair, by status:

- **FILE_DATE:** 1,994 / 1,999 (99.7%) overall
- **PERMIT_DATE:** Active 91/101 (90.1%); Final 1,491/1,497 (99.6%)
- **FINAL_DATE:** Final 1,485/1,497 (99.2%); non-Final all empty

STATUS after: Final 1,497; Inactive 354; Active 101; In Review 47.

## Not repairable

- 5 FILE_DATE shells with no application/issuance timestamps in DATA.
- 10 Active ONGOING rows and 6 Final rows with no Issued/Approved → PERMIT_DATE stays missing.
- 12 Final rows with blank FinaledDate and no completion inspections → FINAL_DATE stays missing.

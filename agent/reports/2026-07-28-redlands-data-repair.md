# Redlands (CA) data repair — 2026-07-28

Redlands was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. CityView task JSON under `DATA` has one top-level key set; status is mostly correct from `CASE_STATUS`, but 51 statuses were null, `FILE_DATE` was missing on ~39% of rows, `PERMIT_DATE` often used Permit Issued `TASK_AVAIL` instead of `ACTUAL_END`, and `FINAL_DATE` frequently mirrored Building-Final schedule/`TASK_AVAIL` (including NOTREADY/CORRECTIO) rather than FINALED completion. Repair fills all null statuses, raises FILE coverage to 97.3%, corrects issuance stamps, and brings Final `FINAL_DATE` coverage to 99.0%.

## Jurisdiction selection

Walked `(JURISDICTION, STATE)` pairs in sample appearance order and compared against `agent/scripts/{state}/data_repair_{state}_{city}.py`. First missing: **Redlands, CA** → `agent/scripts/ca/data_repair_ca_redlands.py` (n=1,999).

## DATA schema

CityView / Civic Access scrape. All 1,999 rows share the same top-level keys (`CASE_STATUS`, `CASE_TYPE1`, `Tasks`, address fields, …). Content tags for issuance / final workflow marks are recorded in `INFERRED_SCHEMA`:

| Schema | n | Description |
| --- | ---: | --- |
| `cityview_issued_finaled` | 781 | ISSUED mark + final/close mark |
| `cityview_issued` | 542 | ISSUED mark, no final mark |
| `cityview_submittal_no_issue` | 281 | submittal task(s) only |
| `cityview_rental_finaled_only` | 137 | rental program + final/close |
| `cityview_finaled_only` | 105 | final/close, no issuance |
| `cityview_rental_other_tasks` | 55 | rental + other tasks |
| `cityview_rental_empty_tasks` | 51 | rental shells, no dated tasks |
| `cityview_other_tasks` | 45 | other dated tasks |
| `cityview_empty_tasks` | 2 | no usable tasks |

Canonical fields: `CASE_STATUS` → status; submittal `TASK_AVAIL` → file; `Permit Issued`/`Issue Permit` + `ISSUED` `ACTUAL_END` → permit; Building-Final/`Fire - Final` `FINALED` (and close/CO/rental/sign-off fallbacks) `ACTUAL_END` → final.

## Field assessment

### STATUS_NORMALIZED

- Missing on 51 / 1,999 (`RENTALPASS` 15, `RENTALPAY` 14, `MYLARRCVD` 13, `RENTALPAID` 5, `APPROVEDC` 2, `CLOSEDR` 1, `FEECALC` 1).
- Upstream mapping from `CASE_STATUS` / `STATUS_ORIGINAL` is otherwise mostly correct (`FINALED`/`CLOSED`/`COMPLETE`→Final, `ISSUED`/`APPROVED`→Active, cancel/expire/removed→Inactive, submitted/plan check/waiting→In Review).
- Incorrect / lagged mappings repaired:
  - 5 `FINALED` labeled Active → **Final**
  - 3 `EXPIRED` labeled Active → **Inactive**
  - 2 `APPROVED` labeled In Review → **Active**
  - 1 `WITHDRAWN` labeled In Review → **Inactive**
  - 6 In Review with an ISSUED task → **Active**
  - 1 Active/`ISSUED` with a strict final/close mark → **Final**
- **Repair:** 51 FILLED, 16 FIXED. Missing after: 0.

### FILE_DATE

- Missing on 783 / 1,999 (39.2%). When present, values almost always match earliest `Bldg Plan Submittal` / `Plans Submitted` / `Plan Submittal` `TASK_AVAIL` (1,207 exact matches).
- 7 near-miss stamps (mostly WQMP plan checks, 7–47 days after submittal AVAIL) → FIXED to submittal AVAIL. Large-gap mismatches (resubmittal / extension vs older parent date) left unchanged.
- Fill path: preferred submittal AVAIL, else earliest any task `TASK_AVAIL` (730 FILLED).
- **Repair:** 730 FILLED, 7 FIXED. Missing after: 53 (empty / undated Tasks). Coverage 97.3%.

### PERMIT_DATE

- Missing on 936 / 1,999. Among present values, 998 matched `Permit Issued`/`Issue Permit` `ISSUED` dates at day resolution, but 51 used `TASK_AVAIL` instead of `ACTUAL_END` (always earlier; median gap 7 days) → FIXED to `ACTUAL_END`.
- Active missing PERMIT with ISSUED task: 32; Final: 49 → FILLED. Additional fills on Inactive (expired-but-issued).
- Spurious PERMIT on In Review without ISSUED → cleared; APPROVED Active shells with fee/plan-check stamps and no ISSUED → cleared.
- **Repair:** 274 FILLED, 56 FIXED. Missing after: 667.
- Post-repair Active PERMIT coverage: 213/244 (87.3%); Final: 791/989 (80.0%); In Review: 0%.

### FINAL_DATE

- Missing on 1,258 / 1,999. Present values often matched Building-Final `TASK_AVAIL` (including NOTREADY/CORRECTIO/CONDITION schedule stamps) rather than FINALED `ACTUAL_END` — only ~94 exact matches to FINALED ACTUAL vs ~272 to FINALED AVAIL before repair.
- Non-Final rows carrying FINAL (Active 84, Inactive 69, In Review 24) → cleared.
- Final missing FINAL filled from Building-Final/`Fire - Final` FINALED, Print Rental/CO CLOSED, Sign Off / Plans Approved / Issue Permit and Close, YES-CLOSE recordation, encroachment PASS- fallback, etc.
- **Repair:** 414 FILLED, 607 FIXED. Missing after: 1,020.
- Post-repair Final FINAL coverage: 979/989 (99.0%). Active / In Review / Inactive: 0% by design.
- Residual Final gaps (10): FINALED/CLOSED shells with only incomplete Building-Final results or no dated close task (plan revisions, fire sprinkler, TI, pool, etc.).

## Repair performance

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | ---: | ---: | ---: | ---: |
| STATUS_NORMALIZED | 51 | 16 | 51 | 0 |
| FILE_DATE | 730 | 7 | 783 | 53 |
| PERMIT_DATE | 274 | 56 | 936 | 667 |
| FINAL_DATE | 414 | 607 | 1,258 | 1,020 |

Status distribution after repair: Final 989 · Inactive 529 · Active 244 · In Review 237.

Post-repair completeness by status:

| Status | n | FILE_DATE | PERMIT_DATE | FINAL_DATE |
| --- | ---: | ---: | ---: | ---: |
| Active | 244 | ~100% | 87.3% | 0% |
| Final | 989 | ~100% | 80.0% | 99.0% |
| In Review | 237 | ~99% | 0% | 0% |
| Inactive | 529 | ~90% | 62.0% | 0% |

Chronology after repair: `PERMIT < FILE` = 0; `FINAL < PERMIT` = 1 (encroachment Sign Off APPROVEDC dated before Issue Permit in source Tasks).

## Artifacts

- Repair script: `agent/scripts/ca/data_repair_ca_redlands.py`
- Repaired parquet: `$AGENT_DATA_PATH/repaired/permits_ca_redlands_repaired.parquet`

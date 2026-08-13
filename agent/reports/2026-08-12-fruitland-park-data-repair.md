# Fruitland Park (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script was **Fruitland Park**. DATA is a uniform civic / eTRAKiT-style payload (`contacts` / `fees` / `inspections` / `permit_info` / `search_data` / `site_info`). Upstream dates already matched `permit_info` whenever present (0 calendar mismatches), but 31 statuses were wrong because of stale `STATUS_ORIGINAL` (FINALED kept as Active/In Review; ISSUED/APPROVED kept as In Review; EXPIRED/VOID kept as Active/In Review). The repair fixed 31 statuses, filled 35 `PERMIT_DATE` values and 23 `FINAL_DATE` values. After repair: STATUS 100%; FILE_DATE 99.95%; Active/Final PERMIT_DATE 100%/99.9%; Final FINAL_DATE 99.8%.

## Jurisdiction selection

`(JURISDICTION, STATE)` pairs in `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` (sorted order) were checked against `agent/scripts/{state}/data_repair_{state}_{city}.py`. First missing: **Fruitland Park, FL** → `agent/scripts/fl/data_repair_fl_fruitland_park.py` (2,000 sample rows).

## DATA schemas (`INFERRED_SCHEMA`)

Every row shares the same top-level key set. Content suffixes split by which canonical `permit_info` dates are populated:

| Schema | n | Notes |
| --- | ---: | --- |
| `civic_issued_finaled` | 1,805 | Issued + finaled |
| `civic_issued` | 115 | Issued, no finaled |
| `civic_applied` | 52 | Applied only |
| `civic_approved` | 25 | Approved, no issued/finaled |
| `civic_finaled` | 2 | Finaled without issued |
| `civic_status_only` | 1 | VOID shell with no dates |

Canonical fields:

| Target field | Source in DATA |
| --- | --- |
| STATUS_NORMALIZED | `permit_info.PermitStatus`; finaled date → Final (except VOID/EXPIRED); In Review + IssuedDate → Active |
| FILE_DATE | `PermitAppliedDate` else `PermitIssuedDate` |
| PERMIT_DATE | `PermitIssuedDate` else `PermitApprovedDate` |
| FINAL_DATE | `PermitFinaledDate` else latest full-pass Final*/CO/CC inspection (`PARTIAL APPROVED` ignored) |

## Field assessments

### STATUS_NORMALIZED

| PermitStatus | n | Upstream STATUS_NORMALIZED | Assessment |
| --- | ---: | --- | --- |
| FINALED | 1,811 | Final (23 Active, 1 In Review) | Fix Active/In Review → Final |
| ISSUED | 64 | Active (3 In Review) | Fix In Review → Active |
| VOID | 66 | Inactive (1 Active) | Fix Active → Inactive |
| EXPIRED | 27 | Inactive (1 Active, 1 In Review) | Fix → Inactive |
| IN REVIEW | 17 | In Review | Correct |
| APPROVED | 11 | Active (1 In Review) | Fix In Review → Active |
| APPLIED ONLINE | 4 | In Review | Correct |

**Root causes:**
1. Upstream often used stale `STATUS_ORIGINAL` (`issued`, `approved`, `paid online`, `in review`) instead of current `PermitStatus`.
2. FINALED rows with `PermitFinaledDate` kept Active labels and missing `FINAL_DATE`.

**Repair performance:** FILLED 0, FIXED 31; missing 0 → 0.

### FILE_DATE

- Before: missing on **1 / 2,000** (VOID `BD18-0963` with blank applied/issued/approved/finaled). Every present value matched `PermitAppliedDate` (0 mismatches).
- Not fillable for the empty VOID shell.

**Repair performance:** FILLED 0, FIXED 0; missing 1 → 1 (99.95% coverage).

### PERMIT_DATE

- Before: NaN on **89 / 2,000**. All 1,911 present values matched `PermitIssuedDate` (0 mismatches).
- 35 fillable gaps from IssuedDate or ApprovedDate on Active / Final / Inactive (including APPROVED shells with approval but no issue stamp, and FINALED shells previously labeled Active).
- After repair: Active 75/75 (100%); Final 1,809/1,811 (99.9%). Two FINALED shells (`BD21-0064`, `BD18-0263`) lack both IssuedDate and ApprovedDate.

**Repair performance:** FILLED 35, FIXED 0; missing 89 → 54.

### FINAL_DATE

- Before: NaN on **216 / 2,000**; Final had 1,784 / 1,787 present; 0 non-Final rows carried a final date. Present values matched `PermitFinaledDate` (0 mismatches).
- 23 Active/In Review FINALED shells had `PermitFinaledDate` but missing `FINAL_DATE` → status FIXED to Final and FINAL_DATE FILLED.
- 4 Final rows still lack FINAL_DATE: blank `PermitFinaledDate` and either empty final inspections or only `PARTIAL APPROVED` (not treated as close-out).

**Repair performance:** FILLED 23, FIXED 0; missing 216 → 193. Final coverage 1,807 / 1,811 (99.8%).

## Repair script performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 0 | 31 | 0 → 0 |
| FILE_DATE | 0 | 0 | 1 → 1 |
| PERMIT_DATE | 35 | 0 | 89 → 54 |
| FINAL_DATE | 23 | 0 | 216 → 193 |

Ideal coverage after repair: FILE_DATE 99.95%; Active PERMIT_DATE 100%; Final PERMIT_DATE 99.9%; Final FINAL_DATE 99.8%.

## Artifacts

- Script: `agent/scripts/fl/data_repair_fl_fruitland_park.py`
- Repaired sample: `$AGENT_DATA_PATH/fruitland_park_repaired_sample.parquet`

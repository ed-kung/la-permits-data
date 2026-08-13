# Groveland (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script was **Groveland**. DATA is a uniform civic / eTRAKiT-style payload (`contacts` / `fees` / `inspections` / `permit_info` / `search_data` / `site_info`). Upstream dates already matched `permit_info` whenever present (0 calendar mismatches on FILE / PERMIT / FINAL vs Applied / Issued / Finaled). The main defects were stale `STATUS_ORIGINAL` labels (FINALED kept as Active/Inactive/In Review; ISSUED/APPROVED kept as In Review; EXPIRED kept as Active) plus missing PERMIT_DATE / FINAL_DATE on shells that already carried IssuedDate, ApprovedDate, or FinaledDate. The repair fixed 31 statuses, filled 82 `PERMIT_DATE` and 22 `FINAL_DATE` values, and cleared 3 incorrect non-Final `FINAL_DATE` values. After repair: STATUS 100%; FILE_DATE 99.95%; Active/Final PERMIT_DATE 99.2%/99.7%; Final FINAL_DATE 89.1% (gap almost entirely legacy `CONVERTED` rows with no finaled stamp).

## Jurisdiction selection

`(JURISDICTION, STATE)` pairs in `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` (sorted order) were checked against `agent/scripts/{state}/data_repair_{state}_{city}.py`. First missing: **Groveland, FL** → `agent/scripts/fl/data_repair_fl_groveland.py` (2,000 sample rows).

## DATA schemas (`INFERRED_SCHEMA`)

Every row shares the same top-level key set. Content suffixes split by which canonical `permit_info` dates are populated:

| Schema | n | Notes |
| --- | ---: | --- |
| `civic_issued_finaled` | 1,319 | Issued + finaled |
| `civic_issued` | 371 | Issued, no finaled (includes most CONVERTED) |
| `civic_applied` | 231 | Applied only |
| `civic_approved` | 53 | Approved, no issued/finaled |
| `civic_finaled` | 25 | Finaled without issued |
| `civic_status_only` | 1 | Empty CONVERTED shell with no dates |

Canonical fields:

| Target field | Source in DATA |
| --- | --- |
| STATUS_NORMALIZED | `permit_info.PermitStatus`; finaled date → Final (except VOID/EXPIRED/DENIED); In Review + IssuedDate → Active |
| FILE_DATE | `PermitAppliedDate` else `PermitIssuedDate` |
| PERMIT_DATE | `PermitIssuedDate` else `PermitApprovedDate` |
| FINAL_DATE | `PermitFinaledDate` else latest full-pass Final*/CO/CC inspection |

## Field assessments

### STATUS_NORMALIZED

| PermitStatus | n | Upstream STATUS_NORMALIZED | Assessment |
| --- | ---: | --- | --- |
| FINALED | 1,344 | Final (20 Active, 1 Inactive, 1 In Review) | Fix non-Final → Final |
| CONVERTED | 163 | Final | Correct (legacy migrated shells) |
| VOID | 160 | Inactive | Correct |
| ISSUED | 99 | Active (6 In Review) | Fix In Review → Active |
| EXPIRED | 81 | Inactive (1 Active) | Fix Active → Inactive |
| PAID | 71 | In Review | Correct |
| INTAKE | 30 | In Review | Correct |
| IN REVIEW | 27 | In Review | Correct |
| APPROVED | 20 | Active (1 In Review) | Fix In Review → Active; 1 APPROVED with FinaledDate → Final |
| DENIED | 3 | Inactive | Correct |
| FEES DUE / PENDING | 2 | In Review | Correct |

**Root causes:**
1. Upstream often used stale `STATUS_ORIGINAL` (`issued`, `approved`, `intake`, `expired`) instead of current `PermitStatus`.
2. FINALED rows with `PermitFinaledDate` kept Active/Inactive/In Review labels and missing `FINAL_DATE`.

**Repair performance:** FILLED 0, FIXED 31; missing 0 → 0.

Status transitions: Active→Final 21, In Review→Active 7, Inactive→Final 1, Active→Inactive 1, In Review→Final 1.

### FILE_DATE

- Before: missing on **1 / 2,000** (empty CONVERTED permit `#16` with blank applied/issued/approved/finaled). Every present value matched `PermitAppliedDate` (0 mismatches).
- Not fillable for that empty shell.

**Repair performance:** FILLED 0, FIXED 0; missing 1 → 1 (99.95% coverage).

### PERMIT_DATE

- Before: NaN on **320 / 2,000**. All 1,680 present values matched `PermitIssuedDate` (0 mismatches). `PermitApprovedDate` is systematically earlier than Issued and is only used when Issued is blank.
- 82 fillable gaps from IssuedDate or ApprovedDate on Active / Final / Inactive (including ISSUED shells previously labeled In Review, and FINALED shells with Approved but no Issued).
- After repair: Active 117/118 (99.2%); Final 1,503/1,508 (99.7%). Remaining gaps: 4 FINALED zoning/fence shells with neither Issued nor Approved, 1 empty CONVERTED shell, 1 APPROVED plan shell with blank ApprovedDate.

**Repair performance:** FILLED 82, FIXED 0; missing 320 → 238.

### FINAL_DATE

- Before: NaN on **676 / 2,000**; Final had 1,319 / 1,485 present. Present values matched `PermitFinaledDate` (0 mismatches).
- 20 Active + 1 Inactive + 1 In Review FINALED shells had `PermitFinaledDate` but missing `FINAL_DATE` → status FIXED to Final and FINAL_DATE FILLED.
- 2 already-Final FINALED shells lacked `PermitFinaledDate` but had a passed `BD FINAL**` inspection → FILLED from inspection.
- 3 Inactive VOID/EXPIRED rows incorrectly carried a FINAL_DATE (portal finaled stamp on a terminal inactive status) → FIXED (cleared).
- 165 Final rows still lack FINAL_DATE: 163 legacy CONVERTED (no finaled date, no inspections) and 2 FINALED special-event / zoning shells with blank finaled date and empty `FR FINAL **` inspections.

**Repair performance:** FILLED 22, FIXED 3; missing 676 → 657. Final coverage 1,343 / 1,508 (89.1%).

## Repair script performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 0 | 31 | 0 → 0 |
| FILE_DATE | 0 | 0 | 1 → 1 |
| PERMIT_DATE | 82 | 0 | 320 → 238 |
| FINAL_DATE | 22 | 3 | 676 → 657 |

| Coverage (after) | Rate |
| --- | --- |
| STATUS_NORMALIZED non-null | 2,000 / 2,000 (100%) |
| FILE_DATE | 1,999 / 2,000 (99.95%) |
| PERMIT_DATE among Active | 117 / 118 (99.2%) |
| PERMIT_DATE among Final | 1,503 / 1,508 (99.7%) |
| FINAL_DATE among Final | 1,343 / 1,508 (89.1%) |

## Artifacts

- Repair script: `agent/scripts/fl/data_repair_fl_groveland.py`
- Repaired sample parquet: `$AGENT_DATA_PATH/groveland_repaired_sample.parquet`

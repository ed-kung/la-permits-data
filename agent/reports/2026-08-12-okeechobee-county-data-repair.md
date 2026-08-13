# Okeechobee County (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script was **Okeechobee County**. DATA is a uniform civic/eTRAKiT payload (`permit_info` + dict-format `inspections`; `search_data` has two key-set variants). Upstream left 40 `STATUS_NORMALIZED` nulls (unmapped `CLOSED FINAL` / holds / plan-review labels) and mislabeled `APPROVED` as Active, `UNKNOWN` as Final, and four finaled `ISSUED`/`INSPECTED` rows as Active. Present dates already matched `PermitAppliedDate` / `PermitIssuedDate` / `PermitFinaledDate` wherever set. The repair filled 37 statuses and 37 `PERMIT_DATE` values (from `PermitApprovedDate`), filled 2 `FINAL_DATE` values from passed FINAL inspections, fixed 17 statuses, and cleared 2 spurious Inactive `FINAL_DATE` values. After repair: STATUS 99.9% populated; FILE_DATE unchanged at 99.9%; Active/Final PERMIT_DATE 98.9%/99.2%; Final FINAL_DATE 97.1%.

## Jurisdiction selection

Ordered `(JURISDICTION, STATE)` pairs in `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` were checked against `agent/scripts/{state}/data_repair_{state}_{city}.py`. First missing: **Okeechobee County, FL** → `agent/scripts/fl/data_repair_fl_okeechobee_county.py` (2,001 sample rows).

## DATA schemas (`INFERRED_SCHEMA`)

All rows share the same top-level keys: `contacts`, `fees`, `inspections`, `permit_info`, `search_data`, `site_info`. `search_data` appears in two key-set variants (legacy `Permit No` / `SITE_*` vs newer `Permit Number` / `Address`), but canonical lifecycle fields always live under `permit_info`. Content variants split by which `permit_info` dates are populated:

| Schema | n | Notes |
| --- | ---: | --- |
| `civic_issued_finaled` | 1,408 | Issued + finaled dates |
| `civic_issued` | 451 | Issued, no finaled |
| `civic_applied` | 80 | Applied only |
| `civic_approved` | 32 | Approved (no issued/finaled) |
| `civic_finaled` | 28 | Finaled without issued |
| `civic_status_only` | 2 | Empty / near-empty shells |

Canonical fields:

| Target field | Source in DATA |
| --- | --- |
| STATUS_NORMALIZED | `permit_info.PermitStatus` (+ Final when `PermitFinaledDate` set, except Inactive terminals; In Review labels with issued → Active) |
| FILE_DATE | `PermitAppliedDate` else `PermitIssuedDate` |
| PERMIT_DATE | `PermitIssuedDate` else `PermitApprovedDate` |
| FINAL_DATE | `PermitFinaledDate` else latest passed FINAL/MSO inspection |

## Field assessments

### STATUS_NORMALIZED

| PermitStatus | n | Upstream STATUS_NORMALIZED | Assessment |
| --- | ---: | --- | --- |
| FINALED | 1,455 | Final | Correct |
| ISSUED | 258 | Active (4 with `PermitFinaledDate`) | 4 should be Final |
| INSPECTED | 117 | Active (1 with `PermitFinaledDate`) | 1 should be Final |
| VOID | 73 | Inactive | Correct |
| EXPIRED | 28 | Inactive | Correct |
| CLOSED FINAL | 20 | **null** | Fill → Final |
| APPLIED | 10 | In Review (1 with issued) | Issued row → Active |
| APPROVED | 10 | **Active** | Without issued → In Review; with issued → Active |
| 1ST HOLD | 7 | **null** | Fill → In Review (or Active if issued) |
| DENIED | 6 | Inactive | Correct |
| BUILDING PLAN REVIEW | 5 | **null** | Fill → In Review |
| (blank) | 3 | **null** | No strong signal → leave null |
| ZONING PLAN REVIEW | 3 | **null** | Fill → In Review |
| FRONT HOLD | 2 | **null** | Fill → In Review |
| UNKNOWN | 2 | **Final** | No issue/final evidence → In Review |
| READY | 1 | In Review (has issued) | → Active |
| ZONING HOLD | 1 | In Review | Correct |

**Root causes:**
1. Upstream mapper omitted `CLOSED FINAL`, hold labels (`1ST HOLD`, `FRONT HOLD`), and plan-review labels.
2. `APPROVED` was treated as Active even when `PermitIssuedDate` was blank (approved ≠ issued).
3. `UNKNOWN` was forced to Final despite having only an applied date.
4. A few `ISSUED`/`INSPECTED` shells still carry `PermitFinaledDate` but kept an Active label.

**Repair performance:** FILLED 37, FIXED 17; missing 40 → 3 (empty shells only).

### FILE_DATE

- Before: missing on **2 / 2,001** rows. Present values always matched `PermitAppliedDate` at calendar-day resolution (0 mismatches).
- Both gaps (VOID + empty shell) have blank `PermitAppliedDate` and blank `PermitIssuedDate` → not fillable from DATA.
- Ideal coverage already ~100% for every populated status class.

**Repair performance:** FILLED 0, FIXED 0; missing 2 → 2 (99.9% coverage).

### PERMIT_DATE

- Before: missing on **142 / 2,001**; present values always matched `PermitIssuedDate` (0 mismatches).
- Gaps concentrated in Active (20), Final (34), Inactive (59), In Review (10), and null-status (19).
- Filled 37 from `PermitApprovedDate` when issued was blank (Final / Active ISSUED / Inactive VOID|DENIED, plus CLOSED FINAL after status fill).
- Remaining Active/Final gaps (16): `FINALED` (12), `ISSUED` (3), `INSPECTED` (1) with neither issued nor approved in DATA.
- In Review rows correctly have no `PERMIT_DATE` after repair.

**Repair performance:** FILLED 37, FIXED 0; missing 142 → 105. Active coverage 98.9%; Final coverage 99.2%.

### FINAL_DATE

- Before: missing on **565 / 2,001**, including 29 Final rows; 4 Active and 2 Inactive (VOID) rows incorrectly carried `PermitFinaledDate`.
- Filled 2 Final gaps from passed `**FINAL MH` / `**FINAL ELECTRIC` inspections when `PermitFinaledDate` was blank.
- Cleared 2 spurious Inactive finals (FIXED). The 4 Active+finaled rows were upgraded to Final (status FIXED) so their dates were retained rather than cleared.
- Remaining Final gaps (43): `FINALED` (25) and `CLOSED FINAL` (18) with no finaled stamp and no usable passed final inspection — mostly older legacy shells.

**Repair performance:** FILLED 2, FIXED 2; missing count stays 565 overall (fills offset by Inactive clears), but Final coverage is 97.1% (1,436 / 1,479) with 0% FINAL_DATE on Active / In Review / Inactive.

## Repair script

- Path: `agent/scripts/fl/data_repair_fl_okeechobee_county.py`
- Entry point: `data_repair(df)`
- Outputs: overwritten `STATUS_NORMALIZED` / `FILE_DATE` / `PERMIT_DATE` / `FINAL_DATE`; flags `{FIELD}_FLAG` ∈ {`FILLED`, `FIXED`}; `INFERRED_SCHEMA`
- Conventions follow `agent/scripts/ny/data_repair_ny_ny.py` and the civic pattern in `agent/scripts/fl/data_repair_fl_sumter_county.py`

## Artifacts

- Repaired sample parquet: `AGENT_DATA_PATH/okeechobee_county_repaired_sample.parquet`

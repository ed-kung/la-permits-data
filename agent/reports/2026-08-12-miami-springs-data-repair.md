# Miami Springs (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script was **Miami Springs**. DATA is a uniform civic/eTRAKiT payload (`permit_info` + dict-format `inspections`). Upstream left 1 null `STATUS_NORMALIZED` (`IN APPROVAL` with an issue date), mislabeled 4 stale `CLOSED` rows as Active and 2 issued/`REVISIONS` rows as In Review, and left many Final rows without `FINAL_DATE` despite usable final inspections or `PermitFinaledDate`. `FILE_DATE` was already complete and correct. The repair filled/fixed 7 statuses, filled 6 `PERMIT_DATE` values and 18 `FINAL_DATE` values. After repair: STATUS 100%; FILE_DATE 100%; Active/Final PERMIT_DATE 98.4%/98.7%; Final FINAL_DATE 46.5% (limited by empty finaled/inspection payloads on older CLOSED and all `FINAL INSPECTION COMPLETE` shells).

## Jurisdiction selection

Ordered `(JURISDICTION, STATE)` pairs in `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` were checked against `agent/scripts/{state}/data_repair_{state}_{city}.py`. First missing: **Miami Springs, FL** → `agent/scripts/fl/data_repair_fl_miami_springs.py` (2,000 sample rows).

## DATA schemas (`INFERRED_SCHEMA`)

All rows share the same top-level keys: `contacts`, `fees`, `inspections`, `permit_info`, `search_data`, `site_info`. Canonical lifecycle fields always live under `permit_info`. Content variants split by which `permit_info` dates are populated:

| Schema | n | Notes |
| --- | ---: | --- |
| `civic_issued` | 1,122 | Issued, no finaled |
| `civic_issued_finaled` | 746 | Issued + finaled dates |
| `civic_applied` | 108 | Applied only |
| `civic_finaled` | 21 | Finaled without issued |
| `civic_approved` | 3 | Approved (no issued/finaled) |

Canonical fields:

| Target field | Source in DATA |
| --- | --- |
| STATUS_NORMALIZED | `permit_info.PermitStatus` (+ Final when `PermitFinaledDate` set, except Inactive terminals; In Review labels with issued → Active) |
| FILE_DATE | `PermitAppliedDate` else `PermitIssuedDate` |
| PERMIT_DATE | `PermitIssuedDate` else `PermitApprovedDate` |
| FINAL_DATE | `PermitFinaledDate` else latest passed FINAL/CO/CC inspection |

## Field assessments

### STATUS_NORMALIZED

| PermitStatus | n | Upstream STATUS_NORMALIZED | Assessment |
| --- | ---: | --- | --- |
| CLOSED | 1,520 | Final (1,516); Active (4) | 4 stale Active → Final |
| FINAL INSPECTION COMPLETE | 160 | Final | Correct |
| PERMIT PRINTED | 79 | Active | Correct |
| ISSUED | 44 | Active (43); In Review (1) | In Review → Active |
| CANCELLED | 40 | Inactive | Correct |
| PERMIT ISSUED | 39 | Active | Correct |
| PERMIT REVOKED | 37 | Inactive | Correct |
| PLAN REVIEW | 29 | In Review | Correct |
| APPROVED | 26 | Active | Correct |
| PLAN CHECK | 8 | In Review | Correct |
| EXPIRED | 6 | Inactive | Correct |
| PERMIT EXPIRED | 3 | Inactive | Correct |
| TO BE ISSUED | 3 | In Review | Correct |
| IN PLAN CHECK | 3 | In Review | Correct |
| IN APPROVAL | 1 | **null** (has issued) | → Active |
| REVISIONS | 1 | In Review (has issued) | → Active |
| ON HOLD | 1 | In Review | Correct |

**Root causes:**
1. Upstream left `IN APPROVAL` unmapped (1 null) even though `PermitIssuedDate` is present.
2. `STATUS_ORIGINAL` lagged live `PermitStatus` on 4 `CLOSED` rows still labeled issued / permit issued → Active; 3 of those also carry `PermitFinaledDate` with a blank `FINAL_DATE`.
3. One `ISSUED` and one `REVISIONS` row kept In Review despite a real issue date.

**Repair performance:** FILLED 1, FIXED 6; missing 1 → 0.

### FILE_DATE

- Before: missing on **0 / 2,000**. Every value matched `PermitAppliedDate` at calendar-day resolution.
- No fills or fixes required. Ideal coverage remains 100% for every status class.

**Repair performance:** FILLED 0, FIXED 0; missing 0 → 0 (100% coverage).

### PERMIT_DATE

- Before: missing on **133 / 2,000**; present values always matched `PermitIssuedDate` (0 mismatches).
- Filled 6 from `PermitIssuedDate` or `PermitApprovedDate` (ISSUED→Active, APPROVED×2, CLOSED Final×2, plus 1 Inactive with an issue/approve stamp).
- Remaining Active/Final gaps (25): `CLOSED` (22) and `ISSUED` (3) with neither issued nor approved in DATA.
- In Review rows correctly have no `PERMIT_DATE` after repair.

**Repair performance:** FILLED 6, FIXED 0; missing 133 → 127. Active coverage 98.4%; Final coverage 98.7%.

### FINAL_DATE

- Before: missing on **1,236 / 2,000**, including 912 Final gaps; 3 Active `CLOSED` rows incorrectly lacked `FINAL_DATE` while carrying `PermitFinaledDate` (no spurious non-Final finals).
- Filled 18 Final gaps: 3 from `PermitFinaledDate` (after Active→Final upgrades), 15 from passed FINAL / CO / CC inspections when `PermitFinaledDate` was blank.
- Remaining Final gaps (898): `CLOSED` (738) and `FINAL INSPECTION COMPLETE` (160) with no finaled stamp and no usable passed final inspection (the 160 FIC shells have empty `inspections` arrays and blank notes).

**Repair performance:** FILLED 18, FIXED 0; overall missing 1,236 → 1,218. Final coverage 46.5% (782 / 1,680) with 0% FINAL_DATE on Active / In Review / Inactive.

## Repair script

- Path: `agent/scripts/fl/data_repair_fl_miami_springs.py`
- Entry point: `data_repair(df)`
- Outputs: overwritten `STATUS_NORMALIZED` / `FILE_DATE` / `PERMIT_DATE` / `FINAL_DATE`; flags `{FIELD}_FLAG` ∈ {`FILLED`, `FIXED`}; `INFERRED_SCHEMA`
- Conventions follow `agent/scripts/ny/data_repair_ny_ny.py` and the civic pattern in `agent/scripts/fl/data_repair_fl_miami_lakes.py`

## Artifacts

- Repaired sample parquet: `AGENT_DATA_PATH/miami_springs_repaired_sample.parquet`

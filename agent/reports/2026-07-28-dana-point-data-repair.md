# Dana Point (CA) data repair — 2026-07-28

Dana Point was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. Civic-portal JSON under `DATA` is consistent with San Clemente-style `permit_info` payloads. Upstream status lagged behind `PermitStatus` / `PermitFinaledDate` on 22 rows; 190 blank-status HISTORICAL/CONVERTED shells were fillable from dates; Active/Final `PERMIT_DATE` gaps were mostly fillable from `PermitApprovedDate`; Final `FINAL_DATE` gaps were fillable from `PermitFinaledDate` or final inspections; 4 CANCELLED close stamps and 2 out-of-range finals were cleared. `FILE_DATE` already matched `PermitAppliedDate` wherever both existed; residual gaps lack AppliedDate in `DATA`.

## Jurisdiction selection

Walked `(JURISDICTION, STATE)` pairs in sample appearance order and compared against `agent/scripts/{state}/data_repair_{state}_{city}.py`. First missing: **Dana Point, CA** → `agent/scripts/ca/data_repair_ca_dana_point.py` (n=2,000).

## DATA schema

All 2,000 rows share top-level keys `fees`, `contacts`, `site_info`, `inspections`, `permit_info`, `search_data`. Canonical fields live under `permit_info` (`PermitStatus`, `PermitAppliedDate`, `PermitIssuedDate`, `PermitApprovedDate`, `PermitFinaledDate`). `INFERRED_SCHEMA` records content variants by which dates are populated:

| Schema | n | Description |
| --- | ---: | --- |
| `permit_info_issued_finaled` | 1,327 | Issued + Finaled present |
| `permit_info_issued` | 241 | Issued present, Finaled blank/invalid |
| `legacy_no_status` | 190 | blank / `<NONE>` PermitStatus but usable dates |
| `permit_info_applied_only` | 123 | only Applied populated |
| `permit_info_finaled_only` | 47 | Finaled present, Issued blank |
| `permit_info_approved_only` | 46 | Approved present, Issued/Finaled blank |
| `permit_info_empty_dates` | 26 | status text and/or shell with no usable dates |

Dates outside 1990–2035 (3 `PermitFinaledDate` values: two 1958, one 5009) are rejected as invalid.

## Field assessment

### STATUS_NORMALIZED

- Missing on 211 / 2,000 (10.6%). All missing rows have blank or `<NONE>` `PermitStatus` (mostly `HISTORICAL` / `CONVERTED` shells).
- **Fillable:** 190 via date inference (Issued/Approved → Active; Finaled → Final; Applied-only → In Review).
- **Unfillable:** 21 shells with no status and no usable dates (`permit_info_empty_dates`).
- **Incorrect (22 FIXED):**
  - Active → Final (18): 9 with `PermitStatus=FINALED` but `STATUS_ORIGINAL=permit issued` (stale upstream label); 9 with `PERMIT ISSUED` plus a populated `PermitFinaledDate` (status text lagged behind finaled stamp).
  - In Review → Active (4): `PERMIT ISSUED` (3) or `APPROVED` (1) mislabeled from `STATUS_ORIGINAL` (`under review` / `pending submittal`).
- Mapping: `FINALED`→Final; `PERMIT ISSUED`/`ISSUED`/`APPROVED`/`ACTIVE*`→Active; `UNDER REVIEW`/`DUE`/`EXPIRED_RENEWED`/`PENDING*`/`PAID`/`SUSPENDED`→In Review; `CANCELLED`/`EXPIRED*` (except `_RENEWED`)/`VOID`/`DENIED`/`INACTIVE`→Inactive. Non-inactive rows with `PermitFinaledDate` promoted to Final.
- **Repair:** 190 FILLED, 22 FIXED. Missing after: 21.

### FILE_DATE

- Missing on 273 / 2,000 (13.6%). Present values match `PermitAppliedDate` on all 1,727 rows (0 incorrect).
- Every missing row also has blank `PermitAppliedDate` in `DATA`. IssuedDate is not used as a FILE substitute (application ≠ issuance; 77 rows already show Issued before Applied in source).
- **Repair:** 0 FILLED, 0 FIXED. Coverage 86.4%.

### PERMIT_DATE

- Missing on 250 / 2,000 (12.5%). When present, every value matches `PermitIssuedDate` (0 incorrect).
- Active: 42 missing; Final: 47 missing before repair. Primary fill path: blank Issued but present `PermitApprovedDate` (fallback used for Active/Final only).
- **Repair:** 76 FILLED, 0 FIXED. Missing after: 174.
- Post-repair Active PERMIT coverage: 323/333 (97.0%); Final: 1,402/1,410 (99.4%). Residual 18 Active/Final gaps lack both Issued and Approved in `DATA`.

### FINAL_DATE

- Missing on 615 / 2,000 (30.8%). When present and status is Final, values match `PermitFinaledDate` except 2 out-of-range years copied from source (1958).
- Among Final (after status repair): fillable from `PermitFinaledDate` (12) or final/C-of-O inspection PASS (3+); 13+ remain without either source.
- **Spurious / bad FINAL_DATE cleared (6 FIXED):**
  - Inactive `CANCELLED` close stamps: 4
  - Final rows with out-of-range years (1958): 2
  - (`5009` finaled was already null in the column; rejected as a source.)
- Non-Final rows with finaled dates that were promoted to Final keep their finals.
- **Repair:** 15 FILLED, 6 FIXED. Missing after: 606.
- Post-repair Final FINAL coverage: 1,394/1,410 (98.9%). Active / In Review / Inactive: 0% by design.

## Repair performance

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | ---: | ---: | ---: | ---: |
| STATUS_NORMALIZED | 190 | 22 | 211 | 21 |
| FILE_DATE | 0 | 0 | 273 | 273 |
| PERMIT_DATE | 76 | 0 | 250 | 174 |
| FINAL_DATE | 15 | 6 | 615 | 606 |

Status distribution: Final 1,372→1,410 · Active 180→333 · In Review 119→118 · Inactive 118→118 · null 211→21.

Post-repair completeness by status:

| Status | n | FILE_DATE | PERMIT_DATE | FINAL_DATE |
| --- | ---: | ---: | ---: | ---: |
| Active | 333 | 66.4% | 97.0% | 0% |
| Final | 1,410 | 91.6% | 99.4% | 98.9% |
| In Review | 118 | 93.2% | 27.1% | 0% |
| Inactive | 118 | 89.0% | 58.5% | 0% |

Overall FILE_DATE coverage: 1,727 / 2,000 (86.4%). Active+Final PERMIT_DATE: 1,725 / 1,743 (99.0%).

Chronology: 77 `PERMIT < FILE` and 5 `FINAL < PERMIT` cases remain; all mirror inverted Applied/Issued/Finaled timestamps already present in `permit_info` (including re-apply / historical shells), not introduced by repair.

## Artifacts

- Script: `agent/scripts/ca/data_repair_ca_dana_point.py`
- Repaired sample: `AGENT_DATA_PATH/repaired/permits_ca_dana_point_repaired.parquet`

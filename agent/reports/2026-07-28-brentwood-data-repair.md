# Brentwood (CA) data repair — 2026-07-28

Brentwood was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. Civic-portal JSON under `DATA` (815 / 2,000 rows) supports filling 425 missing statuses and correcting 33 wrong ones, filling 65 missing `PERMIT_DATE` values from `PermitIssuedDate` / `PermitApprovedDate`, and clearing 1 spurious `FINAL_DATE` on a withdrawn permit. The other 1,185 rows have null `DATA` and cannot be repaired from JSON; their upstream status/date mapping from `STATUS_ORIGINAL` is left as-is.

## Jurisdiction selection

Walked `(JURISDICTION, STATE)` pairs in sample order and compared against `agent/scripts/{state}/data_repair_{state}_{city}.py`. First missing: **Brentwood, CA** → `agent/scripts/ca/data_repair_ca_brentwood.py` (n=2,000).

## DATA schema

When present, all rows share civic-portal top-level keys (`fees`, `contacts`, `site_info`, `inspections`, `permit_info`, `search_data`). Canonical dates/status live under `permit_info` (`PermitStatus`, `PermitAppliedDate`, `PermitIssuedDate` / `PermitApprovedDate`, `PermitFinaledDate`), with `search_data.Application` / `Issued` as redundant mirrors. Content variants recorded in `INFERRED_SCHEMA`:

| Schema | n | Description |
| --- | ---: | --- |
| `missing` | 1,185 | null `DATA` |
| `permit_info_applied_only` | 399 | Applied only (mostly fee-projection / emailed) |
| `permit_info_issued` | 246 | Issued present, Finaled blank |
| `permit_info_approved_only` | 81 | Approved present, no Issued/Finaled |
| `legacy_no_status` | 50 | blank `PermitStatus` but dates present |
| `permit_info_issued_finaled` | 33 | Issued + Finaled |
| `permit_info_empty_dates` | 3 | blank status, no usable dates |
| `permit_info_finaled_only` | 3 | Finaled present, Issued blank |

## Field assessment

### STATUS_NORMALIZED

- Missing on 428 / 2,000 (21.4%), all among rows with `DATA`. Upstream left fee-stage and blank-status labels unmapped:
  - `F_PROJECTION` (330) / `FEE PROJECTION` (40) / `BRENTWOOD REPRO` (4) / `TO BE BILLED` (1) → FILLED
  - Blank `PermitStatus` (53): 49 ENCROACHMENT/GRADING shells with `PermitApprovedDate` → Active; 1 with Applied only → In Review; 3 with no dates → unfillable
- Incorrect mappings / lag vs `PermitStatus` / `PermitFinaledDate`:
  - `FEE ESTIMATE` (7) previously Inactive → FIXED to In Review (same fee workflow as projections)
  - Non-inactive rows with `PermitFinaledDate`: ISSUED/APPROVED Active → Final (20); ACCEPTED In Review → Final (6)
- Rows without `DATA` already have status from `STATUS_ORIGINAL` (`finaled`→Final, `issued`→Active, `expired`/`withdrawn`/`void`→Inactive); left unchanged.
- **Repair:** 425 FILLED, 33 FIXED. Missing after: 3.

### FILE_DATE

- Missing on 9 / 2,000. When both present, every `FILE_DATE` matches `PermitAppliedDate` (0 incorrect).
- 3 gaps are empty-date shells (no Applied / `search_data.Application`); 6 are Final rows with null `DATA`.
- **Repair:** 0 FILLED, 0 FIXED. Coverage 1,991 / 2,000 (99.6%).

### PERMIT_DATE

- Missing on 539 / 2,000. When present with `DATA`, every value matches `PermitIssuedDate` (0 incorrect).
- Fillable gaps: Active ISSUED rows with Approved but blank Issued (14); blank-status shells inferred Active with Approved (49); Final / promoted-Final rows with Issued or Approved (2).
- Unfillable: 1 Active ISSUED (`MP11-0129`) with neither Issued nor Approved; In Review / fee-stage rows by design; null-`DATA` Final shells lacking dates upstream.
- **Repair:** 65 FILLED, 0 FIXED. Missing after: 474.
- Post-repair Active PERMIT coverage: 347/348 (99.7%); Final: 1,021/1,025 (99.6%); Active+Final: 1,368/1,373 (99.6%).

### FINAL_DATE

- Missing on 1,015 / 2,000. When present with `DATA`, values match `PermitFinaledDate` (0 incorrect vs that field).
- Among Final after status repair: 41 still missing FINAL — 23 ISSUED-only FINALED rows (inspections are `Encroachment Inspect` with empty Result, not usable), 1 approved-only, 17 null-`DATA`.
- **Spurious FINAL_DATE:** 1 Inactive `WITHDRAWN` row carried `PermitFinaledDate` as a close stamp → cleared. The other 26 non-Final rows that had Finaled were promoted to Final, so their FINAL_DATE became correct rather than cleared.
- **Repair:** 0 FILLED, 1 FIXED (clear). Missing after: 1,016.
- Post-repair Final FINAL coverage: 984/1,025 (96.0%). Active / In Review / Inactive: 0% by design.

## Repair performance

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | ---: | ---: | ---: | ---: |
| STATUS_NORMALIZED | 425 | 33 | 428 | 3 |
| FILE_DATE | 0 | 0 | 9 | 9 |
| PERMIT_DATE | 65 | 0 | 539 | 474 |
| FINAL_DATE | 0 | 1 | 1,015 | 1,016 |

Status distribution:

| | Before | After |
| --- | ---: | ---: |
| Final | 999 | 1,025 |
| Active | 318 | 348 |
| In Review | 88 | 464 |
| Inactive | 167 | 160 |
| (missing) | 428 | 3 |

Post-repair completeness by status:

| Status | n | FILE_DATE | PERMIT_DATE | FINAL_DATE |
| --- | ---: | ---: | ---: | ---: |
| Active | 348 | 100% | 99.7% | 0% |
| Final | 1,025 | 99.4% | 99.6% | 96.0% |
| In Review | 464 | 100% | 0.4% | 0% |
| Inactive | 160 | 100% | 97.5% | 0% |

Overall FILE_DATE coverage: 1,991 / 2,000 (99.6%). Active+Final PERMIT_DATE: 1,368 / 1,373 (99.6%).

Chronology: 8 `PERMIT < FILE` and 8 `FINAL < PERMIT` cases remain; all mirror inverted Applied/Issued/Finaled timestamps already present in `permit_info`, not introduced by repair.

## Artifacts

- Repair script: `agent/scripts/ca/data_repair_ca_brentwood.py`
- Repaired sample parquet: `$AGENT_DATA_PATH/repaired/permits_ca_brentwood_repaired.parquet`

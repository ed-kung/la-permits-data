# Redding (CA) data repair — 2026-07-28

Redding’s EnerGov `DATA` JSON is high quality: `FILE_DATE` already matches `ApplyDate` on all 2,000 sample rows, and most statuses/dates are correct. The repair script fixes 12 stale/missing `STATUS_NORMALIZED` values (STATUS_ORIGINAL lagged CaseStatus), fills 1 missing `PERMIT_DATE` and 9 missing `FINAL_DATE`s after status correction, and clears 107 spurious `FINAL_DATE`s on non-Final (mostly Void) rows.

## Jurisdiction selected

First `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing `agent/scripts/{state}/data_repair_{state}_{city}.py`: **Redding, CA**.

## DATA schema

Tyler EnerGov-style payload. All 2,000 rows have `entity` + `details` + `fees` (+ `contacts`, `processing_status`).

| INFERRED_SCHEMA | n |
| --- | ---: |
| `entity_fees` | 1,920 |
| `entity_fees_reviews` | 80 |

Canonical sources:
- **STATUS_NORMALIZED** ← `entity.CaseStatus` / `details.PermitStatus`
- **FILE_DATE** ← `entity.ApplyDate`
- **PERMIT_DATE** ← `entity.IssueDate`
- **FINAL_DATE** ← `entity.FinalDate` (not `ExpireDate`)

### CaseStatus → STATUS_NORMALIZED

| CaseStatus | Mapped |
| --- | --- |
| Finaled | Final |
| Issued/Active | Active |
| Expired, Void, Denied, Fee Estimate | Inactive |
| Pending/In Plan Review, Ready to Issue, Online Permit (Pending Review), Waiting for Resubmit | In Review |

## Field assessment (before repair)

### STATUS_NORMALIZED
- Distribution: Final 1,481 / Active 289 / Inactive 174 / In Review 55 / null 1.
- **12 incorrect or missing** vs CaseStatus:
  - 9× Active while CaseStatus=`Finaled` (STATUS_ORIGINAL still `issued/active`)
  - 1× Active while `Expired`
  - 1× In Review while `Void`
  - 1× null for `Waiting for Resubmit`

### FILE_DATE
- **0 missing; 2,000/2,000 match ApplyDate.** No repair needed.

### PERMIT_DATE
- 178 missing overall.
- Among Active/Final: 4 missing — 1 Active has IssueDate (`TPAN-2024-05071`, issue 2025-02-03) and is fillable; 3 Finaled FIRE/GRAD rows have `Issued=False` and null IssueDate (not fillable).
- Existing non-null values match IssueDate when present.

### FINAL_DATE
- All 1,481 Final rows already have FINAL_DATE matching FinalDate.
- **9 Finaled-but-labeled-Active rows** have FinalDate in DATA but null FINAL_DATE → fillable after status fix.
- **107 non-Final rows** carry FINAL_DATE (mostly Void close stamps; 1 Issued/Active; 2 Expired) — not permit finaling dates; clear them.

## Repair performance

Script: `agent/scripts/ca/data_repair_ca_redding.py`  
Artifact: `AGENT_DATA_PATH/repaired/permits_ca_redding_repaired.parquet`

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 1 | 11 | 1 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 1 | 0 | 178 → 177 |
| FINAL_DATE | 9 | 107 | 412 → 510 |

Status transitions: Active→Final (9), Active→Inactive (1), In Review→Inactive (1); plus null→In Review (1 FILLED).

### After-repair coverage

| Status | PERMIT_DATE | FINAL_DATE |
| --- | --- | --- |
| Active | 279/279 (100%) | 0/279 (0%) |
| Final | 1,487/1,490 (99.8%) | 1,490/1,490 (100%) |
| In Review | 1/55 | 0/55 |
| Inactive | 56/176 | 0/176 |

FILE_DATE: 2,000/2,000 (100%).

### Residual gaps (not repairable from DATA)
- 3 Finaled rows without IssueDate → PERMIT_DATE remains missing.
- 10 FILE>PERMIT and 20 PERMIT>FINAL day inversions exist in source IssueDate/FinalDate (timezone / data-entry artifacts); script does not invent alternate dates.

## Summary

Redding’s upstream mapping is mostly correct but occasionally stale relative to live CaseStatus. Aligning status to CaseStatus/PermitStatus, filling the few missing issue/final dates those corrections unlock, and stripping FinalDate from non-Final shells yields complete FILE_DATE, complete FINAL_DATE for Final, and complete PERMIT_DATE for Active (with only three Final shells lacking issuance timestamps in DATA).

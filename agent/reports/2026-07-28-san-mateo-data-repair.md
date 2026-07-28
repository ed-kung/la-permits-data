# San Mateo (CA) data repair — 2026-07-28

San Mateo was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. EnerGov JSON under `DATA` already has correct `FILE_DATE` (all 2,000 rows) and, when populated, correct `PERMIT_DATE` / `FINAL_DATE` matching `entity.IssueDate` / `entity.FinalDate`. Main issues were 1 stale `STATUS_NORMALIZED` (CaseStatus Issued while PermitStatus Finaled), 2 Final rows missing `FINAL_DATE` fillable from Passed final inspections, 1 additional `FINAL_DATE` fill after status catch-up, and 5 spurious `FINAL_DATE` values on non-Final Issued/Pending/Cancelled shells.

## Jurisdiction selected

First `(JURISDICTION, STATE)` pair without `agent/scripts/{state}/data_repair_{state}_{city}.py`: **San Mateo, CA**.

## DATA schema

All rows share Tyler EnerGov top-level keys (`entity`, `details`, `contacts`, `fees`, `processing_status`). 103 rows also carry a reviews bundle (`reviews` / `holds` / `attachments` / `more_info`). Canonical dates/status live under `entity` (`CaseStatus`, `ApplyDate`, `IssueDate`, `FinalDate`) with `details` fallbacks (`PermitStatus`, `ApplyDate`, `IssueDate`, `FinalizeDate`). When `FinalDate`/`FinalizeDate` are null on Final rows, the latest Passed `processing_status` inspection whose description mentions “Final” is used. Recorded in `INFERRED_SCHEMA`:

| INFERRED_SCHEMA | n |
| --- | ---: |
| `entity_fees` | 1,897 |
| `entity_fees_reviews` | 103 |

### CaseStatus → STATUS_NORMALIZED

| CaseStatus | Mapped |
| --- | --- |
| Finaled | Final |
| Issued, Issued (Revision Pending) | Active |
| Expired, Expired Plan Check, Cancelled, Withdrawn | Inactive |
| Under Review, Ready for Issuance, Ready for Issuance (Revision), Pending | In Review |

When CaseStatus and PermitStatus disagree, the more advanced mapped status wins (Finaled over Issued).

## Field assessment (before repair)

### STATUS_NORMALIZED
- Distribution: Final 1,277 / Inactive 376 / Active 256 / In Review 91 / null 0.
- Upstream mapping from `STATUS_ORIGINAL` matches CaseStatus on 1,999/2,000 rows.
- **1 incorrect**: `BD-2023-291872` labeled Active (CaseStatus=`Issued`, STATUS_ORIGINAL=`issued`) while `details.PermitStatus`=`Finaled` and FinalizeDate is present.

### FILE_DATE
- **0 missing; 2,000/2,000 match ApplyDate.** No repair needed.

### PERMIT_DATE
- 185 missing overall; existing non-null values match IssueDate on every overlapping row.
- Among Active/Final: **5 missing**, all Finaled “Converted” historical shells with `Issued=False` and null IssueDate — not fillable from DATA.
- Active coverage already 100% (IssueDate present on every Issued / Issued-Revision-Pending row).

### FINAL_DATE
- 1,275/1,277 Final rows already match FinalDate; **2 Final rows** have null FinalDate/FinalizeDate but Passed Building Final inspections → fillable.
- **5 non-Final rows** carry FINAL_DATE (3 Issued, 1 Pending, 1 Cancelled) from entity.FinalDate close stamps — clear them; do not promote status from FinalDate alone.

## Repair performance

Script: `agent/scripts/ca/data_repair_ca_san_mateo.py`  
Artifact: `AGENT_DATA_PATH/repaired/permits_ca_san_mateo_repaired.parquet`

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 0 | 1 | 0 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 0 | 0 | 185 → 185 |
| FINAL_DATE | 3 | 5 | 720 → 722 |

Status transitions: Active→Final (1).

FINAL_DATE missing count rises slightly because 5 spurious non-Final values were cleared while only 3 Final gaps were filled.

### After-repair coverage

| Status | PERMIT_DATE | FINAL_DATE |
| --- | --- | --- |
| Active | 255/255 (100%) | 0/255 (0%) |
| Final | 1,273/1,278 (99.6%) | 1,278/1,278 (100%) |
| In Review | 2/91 | 0/91 |
| Inactive | 285/376 | 0/376 |

FILE_DATE: 2,000/2,000 (100%).

### Not repairable from DATA
- Five Finaled Converted shells lack IssueDate → PERMIT_DATE stays missing.
- One FILE>PERMIT and two PERMIT>FINAL day inversions remain in source EnerGov dates; dates are left as in DATA.
- ExpireDate is a validity window, not a completion date.

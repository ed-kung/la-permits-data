# Seal Beach (CA) data repair

**Summary:** Seal Beach was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. Assessed 2,000 Tyler EnerGov records against `DATA`. Main defects: 69 Issued (and 2 In Review) shells already carrying `FinalDate` / `FinalizeDate` left Active / In Review; 3 review-pipeline rows with `IssueDate` left In Review; 3 Approved shells left Active with no issuance; 7 Void Inactive rows carrying spurious `FINAL_DATE`; and 2 Issued/`PermitStatus=Complete` rows with `FinalizeDate` only and null `FINAL_DATE`. Repair fixes 77 statuses, fills 2 finals, and clears 7 spurious finals. `FILE_DATE` already matched `ApplyDate` everywhere. Residual gaps: 149 Complete/Final rows with no final stamp → `FINAL_DATE` stays missing; 137 Final rows with no `IssueDate` → `PERMIT_DATE` stays missing. Script: `agent/scripts/ca/data_repair_ca_seal_beach.py`.

## Jurisdiction selection

First `(JURISDICTION, STATE)` in sample order without `agent/scripts/{state}/data_repair_{state}_{city}.py` was **Seal Beach, CA** (2,000 rows; index 153 after Petaluma).

## DATA schema

All rows share Tyler EnerGov top-level keys. Canonical dates/status live under `entity` with `details` fallbacks (`CaseStatus` / `PermitStatus`, `ApplyDate`, `IssueDate`, `FinalDate` / `FinalizeDate`). Content variants in `INFERRED_SCHEMA`:

| Schema | n | Keys |
| --- | ---: | --- |
| `entity_fees` | 1,909 | entity, details, contacts, fees, processing_status |
| `entity_fees_reviews` | 91 | above + reviews / holds / attachments / more_info |

`ExpireDate` is a validity window, not completion. `CompleteDate` / `ClosedDate` / `OpenedDate` are always null in this sample. Prefer `entity.FinalDate` over `details.FinalizeDate` (98 day offsets are timezone artifacts; existing `FINAL_DATE` always matches `FinalDate`).

## Field assessment

### STATUS_NORMALIZED

Before repair: Final 1,415 / Active 276 / In Review 170 / Inactive 139 / missing 0. Mapping tracked `CaseStatus` 1:1 (`Complete`→Final, `Issued`→Active, review labels→In Review, `Expired`/`Void`/`Canceled`/`Withdrawn`→Inactive, `Approved`→Active).

| CaseStatus | Before STATUS_NORMALIZED | n |
| --- | --- | ---: |
| Complete | Final | 1,415 |
| Issued | Active | 273 |
| Expired / Void / Canceled / Withdrawn | Inactive | 139 |
| In Review / Fees Due / On Hold / Submitted / Submitted - Online | In Review | 170 |
| Approved | Active | 3 |

Issues:

- **67** `Issued` / Active rows already carry `FinalDate` (+ matching `FinalizeDate`; mostly Public Works encroachment) → Final (FIXED).
- **2** `Issued` / Active rows with `PermitStatus=Complete` and `FinalizeDate` only (no `entity.FinalDate`) → Final (FIXED); `FINAL_DATE` FILLED from `FinalizeDate`.
- **2** `In Review` rows with `FinalDate` → Final (FIXED).
- **2** `In Review` + **1** `On Hold` with `IssueDate` but no final stamp → Active (FIXED).
- **3** `Approved` shells with no `IssueDate` left Active → In Review (FIXED; plan approval, not issuance).
- Inactive terminal labels (Expired / Void / Canceled / Withdrawn) are sticky even when `FinalDate` is present as a case-closure stamp.
- `CaseStatus=Complete` stays Final even when `FinalDate` is absent (149 rows); do not demote to Active via `IssueDate`.

### FILE_DATE

2,000 / 2,000 populated. Every FILE_DATE matches `entity.ApplyDate` at UTC calendar-day resolution (0 mismatches). **No FILE_DATE repairs.**

### PERMIT_DATE

Where both exist, PERMIT_DATE matches `IssueDate` (0 mismatches). Gaps:

- After repair, all Active rows have PERMIT_DATE (207 / 207), including the 3 promoted from In Review / On Hold.
- **137** Final/`Complete` rows with null IssueDate → not fillable; DATA has no alternate issuance stamp.
- After promoting 71 issued/review shells into Final, Final PERMIT coverage is 1,349 / 1,486 (90.8%).
- Five pre-existing FILE_DATE > PERMIT_DATE day inversions remain (including one 1965 IssueDate stamp); not introduced by repair.

### FINAL_DATE

Where both exist, FINAL_DATE matches `entity.FinalDate` (0 mismatches). Issues:

- **149** Complete/Final rows missing FinalDate and FinalizeDate → not fillable (mostly older encroachment / banner / POD shells).
- **2** Issued→Final promotions with FinalizeDate only → FINAL_DATE FILLED.
- **7** Void Inactive rows carried FINAL_DATE from case-closure `FinalDate` → cleared (FIXED).
- The 67 Active and 2 In Review rows that previously carried FINAL_DATE were promoted to Final and retained the stamp.
- Two pre-existing PERMIT_DATE > FINAL_DATE day inversions remain; not introduced by repair.

## Repair performance

Script: `agent/scripts/ca/data_repair_ca_seal_beach.py`  
Artifact: `$AGENT_DATA_PATH/repaired/permits_ca_seal_beach_repaired.parquet`

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 0 | 77 | 0 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 0 | 0 | 381 → 381 |
| FINAL_DATE | 2 | 7 | 658 → 663 |

Status transitions:

- Active → Final: 69
- Active → In Review: 3
- In Review → Active: 3
- In Review → Final: 2

Post-repair coverage:

| Status | PERMIT_DATE | FINAL_DATE |
| --- | --- | --- |
| Active | 207 / 207 (100%) | 0 / 207 (0%) |
| Final | 1,349 / 1,486 (90.8%) | 1,337 / 1,486 (90.0%) |
| In Review | 0 / 168 (0%) | 0 / 168 (0%) |
| Inactive | 63 / 139 (45.3%) | 0 / 139 (0%) |

FILE_DATE: 2,000 / 2,000 (100%). Chronology inversions unchanged from input (FILE>PERMIT: 5; PERMIT>FINAL: 2).

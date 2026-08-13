# North Miami Beach (FL) data repair

**Summary:** North Miami Beach was the first `(JURISDICTION, STATE)` pair in `permits_fl_sample.parquet` without an existing repair script. Its `DATA` column is Tyler EnerGov JSON (`entity` / `details` / `fees` / `processing_status`, with a small `energov_full` subset). After repair, `STATUS_NORMALIZED` has no nulls and aligns with `CaseStatus`; `FILE_DATE` was already complete; all `Final` rows have `FINAL_DATE`; residual `PERMIT_DATE` gaps on Active/Final are blank `IssueDate` shells (mostly Finaled / Approved) that cannot be filled from `DATA`.

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_fl_sample.parquet`
- Jurisdiction: **North Miami Beach**, FL (2,000 sample rows)
- Script: `agent/scripts/fl/data_repair_fl_north_miami_beach.py`
- Artifact: `AGENT_DATA_PATH/repaired/permits_fl_north_miami_beach_repaired.parquet`

## DATA schemas (`INFERRED_SCHEMA`)

| Schema | n |
| --- | ---: |
| energov_issued_finaled | 1,152 |
| energov_issued | 459 |
| energov_applied | 252 |
| energov_finaled | 93 |
| energov_full_applied | 30 |
| energov_full_issued | 7 |
| energov_full_issued_finaled | 6 |
| energov_full_finaled | 1 |

Canonical sources: `entity.CaseStatus` → status; `ApplyDate` → file; `IssueDate` → permit; `FinalDate` / `FinalizeDate` → final. `processing_status` is null for every sample row.

## Findings by field

### STATUS_NORMALIZED

- Before: Final 1,190 / Inactive 634 / Active 93 / null 59 / In Review 24.
- Nulls were unmapped EnerGov statuses: In Review-ProjectDox (24), Prescreen (17), Waiting for Master Approval (5), Pending Application Correction (4), Prescreen Correction (3), Approved (3), Issued (2), On Hold (1).
- Mislabels vs `CaseStatus`: Finaled→Active (6) or Inactive (7); Issued→Inactive (3) or Final (1); Expired→Active (3).
- After repair: Final 1,202 / Inactive 627 / Active 93 / In Review 78 / null 0.
- Flags: **FILLED 59**, **FIXED 20**.

### FILE_DATE

- Already populated for all 2,000 rows; calendar day matches `entity.ApplyDate` everywhere.
- Flags: **FILLED 0**, **FIXED 0**.

### PERMIT_DATE

- When present, always matched `IssueDate` (no incorrect non-null values).
- Filled 2 Issued rows that had null `STATUS_NORMALIZED` but a usable `IssueDate`; cleared 1 spurious In Review `PERMIT_DATE`.
- After repair, Active/Final still missing `PERMIT_DATE`: **103** — Finaled 78, Approved 19, Issued 6 (all blank `IssueDate` in `DATA`; Approved shells also have `details.Issued=false`).
- Flags: **FILLED 2**, **FIXED 1**. Missing: 378 → 377.

### FINAL_DATE

- All true Finaled rows with stored `FinalDate` were recoverable; after reclassification, **Final has FINAL_DATE 1,202 / 1,202 (100%)**.
- Filled 12 Finaled shells that lacked `FINAL_DATE` (mostly mislabeled Active/Inactive).
- Fixed 1 stale `FINAL_DATE` (2021-02-25 vs agency `FinalDate` 2024-08-20) and cleared 50 spurious finals on non-Final statuses (Issued / On Hold / Void / Expired).
- Overall missing rose 760 → 798 because clears on non-Final outweigh fills — intended.
- Flags: **FILLED 12**, **FIXED 51**.

## Repair performance (sample)

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 59 | 20 | 59 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 2 | 1 | 378 → 377 |
| FINAL_DATE | 12 | 51 | 760 → 798 |

Post-repair coverage:

- `FILE_DATE`: 100% all statuses
- `PERMIT_DATE`: Active 73.1%, Final 93.5%, In Review 0%, Inactive 68.7%
- `FINAL_DATE`: Final 100%; other statuses 0%

Agency date-order quirks left as-is: 4 rows with `FILE_DATE` > `PERMIT_DATE`, 45 Finaled rows with `IssueDate` after `FinalDate` (both dates taken from EnerGov).

## Mapping used

| CaseStatus | STATUS_NORMALIZED |
| --- | --- |
| Finaled | Final |
| Issued, Approved | Active |
| In Review, In Review-ProjectDox, On Hold, Prescreen, Prescreen Correction, Pending Application Correction, Submitted, Submitted - Online, Waiting for Master Approval, Stop Work Order | In Review |
| Expired, Void | Inactive |

# Doral (FL) data repair

**Summary:** Doral’s Tyler EnerGov `DATA` payload maps cleanly via `entity.CaseStatus` / `ApplyDate` / `IssueDate` / `FinalDate`. Upstream status was already correct for mapped CaseStatuses; the main defects were 14 unmapped statuses left null, 2 In Review rows carrying an IssueDate as `PERMIT_DATE`, and 264 non-Final rows carrying cancel/spurious `FinalDate` stamps as `FINAL_DATE`. The repair fills the missing statuses and clears those spurious dates.

## Jurisdiction selected

First `(JURISDICTION, STATE)` in `permits_fl_sample.parquet` without an existing `agent/scripts/{state}/data_repair_{state}_{city}.py`: **Doral, FL** (2,000 sample rows).

## DATA shape

Tyler EnerGov payload for all rows:

- Top-level keys: `entity`, `details`, `contacts`, `fees`, `processing_status` (always null)
- Full variant (+50 rows): also `reviews`, `holds`, `attachments`, `more_info`
- Canonical fields: `entity.CaseStatus` (fallback `details.PermitStatus`), `entity.ApplyDate`, `entity.IssueDate`, `entity.FinalDate` (fallback `details.FinalizeDate`)

`INFERRED_SCHEMA` labels are `energov_{date_suffix}` / `energov_full_{date_suffix}` (e.g. `energov_issued_finaled`).

| INFERRED_SCHEMA | n |
| --- | ---: |
| energov_issued_finaled | 1,260 |
| energov_applied | 286 |
| energov_finaled | 286 |
| energov_issued | 118 |
| energov_full_applied | 34 |
| energov_full_issued | 10 |
| energov_full_finaled | 5 |
| energov_full_issued_finaled | 1 |

## Field assessment

### STATUS_NORMALIZED

| `entity.CaseStatus` | Upstream `STATUS_NORMALIZED` | n |
| --- | --- | ---: |
| Closed/No Further Action | Final | 1,254 |
| CO/CC Issued | Final | 35 |
| Issued | Active | 32 |
| Inspect | Active | 13 |
| Inspect - PW | *(null)* | 3 |
| Submitted - Online | In Review | 51 |
| Submitted - In Office | *(null)* | 11 |
| In Review | In Review | 57 |
| Fees Due | In Review | 14 |
| Apply | In Review | 4 |
| On Hold | In Review | 3 |
| Cancel | Inactive | 249 |
| Expired | Inactive | 221 |
| Void | Inactive | 47 |
| Denied | Inactive | 4 |
| Process Expired | Inactive | 2 |

Upstream mapping matched CaseStatus 1:1 wherever it was populated. **14 FILLED**: `Submitted - In Office` → In Review (11), `Inspect - PW` → Active (3). No status FIXED. One row has `CaseStatus=Inspect` but `PermitStatus=Closed/No Further Action`; repair follows `CaseStatus` (Active).

### FILE_DATE

- Populated on all 2,000 rows; every value equals `entity.ApplyDate` at day resolution.
- No fills or fixes needed.

### PERMIT_DATE

- When present (1,389), always equals `entity.IssueDate` / `details.IssueDate`.
- Missing (611): Active 2, Final 31, In Review 127, Inactive 440, null-status 11.
- Fillable Active/Final gaps: none — the 33 Active/Final shells with blank `IssueDate` also have `details.Issued=False`.
- In Review incorrectly carried `PERMIT_DATE` on 2 rows (On Hold / Fees Due with IssueDate) → **2 FIXED** (cleared).
- After status fills, Active coverage is 46/48 (95.8%); Final 1,258/1,289 (97.6%).

### FINAL_DATE

- When present, always equals `entity.FinalDate` / `details.FinalizeDate`.
- Final missing `FINAL_DATE`: 2 Closed/No Further Action rows with blank FinalDate/FinalizeDate → not fillable.
- Non-Final with `FINAL_DATE`: 264 (Cancel 222, Void 36, Process Expired 2, Active 3, In Review 1). These are cancel/close or inconsistent stamps, not completion dates → **264 FIXED** by clearing.
- Active / In Review / Inactive correctly have no `FINAL_DATE` after repair; Final retains 1,287/1,289 (99.8%).

## Repair performance

Script: `agent/scripts/fl/data_repair_fl_doral.py`  
Artifact: `$AGENT_DATA_PATH/repaired/permits_fl_doral_repaired.parquet`

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 14 | 0 | 14 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 0 | 2 | 611 → 613 |
| FINAL_DATE | 0 | 264 | 449 → 713 |

Missing `PERMIT_DATE` / `FINAL_DATE` rise because clearing spurious non-target-status stamps outweighs any fills (none available from DATA).

### Coverage after repair

| Status | n | FILE_DATE | PERMIT_DATE | FINAL_DATE |
| --- | ---: | ---: | ---: | ---: |
| Active | 48 | 100% | 95.8% | 0% |
| Final | 1,289 | 100% | 97.6% | 99.8% |
| In Review | 140 | 100% | 0% | 0% |
| Inactive | 523 | 100% | 15.9% | 0% |

### Status transitions

| Before | After | n |
| --- | --- | ---: |
| (null) | In Review | 11 |
| (null) | Active | 3 |

### Remaining gaps / source quirks

- 31 Final + 2 Active rows: no IssueDate in DATA → `PERMIT_DATE` stays missing.
- 2 Final rows: no FinalDate/FinalizeDate → `FINAL_DATE` stays missing.
- 1 residual `FILE_DATE > PERMIT_DATE` and 2 `PERMIT_DATE > FINAL_DATE` inversions come from agency timestamps (not introduced by repair).

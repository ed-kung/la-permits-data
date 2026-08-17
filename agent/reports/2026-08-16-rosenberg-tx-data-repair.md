# Rosenberg (TX) data repair

**Summary:** Rosenberg was the first TX jurisdiction in `permits_tx_sample.parquet` without a repair script (after Mesquite). All 1,999 rows are CivicPlus / EnerGov case payloads (`entity_core` 1,947; `entity_rich` 52). STATUS_NORMALIZED already matches `entity.CaseStatus` 1:1, and FILE_DATE already matches `ApplyDate` on every row. PERMIT_DATE matches `IssueDate` whenever present (109 rows lack both). The only repairs were clearing 32 spurious FINAL_DATE values on non-Final rows (Void / Issued / Expired that still carried `FinalDate`). Final FINAL_DATE coverage is 85.7%; Active/Final PERMIT_DATE coverage is 90.5% / 92.3%.

## Scope

- Input: `MY_DATA_PATH/processed_data/permits_tx_sample.parquet`
- Jurisdiction: Rosenberg, TX (first pair lacking `agent/scripts/{state}/data_repair_{state}_{city}.py`)
- Script: `agent/scripts/tx/data_repair_tx_rosenberg.py`
- Artifact: `AGENT_DATA_PATH/repaired/permits_tx_rosenberg_repaired.parquet`

## DATA schema

EnerGov-style nested object with `entity`, `details`, `contacts`, and `processing_status`. Variants differ only by optional review extras:

| INFERRED_SCHEMA | n |
| --- | ---: |
| entity_core | 1,947 |
| entity_rich | 52 |

Canonical source fields:

| Target field | Primary source | Fallback |
| --- | --- | --- |
| STATUS_NORMALIZED | `entity.CaseStatus` | — |
| FILE_DATE | `entity.ApplyDate` | — |
| PERMIT_DATE | `entity.IssueDate` | — |
| FINAL_DATE | `entity.FinalDate` | `details.FinalizeDate` |

`entity.CaseStatus` and `details.PermitStatus` agree on all 1,999 rows. `processing_status` is null on every sample row (no inspection-date fallback).

## Field assessment

### STATUS_NORMALIZED

No missing values. Mapping from `CaseStatus` is already correct on every row:

| CaseStatus | STATUS_NORMALIZED | n |
| --- | --- | ---: |
| Expired | Inactive | 1,618 |
| Complete | Final | 187 |
| Issued | Active | 87 |
| Void | Inactive | 39 |
| In Review | In Review | 24 |
| Closed | Final | 9 |
| Approved | Active | 8 |
| On Hold | In Review | 8 |
| Requires Re-Submittal | In Review | 6 |
| Plan Approval Expired | Inactive | 5 |
| Denied | Inactive | 4 |
| Waiting for resubmittal | In Review | 2 |
| Submitted | In Review | 1 |
| Stop Work Order | In Review | 1 |

0 FILLED / 0 FIXED.

### FILE_DATE

Fully populated (0 missing). Every row matches `entity.ApplyDate` at calendar-day resolution (0 FILLED, 0 FIXED).

### PERMIT_DATE

109 missing before and after repair. When `IssueDate` is present, PERMIT_DATE already matches at calendar-day resolution (1,890 matches; 0 mismatches). Remaining Active/Final gaps all have null `IssueDate` in DATA:

| CaseStatus | STATUS_NORMALIZED | n missing PERMIT_DATE |
| --- | --- | ---: |
| Approved | Active | 8 |
| Complete | Final | 9 |
| Closed | Final | 6 |
| Issued | Active | 1 |

Approved rows are pre-issuance (plans approved, not yet issued). Complete/Closed shells without `IssueDate` are mostly CO / reconnect / legacy cases. No fill source available.

### FINAL_DATE

1,799 missing before repair. Final rows that carry `FinalDate`/`FinalizeDate` already have the correct FINAL_DATE (168 matches). Twenty-eight Complete rows have neither date → unfillable legacy shells.

Thirty-two non-Final rows incorrectly carried FINAL_DATE copied from `FinalDate` while `CaseStatus` remained Void (27), Issued (4), or Expired (1). Repair cleared these (FIXED). After repair, non-Final FINAL_DATE is empty; Final coverage is 168/196 (85.7%).

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 0 | 0 | 0 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 0 | 0 | 109 → 109 |
| FINAL_DATE | 0 | 32 | 1,799 → 1,831 |

STATUS_NORMALIZED after repair: Inactive 1,666; Final 196; Active 95; In Review 42 (unchanged).

After repair, by status:

- **FILE_DATE:** 100% for all statuses
- **PERMIT_DATE:** Active 86/95 (90.5%); Final 181/196 (92.3%)
- **FINAL_DATE:** Final 168/196 (85.7%); non-Final remain empty

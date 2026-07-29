# Gilroy (CA) data repair

**Summary:** Gilroy was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. Assessed 2,000 Tyler EnerGov records against `DATA`. Main defects: 154 unmapped `Legacy - Open` statuses (left null); 1 Issued/Active row missing `PERMIT_DATE` despite `IssueDate` in DATA; and 11 spurious `FINAL_DATE` stamps on Inactive/In Review rows from case-closure `FinalDate`. Repair fills all 154 statuses and the one permit date, and clears those 11 finals. `FILE_DATE` already matched `ApplyDate` everywhere. Residual gap: 32 Complete/Final rows with no `IssueDate` (many share a bulk 2023-06-13 `FinalDate`). Script: `agent/scripts/ca/data_repair_ca_gilroy.py`.

## Jurisdiction selection

First `(JURISDICTION, STATE)` in sample order without `agent/scripts/{state}/data_repair_{state}_{city}.py` was **Gilroy, CA**.

## DATA schema

All rows share Tyler EnerGov top-level keys. Canonical dates/status live under `entity` with `details` fallbacks (`CaseStatus` / `PermitStatus`, `ApplyDate`, `IssueDate`, `FinalDate` / `FinalizeDate`). `CaseStatus` and `PermitStatus` agree on every sample row. Content variants in `INFERRED_SCHEMA`:

| Schema | n | Keys |
| --- | ---: | --- |
| `entity_fees` | 1,963 | entity, details, contacts, fees, processing_status |
| `entity_fees_reviews` | 37 | above + reviews / holds / attachments / more_info |

`ExpireDate` is a validity window, not completion. `processing_status` lists inspections but were not needed for date repair in this sample.

## Field assessment

### STATUS_NORMALIZED

Before repair: Final 1,295 / Inactive 420 / missing 154 / Active 70 / In Review 61.

| CaseStatus | Before STATUS_NORMALIZED | n |
| --- | --- | ---: |
| Complete | Final | 1,295 |
| Expired / Void / Denied / Plan Approval Expired | Inactive | 420 |
| Issued | Active | 70 |
| Fees Due / Fees Paid / In Review / Submitted / Submitted - Online | In Review | 61 |
| Legacy - Open | missing | 154 |

- All non-null statuses already matched CaseStatus.
- **154** `Legacy - Open` rows had null STATUS_NORMALIZED. Of these: **116** issued (IssueDate + Issued) → Active; **1** issued with FinalDate → Final; **37** unissued → In Review.

### FILE_DATE

2,000 / 2,000 populated. Every FILE_DATE matches `entity.ApplyDate` at UTC calendar-day resolution (0 mismatches). **No FILE_DATE repairs.**

### PERMIT_DATE

Where both exist, PERMIT_DATE matches `IssueDate` (0 mismatches). Gaps:

- **1** Active/`Issued` row missing PERMIT_DATE while `entity.IssueDate` (`2025-05-09T00:00:00`, no `Z`) and `details.IssueDate` are present → fillable.
- **32** Final/`Complete` rows with null IssueDate (28 share FinalDate `2023-06-13T23:19:45.13Z`, likely a bulk close-out) → not fillable without inventing an issuance date.

### FINAL_DATE

All 1,295 Final rows already had FINAL_DATE matching FinalDate/FinalizeDate. Incorrect values:

- **10** Inactive (Void / Expired / Plan Approval Expired) and **1** In Review (Fees Due) carried FINAL_DATE from case-closure `FinalDate` → cleared.
- The one Legacy-Open→Final row already had the correct FINAL_DATE and kept it.

## Repair performance

Script: `agent/scripts/ca/data_repair_ca_gilroy.py`  
Artifact: `$AGENT_DATA_PATH/repaired/permits_ca_gilroy_repaired.parquet`

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 154 | 0 | 154 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 1 | 0 | 310 → 309 |
| FINAL_DATE | 0 | 11 | 693 → 704 |

Status transitions (all FILLED from null):

- nan → Active: 116
- nan → In Review: 37
- nan → Final: 1

After-repair coverage:

| Status | PERMIT_DATE | FINAL_DATE |
| --- | --- | --- |
| Active (186) | 186 / 186 (100%) | 0 / 186 |
| Final (1,296) | 1,264 / 1,296 (97.5%) | 1,296 / 1,296 (100%) |
| In Review (98) | 0 / 98 | 0 / 98 |
| Inactive (420) | 241 / 420 | 0 / 420 |

FILE_DATE: 2,000 / 2,000 (100%). Chronology inversions after repair: FILE > PERMIT = 0; PERMIT > FINAL = 0.

## Not repaired

- **32** Final rows still lack PERMIT_DATE (no IssueDate in DATA; FinalDate is not used as an issuance proxy).
- `ExpireDate` never copied into FINAL_DATE.
- Spurious FinalDate on terminal Inactive / pre-issue In Review rows is cleared rather than treated as completion.

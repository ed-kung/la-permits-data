# San Jacinto (CA) data repair

**Summary:** San Jacinto was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. Assessed 2,000 Tyler EnerGov records against `DATA`. Main defects: 41 Issued/Approved shells already carrying `FinalDate` / `FinalizeDate` left Active; 6 Fees Due shells with issuance + final stamps left In Review; 4 Fees Due / Fees Paid shells with `IssueDate` only left In Review; 3 unmapped statuses (`Visual Final`, `Awaiting 48 Hour…`); 9 Issued/`PermitStatus=Complete` rows with `FinalizeDate` only and null `FINAL_DATE`; 13 spurious `FINAL_DATE` values on Inactive or junk Fees Due shells. Repair fills 3 statuses, fixes 51 statuses, fills 9 finals, and clears 13 spurious finals. `FILE_DATE` already matched `ApplyDate` everywhere. Residual gaps: 7 Final rows with no `IssueDate` → `PERMIT_DATE` stays missing. Script: `agent/scripts/ca/data_repair_ca_san_jacinto.py`.

## Jurisdiction selection

First `(JURISDICTION, STATE)` in sample order without `agent/scripts/{state}/data_repair_{state}_{city}.py` was **San Jacinto, CA** (2,000 rows; after Seal Beach in appearance order among missing scripts).

## DATA schema

All rows share Tyler EnerGov top-level keys. Canonical dates/status live under `entity` with `details` fallbacks (`CaseStatus` / `PermitStatus`, `ApplyDate`, `IssueDate`, `FinalDate` / `FinalizeDate`). Content variants in `INFERRED_SCHEMA`:

| Schema | n | Keys |
| --- | ---: | --- |
| `entity_fees` | 1,879 | entity, details, contacts, fees, processing_status |
| `entity_fees_reviews` | 121 | above + reviews / holds / attachments / more_info |

`ExpireDate` is a validity window, not completion. `CompleteDate` / `ClosedDate` / `OpenedDate` are always null in this sample. Prefer `entity.FinalDate` over `details.FinalizeDate` when both exist (they match at day resolution for all 1,413 dual-stamp rows); 9 rows have `FinalizeDate` only.

## Field assessment

### STATUS_NORMALIZED

Before repair: Final 1,360 / Inactive 385 / Active 160 / In Review 92 / missing 3.

| CaseStatus | Before STATUS_NORMALIZED | n |
| --- | --- | ---: |
| Complete | Final | 1,337 |
| Finaled | Final | 23 |
| Issued | Active | 156 |
| Approved | Active | 4 |
| Expired / Void / Cancelled / Plan Approval Expired | Inactive | 385 |
| Fees Due / Fees Paid / In Review / Incomplete / On Hold / Submitted / Submitted - Online / Resubmittal Required | In Review | 92 |
| Visual Final | missing | 2 |
| Awaiting 48 Hour Engineering Inspection Notice | missing | 1 |

Issues:

- **28** `Issued` / Active rows already carry `FinalDate` → Final (FIXED).
- **9** `Issued` / Active rows with `PermitStatus=Complete` and `FinalizeDate` only (no `entity.FinalDate`) → Final (FIXED); `FINAL_DATE` FILLED from `FinalizeDate`.
- **4** `Approved` / Active encroachment shells with `FinalDate` (days after ApplyDate; 3 lack IssueDate) → Final (FIXED).
- **6** `Fees Due` / In Review with IssueDate + FinalDate (sensible chronology on older construction shells) → Final (FIXED).
- **3** `Fees Due` + **1** `Fees Paid` with IssueDate but no final stamp → Active (FIXED).
- **2** `Fees Due` solar shells with `FinalDate` ≈ `ApplyDate` (seconds apart), no IssueDate, `details.Issued=False` → stay In Review; treat FinalDate as junk and clear `FINAL_DATE` (FIXED). Credible final-stamp filter requires IssueDate, an explicit Complete/Finaled/Visual Final label, or FinalDate on a later calendar day than ApplyDate.
- **2** `Visual Final` missing STATUS_NORMALIZED (both already have IssueDate + FinalDate) → Final (FILLED).
- **1** `Awaiting 48 Hour Engineering Inspection Notice` missing STATUS_NORMALIZED → In Review (FILLED).
- Inactive terminal labels (Expired / Void / Cancelled / Plan Approval Expired) are sticky even when FinalDate is present as a case-closure stamp.
- `CaseStatus=Complete` / `Finaled` stays Final even when FinalDate is absent (none of these lack FinalDate in the sample).

### FILE_DATE

2,000 / 2,000 populated. Every FILE_DATE matches `entity.ApplyDate` at UTC calendar-day resolution (0 mismatches). **No FILE_DATE repairs.**

### PERMIT_DATE

Where both exist, PERMIT_DATE matches `IssueDate` (0 mismatches; 1,787 dual-populated). Gaps:

- After repair, all Active rows have PERMIT_DATE (123 / 123), including the 4 promoted from Fees Due / Fees Paid.
- **7** Final rows with null IssueDate → not fillable (3 pre-existing Complete, 1 Finaled, 3 Approved→Final encroachment promotions). Final PERMIT coverage is 1,402 / 1,409 (99.5%).
- Three pre-existing FILE_DATE > PERMIT_DATE day inversions remain; not introduced by repair.

### FINAL_DATE

Where both exist, FINAL_DATE matches `entity.FinalDate` (0 mismatches among 1,413). Issues:

- **9** Issued→Final promotions with FinalizeDate only → FINAL_DATE FILLED.
- **11** Inactive rows (Expired / Void / Plan Approval Expired) carried FINAL_DATE from case-closure `FinalDate` → cleared (FIXED).
- **2** Fees Due junk FinalDate≈ApplyDate shells → FINAL_DATE cleared (FIXED); status remains In Review.
- Active / In Review rows that previously carried FINAL_DATE were either promoted to Final (and retained the stamp) or had the stamp cleared.
- After repair, Final FINAL_DATE coverage is 1,409 / 1,409 (100%).
- Pre-existing PERMIT_DATE > FINAL_DATE day inversions: 27 before → 26 after (one cleared with a spurious Inactive final); not introduced by repair.

## Repair performance

Script: `agent/scripts/ca/data_repair_ca_san_jacinto.py`  
Artifact: `$AGENT_DATA_PATH/repaired/permits_ca_san_jacinto_repaired.parquet`

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 3 | 51 | 3 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 0 | 0 | 213 → 213 |
| FINAL_DATE | 9 | 13 | 587 → 591 |

Status transitions:

- Active → Final: 41
- In Review → Final: 6
- In Review → Active: 4
- nan → Final: 2
- nan → In Review: 1

Post-repair coverage:

| Status | PERMIT_DATE | FINAL_DATE |
| --- | --- | --- |
| Active | 123 / 123 (100%) | 0 / 123 (0%) |
| Final | 1,402 / 1,409 (99.5%) | 1,409 / 1,409 (100%) |
| In Review | 0 / 83 (0%) | 0 / 83 (0%) |
| Inactive | 262 / 385 (68.1%) | 0 / 385 (0%) |

FILE_DATE: 2,000 / 2,000 (100%). Chronology inversions: FILE>PERMIT 3 (unchanged); PERMIT>FINAL 26 (was 27).

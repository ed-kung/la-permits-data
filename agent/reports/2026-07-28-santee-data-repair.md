# Santee (CA) data repair

**Summary:** Santee was the first sample jurisdiction lacking a repair script (2,000 rows). DATA is Tyler EnerGov (`entity` / `details`). Upstream status mapping was mostly correct; repair FIXED 2 stale `Issued` shells with FinalDate after IssueDate to Final, and FIXED 2 review-pipeline shells that already carried IssueDate (`In Review` / `Fees Due`) to Active. FILE_DATE was already complete and matched ApplyDate. PERMIT_DATE filled 1 missing issuance on a promoted Active row and cleared 3 EnerGov `1900-01-01` sentinel values. FINAL_DATE cleared 26 junk stamps on non-Final rows (Expired 1900 sentinels, Void closure stamps, one inverted Issued stamp). After repair: FILE_DATE 100%, Active PERMIT_DATE 100%, Final FINAL_DATE 99.4% (3 Complete shells lack FinalDate); 4 Complete shells still lack IssueDate so PERMIT_DATE stays missing.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_ca_sample.parquet` and walked `(JURISDICTION, STATE)` in first-appearance order. The first pair without `agent/scripts/{state}/data_repair_{state}_{city}.py` was **Santee, CA**.

## DATA schemas (`INFERRED_SCHEMA`)

Tyler EnerGov portal payload. Core keys: `entity`, `details`, `contacts`, `fees`, `processing_status`. Optional reviews bundle (`reviews` / `holds` / `attachments` / `more_info`) distinguishes variants. `processing_status` is null for all sample rows.

| Schema | n |
| --- | ---: |
| `entity_fees` | 1,903 |
| `entity_fees_reviews` | 97 |

Canonical fields: `entity.CaseStatus` / `details.PermitStatus`; `ApplyDate` → FILE_DATE; `IssueDate` → PERMIT_DATE; `FinalDate` / `details.FinalizeDate` → FINAL_DATE. `ExpireDate` is a validity window, not a completion date.

## Field assessment

### STATUS_NORMALIZED

Before: Inactive 1,201 / Final 537 / Active 175 / In Review 87 / missing 0.

Upstream CaseStatus → STATUS_NORMALIZED was correct for all labels present (`Expired`, `Complete`, `Issued`, `Void`, `Fees Paid`, `In Review`, `Fees Due`, `Waiting for Files`, `Submitted - Online`, `On Hold`, `Cancelled`). Issues were date-evidence overrides, not unmapped labels:

| DATA evidence | Upstream | Repair |
| --- | --- | --- |
| Issued + FinalDate/FinalizeDate strictly after IssueDate (2: N2022-191, N2021-137) | Active | FIXED → Final |
| In Review with details.IssueDate / PermitStatus=Issued (ROW-2024-0150); Fees Due with IssueDate (ROW-2025-0097) | In Review | FIXED → Active |

One Issued shell (N2022-186) has FinalDate *before* IssueDate — inverted stamp is not treated as Final; status stays Active.

After: Inactive 1,201 / Final 539 / Active 175 / In Review 85 / missing 0.

### FILE_DATE

Fully populated. Every value equals `entity.ApplyDate` at calendar-day resolution. No FILLED/FIXED. Coverage remains 2,000 / 2,000.

### PERMIT_DATE

Wherever a credible `IssueDate` exists (year in 1990–2035), `PERMIT_DATE` already matched at calendar-day resolution except:

| Issue | n | Repair |
| --- | ---: | --- |
| In Review→Active shell missing PERMIT_DATE despite details.IssueDate | 1 | FILLED |
| EnerGov `1900-01-01` sentinel IssueDate copied into PERMIT_DATE | 3 | FIXED → cleared |

Active coverage after repair is 175 / 175 (100%). Final coverage is 535 / 539 (99.3%); the 4 gaps are `Complete` zzEncroachment shells with null IssueDate (3 also lack FinalDate; 1 has FinalDate only).

Inactive retains PERMIT_DATE when a real IssueDate exists (1,172 / 1,201). In Review has 0 / 85 after clearing review-pipeline rows that were upgraded or had no issuance.

### FINAL_DATE

`FinalDate` / `FinalizeDate` are identical at day resolution whenever both are present (546 rows). Before repair, 534 / 537 Complete rows already had matching FINAL_DATE; after promoting 2 Active→Final, both already carried FINAL_DATE (no FILLED needed).

Junk FINAL_DATE on non-Final rows was cleared (FIXED 26):

- 16 Expired with EnerGov `1900-01-01` FinalDate sentinels
- 9 Void with same-day closure FinalDate (not permit finaling)
- 1 Issued with inverted FinalDate before IssueDate (N2022-186)

After repair: Final 536 / 539 (99.4%); absent on all non-Final. The 3 Final gaps are Complete shells with null FinalDate and null IssueDate in DATA.

## Repair performance

Script: `agent/scripts/ca/data_repair_ca_santee.py` (`data_repair`).

Artifact: `AGENT_DATA_PATH/repaired/permits_ca_santee_repaired.parquet`

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 0 | 4 | 0 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 1 | 3 | 116 → 118 |
| FINAL_DATE | 0 | 26 | 1,438 → 1,464 |

After repair:

- FILE_DATE: 2,000 / 2,000 (100%)
- PERMIT_DATE: Active 100%; Final 99.3% (4 Complete without IssueDate)
- FINAL_DATE: Final 99.4% (3 Complete without FinalDate); absent on non-Final

Pre-existing chronology quirks remain in a handful of EnerGov timestamps (11 FILE > PERMIT; 3 PERMIT > FINAL) and were not rewritten beyond the canonical ApplyDate / IssueDate / FinalDate fields.

# Grand Prairie (TX) data repair

**Summary:** Grand Prairie was the first TX jurisdiction in `permits_tx_sample.parquet` (appearance order) without a repair script. All 2,000 rows use a CivicPlus/EnerGov payload (`entity_core` 1,935 / `entity_rich` 65). STATUS_NORMALIZED was stale on 14 rows vs `CaseStatus`; FILE_DATE was already complete and correct; PERMIT_DATE gained 3 fills on Issued rows; FINAL_DATE gained 24 fills (6 from FinalDate, 18 from Passed inspections), 2 value corrections, and 49 spurious non-Final dates cleared.

## Scope

- Input: `MY_DATA_PATH/processed_data/permits_tx_sample.parquet`
- Jurisdiction: Grand Prairie, TX (first pair lacking `agent/scripts/{state}/data_repair_{state}_{city}.py`)
- Script: `agent/scripts/tx/data_repair_tx_grand_prairie.py`
- Artifact: `AGENT_DATA_PATH/repaired/permits_tx_grand_prairie_repaired.parquet`

## DATA schema

Two top-level key-set variants; both expose the same `entity` / `details` fields used for repair:

| INFERRED_SCHEMA | n | Top-level keys |
| --- | --- | --- |
| entity_core | 1,935 | contacts, details, entity, fees, processing_status |
| entity_rich | 65 | entity_core + attachments, holds, more_info, reviews |

Canonical source fields:

| Target field | Primary source | Fallback |
| --- | --- | --- |
| STATUS_NORMALIZED | entity.CaseStatus | — |
| FILE_DATE | entity.ApplyDate | — |
| PERMIT_DATE | entity.IssueDate | — |
| FINAL_DATE | entity.FinalDate | details.FinalizeDate; else latest Passed `processing_status` scheduled/requested date |

`CaseStatus` and `details.PermitStatus` agree on all 2,000 rows. `FinalDate` and `FinalizeDate` never disagree when both are present.

## Field assessment

### STATUS_NORMALIZED

No missing values. Prior mapping from `STATUS_ORIGINAL` was mostly right, but 14 rows lagged behind the live portal `CaseStatus`:

| CaseStatus | Prior STATUS_NORMALIZED | Expected | n |
| --- | --- | --- | --- |
| Issued | In Review | Active | 3 |
| Complete | Active / Inactive | Final | 4 |
| Closed | Active / Inactive | Final | 3 |
| Expired | Active / In Review | Inactive | 4 |

Root cause: `STATUS_ORIGINAL` captured an earlier state (`in review`, `issued`, `expired`, `on hold`) while DATA already showed the updated `CaseStatus`. After repair, STATUS_NORMALIZED matches CaseStatus for every row (Active 85, Final 715, In Review 102, Inactive 1,098).

### FILE_DATE

Fully populated (0 missing). All 2,000 values match `ApplyDate` at day resolution. No fills or fixes.

### PERMIT_DATE

- When present (1,248), always matched `IssueDate`.
- 3 Issued rows were missing PERMIT_DATE because status was wrongly In Review; filled from `IssueDate` after status fix.
- Large structural gap remains: Complete / Closed / Certificate Issued / Approved rarely store `IssueDate` in DATA (Final PERMIT_DATE coverage only 96/715 = 13.4%; Active 75/85 = 88.2%, with the 10 gaps all `Approved` and `Issued=false`).

### FINAL_DATE

- When present and status Final, almost always matched FinalDate; 2 Complete rows had wrong FINAL_DATE (one equal to ApplyDate, one unrelated) → FIXED to FinalDate.
- 6 Final rows gained FINAL_DATE from FinalDate after status was corrected to Final.
- 18 Final rows with blank FinalDate/FinalizeDate recovered a date from a Passed inspection in `processing_status`.
- 49 non-Final rows carried spurious FINAL_DATE (Issued 26, Approved 10, Plan Approval Expired 6, Withdrawn 3, On Hold 2, Denied 1, Void 1) → cleared.
- 575/715 Final rows still lack FINAL_DATE: portal simply does not stamp FinalDate/FinalizeDate on most Complete/Closed (and all Certificate Issued) records, and most have empty inspection lists.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | --- | --- | --- |
| STATUS_NORMALIZED | 0 | 14 | 0 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 3 | 0 | 752 → 749 |
| FINAL_DATE | 24 | 51 (2 corrected + 49 cleared) | 1,835 → 1,860 |

After repair, by status:

- **PERMIT_DATE:** Active 75/85 (88.2%), Final 96/715 (13.4%)
- **FINAL_DATE:** Final 140/715 (19.6%); non-Final all clear (0%)

## Not repairable

- 10 Active (`Approved`) and 619 Final rows with null `IssueDate` → PERMIT_DATE stays missing.
- 575 Final rows with neither FinalDate/FinalizeDate nor a Passed inspection date → FINAL_DATE stays missing.

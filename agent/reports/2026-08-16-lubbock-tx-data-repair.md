# Lubbock (TX) data repair

**Summary:** Lubbock is the first TX sample jurisdiction without an existing repair script (2,001 rows). DATA is a CivicPlus/EnerGov payload (`entity_core` / `entity_rich`). STATUS_NORMALIZED had 7 missing uncommon statuses and 19 stale mappings vs `entity.CaseStatus`. FILE_DATE was already complete and correct. PERMIT_DATE gained 3 fills from `IssueDate`. FINAL_DATE gained 260 fills (mostly Passed inspection dates on Completed rows lacking `FinalDate`) and cleared 15 spurious values on non-Final rows. After repair, Final FINAL_DATE coverage is 99.4%; Active/Final PERMIT_DATE coverage is 95.5% / 96.6%.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_tx_sample.parquet` and walked unique `(JURISDICTION, STATE)` pairs in appearance order. Existing TX scripts covered through Grand Prairie; **Lubbock** was the first missing pair → `agent/scripts/tx/data_repair_tx_lubbock.py`.

## DATA schema

All 2,001 rows parse. Two top-level key-set variants (same repair fields):

| Schema | n | Top-level keys |
| --- | ---: | --- |
| `entity_core` | 1,895 | contacts, details, entity, fees, processing_status |
| `entity_rich` | 106 | core + attachments, holds, more_info, reviews |

Canonical sources:

- `entity.CaseStatus` → STATUS_NORMALIZED
- `entity.ApplyDate` → FILE_DATE
- `entity.IssueDate` → PERMIT_DATE
- `entity.FinalDate` / `details.FinalizeDate` / latest Passed `processing_status` date → FINAL_DATE (Final only)

Inspections expose `scheduled_date` / `requested_date` only (no `completed_date` in this sample).

## Field assessment

### STATUS_NORMALIZED

Before: Final 1,236 / Inactive 506 / Active 164 / In Review 88 / missing 7.

Issues:

1. **Missing (7):** uncommon CaseStatus values not in the original normalizer — Pending Applicant Action (3), Under Review - Online (2), Approved - WSSC/Small Cell (1), LPL/ROW Denied (1).
2. **Stale vs CaseStatus (19):** STATUS_ORIGINAL lagged portal CaseStatus — e.g. Completed still coded as issued/reviewed (15), Issued as reviewed (2), Expired as issued (1), Canceled as reviewed (1).

Repair map (CaseStatus → normalized): Completed→Final; Issued/Active/Approved - WSSC/Small Cell→Active; Reviewed/Under Review/Under Review - Online/Pending Applicant Action→In Review; Expired/Canceled/Void/LPL/ROW Denied→Inactive.

### FILE_DATE

Already 2,001/2,001 populated; all match `entity.ApplyDate` at day resolution. No fills or fixes. (One entity vs details ApplyDate pair differs only by timezone offset; FILE_DATE correctly follows entity.)

### PERMIT_DATE

When present, always matches `IssueDate`. Three rows had IssueDate but missing PERMIT_DATE (status wrongly In Review). Remaining Active/Final gaps have null IssueDate in DATA (not fillable).

### FINAL_DATE

- Existing Final FINAL_DATE values match FinalDate/FinalizeDate when those exist (no wrong-date fixes among populated Final rows).
- 253 originally Final rows lacked FINAL_DATE; FinalDate also null for most of those, but Passed inspections recover most.
- After status repair, 15 newly Final (Completed) rows get FINAL_DATE from FinalDate.
- 15 non-Final rows (mostly Expired) carried spurious FINAL_DATE → cleared.

## Repair performance

Script: `agent/scripts/tx/data_repair_tx_lubbock.py`  
Artifact: `AGENT_DATA_PATH/repaired/permits_tx_lubbock_repaired.parquet`

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 7 | 19 | 7 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 3 | 0 | 210 → 207 |
| FINAL_DATE | 260 | 15 | 1,003 → 758 |

After repair by STATUS_NORMALIZED:

| Status | n | PERMIT_DATE | FINAL_DATE |
| --- | ---: | --- | --- |
| Active | 154 | 147 / 154 (95.5%) | 0 / 154 |
| Final | 1,251 | 1,208 / 1,251 (96.6%) | 1,243 / 1,251 (99.4%) |
| In Review | 87 | 2 / 87 (2.3%) | 0 / 87 |
| Inactive | 509 | 437 / 509 (85.9%) | 0 / 509 |

## Remaining gaps

- **PERMIT_DATE:** 7 Active and 43 Final rows still lack IssueDate in DATA.
- **FINAL_DATE:** 8 Final rows have neither FinalDate/FinalizeDate nor a Passed inspection date.

# Missouri City (TX) data repair

**Summary:** Missouri City was the first TX jurisdiction in `permits_tx_sample.parquet` without a repair script (2,000 rows). DATA is a CivicPlus/EnerGov payload (`entity_core` / `entity_rich`). STATUS_NORMALIZED had 26 nulls for uncommon `CaseStatus` values (now filled as In Review). FILE_DATE was already complete and matched `ApplyDate`. PERMIT_DATE needed no changes (already matched `IssueDate` where present). FINAL_DATE cleared 496 spurious values on non-Final rows that carried `FinalDate`/`FinalizeDate` while `CaseStatus` was not Complete. After repair, Active PERMIT_DATE coverage is 100%; Final FINAL_DATE coverage is 98.2%.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_tx_sample.parquet` and walked unique `(JURISDICTION, STATE)` pairs in appearance order. Existing TX scripts covered through Brownsville; **Missouri City** was the first missing pair → `agent/scripts/tx/data_repair_tx_missouri_city.py`.

## DATA schema

All 2,000 rows parse. Two top-level key-set variants (same repair fields):

| Schema | n | Top-level keys |
| --- | ---: | --- |
| `entity_core` | 1,943 | contacts, details, entity, fees, processing_status |
| `entity_rich` | 57 | core + attachments, holds, more_info, reviews |

Canonical sources:

- `entity.CaseStatus` → STATUS_NORMALIZED
- `entity.ApplyDate` → FILE_DATE
- `entity.IssueDate` (years outside 1900–2035 rejected) → PERMIT_DATE
- `entity.FinalDate` / `details.FinalizeDate` → FINAL_DATE (Final only)

`details.FinalizeDate` matches `entity.FinalDate` at UTC calendar-day resolution on 601/603 rows where both are set; the two day-boundary differences are timezone offsets (local vs `Z`). Prefer `entity.FinalDate`. `processing_status` is null on every sample row (no inspection fallback).

## Field assessment

### STATUS_NORMALIZED

Before: Active 1,669 / Inactive 126 / Final 109 / In Review 70 / missing 26.

`entity.CaseStatus` categories: Issued (1,669), Complete (109), Void (61), Denied (51), In Review (48), Application incomplete - Attention required (16), Withdrawn (13), Submitted - Online (8), Review Disapproved - Response required (6), Completeness Check (5), Fees Invoiced - Payment Required (4), Submitted (4), On Hold (3), Fees Paid (2), Expired (1).

Existing non-null mappings matched CaseStatus 1:1. The 26 nulls were unmapped uncommon statuses (STATUS_ORIGINAL already held the raw CaseStatus text):

| CaseStatus | n | Repair |
| --- | ---: | --- |
| Application incomplete - Attention required | 16 | In Review |
| Review Disapproved - Response required | 6 | In Review |
| Fees Invoiced - Payment Required | 4 | In Review |

After repair: Active 1,669 / Inactive 126 / Final 109 / In Review 96 / missing 0.

### FILE_DATE

Already 2,000 / 2,000 populated; all match `entity.ApplyDate` at calendar-day resolution. No FILLED/FIXED changes. (`details.ApplyDate` differs by one calendar day on 26 rows due to UTC vs local timestamps; `entity.ApplyDate` is the authoritative source already used.)

### PERMIT_DATE

When present (1,780), always matched `entity.IssueDate`. No fills or fixes needed.

Remaining Active/Final gaps have null `IssueDate` in DATA:
- 0 Active (100% coverage)
- 8 Final Complete shells (mostly Certificate of Occupancy / similar) with `FinalDate` but no `IssueDate`

After repair by status: Active 1,669/1,669 (100%); Final 101/109 (92.7%); In Review 3/96 (3.1%); Inactive 7/126 (5.6%).

### FINAL_DATE

All 107 already-Final rows with a date matched `entity.FinalDate`. Two Complete rows have neither `FinalDate` nor `FinalizeDate` → remain missing.

496 non-Final rows carried spurious FINAL_DATE → cleared (FIXED):

| Prior STATUS / CaseStatus | n |
| --- | ---: |
| Active / Issued | 393 |
| Inactive / Void | 48 |
| Inactive / Denied | 35 |
| Inactive / Withdrawn | 10 |
| In Review / In Review | 8 |
| Inactive / Expired | 1 |
| In Review / On Hold | 1 |

Issued rows with `FinalDate` are intentionally left Active without FINAL_DATE because `CaseStatus` remains Issued (same convention as Edinburg).

After repair: Final 107/109 (98.2%); other statuses 0%.

## Repair performance

Script: `agent/scripts/tx/data_repair_tx_missouri_city.py`  
Artifact: `AGENT_DATA_PATH/repaired/permits_tx_missouri_city_repaired.parquet`

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 26 | 0 | 26 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 0 | 0 | 220 → 220 |
| FINAL_DATE | 0 | 496 | 1,397 → 1,893 |

(Missing FINAL_DATE rises because clearing spurious non-Final dates outweighs any fills; no Final rows needed fills.)

After repair by STATUS_NORMALIZED:

| Status | n | FILE_DATE | PERMIT_DATE | FINAL_DATE |
| --- | ---: | ---: | ---: | ---: |
| Active | 1,669 | 100% | 1,669 / 1,669 (100%) | 0 / 1,669 |
| Final | 109 | 100% | 101 / 109 (92.7%) | 107 / 109 (98.2%) |
| In Review | 96 | 100% | 3 / 96 (3.1%) | 0 / 96 |
| Inactive | 126 | 100% | 7 / 126 (5.6%) | 0 / 126 |

## Remaining gaps

- **PERMIT_DATE:** 8 Complete Final rows have null `IssueDate` in DATA (not fillable).
- **FINAL_DATE:** 2 Complete Final rows (temporary foster/day-care facility permits) have null `FinalDate`/`FinalizeDate` (not fillable).

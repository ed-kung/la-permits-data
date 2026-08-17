# McKinney (TX) data repair

**Summary:** McKinney was the first TX jurisdiction in `permits_tx_sample.parquet` without a repair script (2,004 rows). DATA is a CivicPlus/EnerGov payload (`entity_core` / `entity_rich`). STATUS_NORMALIZED had 29 missing uncommon statuses and 14 stale mappings vs `entity.CaseStatus`. FILE_DATE was already complete and correct. PERMIT_DATE gained 7 fills from `IssueDate`. FINAL_DATE gained 10 fills (9 from `FinalDate` on stale Complete rows, 1 from a final Approved inspection on Temporary Certificate) and cleared 219 spurious values on non-Final rows (mostly Issued stamped with ExpireDate). After repair, Final FINAL_DATE coverage is 88.1%; Active/Final PERMIT_DATE coverage is 76.7% / 87.6%.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_tx_sample.parquet` and walked unique `(JURISDICTION, STATE)` pairs in appearance order. Existing TX scripts covered through Denton; **McKinney** was the first missing pair → `agent/scripts/tx/data_repair_tx_mckinney.py`.

## DATA schema

All 2,004 rows parse. Two top-level key-set variants (same repair fields):

| Schema | n | Top-level keys |
| --- | ---: | --- |
| `entity_core` | 1,913 | contacts, details, entity, fees, processing_status |
| `entity_rich` | 91 | core + attachments, holds, more_info, reviews |

Canonical sources:

- `entity.CaseStatus` → STATUS_NORMALIZED
- `entity.ApplyDate` → FILE_DATE
- `entity.IssueDate` → PERMIT_DATE
- `entity.FinalDate` / `details.FinalizeDate` / latest Passed or final-Approved `processing_status` date → FINAL_DATE (Final only)

`entity.CaseStatus` and `details.PermitStatus` agree on 2,002 / 2,004 rows. Inspections use Approved / Disapproved (not Passed); scheduled/requested dates only.

## Field assessment

### STATUS_NORMALIZED

Before: Final 1,079 / Active 445 / Inactive 414 / In Review 37 / missing 29.

Issues:

1. **Missing (29):** uncommon CaseStatus values not in the original normalizer — Revisions Necessary (24), Submitted - Internal (3), plus two lagged STATUS_ORIGINAL=`revisions necessary` rows whose portal CaseStatus is To Be Issued (1) / Void (1).
2. **Stale vs CaseStatus (14):** STATUS_ORIGINAL lagged portal CaseStatus — Complete still coded as issued/expired/payment pending (9), Issued as expired/payment pending (2), Expired as issued (2), Void as issued (1).

Repair map (CaseStatus → normalized): Complete / Temporary Certificate → Final; Issued / Approved → Active; In Review / Under Review / Payment Pending / Submitted* / To Be Issued / Revisions Necessary → In Review; Cancelled / Denied / Expired / Out of Business / Rejected / Void → Inactive.

### FILE_DATE

Already 2,004 / 2,004 populated; all match `entity.ApplyDate` at day resolution. No fills or fixes.

### PERMIT_DATE

When present, always matches `IssueDate` (entity and details IssueDate are identical whenever either is set). Seven rows had IssueDate but missing PERMIT_DATE (5 Issued Active garage-sale/irrigation, 2 status-stale rows with IssueDate). Remaining Active/Final gaps have null IssueDate in DATA (not fillable) — common on older `HTE-Permit-*` Complete rows and Approved (never issued) cases.

### FINAL_DATE

- Existing Final FINAL_DATE values match FinalDate/FinalizeDate when those exist (no wrong-date fixes among populated Final rows).
- 9 Complete rows with FinalDate were wrongly non-Final (stale status) and lacked FINAL_DATE → FILLED after status repair.
- 1 Temporary Certificate Final row lacked FinalDate but had a final Approved inspection date → FILLED.
- 219 non-Final rows carried spurious FINAL_DATE → cleared. Of these, 201 were Issued Active where FinalDate often equals ExpireDate (171 / 201) — expiration stamped into the finaling field, not a true final.

## Repair performance

Script: `agent/scripts/tx/data_repair_tx_mckinney.py`  
Artifact: `AGENT_DATA_PATH/repaired/permits_tx_mckinney_repaired.parquet`

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 29 | 14 | 29 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 7 | 0 | 408 → 401 |
| FINAL_DATE | 10 | 219 | 836 → 1,045 |

(Missing FINAL_DATE rises after repair because clearing 219 spurious non-Final dates outweighs the 10 fills.)

After repair by STATUS_NORMALIZED:

| Status | n | PERMIT_DATE | FINAL_DATE |
| --- | ---: | --- | --- |
| Active | 437 | 335 / 437 (76.7%) | 0 / 437 |
| Final | 1,088 | 953 / 1,088 (87.6%) | 959 / 1,088 (88.1%) |
| In Review | 63 | 0 / 63 (0.0%) | 0 / 63 |
| Inactive | 416 | 315 / 416 (75.7%) | 0 / 416 |

## Remaining gaps

- **PERMIT_DATE:** 102 Active and 135 Final rows still lack IssueDate in DATA (Approved never-issued cases; older Complete rows with null IssueDate).
- **FINAL_DATE:** 129 Final (Complete) rows have neither FinalDate/FinalizeDate nor a usable final inspection date — all older `HTE-Permit-*` records with null `processing_status`.

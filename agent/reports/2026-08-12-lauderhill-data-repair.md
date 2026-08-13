# Lauderhill (FL) data repair

Lauderhill was the first `(JURISDICTION, STATE)` pair in `permits_fl_sample.parquet` without an existing repair script. Its DATA JSON is a single `permit_bundle` schema (same family as Highlands County / Stuart legacy). FILE_DATE and PERMIT_DATE already matched Application Date / Issued Date; the main defects were Open+Issued mapped to In Review instead of Active, and Final (Closed) rows almost entirely missing FINAL_DATE because upstream only copied C.O. Issued.

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_fl_sample.parquet`
- Jurisdiction: Lauderhill, FL (2,000 sample rows)
- Script: `agent/scripts/fl/data_repair_fl_lauderhill.py`
- Artifact: `AGENT_DATA_PATH/lauderhill_permits_repaired.parquet`

## DATA schemas

| Schema | n | Contents |
| --- | ---: | --- |
| `permit_bundle` | 2,000 | `permit_info`, `inspection_info`, `plan_info`, `fee_info`, owner/applicant/contractor/property blocks |

## Field assessment

### STATUS_NORMALIZED

- Before: Final 1,467; In Review 453; Inactive 72; **null 8**.
- Portal `permit_info.Status`: Closed 1,467; Open 448; Expired 51; Void 21; Hold 5; blank 8.
- Upstream mapped all Open → In Review, including **264 Open rows with Issued Date** (should be Active).
- Hold → In Review; Expired/Void → Inactive; Closed → Final — already correct.
- 8 blank-Status rows have no Issued Date and inspections with empty RES codes → not fillable.

### FILE_DATE

- 1,998 / 2,000 match `Application Date` exactly; 2 rows have blank Application Date (1 Expired, 1 Closed) → stay missing.
- No fill or fix needed.

### PERMIT_DATE

- Whenever Issued Date is present (1,691 rows), PERMIT_DATE already matches it.
- 309 missing all lack Issued Date in DATA (90 Closed, 184 Open/In Review, 27 Inactive, 8 blank Status) → not fillable.
- After status repair, Active has 100% PERMIT_DATE; Final 93.9%.

### FINAL_DATE

- Upstream populated FINAL_DATE almost only from `C.O. Issued` (45 rows: 44 Final + 1 Open).
- Closed rows have rich `inspection_info`; RES=`P` means pass. Prefer C.O. Issued, else latest passed `*FINAL*` inspection, else latest passed inspection.
- One Open row had a spurious FINAL_DATE from C.O. Issued → cleared.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 0 | 264 | 8 → 8 |
| FILE_DATE | 0 | 0 | 2 → 2 |
| PERMIT_DATE | 0 | 0 | 309 → 309 |
| FINAL_DATE | 1,248 | 1 | 1,955 → 708 |

STATUS after repair: Final 1,467; Active 264; In Review 189; Inactive 72; null 8.

After repair:

- FILE_DATE: Active/In Review 100%; Final 99.9%; Inactive 98.6%.
- PERMIT_DATE: Active 100%; Final 93.9%; In Review 2.6% (5 Hold with Issued Date); Inactive 62.5%.
- FINAL_DATE: Final 88.1%; cleared on non-Final.
- FILE_DATE == Application Date whenever Application Date present (1,998 / 1,998).
- PERMIT_DATE == Issued Date whenever Issued Date present (1,691 / 1,691).
- FINAL_DATE == C.O. Issued for all 44 Final rows that have C.O. Issued.
- Ordering: FILE_DATE > PERMIT_DATE on 0 rows; PERMIT_DATE > FINAL_DATE on 1 row (source inspection before issue).

## Not repairable from DATA

- 8 blank `permit_info.Status` rows → STATUS stays null.
- 2 rows with blank Application Date → FILE_DATE stays missing.
- 90 Active/Final (all Closed) rows with no Issued Date → PERMIT_DATE stays missing.
- 175 Final rows with neither C.O. Issued nor a dated passed inspection → FINAL_DATE stays missing.

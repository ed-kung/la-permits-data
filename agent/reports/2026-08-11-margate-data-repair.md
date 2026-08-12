# Margate (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script (parquet encounter order after North Port) was Margate (1,999 records). DATA is the legacy city portal family (`fees_detail` 1,470 + `permit_status` 527 + `application` 2). STATUS_NORMALIZED: 12 FILLED + 15 FIXED (nulls 1,472→1,460; remaining nulls are empty fees shells). FILE_DATE already matched Application Date wherever present (0 changes). PERMIT_DATE: 480 FIXED from portal “Permit Date” to Issue Date, cutting PERMIT>FINAL inversions from 294 to 14. FINAL_DATE already matched approved inspection closeouts on Final rows that have them (0 changes; 98.3% Final coverage after status remaps).

## Scope

- Input: `MY_DATA_PATH/processed_data/permits_fl_sample.parquet`
- Jurisdiction: Margate, FL (first `(JURISDICTION, STATE)` lacking `agent/scripts/{state}/data_repair_{state}_{city}.py` in parquet encounter order)
- Script: `agent/scripts/fl/data_repair_fl_margate.py`
- Artifact: `AGENT_DATA_PATH/margate_repaired_sample.parquet`

## DATA schemas (`INFERRED_SCHEMA`)

| Schema | Count | Distinguishing feature |
| --- | ---: | --- |
| `fees_detail` | 1,470 | Legacy `detail` + `fees` + `fees_total` only (1,460 empty shells) |
| `permit_status` | 527 | Full `permit_status_detail` + `insp_status_detail` |
| `application` | 2 | mini_set with top-level `application_status` only |

## Field assessment

### STATUS_NORMALIZED

- Before: null 1,472; Final 483; Active 30; In Review 10; Inactive 4
- **`permit_status`:** `Status for Permit Number` already mapped correctly for all 527 rows (FINAL INSPECTION COMPLETE / CLOSED / C.O. ISSUED → Final; PERMIT PRINTED → Active; PLAN CHECK / TO BE ISSUED → In Review; PERMIT REVOKED → Inactive). However, Application Status NULL AND VOID / CANCELLED / PERMITS EXPIRED incorrectly left rows as Active / Final / In Review → FIXED to Inactive (15 rows). Exception: FINAL INSPECTION COMPLETE + PERMITS EXPIRED kept as Final (completion evidence wins over a later expired admin flag).
- **`fees_detail`:** 10 non-empty rows had null STATUS → FILLED from Application Status (4 IN PLAN CHECK→In Review, 3 NULL AND VOID→Inactive, 2 CLOSED→Final, 1 CANCELLED→Inactive). 1,460 shells have blank Application Status → remain null.
- **`application`:** 2 CLOSED mini_set rows → FILLED as Final (no date fields available).
- After: null 1,460; Final 482; Inactive 23; Active 21; In Review 13

### FILE_DATE

- Ideal: populated for all records.
- Source: Application Date (`permit_status_detail` / `detail`).
- Already matched on every row that has a source date. **0 FILLED / 0 FIXED.**
- Remaining gaps: 1,460 empty fees shells + 2 application mini_set rows. Among non-null STATUS_NORMALIZED: Active / In Review / Inactive 100%; Final 99.6% (the 2 application shells).

### PERMIT_DATE

- Ideal: populated for Active and Final.
- Upstream used portal “Permit Date” on all 527 `permit_status` rows; Issue Date equals Permit Date on only 42. Canonical source is Issue Date; fallback to Permit Date only for Active/Final when Issue is blank and not after FINAL. Clear PERMIT on unissued In Review (PLAN CHECK / TO BE ISSUED with blank Issue Date).
- **0 FILLED + 480 FIXED.**
- After: Active 21/21 (100%); Final 478/482 (99.2% — gaps are 2 application + 2 fees Final shells with no Issue/Permit Date); In Review 0/13. PERMIT>FINAL inversions **294 → 14** (remaining 14 are source Issue Date after approved final inspection — left as-is).

### FINAL_DATE

- Ideal: populated for Final.
- Before: 474/483 Final (98.1%) already matched latest APPROVED FINAL/FNL/CLOSEOUT (else latest non-NOC APPROVED) inspection date.
- Remapping CLOSED+PERMITS EXPIRED Final→Inactive cleared no FINAL values (those rows had none). Unsupported / non-Final FINALs were already absent.
- **0 FILLED + 0 FIXED.**
- Not repairable: 3 `permit_status` Final rows with empty or only DISAPPROVED/CANCELLED inspections; 2 fees Final + 2 application Final shells with no inspection history.
- After: Final 474/482 (98.3%); non-Final FINAL_DATE all null.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 12 | 15 | 1,472 → 1,460 |
| FILE_DATE | 0 | 0 | 1,462 → 1,462 |
| PERMIT_DATE | 0 | 480 | 1,472 → 1,481 |
| FINAL_DATE | 0 | 0 | 1,525 → 1,525 |

Ideal-field coverage after repair (among non-null STATUS_NORMALIZED):

- FILE_DATE: 100% of Active / In Review / Inactive; 99.6% of Final
- PERMIT_DATE: 100% of Active; 99.2% of Final; 0% of In Review
- FINAL_DATE: 98.3% of Final; 0% of non-Final

Post-repair checks: PERMIT>FINAL inversions 294 → 14 (source Issue-after-FINAL only); In Review no longer carries processing Permit Dates; Inactive remaps from CANCELLED / NULL AND VOID / PERMITS EXPIRED; remaining STATUS nulls are empty fees shells only.

## Artifacts

- `agent/scripts/fl/data_repair_fl_margate.py`
- `AGENT_DATA_PATH/margate_repaired_sample.parquet`

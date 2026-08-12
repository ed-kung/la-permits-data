# Boca Raton (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script (parquet encounter order after Tampa) was Boca Raton (2,000 records). DATA matches the Lake Mary portal family: `permit_status` (811) vs sparse `fees_detail` (1,189). STATUS_NORMALIZED was already correct on all `permit_status` rows; 23 `fees_detail` nulls were FILLED from Application Status (WITHDRAWN→Inactive, CLOSED MANUALLY - FINALED→Final). FILE_DATE was already complete whenever Application Date existed (0 changes). PERMIT_DATE was wrongly taken from portal “Permit Date” (often a post-finalization or 2011-05-03 migration stamp); 707 FIXED to Issue Date / cleared bad values, cutting PERMIT>FINAL inversions from 448 to 2. FINAL_DATE: 10 FIXED (inspection alignment / clear NOC-only), Final coverage 93.8% after repair.

## Scope

- Input: `MY_DATA_PATH/processed_data/permits_fl_sample.parquet`
- Jurisdiction: Boca Raton, FL (first `(JURISDICTION, STATE)` lacking `agent/scripts/{state}/data_repair_{state}_{city}.py` in parquet encounter order)
- Script: `agent/scripts/fl/data_repair_fl_boca_raton.py`
- Artifact: `AGENT_DATA_PATH/boca_raton_repaired_sample.parquet`

## DATA schemas (`INFERRED_SCHEMA`)

| Schema | Count | Distinguishing feature |
| --- | ---: | --- |
| `fees_detail` | 1,189 | `detail` + `fees` + `fees_total` only; 1,166 are empty shells |
| `permit_status` | 811 | adds `permit_status_detail` + `insp_status_detail` |

## Field assessment

### STATUS_NORMALIZED

- Before: null 1,189; Final 670; Active 88; Inactive 27; In Review 26
- `permit_status`: `Status for Permit Number` maps 1:1 to current STATUS_NORMALIZED (CLOSED / FINAL INSPECTION COMPLETE / C.O. ISSUED → Final; PERMIT PRINTED → Active; PLAN CHECK / TO BE ISSUED → In Review; PERMIT REVOKED → Inactive). No incorrect values among these 811.
- `fees_detail`: 23 non-empty Application Status values with null STATUS_NORMALIZED → FILLED (21 WITHDRAWN→Inactive, 2 CLOSED MANUALLY - FINALED→Final). Remaining 1,166 shells have no status text.
- Application Status on `permit_status` rows is often WITHDRAWN even when Status for Permit Number is CLOSED / PERMIT PRINTED; repair keeps Status for Permit Number as authoritative.
- After: null 1,166; Final 672; Active 88; Inactive 48; In Review 26

### FILE_DATE

- Ideal: populated for all records.
- Source: Application Date (`permit_status_detail` / `detail`).
- All 811 `permit_status` rows already matched Application Date.
- The 23 non-empty `fees_detail` rows already had FILE_DATE; 1,166 empty shells have no Application Date → not fillable.
- 0 FILLED / 0 FIXED. Among records with a non-null status after repair, FILE_DATE is 100%.

### PERMIT_DATE

- Ideal: populated for Active and Final.
- Upstream used portal “Permit Date”, which equals Issue Date on only 78/811 rows; 733 matched Permit Date alone. Permit Date frequently post-dates FINAL (448 PERMIT>FINAL inversions before repair), including a mass 2011-05-03 batch stamp on CLOSED rows.
- Canonical source: Issue Date; fallback to Permit Date only for Active/Final when Issue is blank, excluding the 2011-05-03 batch and any Permit Date after FINAL. Clear PERMIT on unissued In Review (no Issue Date).
- **0 FILLED + 707 FIXED** (Issue Date overwrites + In Review clears + bad Permit Date clears).
- After: Active 88/88 (100%); Final 654/672 (97.3%); In Review 0/26. Remaining Final gaps are mostly blank-Issue rows whose only Permit Date was the batch stamp or post-FINAL, plus 2 `fees_detail` Final rows with no issuance fields.
- Chronology: PERMIT>FINAL inversions 448 → 2 (legacy rows where Issue Date itself is after an approved final inspection).

### FINAL_DATE

- Ideal: populated for Final.
- Before: 635/670 Final (94.8%); usually latest APPROVED inspection, but some values were NOC-only or off-by-one from inspection result dates.
- Repair: latest APPROVED with FINAL / FNL / CLOSEOUT in the title; else latest non-NOC APPROVED; clear FINAL when no completion inspection supports it; clear FINAL on non-Final.
- **0 FILLED + 10 FIXED** (5 inspection realignments + 5 NOC-only / unsupported clears).
- Not repairable: 35+ CLOSED Final rows with empty or non-APPROVED completion inspections; 2 fees_detail Final rows with no inspection history.
- After: Final 630/672 (93.8%); non-Final FINAL_DATE all null.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 23 | 0 | 1,189 → 1,166 |
| FILE_DATE | 0 | 0 | 1,166 → 1,166 |
| PERMIT_DATE | 0 | 707 | 1,189 → 1,231 |
| FINAL_DATE | 0 | 10 | 1,365 → 1,370 |

Ideal-field coverage after repair (among non-null STATUS_NORMALIZED):

- FILE_DATE: 100% of Active / Final / In Review / Inactive
- PERMIT_DATE: 100% of Active; 97.3% of Final; 0% of In Review (intentional)
- FINAL_DATE: 93.8% of Final

Post-repair checks: PERMIT>FINAL inversions 448 → 2; all `permit_status` rows with Issue Date have PERMIT_DATE = Issue Date; In Review PERMIT_DATE cleared; STATUS_NORMALIZED nulls remaining are empty `fees_detail` shells only.

## Artifacts

- `agent/scripts/fl/data_repair_fl_boca_raton.py`
- `AGENT_DATA_PATH/boca_raton_repaired_sample.parquet`

# Orange County (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script (parquet encounter order after Miramar) was Orange County (1,999 records). DATA uses one top-level key set but four sub-schemas by PERMIT INFORMATION richness and PROCESSES AND REPORTS shape. STATUS_NORMALIZED gained **43 FILLED** In Review labels from previously unmapped portal statuses (64 shell stubs remain null). FILE_DATE and PERMIT_DATE already matched APPLY / ISSUE DATE wherever present (0 changes). FINAL_DATE was the main defect: list-shaped process rows had FINAL_DATE set to Final Issuance Review (often equal to PERMIT_DATE); repair **FIXED 253** to the Passed final inspection, **cleared 46** incorrect values (25 Final with no true final stamp + 21 non-Final), and **FILLED 1,097** from Certificate of Completion / final inspections, raising Final coverage from 18.6% (278/1,495) to 90.3% (1,350/1,495).

## Scope

- Input: `MY_DATA_PATH/processed_data/permits_fl_sample.parquet`
- Jurisdiction: Orange County, FL (first `(JURISDICTION, STATE)` lacking `agent/scripts/{state}/data_repair_{state}_{city}.py` in parquet encounter order)
- Script: `agent/scripts/fl/data_repair_fl_orange_county.py`
- Artifact: `AGENT_DATA_PATH/orange_county_repaired_sample.parquet`

## DATA schemas (`INFERRED_SCHEMA`)

| Schema | Count | Distinguishing feature |
| --- | ---: | --- |
| `permit_info_dict_pr` | 1,543 | Full PERMIT INFORMATION + dict PROCESSES AND REPORTS (Finalize Permit / Inspection History / Issuance) |
| `permit_info_list_pr` | 305 | Full PERMIT INFORMATION + flat list of PROCESS / STATUS / END DT rows |
| `permit_info_empty_pr` | 87 | Full PERMIT INFORMATION + empty processes dict |
| `permit_info_shell` | 64 | PERMIT INFORMATION contains only `PERMIT#` (no STATUS / dates) |

## Field assessment

### STATUS_NORMALIZED

- Before: Final 1,495; Active 244; null 107; Inactive 84; In Review 69
- Full schemas: `PERMIT INFORMATION.STATUS` maps Complete→Final, Issued→Active, Expired / Application Expired / Cancelled→Inactive, Review / New / Ready to Issue / Replaced / Stop Work→In Review. Already-normalized rows matched this map (0 FIXED).
- **43 nulls FILLED** from previously unmapped labels: Internet Incomplete (20), Pending W/Comments (10), Internet Pending (8), Final Plan Prep (3), Masterfile (1), Final Issuance Review (1) → In Review.
- **64 shell** rows have no STATUS in DATA → remain null.
- After: Final 1,495; Active 244; In Review 112; Inactive 84; null 64

### FILE_DATE

- Ideal: populated for all records.
- Source: `PERMIT INFORMATION['APPLY DATE']`.
- All 1,935 non-shell rows already had FILE_DATE matching APPLY DATE at calendar-day resolution.
- 64 shells have neither FILE_DATE nor APPLY DATE → not fillable.
- 0 FILLED / 0 FIXED. After repair: 100% FILE_DATE for every non-null STATUS_NORMALIZED class.

### PERMIT_DATE

- Ideal: populated for Active and Final.
- Source: `PERMIT INFORMATION['ISSUE DATE']`.
- All 1,837 rows with an ISSUE DATE already matched PERMIT_DATE (0 mismatches). Active 244/244 and Final 1,495/1,495 already complete.
- Remaining PERMIT_DATE nulls are In Review / Inactive / shell rows without ISSUE DATE — left as-is.
- **0 FILLED + 0 FIXED.**

### FINAL_DATE

- Ideal: populated for Final.
- Before: 299 rows had FINAL_DATE, of which 278 were Final (18.6% of Final) and 21 were non-Final. Every populated list_pr Final value equaled Final Issuance Review END DT (253 of those also equaled PERMIT_DATE) while a later Passed final inspection existed — upstream used the issuance step as the final date.
- Repair sources (in order): Finalize Permit Certificate of Completion / Cert. of Occupancy with Complete-like status → END DATE; else latest Passed/History/Approved final inspection (excluding Final Issuance Review, Final Plan Prep, Final Power / TCO / intake). Non-Final FINAL_DATE cleared. Final rows whose only stamp was Final Issuance Review cleared.
- **1,097 FILLED + 299 FIXED** (253 list_pr corrected to true final inspection; 46 cleared — 25 Final without a true final stamp + 16 Inactive + 4 In Review + 1 Active).
- Not repairable: 145 Final with empty / non-final process history (69 dict_pr + 49 empty_pr + 27 list_pr).
- After: Final 1,350/1,495 (90.3%); non-Final FINAL_DATE all null. Chronology: PERMIT&lt;FILE 0; FINAL&lt;PERMIT 0.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 43 | 0 | 107 → 64 |
| FILE_DATE | 0 | 0 | 64 → 64 |
| PERMIT_DATE | 0 | 0 | 162 → 162 |
| FINAL_DATE | 1,097 | 299 | 1,700 → 649 |

Ideal-field coverage after repair (among non-null STATUS_NORMALIZED):

- FILE_DATE: 100% of Active / Final / In Review / Inactive
- PERMIT_DATE: 100% of Active; 100% of Final; 23.2% of In Review (issued-then-replaced / stop-work style rows)
- FINAL_DATE: 90.3% of Final

Post-repair checks: remaining STATUS nulls are shells only; FILE_DATE complete for all mapped statuses; FINAL_DATE only on Final; no PERMIT&lt;FILE or FINAL&lt;PERMIT inversions; remaining FINAL gaps lack certificate / final-inspection stamps in DATA.

## Artifacts

- `agent/scripts/fl/data_repair_fl_orange_county.py`
- `AGENT_DATA_PATH/orange_county_repaired_sample.parquet`

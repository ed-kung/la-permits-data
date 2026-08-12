# Lake Mary (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script (in parquet encounter order) was Lake Mary (2,000 records). Most rows are empty `fees_detail` shells with no recoverable status or dates. On the 157 full `permit_status` rows, STATUS_NORMALIZED was mostly correct; PERMIT_DATE had been taken from portal `Permit Date`, which often post-dates finalization — FIXED to `Issue Date` (132 corrections; 0 remaining PERMIT>FINAL violations). FILE_DATE already matched `Application Date` except 2 fills. FINAL_DATE gained 1 fill from inspections; 58 CLOSED Final rows still lack any inspection history.

## Scope

- Input: `MY_DATA_PATH/processed_data/permits_fl_sample.parquet`
- Jurisdiction: Lake Mary, FL (first `(JURISDICTION, STATE)` lacking `agent/scripts/{state}/data_repair_{state}_{city}.py` in sample order)
- Script: `agent/scripts/fl/data_repair_fl_lake_mary.py`
- Artifact: `AGENT_DATA_PATH/lake_mary_repaired_sample.parquet`

## DATA schemas (`INFERRED_SCHEMA`)

| Schema | Count | Distinguishing keys |
| --- | ---: | --- |
| `fees_detail` | 1,841 | `detail`, `fees`, `fees_total` only (1,830 empty shells; 11 with Application Date/Status) |
| `permit_status` | 157 | above + `permit_status_detail`, `insp_status_detail`, … |
| `application` | 2 | `application_status`, `application_type`, `mini_set`, … |

## Field assessment

### STATUS_NORMALIZED

- Before: null 1,845; Final 123; Active 25; In Review 6; Inactive 1
- Raw sources: `Status for Permit Number`, `detail.Application Status`, `application_status`
- Mapping: FINAL INSPECTION COMPLETE / CLOSED / C.O. ISSUED / FINALED → Final; PERMIT PRINTED → Active; TO BE ISSUED / PLAN CHECK / PLANS BEING CHECKED → In Review; PERMIT REVOKED / PERMIT EXPIRED → Inactive
- Incorrect: 1 row with STATUS_ORIGINAL `plan check` / In Review while DATA status is PERMIT PRINTED → **FIXED** to Active
- Missing fillable: 15 rows (11 fees_detail with Application Status, 2 application FINALED, 2 permit_status) → **FILLED**
- Not fillable: 1,830 empty `fees_detail` shells
- After: null 1,830; Final 135; Active 26; In Review 7; Inactive 2

### FILE_DATE

- Ideal: populated for all records.
- On `permit_status`: 155/157 already equal `Application Date`; **2 FILLED**; 0 FIXED.
- On contentful `fees_detail`: all 11 already had FILE_DATE = Application Date.
- After: missing 1,832 (empty shells + 2 application mini_sets with no dates). Among statused records: 168/170 (98.8%).

### PERMIT_DATE

- Ideal: populated for Active and Final.
- Upstream used portal **Permit Date**, which matches ingested PERMIT_DATE on 153/155 populated `permit_status` rows — but among Final rows with FINAL_DATE, Permit Date is **after** FINAL in 36/65 cases, while Issue Date is always ≤ FINAL (65/65). Issue Date is the issuance date.
- Repair: overwrite from **Issue Date**; fallback to Permit Date only for Active/Final with blank Issue Date (1 CLOSED stub). Clear PERMIT_DATE on unissued In Review rows.
- **132 FIXED** (Issue Date corrections) + **5 FIXED** (cleared In Review) + **1 FILLED**
- After: Active 26/26 (100%); Final 124/135 (91.9%); In Review 0/7. Remaining Final gaps are fees_detail/application rows with no Issue Date. Chronology: 0 rows with PERMIT_DATE > FINAL_DATE.

### FINAL_DATE

- Ideal: populated for Final.
- Before: 65 populated, all on `permit_status`; 62 matched an APPROVED inspection whose name contains FINAL; 3 used other approved inspections (status FINAL INSPECTION COMPLETE).
- Repair for Final: latest APPROVED FINAL-* inspection date, else latest APPROVED inspection → **1 FILLED** (WINDOWS/DOORS on FINAL INSPECTION COMPLETE).
- Not repairable: 58 CLOSED with empty `insp_status_detail`; 9 fees_detail/application Final rows with no inspections.
- After: Final 66/135 (48.9%). Non-Final rows keep FINAL_DATE null.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 15 | 1 | 1,845 → 1,830 |
| FILE_DATE | 2 | 0 | 1,834 → 1,832 |
| PERMIT_DATE | 1 | 137 | 1,845 → 1,849 |
| FINAL_DATE | 1 | 0 | 1,935 → 1,934 |

Ideal-field coverage after repair (statused records only, n=170):

- FILE_DATE: 98.8% of statused records
- PERMIT_DATE: 100% of Active; 91.9% of Final
- FINAL_DATE: 48.9% of Final

Post-repair checks: 150/150 `permit_status` rows with Issue Date have PERMIT_DATE = Issue Date; 157/157 have FILE_DATE = Application Date; 0 PERMIT>FINAL date inversions.

## Artifacts

- `agent/scripts/fl/data_repair_fl_lake_mary.py`
- `AGENT_DATA_PATH/lake_mary_repaired_sample.parquet`

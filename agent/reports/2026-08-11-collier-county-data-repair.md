# Collier County (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script was Collier County (2,000 records). STATUS_NORMALIZED had 56 nulls from unmapped Application Status values (mainly Inspections Commenced); all were filled. FILE_DATE and PERMIT_DATE already matched Summary dates when present. FINAL_DATE was filled for 35 Final rows that lacked Date Finaled, using passed inspection DateCompleted. After repair, every Active/Final row has PERMIT_DATE and every Final row has FINAL_DATE.

## Scope

- Input: `MY_DATA_PATH/processed_data/permits_fl_sample.parquet`
- Jurisdiction: Collier County, FL (first `(JURISDICTION, STATE)` lacking `agent/scripts/{state}/data_repair_{state}_{city}.py`)
- Script: `agent/scripts/fl/data_repair_fl_collier_county.py`
- Artifact: `AGENT_DATA_PATH/collier_county_repaired_sample.parquet`

## DATA schemas (`INFERRED_SCHEMA`)

| Schema | Count | Distinguishing keys |
| --- | ---: | --- |
| `permit_info` | 1,341 | `Summary` + `Permit Info` (+ optional Locations / Business Name) |
| `project_permits` | 659 | `Summary` + `Permits` list (+ `project_id`) |

Both schemas share `Summary` fields used for repair: Application Status/Date, Issued Date, Date Finaled, plus `Inspections`.

## Field assessment

### STATUS_NORMALIZED

- Before: Final 1,682; Inactive 184; Active 53; In Review 25; **null 56**
- Nulls were unmapped `STATUS_ORIGINAL` / `Summary.Application Status` values, not missing DATA:
  - Inspections Commenced → Active (43)
  - Finalled - Processing Refund → Final (8)
  - Invalid License / Revision – Rejected → Inactive (2)
  - Pending Fees GMD / Address Verification / Fees Paid GMD → In Review (3)
- Already-populated statuses agreed with Application Status under the same map (0 FIXED).
- After: Final 1,690; Inactive 186; Active 96; In Review 28; **null 0**

### FILE_DATE

- Ideal: populated for all records.
- Before/after: 0 missing. All 2,000 matched `Summary.Application Date` (0 FILLED / 0 FIXED).

### PERMIT_DATE

- Ideal: populated for Active and Final.
- Before: 105 missing — all Inactive (81), In Review (21), or null status that became In Review (3). None had an Issued Date in DATA.
- Active and Final already had PERMIT_DATE matching Issued Date in every case.
- After: Active 96/96 (100%); Final 1,690/1,690 (100%). Remaining missing PERMIT_DATE are pre-issuance / never-issued Inactive and In Review rows (expected).

### FINAL_DATE

- Ideal: populated for Final.
- When present, FINAL_DATE always matched `Summary.Date Finaled` (1,655 matches; 345 both missing). Not an Expiration copy.
- 35 Final rows (32 Inspections Completed + 3 Finaled) had null Date Finaled → filled from:
  1. last passed inspection with “final” in Activity, else
  2. last passed inspection DateCompleted
- After status fill, 8 Finalled - Processing Refund rows already carried correct FINAL_DATE.
- After: Final 1,690/1,690 (100%); no FINAL_DATE on Active / In Review / Inactive.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 56 | 0 | 56 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 0 | 0 | 105 → 105 |
| FINAL_DATE | 35 | 0 | 345 → 310 |

Ideal-field coverage after repair:

- FILE_DATE: 100% of all records
- PERMIT_DATE: 100% of Active and Final
- FINAL_DATE: 100% of Final

## Artifacts

- `agent/scripts/fl/data_repair_fl_collier_county.py`
- `AGENT_DATA_PATH/collier_county_repaired_sample.parquet`

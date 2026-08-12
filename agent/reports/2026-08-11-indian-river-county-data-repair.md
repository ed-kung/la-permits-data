# Indian River County (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script was Indian River County (2,001 records). STATUS_NORMALIZED had 12 nulls (Expired Older Permits / Impasse) — all filled as Inactive. FILE_DATE was missing on all 380 flat-schema rows and filled from Submission Date (100% coverage after repair). Upstream flat PERMIT_DATE/FINAL_DATE were systematic mis-copies of Submission Date and Expiration Date; those 59 rows were corrected (PERMIT cleared; FINAL replaced with Completed Date for 33 Final rows or cleared otherwise). MGO `DateIssued` is always a sentinel, so Active/Final PERMIT_DATE cannot be populated from DATA.

## Scope

- Input: `MY_DATA_PATH/processed_data/permits_fl_sample.parquet`
- Jurisdiction: Indian River County, FL (first `(JURISDICTION, STATE)` lacking `agent/scripts/{state}/data_repair_{state}_{city}.py`)
- Script: `agent/scripts/fl/data_repair_fl_indian_river_county.py`
- Artifact: `AGENT_DATA_PATH/indian_river_county_repaired_sample.parquet`

## DATA schemas (`INFERRED_SCHEMA`)

| Schema | Count | Distinguishing keys |
| --- | ---: | --- |
| `mgo_project` | 1,621 | `ProjectStatus`, `DateCreated`, `DateIssued`, … |
| `flat_basic` | 329 | `Status`, `Submission Date`, `Expiration Date` |
| `flat_with_completion` | 51 | flat keys plus `City` / `CO Date` / `Completed Date` |

## Field assessment

### STATUS_NORMALIZED

- Before: Final 1,629; Inactive 239; Active 95; In Review 26; **null 12**
- Nulls were unmapped originals, not missing DATA:
  - `expired (older permits)` / `Expired (Older Permits)` → Inactive (11; 69 peers already Inactive)
  - `impasse` / `Impasse` → Inactive (1)
- Already-populated statuses agreed with ProjectStatus / Status under the same map (0 FIXED).
- After: Final 1,629; Inactive 251; Active 95; In Review 26; **null 0**

### FILE_DATE

- Ideal: populated for all records.
- Before: 380 missing — all `flat_basic` / `flat_with_completion` rows. Every flat row has `Submission Date`.
- `mgo_project` FILE_DATE already matched `DateCreated` for all 1,621 rows.
- After: **0 missing** (380 FILLED from Submission Date).

### PERMIT_DATE

- Ideal: populated for Active and Final.
- Before: 1,942 missing; the 59 populated values were **all** equal to flat `Submission Date` (application date), not an issuance date.
- `mgo_project` `DateIssued` is always the sentinel `0001-01-01T00:00:00` — no usable issuance source.
- Flat schemas have no issuance field.
- Repair: cleared the 59 Submission copies (FIXED). No FILLED (no true candidate in DATA).
- After: Active 0/95; Final 0/1,629. Remaining gaps are not fillable from DATA.

### FINAL_DATE

- Ideal: populated for Final.
- Before: 1,942 missing; the 59 populated values were **all** equal to flat `Expiration Date` (validity window), not finalization.
- `CO Date` is present on `flat_with_completion` but never populated.
- `Completed Date` is real on all 33 Final `flat_with_completion` rows → FINAL_DATE FIXED from Expiration to Completed.
- Other Expiration copies cleared (3 Final without Completed, 7 Active, 16 Inactive).
- After: Final 33/1,629 (2.0%) — all from `Completed Date`. Non-Final FINAL_DATE = 0. Remaining Final gaps (`mgo_project` 1,303 + `flat_basic` 293) have no completion date in DATA.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 12 | 0 | 12 → 0 |
| FILE_DATE | 380 | 0 | 380 → 0 |
| PERMIT_DATE | 0 | 59 | 1,942 → 2,001 |
| FINAL_DATE | 0 | 59 | 1,942 → 1,968 |

Ideal-field coverage after repair:

- FILE_DATE: 100% of all records
- PERMIT_DATE: 0% of Active and Final (no issuance date in DATA)
- FINAL_DATE: 2.0% of Final (33/33 `flat_with_completion` Final rows; none elsewhere)

Post-repair checks: 0 flat FINAL_DATE still equal Expiration; 0 flat PERMIT_DATE still equal Submission.

## Artifacts

- `agent/scripts/fl/data_repair_fl_indian_river_county.py`
- `AGENT_DATA_PATH/indian_river_county_repaired_sample.parquet`

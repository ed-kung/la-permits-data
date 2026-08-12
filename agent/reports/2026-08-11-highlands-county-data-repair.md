# Highlands County (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script was Highlands County (1,998 records). All DATA rows share one `permit_bundle` schema. STATUS_NORMALIZED incorrectly mapped 151 issued `Open` permits to In Review — FIXED to Active. FILE_DATE and PERMIT_DATE already matched `Application Date` / `Issued Date` with no incorrect values. FINAL_DATE was missing on 488 Final rows with empty `C.O. Issued`; 187 were FILLED from passed inspection dates (prefer TYPE containing FINAL). Remaining Final gaps have no dated passed inspection in DATA.

## Scope

- Input: `MY_DATA_PATH/processed_data/permits_fl_sample.parquet`
- Jurisdiction: Highlands County, FL (first `(JURISDICTION, STATE)` lacking `agent/scripts/{state}/data_repair_{state}_{city}.py`)
- Script: `agent/scripts/fl/data_repair_fl_highlands_county.py`
- Artifact: `AGENT_DATA_PATH/highlands_county_repaired_sample.parquet`

## DATA schemas (`INFERRED_SCHEMA`)

| Schema | Count | Distinguishing keys |
| --- | ---: | --- |
| `permit_bundle` | 1,998 | `permit_info`, `inspection_info`, `plan_info`, `fee_info`, … |

`permit_info` always includes `Status`, `Application Date`, `Issued Date`, `C.O. Issued`.

## Field assessment

### STATUS_NORMALIZED

- Before: Final 1,558; Inactive 277; In Review 163; Active 0; null 0
- Raw `Status` mapping already correct for Closed→Final, Expired/Void/Reject→Inactive, Hold→In Review, Open without Issued→In Review.
- Incorrect: **151** `Open` rows with a real `Issued Date` were In Review; they are issued / under inspection → **Active**.
- After: Final 1,558; Inactive 277; Active 151; In Review 12 (11 unissued Open + 1 Hold)

### FILE_DATE

- Ideal: populated for all records.
- Before/after: **0 missing**. Every row matches `Application Date` (0 FIXED / 0 FILLED).

### PERMIT_DATE

- Ideal: populated for Active and Final.
- Before: 125 missing; every populated value equals `Issued Date` (0 mismatches).
- Missing exactly when `Issued Date` is blank — including 10 Closed/Final GUP stubs with no issuance or inspections.
- After status repair: Active 151/151 (100%); Final 1,548/1,558 (99.4%). Remaining Final gaps are not fillable from DATA.
- No FILLED/FIXED on PERMIT_DATE (values were already correct where present).

### FINAL_DATE

- Ideal: populated for Final.
- Before: 928 missing overall; among Final, 488 missing. Every populated FINAL_DATE equals `C.O. Issued`.
- Non-Final rows already had no FINAL_DATE.
- Repair for Final missing CO: fill from latest passed (`RES == "P"`) inspection with `TYPE` containing `FINAL` (100), else latest passed inspection (87) → **187 FILLED**.
- After: Final 1,257/1,558 (80.7%). Remaining 301 Final gaps have neither `C.O. Issued` nor a dated passed inspection.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 0 | 151 | 0 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 0 | 0 | 125 → 125 |
| FINAL_DATE | 187 | 0 | 928 → 741 |

Ideal-field coverage after repair:

- FILE_DATE: 100% of all records
- PERMIT_DATE: 100% of Active; 99.4% of Final
- FINAL_DATE: 80.7% of Final

Post-repair checks: 0 Open+Issued still In Review; 1,070/1,070 Final rows with `C.O. Issued` keep FINAL_DATE equal to CO.

## Artifacts

- `agent/scripts/fl/data_repair_fl_highlands_county.py`
- `AGENT_DATA_PATH/highlands_county_repaired_sample.parquet`

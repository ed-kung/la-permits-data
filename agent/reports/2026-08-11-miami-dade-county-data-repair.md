# Miami-Dade County (FL) data repair

Summary: Miami-Dade County was the first FL sample jurisdiction without a repair script after Jacksonville, Lee County, Sarasota County, Osceola County, Orlando, Charlotte County, and Pasco County. The DATA payload is a flat open-data schema (list-valued fields) with `Issue Date`, inspection request/type/disposition dates, and CO/CC release dates — but no application/submittal date. The repair fills all **134** null `STATUS_NORMALIZED` values and fixes **5** mis-labeled Final rows; clears **151** incorrect `FILE_DATE` values that had been copied from inspection `Request Date` (true file dates are not in DATA); leaves `PERMIT_DATE` unchanged (already matches `Issue Date` on 2,000/2,001 rows); and brings Final `FINAL_DATE` coverage to **100%** while clearing spurious finals on non-Final rows and preferring CO/CC release over earlier inspection dates when available.

## Jurisdiction selected

- Sample file: `MY_DATA_PATH/processed_data/permits_fl_sample.parquet`
- First `(JURISDICTION, STATE)` without `agent/scripts/{state}/data_repair_{state}_{city}.py`: **Miami-Dade County, FL**
- Sample size: **2,001** records
- Script: `agent/scripts/fl/data_repair_fl_miami_dade_county.py` (`data_repair`)

## DATA schemas (`INFERRED_SCHEMA`)

All rows share the same key set; subtypes reflect field population:

| Schema | n | Notes |
| --- | ---: | --- |
| `mdc_with_inspection` | 1,760 | Has Request Date and/or Inspection Type/Date |
| `mdc_issued_only` | 240 | Has Issue Date, no inspection/request fields |
| `mdc_minimal` | 1 | Empty Issue Date and no inspection fields |

Canonical field sources:

- `STATUS_ORIGINAL` `finaled` / `issued` / `expired`, else CO/CC or approved FINAL-family inspection, else Issue Date → `STATUS_NORMALIZED`
- No application date in DATA → `FILE_DATE` (cannot fill; clear Request-Date copies)
- `DATA["Issue Date"]` (fallback `New Issue Date`) → `PERMIT_DATE`
- `CO/CC Release Date` / `Bldg CO Release Date`; else `Last Approved Inspection Date`; else approved `Inspection Date` → `FINAL_DATE`

Important DATA nuance: `Request Date` is an **inspection request** date (Request ≥ Issue on 1,706/1,760 rows with both; typically one day before `Inspection Date`), not a permit application/submittal date.

## Findings by field

### STATUS_NORMALIZED

- Before: Final 1,618; Active 234; missing 134; Inactive 15. No In Review.
- Upstream mapping covers only `finaled`→Final, `final`→Final, `issued`→Active, `expired`→Inactive. The **134** nulls are:
  - **89** with null `STATUS_ORIGINAL` (88 issued with no inspections yet; 1 with approved FINAL inspection)
  - **45** where `STATUS_ORIGINAL` equals the current Inspection Type label (`buck and fastener`, `fire final`, `rough`, etc.) without a normalized status
- `STATUS_ORIGINAL == "final"` mirrors Inspection Type `FINAL` and is not always a completed final: rejected / corrections / non-approved dispositions were still labeled Final.
- Repair:
  - **134 FILLED** — 121→Active (88 empty-status issued + 33 mid-inspection), 13→Final (approved fire final / final zoning / one approved FINAL with null original)
  - **5 FIXED** — Final→Active (3: `REJECTED WORK` / `INSPECTED FR Q` without CO); Final→Inactive (2: expired with `CORRECTIONS RE`)
- After: Final 1,626; Active 358; Inactive 17; missing **0**.

### FILE_DATE

- Before: 1,850 missing (92.5%). The **151** populated values all matched `Request Date` exactly and never represented an earlier application date.
- DATA has no application / submittal / filed date field (`Process Number` encodes a year token only).
- Repair: **0 FILLED**, **151 FIXED** (cleared incorrect Request-Date copies).
- After: **2,001 missing**. Not fillable from DATA.

### PERMIT_DATE

- Before: 1 missing. All 2,000 present values matched `Issue Date` at day resolution.
- The single missing row is `mdc_minimal` (empty `Issue Date` / `New Issue Date`) with status Active/`issued`.
- Repair: **0 FILLED**, **0 FIXED**.
- After: Active **357/358 (99.7%)**; Final **1,626/1,626 (100%)**; Inactive 17/17.

### FINAL_DATE

- Before: 349 missing. Among populated values, **1,648/1,652** matched `Inspection Date`; CO/CC was present on 124 rows but only matched FINAL_DATE on 93 (21+ cases where CO/CC is later than the inspection date used upstream).
- Spurious `FINAL_DATE` on non-Final rows: 35 null-status mid-inspection rows + 1 Inactive.
- Repair: **6 FILLED** (newly Final rows / missing finals with a CO or approved inspection date); **63 FIXED** (31 value corrections — **22** to CO/CC, others to Last Approved / approved inspection hierarchy; **32** cleared on non-Final).
- After: Final **1,626/1,626 (100%)**; Active / Inactive have **0**.

## Repair performance

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | ---: | ---: | ---: | ---: |
| STATUS_NORMALIZED | 134 | 5 | 134 | 0 |
| FILE_DATE | 0 | 151 | 1,850 | 2,001 |
| PERMIT_DATE | 0 | 0 | 1 | 1 |
| FINAL_DATE | 6 | 63 | 349 | 375 |

Coverage after repair (share non-null):

| Status | n | FILE_DATE | PERMIT_DATE | FINAL_DATE |
| --- | ---: | ---: | ---: | ---: |
| Active | 358 | 0% | 99.7% | 0% |
| Final | 1,626 | 0% | 100% | 100% |
| In Review | 0 | — | — | — |
| Inactive | 17 | 0% | 100% | 0% |

## Artifacts

- Repair script: `agent/scripts/fl/data_repair_fl_miami_dade_county.py`
- Repaired sample parquet: `AGENT_DATA_PATH/miami_dade_county_repaired_sample.parquet`

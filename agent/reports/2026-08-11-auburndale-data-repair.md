# Auburndale (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script (after Alachua County through Atlantic Beach) was Auburndale. Its DATA is SmartGov community-portal JSON (`My Project` / `Build Status` / `Permit Inspections`). Five `Expired: 10/7/2022` rows had null STATUS_NORMALIZED and were FILLED as Inactive. FILE_DATE already matched `Submitted` on all 2,000 rows. PERMIT_DATE already matched `Issued` when present; 31 Active/Final rows lack issuance stamps and stay missing. FINAL_DATE was universally null (Closed always blank); 1,025 Final rows were FILLED from Passed/Approved/Completed Final inspections. 781 Closed rows still lack a usable final date.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` and walked unique `(JURISDICTION, STATE)` pairs in sort order. Existing FL repair scripts covered Alachua County, Altamonte Springs, Anna Maria, Apopka, Arcadia, and Atlantic Beach. **Auburndale** was the first without `agent/scripts/fl/data_repair_fl_auburndale.py`.

Sample size: **2,000** records.

## DATA schemas

SmartGov portal scrape (`ci-auburndale-fl…smartgovcommunity.com`). Top-level keys include `Department`, `My Project`, `Permit Type`, `Build Status`, `Permit Number`, contacts/fees/inspections arrays, and usually `Parcel Number` / `ProjectDescription`.

| INFERRED_SCHEMA    | Count |
| ------------------ | ----: |
| `smartgov_full`    | 1,999 |
| `smartgov_no_desc` |     1 |

Canonical source fields:

| Target field      | DATA source                                                      |
| ----------------- | ---------------------------------------------------------------- |
| STATUS_NORMALIZED | `Build Status` (`Closed`→Final, `Approved`→Active, `Expired*`→Inactive) |
| FILE_DATE         | `My Project.Submitted` (else `Created`)                          |
| PERMIT_DATE       | `My Project.Issued` (else `Approved`)                            |
| FINAL_DATE        | `My Project.Closed` (else latest Passed/Approved/Completed Final inspection) |

## Field assessments

### STATUS_NORMALIZED

Before: Final 1,806 · Inactive 163 · Active 26 · missing 5.  
After: Final 1,806 · Inactive 168 · Active 26 · missing 0.

- Maps cleanly from `Build Status` / `STATUS_ORIGINAL` prefixes (`closed` / `approved` / `expired: …`).
- **5** rows with `Build Status = Expired: 10/7/2022` were left null upstream while 163 other `Expired*` rows were already Inactive → **FILLED** as Inactive.
- No incorrect non-null statuses found; no FIXED.

Flags: **FILLED 5 · FIXED 0**.

### FILE_DATE

Before/after: **0 missing**. Ideal: populated for all records.

- Every row’s FILE_DATE matches `My Project.Submitted` at day resolution.
- `Created` is always the SmartGov blank placeholder (` - -`).

Flags: **FILLED 0 · FIXED 0**.

### PERMIT_DATE

Before/after: **31 missing**. Ideal: populated for Active and Final.

- When `Issued` is present (1,969 rows), upstream PERMIT_DATE matches it exactly; Inactive rows also carry Issued → PERMIT_DATE.
- Gaps:
  - **26 Active** (`Build Status = Approved`): `Issued` and `Approved` both blank; no inspections → cannot fill.
  - **5 Final** (`Closed`): blank Issued/Approved and empty inspections → cannot fill.
- `Approved` date is never populated in this sample, so the Approved fallback never fires.

Coverage after repair: Active **0%** · Final **99.7%**.  
Flags: **FILLED 0 · FIXED 0**.

### FINAL_DATE

Before: **2,000 missing**. After: **975 missing** (781 of them Final). Ideal: populated for Final.

- `My Project.Closed` is blank on every row.
- **1,025** Final rows have a Passed/Approved/Completed inspection whose name contains `Final` (e.g. `BLDG Final`, `Roof Final`) → **FILLED** from the latest such date.
- Remaining **781** Closed rows have no usable Final inspection (712 empty inspection lists; 58 only non-final passed inspections; others failed/pending finals) → stay missing.
- Source chronology quirks: 4 rows have Final inspection dates before Issued (likely migrated/prior-cycle stamps); left as agency values.

Flags: **FILLED 1,025 · FIXED 0**.

## Repair script

- Path: `agent/scripts/fl/data_repair_fl_auburndale.py`
- Entry point: `data_repair(df)`
- Adds `INFERRED_SCHEMA` and `{FIELD}_FLAG` (`FILLED` / `FIXED`) for STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, FINAL_DATE.
- Conventions aligned with SmartGov repair for Seaside (CA) and recent FL scripts.

## Repair performance (sample)

| Field             | FILLED | FIXED | Missing before | Missing after |
| ----------------- | -----: | ----: | -------------: | ------------: |
| STATUS_NORMALIZED |      5 |     0 |              5 |             0 |
| FILE_DATE         |      0 |     0 |              0 |             0 |
| PERMIT_DATE       |      0 |     0 |             31 |            31 |
| FINAL_DATE        |  1,025 |     0 |          2,000 |           975 |

Ideal-coverage gaps remaining: Active/Final missing PERMIT_DATE **31**; Final missing FINAL_DATE **781**; FILE_DATE / STATUS_NORMALIZED fully populated.

## Artifacts

- Repaired parquet: `AGENT_DATA_PATH/repaired/permits_fl_auburndale_repaired.parquet`

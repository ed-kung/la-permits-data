# Winter Springs (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script was **Winter Springs**. DATA is a Logos/TRAKiT-style portal payload (`Permit Summary` / `Permit Details` / Inspections / empty Notes). Upstream left 2 stale statuses where `STATUS_ORIGINAL` stayed `permit issued` while `StatusValue` had advanced to Completed. `FILE_DATE` was missing on 1,988/2,000 rows with no Application Received Date or notes to recover from; repair filled 17 Pending Payment as-of stamps. `PERMIT_DATE` was already correct for all Issued/Active rows and cannot be invented for Completed shells. `FINAL_DATE` matched Completed status dates on 1,850 rows; repair filled the 2 mislabeled Completed shells. After repair: STATUS 100%; FILE_DATE 1.5% overall (58% of In Review); Active PERMIT_DATE 100%; Final FINAL_DATE 100%.

## Jurisdiction selection

`(JURISDICTION, STATE)` pairs in `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` (first-appearance order) were checked against `agent/scripts/{state}/data_repair_{state}_{city}.py`. First missing: **Winter Springs, FL** → `agent/scripts/fl/data_repair_fl_winter_springs.py` (2,000 sample rows).

## DATA schemas (`INFERRED_SCHEMA`)

All 2,000 rows share Logos top-level keys (`Permit Summary`, `Permit Details`, `Inspections`, `Notes`, `Conditions`, `Payment Summary`, `Location`, …). Optional sections: `CONTRACTOR INFORMATION`, `GARAGE SALE INFORMATION`. Notes are empty throughout; `Permit Details` never exposes `Application Received Date`. Content suffixes split by StatusValue lifecycle plus contractor/garage markers:

| Schema | n | Notes |
| --- | ---: | --- |
| `logos_completed` | 1,418 | `Permit Completed on …` |
| `logos_completed_contractor` | 362 | + CONTRACTOR INFORMATION |
| `logos_completed_garage` | 72 | + GARAGE SALE INFORMATION |
| `logos_issued` | 63 | `Permit Issued on …` |
| `logos_issued_contractor` | 23 | Issued + contractor |
| `logos_pending_review` | 21 | `Pending Review as of …` |
| `logos_pending` | 16 | `Pending Payment as of …` |
| `logos_issued_garage` | 12 | Issued + garage |
| `logos_created` | 7 | `Permit Created as of …` |
| `logos_created_contractor` | 5 | Created + contractor |
| `logos_pending_contractor` | 1 | Pending Payment + contractor |

Canonical fields:

| Target field | Source in DATA |
| --- | --- |
| STATUS_NORMALIZED | `Permit Summary.StatusValue` base text |
| FILE_DATE | `Application Received Date` / notes / routed (absent here); else Created status date; else Pending Payment as-of |
| PERMIT_DATE | Issued status date only (`PaidValue` unused) |
| FINAL_DATE | Completed status date; else final-ish Completed+Pass inspection |

StatusValue bases → normalized: Completed→Final; Issued→Active; Pending Payment / Pending Review / Created→In Review; Expired→Inactive (none in sample).

## Field assessments

### STATUS_NORMALIZED

| StatusValue base | n | Upstream STATUS_NORMALIZED | Assessment |
| --- | ---: | --- | --- |
| Permit Completed | 1,852 | Final 1,850 / **Active 2** | Fix Active → Final |
| Permit Issued | 98 | Active | Correct |
| Pending Review | 21 | In Review | Correct |
| Pending Payment | 17 | In Review | Correct |
| Permit Created | 12 | In Review | Correct |

**Root cause:** Upstream mapped from stale `STATUS_ORIGINAL` (`permit issued`) instead of current `StatusValue` (`Permit Completed on …`) on 2 rows.

**Repair performance:** FILLED 0, FIXED 2; missing 0 → 0. After: Final 1,852; Active 98; In Review 50.

### FILE_DATE

Ideal: populated for all records.

- Before: missing on **1,988 / 2,000**. The 12 present values are `Permit Created as of …` rows already equal to the create stamp (**0 FIXED**).
- No Application Received Date, Notes, or Application Routed conditions → no submittal stamp for Issued / Completed / Pending Review.
- **17 FILLED** from Pending Payment as-of dates (weak proxy, same Logos convention as Winter Haven / Greenacres).

Coverage after repair: In Review 29/50 (58.0%); Active / Final 0%. Overall 29/2,000 (1.5%). Date-order inversions: 0.

### PERMIT_DATE

Ideal: populated for Active and Final.

- All 98 correctly Active Issued rows already matched `Permit Issued on …` (0 calendar mismatches; **0 FILLED / 0 FIXED**).
- Final stays almost empty: Completed StatusValue only embeds completion; `PaidValue` is fee payment, not used. **2** Final rows retain a pre-existing PERMIT_DATE from when they were still labeled Active/`permit issued` (left intact; both precede their Completed status dates).

Coverage after repair: Active 98/98 (100%); Final 2/1,852 (0.1%).

### FINAL_DATE

Ideal: populated for Final; absent otherwise.

- 1,850 already-Final rows with embedded Completed dates matched `FINAL_DATE` (0 mismatches).
- **2 FILLED** on Completed rows previously labeled Active (after status → Final).
- Non-Final correctly have no FINAL_DATE after repair. Inspections exist for many rows but were unused as a primary source because every Completed StatusValue already embeds a date.

Coverage after repair: Final 1,852/1,852 (100%); Active / In Review 0%. PERMIT>FINAL inversions: 0.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 0 | 2 | 0 → 0 |
| FILE_DATE | 17 | 0 | 1,988 → 1,971 |
| PERMIT_DATE | 0 | 0 | 1,900 → 1,900 |
| FINAL_DATE | 2 | 0 | 150 → 148 |

Remaining structural gaps: FILE_DATE on Issued/Completed/Pending Review (no application stamp in DATA); Final PERMIT_DATE (no issuance stamp once Completed).

## Artifacts

- Repair script: `agent/scripts/fl/data_repair_fl_winter_springs.py` (`data_repair`)
- Repaired sample parquet: `$AGENT_DATA_PATH/repaired/permits_fl_winter_springs_repaired.parquet`

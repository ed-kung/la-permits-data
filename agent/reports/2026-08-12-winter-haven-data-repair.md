# Winter Haven (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script was **Winter Haven**. DATA is a Logos/TRAKiT-style portal payload (`Permit Summary` / `Permit Details` / empty Notes·Inspections·Conditions). Upstream often kept stale `STATUS_ORIGINAL` (`permit issued`, `pending payment`) while `StatusValue` had advanced to Completed/Issued, and left 98 `Permit Expired` rows with null `STATUS_NORMALIZED`. FILE_DATE was missing on 1,999/2,000 rows with no Application Received Date or notes to recover from. The repair filled 98 statuses and fixed 100, filled 15 `FILE_DATE`, 25 `PERMIT_DATE`, and 75 `FINAL_DATE` values. After repair: STATUS 100%; FILE_DATE 0.8% overall (42.1% of In Review); Active PERMIT_DATE 100%; Final FINAL_DATE 98.4%.

## Jurisdiction selection

`(JURISDICTION, STATE)` pairs in `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` (first-appearance order) were checked against `agent/scripts/{state}/data_repair_{state}_{city}.py`. First missing: **Winter Haven, FL** → `agent/scripts/fl/data_repair_fl_winter_haven.py` (2,000 sample rows).

## DATA schemas (`INFERRED_SCHEMA`)

All 2,000 rows share Logos top-level keys (`Permit Summary`, `Permit Details`, `Inspections`, `Notes`, `Conditions`, `Payment Summary`, `Location`, …). Notes, Inspections, Conditions, and GENERAL CONSTRUCTION are empty throughout; Permit Details never exposes `Application Received Date`. Content suffixes split by StatusValue lifecycle and whether an embedded lifecycle date is present:

| Schema | n | Notes |
| --- | ---: | --- |
| `logos_completed` | 1,422 | `Permit Completed on …` |
| `logos_issued` | 319 | `Permit Issued on …` |
| `logos_expired` | 177 | `Permit Expired MM/DD/YYYY` |
| `logos_completed_bare` | 23 | `Permit Completed` with no date |
| `logos_expired_bare` | 21 | `Permit Expired` with no date |
| `logos_pending` | 14 | `Pending Payment as of …` |
| `logos_pending_review` | 13 | `Pending Review as of …` |
| `logos_pending_review_bare` | 8 | bare Pending Review |
| `logos_created` | 2 | `Permit Created as of …` |
| `logos_pending_bare` | 1 | bare Pending Payment |

Canonical fields:

| Target field | Source in DATA |
| --- | --- |
| STATUS_NORMALIZED | `Permit Summary.StatusValue` base text |
| FILE_DATE | `Application Received Date` / notes / routed (absent here); else Created status date; else Pending Payment as-of |
| PERMIT_DATE | Issued status date only (`PaidValue` unused) |
| FINAL_DATE | Completed status date; else final-ish inspection (none in sample) |

StatusValue bases → normalized: Completed→Final; Issued→Active; Pending Payment / Pending Review / Created→In Review; Expired→Inactive.

## Field assessments

### STATUS_NORMALIZED

| StatusValue base | n | Upstream STATUS_NORMALIZED | Assessment |
| --- | ---: | --- | --- |
| Permit Completed | 1,445 | Final 1,370 / **Active 55** / **In Review 20** | Fix Active/In Review → Final |
| Permit Issued | 319 | Active 294 / **In Review 25** | Fix In Review → Active |
| Permit Expired | 198 | Inactive 100 / **null 98** | Fill null → Inactive |
| Pending Review | 21 | In Review | Correct |
| Pending Payment | 15 | In Review | Correct |
| Permit Created | 2 | In Review | Correct |

**Root causes:**
1. Upstream mapped from stale `STATUS_ORIGINAL` (`permit issued`, `pending payment`) instead of current `StatusValue`.
2. `Permit Expired MM/DD/YYYY` in `STATUS_ORIGINAL` was not normalized → 98 nulls.

**Repair performance:** FILLED 98, FIXED 100; missing 98 → 0. After: Final 1,445; Active 319; Inactive 198; In Review 38.

### FILE_DATE

Ideal: populated for all records.

- Before: missing on **1,999 / 2,000**. The single present value is a `Permit Created as of …` row matching the create stamp.
- No Application Received Date, Notes, Inspections, or Conditions in this sample → no submittal stamp for Issued / Completed / Expired.
- **15 FILLED** from the second Created stamp + 14 Pending Payment as-of dates (weak proxy, same convention as Greenacres).

Coverage after repair: In Review 16/38 (42.1%); Active / Final / Inactive 0%. Overall 16/2,000 (0.8%). Date-order inversions: 0.

### PERMIT_DATE

Ideal: populated for Active and Final.

- All 294 correctly Active Issued rows already matched `Permit Issued on …` (0 calendar mismatches).
- **25 FILLED** on Issued rows mislabeled In Review (after status → Active).
- Final stays mostly empty: Completed StatusValue only embeds completion; `PaidValue` is fee payment, not used. **55** Final rows retain a pre-existing PERMIT_DATE from when they were still labeled Active/`permit issued` (left intact; 11 of those differ from PaidValue, supporting that they are real issue stamps).

Coverage after repair: Active 319/319 (100%); Final 55/1,445 (3.8%).

### FINAL_DATE

Ideal: populated for Final; absent otherwise.

- 1,347 already-Final rows with embedded Completed dates matched `FINAL_DATE` (0 mismatches); 23 bare `Permit Completed` rows had no date and no inspections → remain missing.
- **75 FILLED** on Completed rows previously labeled Active (55) or In Review (20).
- Non-Final correctly have no FINAL_DATE after repair.

Coverage after repair: Final 1,422/1,445 (98.4%); Active / In Review / Inactive 0%. PERMIT>FINAL inversions: 0.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 98 | 100 | 98 → 0 |
| FILE_DATE | 15 | 0 | 1,999 → 1,984 |
| PERMIT_DATE | 25 | 0 | 1,651 → 1,626 |
| FINAL_DATE | 75 | 0 | 653 → 578 |

Remaining structural gaps: FILE_DATE on Issued/Completed/Expired (no application stamp in DATA); Final PERMIT_DATE (no issuance stamp once Completed); 23 bare Completed FINAL_DATE.

## Artifacts

- Repair script: `agent/scripts/fl/data_repair_fl_winter_haven.py` (`data_repair`)
- Repaired sample parquet: `$AGENT_DATA_PATH/repaired/permits_fl_winter_haven_repaired.parquet`

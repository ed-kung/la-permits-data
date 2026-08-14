# South Daytona (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script (first-appearance order) was **South Daytona**. DATA is a uniform city-portal payload (`app` / `permit` / `inspection_list`), same family as Nassau County. Upstream left `STATUS_NORMALIZED` null on 592/2,000 rows and never ingested `FINAL_DATE` despite PASS inspections. Repair fills all statuses from `app.Status` + `Permit Status`, keeps FILE/PERMIT dates (already correct when present), and fills FINAL_DATE from the latest PASS inspection. After repair: STATUS fully populated; FILE_DATE 99.85%; Active/Final PERMIT_DATE 1,843/1,853 (99.5%); Final FINAL_DATE 1,581/1,674 (94.4%).

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` and walked `(JURISDICTION, STATE)` pairs in first-appearance order. South Daytona was the first pair without `agent/scripts/fl/data_repair_fl_south_daytona.py`.

## DATA shape

| Schema | n |
| --- | ---: |
| `city_app_issued_insp` | 1,654 |
| `city_app_issued` | 236 |
| `city_app_permit_no_issued` | 95 |
| `city_app_app_only` | 15 |

Canonical sources:

| Field | DATA source |
| --- | --- |
| STATUS_NORMALIZED | `app.Status` + `permit.Permit Status` (+ Issued Date): COMPLETED → Final; WITHDRAWN/EXPIRED/DENIED/ENTERED IN ERROR → Inactive; COMPLETE left → Final; ISSUED → Active; REVIEWING / NEW* / READY TO ISSUE → In Review |
| FILE_DATE | `app.Application Received Date` |
| PERMIT_DATE | `permit.Issued Date` |
| FINAL_DATE | Latest inspection with result starting `PASS` (floored at Issued Date) |

## Field assessments

### STATUS_NORMALIZED

Before: Final 1,354; null 592; Active 54; no In Review / Inactive.

Root cause of nulls: upstream normalized only a subset of `COMPLETE / CLOSED APPLICATION` and `ACTIVE / ISSUED`; other app.Status values (including `COMPLETE / CLOSED COMPLETE`, withdrawn/expired, and review-stage Active shells) were left blank.

| Fill → | Main sources | n |
| --- | --- | ---: |
| Final | COMPLETE / CLOSED COMPLETE + COMPLETED; COMPLETE / NEW APPLICATION; ACTIVE / CLOSED* + COMPLETED | 320 |
| Active | ACTIVE / ISSUED; ACTIVE / NEW* + ISSUED; ACTIVE / CLOSED* + ISSUED | 125 |
| Inactive | WITHDRAWN / EXPIRED / ENTERED IN ERROR / DENIED | 92 |
| In Review | ACTIVE / NEW*|READY TO ISSUE + REVIEWING | 55 |

No incorrect non-null statuses found (0 FIXED). After: Final 1,674; Active 179; Inactive 92; In Review 55; null 0.

### FILE_DATE

Missing on 3/2,000 before and after. Those three Final shells have an empty `app` object (no Application Received Date). The other 1,997 rows already match Application Received Date at calendar-day resolution. Flags: **0 FILLED, 0 FIXED**.

### PERMIT_DATE

Missing on 111/2,000 before. Where Issued Date exists, calendar day already matched PERMIT_DATE (1,888/1,888). Two Active rows had Issued Date but null PERMIT_DATE → FILLED. Remaining misses are mostly In Review / Inactive REVIEWING shells with blank Issued Date; 10 Final rows stay missing (COMPLETE + REVIEWING or empty permit). Flags: **2 FILLED, 0 FIXED**.

Ideal Active/Final coverage after repair: **1,843/1,853 (99.5%)**.

### FINAL_DATE

Missing on all 2,000 rows before — never ingested despite `inspection_list` PASS rows on 1,641 records.

| Repair action | n |
| --- | ---: |
| FILLED from latest PASS inspection (Final only) | 1,581 |
| Cleared on non-Final (none had values) | 0 |

Final still missing FINAL_DATE: **93** (mostly `city_app_issued` shells with no PASS-dated inspections; a few have dated non-PASS inspections only). Ideal Final coverage: **1,581/1,674 (94.4%)**. Zero `PERMIT_DATE > FINAL_DATE` inversions after flooring FINAL at Issued Date.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 592 | 0 | 592 → 0 |
| FILE_DATE | 0 | 0 | 3 → 3 |
| PERMIT_DATE | 2 | 0 | 111 → 109 |
| FINAL_DATE | 1,581 | 0 | 2,000 → 419 |

## Artifacts

- Script: `agent/scripts/fl/data_repair_fl_south_daytona.py` (`data_repair`)
- Repaired sample: `$AGENT_DATA_PATH/south_daytona_repaired_sample.parquet`

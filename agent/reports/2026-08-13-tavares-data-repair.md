# Tavares (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script was **Tavares**. DATA is the legacy city portal payload (`detail` / `permit_status_detail` / `insp_status_detail`). Upstream `PERMIT_DATE` was taken from portal **Permit Date** (often a conversion sentinel such as `2018-01-01`, and frequently after `FINAL_DATE`); repair overwrites it with **Issue Date**, eliminating all 1,100 `PERMIT_DATE > FINAL_DATE` inversions. `EXPIRED` / `WITHDRAWN` Application Status values that were labeled Active/Final are corrected to Inactive. After repair: STATUS fully populated; FILE_DATE 100%; Active/Final PERMIT_DATE 1,864/1,865 (99.9%); Final FINAL_DATE 1,223/1,440 (84.9%).

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` and walked `(JURISDICTION, STATE)` pairs in first-appearance order. Tavares was the first pair without `agent/scripts/fl/data_repair_fl_tavares.py`.

## DATA shape

| Schema | n |
| --- | ---: |
| `permit_status` | 1,980 |
| `fees_detail` | 20 |

Canonical sources:

| Field | DATA source |
| --- | --- |
| STATUS_NORMALIZED | `Status for Permit Number`, overridden to Inactive when `Application Status` ∈ {WITHDRAWN, EXPIRED, VOID, CANCELLED, ABANDONED}; else `Application Status` on `fees_detail` |
| FILE_DATE | `Application Date` |
| PERMIT_DATE | `Issue Date` (fallback: `Permit Date` for Active/Final when Issue blank and not after FINAL) |
| FINAL_DATE | Latest APPROVED / APPROVED WITH EXCEPTION inspection with FINAL/FNL/CLOSEOUT in the name; else latest non-NOC passed inspection |

## Field assessments

### STATUS_NORMALIZED

Before: Final 1,472; Active 457; In Review 43; null 21; Inactive 7.

| Issue | n | Repair |
| --- | ---: | --- |
| Null on `fees_detail` / sparse rows (WITHDRAWN, PLAN CHECK, HOLD, ONLINE SUBMITTAL, APPROVED, CLOSED) | 21 | FILLED |
| EXPIRED + CLOSED/PERMIT PRINTED labeled Final/Active | 42 | FIXED → Inactive |
| WITHDRAWN + CLOSED labeled Final | 26 | FIXED → Inactive |
| C.O. ISSUED labeled Active | 5 | FIXED → Final |
| In Review while Status for Permit Number is PERMIT PRINTED | 3 | FIXED → Active |

Flags: **21 FILLED, 76 FIXED**; 0 null after repair.

After: Final 1,440; Active 425; Inactive 88; In Review 47.

### FILE_DATE

Missing on 0/2,000. Calendar day matches `Application Date` on every row. Flags: **0 FILLED, 0 FIXED**.

### PERMIT_DATE

Missing on 20/2,000 before repair (all `fees_detail` shells with no Issue/Permit Date).

Root cause of incorrect values: upstream used portal **Permit Date** rather than **Issue Date**. Permit Date equals Issue Date on only 326/1,918 rows with both present; 649 rows carry the conversion-like value `2018-01-01`. That produced **1,100** rows where `PERMIT_DATE > FINAL_DATE`.

| Repair action | n |
| --- | ---: |
| FIXED to Issue Date | 1,584 |
| Cleared spurious Permit Date on In Review (no Issue Date) | 31 |
| Still missing (no Issue/Permit Date in DATA) | 51 |

After repair: **0** `PERMIT_DATE > FINAL_DATE` inversions. Active/Final coverage 1,864/1,865 (one `fees_detail` CLOSED shell has no dates). Eight Issue Dates of `07/07/59` (year 2059) are rejected as out of range.

### FINAL_DATE

Missing on 779/2,000 before (251 of 1,472 Final rows).

| Repair action | n |
| --- | ---: |
| FILLED from passed inspections | 6 |
| FIXED to inspection-derived date | 12 |
| Cleared on rows reclassified Inactive | 4 |

Final rows still missing FINAL_DATE (217 after status repair) almost all have empty `insp_status_detail` — no completion timestamp in DATA. Ideal Final coverage: **1,223/1,440 (84.9%)**. Non-Final rows have FINAL_DATE cleared.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 21 | 76 | 21 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 0 | 1,615 | 20 → 51 |
| FINAL_DATE | 6 | 16 | 779 → 777 |

Coverage after repair: FILE_DATE 100% all statuses; Active/Final PERMIT_DATE 99.9%; Final FINAL_DATE 84.9%.

## Artifacts

- Repair script: `agent/scripts/fl/data_repair_fl_tavares.py` (`data_repair`)
- Repaired sample: `AGENT_DATA_PATH/repaired/permits_fl_tavares_repaired.parquet`

# Sweetwater (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script was **Sweetwater**. DATA is a uniform Logos / TRAKiT portal payload (`Permit Summary`, `Permit Details`, `Inspections`, `Payment Summary`). `STATUS_NORMALIZED` was stale vs live `StatusValue` on 22 rows (Active/In Review while portal already showed Permit Completed or Permit Issued) → FIXED. `FILE_DATE` was missing on 1,891/2,000; filled 1,641 from Created/Pending status dates or earliest Completed plan-review / non-final inspection (≤ lifecycle date). `PERMIT_DATE` filled for 8 Issued rows previously mislabeled In Review; Final rows still lack a true issuance stamp (PaidValue is fee payment, not issue date). `FINAL_DATE` was already correct for all properly labeled Final rows; filled 14 after status upgrades. After repair: STATUS 0 null; FILE_DATE 87.5%; Active PERMIT_DATE 100%; Final FINAL_DATE 100%; 0 date inversions.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` and walked `(JURISDICTION, STATE)` pairs in file order. Sweetwater was the first pair without `agent/scripts/fl/data_repair_fl_sweetwater.py`.

## DATA shape

All 2,000 rows share the same top-level key set. Content variants (`INFERRED_SCHEMA`) follow StatusValue lifecycle:

| Schema | n | Role |
| --- | ---: | --- |
| `logos_completed` | 1,465 | `Permit Completed on …` |
| `logos_issued` | 321 | `Permit Issued on …` |
| `logos_pending` | 111 | `Pending Payment as of …` |
| `logos_created` | 103 | `Permit Created as of …` |

Canonical sources:

| Field | DATA source |
| --- | --- |
| STATUS_NORMALIZED | `Permit Summary.StatusValue` base (`Permit Completed`→Final, `Permit Issued`→Active, `Pending Payment`/`Permit Created`→In Review) |
| FILE_DATE | Created / Pending Payment embedded date; else earliest Completed plan-review / CU Application Review ≤ lifecycle date; else earliest Completed non-final inspection ≤ lifecycle date |
| PERMIT_DATE | Embedded date only when StatusValue is `Permit Issued on …` (PaidValue not used) |
| FINAL_DATE | Embedded date when StatusValue is `Permit Completed on …`; else latest Completed+Pass final inspection |

Notes, Conditions, Application Received Date, CONTACT INFORMATION, and GENERAL CONSTRUCTION are empty throughout the sample.

## Field assessments

### STATUS_NORMALIZED

Before: Final 1,451; Active 323; In Review 226; **0 null**.

Upstream mapped from stale `STATUS_ORIGINAL` while live `StatusValue` had advanced on 22 rows:

| Before → after | n | Cause |
| --- | ---: | --- |
| Active → Final | 10 | `STATUS_ORIGINAL=permit issued`, StatusValue=`Permit Completed on …` |
| In Review → Active | 8 | `permit created` / `pending payment`, StatusValue=`Permit Issued on …` |
| In Review → Final | 4 | `permit created` / `pending payment`, StatusValue=`Permit Completed on …` |

After: Final 1,465; Active 321; In Review 214; every row matches StatusValue base. Flags: **0 FILLED, 22 FIXED**.

### FILE_DATE

Missing on 1,891/2,000 before. The 109 present values were almost all `Permit Created as of …` stamps (102 exact matches); none were post-lifecycle.

| Repair action | n |
| --- | ---: |
| FILLED from earliest plan-review / CU Application Review | 1,452 |
| FILLED from earliest Completed non-final inspection | 104 |
| FILLED from Pending Payment as-of date | 84 |
| FILLED from Permit Created as-of date | 1 |
| Still missing (no dated non-final Completed inspection / status stamp) | 250 |

Final-type inspections (e.g. Building Final, Public Works Final) are excluded as FILE proxies — they are completion stamps and produced `FILE_DATE > PERMIT_DATE` when used. After: **1,750/2,000 (87.5%)**; 0 `FILE_DATE > PERMIT_DATE` / `FILE_DATE > FINAL_DATE` inversions. In Review coverage 100%; Active 78.5%; Final 87.6%.

### PERMIT_DATE

Missing on 1,677/2,000 before. All 323 present Active/`Permit Issued` values already matched the Issued status date (0 mismatches).

| Issue | n | Repair |
| --- | ---: | --- |
| Issued StatusValue mislabeled In Review → missing PERMIT_DATE | 8 | FILLED from Issued status date |
| Final / `Permit Completed` has no issuance stamp in StatusValue | 1,455 | left missing (PaidValue ≠ issue on 171/310 Issued rows with both dates) |

The 10 Final rows that retain PERMIT_DATE were previously Active with a correct Issued mapping before status upgrade. Active coverage after repair: **321/321 (100%)**. Active/Final combined: **331/1,786 (18.5%)** — Final stays nearly empty by design. Flags: **8 FILLED, 0 FIXED**.

### FINAL_DATE

Missing on 549/2,000 before. Every Final row with `Permit Completed on …` already had FINAL_DATE equal to the embedded completion date (1,451/1,451).

| Repair action | n |
| --- | ---: |
| FILLED after Active/In Review → Final status upgrade | 14 |

Final coverage after repair: **1,465/1,465 (100%)**. Non-Final rows keep FINAL_DATE cleared. Flags: **14 FILLED, 0 FIXED**.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 0 | 22 | 0 → 0 |
| FILE_DATE | 1,641 | 0 | 1,891 → 250 |
| PERMIT_DATE | 8 | 0 | 1,677 → 1,669 |
| FINAL_DATE | 14 | 0 | 549 → 535 |

Coverage after repair: FILE_DATE 87.5% all statuses; Active PERMIT_DATE 321/321 (100%); Final FINAL_DATE 1,465/1,465 (100%). Remaining gaps are Final PERMIT_DATE (no issuance field in DATA) and Issued/Completed shells with only undated or final-only inspections for FILE_DATE.

## Artifacts

- Repair script: `agent/scripts/fl/data_repair_fl_sweetwater.py` (`data_repair`)
- Repaired sample parquet: `$AGENT_DATA_PATH/repaired/permits_fl_sweetwater_repaired.parquet`

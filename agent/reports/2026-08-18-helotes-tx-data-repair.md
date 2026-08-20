# Helotes (TX) data repair

**Summary:** Helotes was the first TX jurisdiction in `permits_tx_sample.parquet` without a repair script (89 rows; scripts already existed through Hays County). DATA is a MyGovernmentOnline (MGO) project payload (`mgo_ppm` only in this sample). STATUS_NORMALIZED was correct on 88/89 rows; the single missing value (`Closed (Completed)`) was filled as Final. FILE_DATE already matches `DateCreated` on every row. PERMIT_DATE and FINAL_DATE remain universally missing because `DateIssued` / `DateUpdated` are the .NET sentinel `0001-01-01` and no other issuance or finaling timestamps exist in DATA.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_tx_sample.parquet` and walked unique `(JURISDICTION, STATE)` pairs in alphabetical order. Existing TX repair scripts covered Abilene through Hays County. **Helotes** was the first missing pair → `agent/scripts/tx/data_repair_tx_helotes.py`.

## DATA schema

All 89 rows parse as flat MGO project objects with the same key set, including `PaymentProcessorModule`:

| INFERRED_SCHEMA | n | Notes |
| --- | ---: | --- |
| `mgo_ppm` | 89 | includes `PaymentProcessorModule` (= `MGO`) |

Canonical sources:

| Target field | Primary source | Notes |
| --- | --- | --- |
| STATUS_NORMALIZED | `ProjectStatus` | heuristic keyword fallback for unseen strings |
| FILE_DATE | `DateCreated` | — |
| PERMIT_DATE | `DateIssued` (non-sentinel only) | always `0001-01-01` in sample |
| FINAL_DATE | — | no finaled/CO timestamp in payload |

## Field assessment

### STATUS_NORMALIZED

Before: In Review 71 / Active 17 / missing 1. After: In Review 71 / Active 17 / Final 1.

| ProjectStatus | STATUS_ORIGINAL | STATUS_NORMALIZED | n | Notes |
| --- | --- | --- | ---: | --- |
| In Review | in review | In Review | 55 | already correct |
| Permit Issued | permit issued | Active | 15 | already correct |
| Pending | pending | In Review | 9 | already correct |
| Pending (In Review) | pending (in review) | In Review | 7 | already correct |
| Issued | issued | Active | 2 | already correct |
| Closed (Completed) | closed (completed) | Final | 1 | was missing → FILLED |

Root cause of the missing status: the upstream normalizer did not map `Closed (Completed)` (Helotes wording differs from Elgin’s `Closed/Completed`).

### FILE_DATE

Fully populated (0 missing). Every row’s FILE_DATE matches `DateCreated` at calendar-day resolution. No FILLED or FIXED changes.

### PERMIT_DATE

Universally missing (89 / 89). `DateIssued` is `0001-01-01T00:00:00` on every row (MGO / .NET empty-date sentinel). No alternate issuance or approval timestamp appears in DATA (`ScheduledDueDate` and power-request dates are null). Active (17) and Final (1) rows therefore remain without PERMIT_DATE.

### FINAL_DATE

Universally missing (89 / 89). `DateUpdated` is also always the .NET sentinel; no finaled / completion / certificate-of-occupancy field exists. The single Final row cannot be filled. No spurious FINAL_DATE values were present on non-Final rows.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 1 | 0 | 1 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 0 | 0 | 89 → 89 |
| FINAL_DATE | 0 | 0 | 89 → 89 |

After repair, by status:

- **FILE_DATE:** 100% for all statuses
- **PERMIT_DATE:** Active 0/17 (0%), Final 0/1 (0%)
- **FINAL_DATE:** Final 0/1 (0%); non-Final remain empty

Date-order violations: none (no PERMIT_DATE / FINAL_DATE values to compare).

## Not repairable

- All Active/Final rows lack a real `DateIssued` → PERMIT_DATE stays missing.
- The Final row lacks a finaling/completion timestamp → FINAL_DATE stays missing.
- The repair function still applies the MGO mappings so future rows with real `DateIssued` values (or additional `ProjectStatus` strings) can be corrected when present.

## Artifacts

- Script: `agent/scripts/tx/data_repair_tx_helotes.py` (`data_repair`)
- Repaired sample: `AGENT_DATA_PATH/repaired/permits_tx_helotes_repaired.parquet`

# Jonestown (TX) data repair

**Summary:** Jonestown was the first TX jurisdiction in `permits_tx_sample.parquet` without a repair script (2,000 rows, alphabetical order). DATA is a MyGovernmentOnline (MGO) project payload (`mgo_ppm` / `mgo_base`). FILE_DATE already matches `DateCreated` 1:1. One STATUS_NORMALIZED row was FIXED (Active → In Review) because `STATUS_ORIGINAL` was stale relative to DATA `ProjectStatus`. PERMIT_DATE and FINAL_DATE remain universally missing because `DateIssued` / `DateUpdated` are the .NET sentinel `0001-01-01` and no other issuance or finaling timestamps exist in DATA.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_tx_sample.parquet` and walked unique `(JURISDICTION, STATE)` pairs in alphabetical order. **Jonestown** was the first missing pair → `agent/scripts/tx/data_repair_tx_jonestown.py`.

## DATA schema

All 2,000 rows parse as flat MGO project objects. Variants differ only by presence of `PaymentProcessorModule`:

| INFERRED_SCHEMA | n | Notes |
| --- | ---: | --- |
| `mgo_ppm` | 1,996 | includes `PaymentProcessorModule` (= `MGO`) |
| `mgo_base` | 4 | same key set without that field |

Canonical sources:

| Target field | Primary source | Notes |
| --- | --- | --- |
| STATUS_NORMALIZED | `ProjectStatus` | heuristic keyword fallback for unseen strings |
| FILE_DATE | `DateCreated` | — |
| PERMIT_DATE | `DateIssued` (non-sentinel only) | always `0001-01-01` in sample |
| FINAL_DATE | — | no finaled/CO timestamp in payload |

## Field assessment

### STATUS_NORMALIZED

Before: Final 1,475 / Active 252 / Inactive 149 / In Review 124. After: Final 1,475 / Active 251 / Inactive 149 / In Review 125.

| ProjectStatus | STATUS_ORIGINAL | STATUS_NORMALIZED (expected) | n |
| --- | --- | --- | ---: |
| Project Closed/Complete | project closed/complete | Final | 1,475 |
| Permit Issued | permit issued | Active | 251 |
| Pending (Under Review) | pending (under review) | In Review | 124 |
| Expired | expired | Inactive | 125 |
| Withdrawn | withdrawn | Inactive | 24 |
| Pending (Under Review) | permit issued *(stale)* | In Review *(FIXED)* | 1 |

Cause of the mismatch: permit `2024-1279` has `STATUS_ORIGINAL` = `permit issued` and `STATUS_NORMALIZED` = `Active`, but DATA `ProjectStatus` = `Pending (Under Review)` (`ProjectStatusID` 1357). Repair trusts DATA and FIXED the status to In Review.

### FILE_DATE

Fully populated (0 missing). Every row’s FILE_DATE matches `DateCreated` at calendar-day resolution. No FILLED or FIXED changes.

### PERMIT_DATE

Universally missing (2,000 / 2,000). `DateIssued` is `0001-01-01T00:00:00` on every row (MGO / .NET empty-date sentinel). No alternate issuance or approval timestamp appears in DATA (`ScheduledDueDate`, power-request dates, and `RequestInspections` are empty/false). Active (251) and Final (1,475) rows therefore remain without PERMIT_DATE.

### FINAL_DATE

Universally missing (2,000 / 2,000). `DateUpdated` is also always the .NET sentinel; no finaled / completion / certificate-of-occupancy field exists. Final rows (1,475) cannot be filled. No spurious FINAL_DATE values were present on non-Final rows.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 0 | 1 | 0 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 0 | 0 | 2,000 → 2,000 |
| FINAL_DATE | 0 | 0 | 2,000 → 2,000 |

After repair, by status:

- **FILE_DATE:** 100% for all statuses
- **PERMIT_DATE:** Active 0/251 (0%), Final 0/1,475 (0%)
- **FINAL_DATE:** Final 0/1,475 (0%); non-Final remain empty

Date-order violations: none (no PERMIT_DATE / FINAL_DATE values to compare).

## Not repairable

- All Active/Final rows lack a real `DateIssued` → PERMIT_DATE stays missing.
- All Final rows lack a finaling/completion timestamp → FINAL_DATE stays missing.
- The repair function still applies the MGO mappings so future rows with real `DateIssued` values (or new `ProjectStatus` strings) can be corrected when present.

## Artifacts

- Script: `agent/scripts/tx/data_repair_tx_jonestown.py` (`data_repair`)
- Repaired sample: `AGENT_DATA_PATH/repaired/permits_tx_jonestown_repaired.parquet`

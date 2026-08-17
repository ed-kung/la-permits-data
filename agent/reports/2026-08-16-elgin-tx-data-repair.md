# Elgin (TX) data repair

**Summary:** Elgin was the first TX jurisdiction in `permits_tx_sample.parquet` without a repair script (2,000 rows, alphabetical order). DATA is a MyGovernmentOnline (MGO) project payload (`mgo_ppm` / `mgo_base`). STATUS_NORMALIZED and FILE_DATE already match `ProjectStatus` and `DateCreated` 1:1. PERMIT_DATE and FINAL_DATE are universally missing because `DateIssued` / `DateUpdated` are the .NET sentinel `0001-01-01` and no other issuance or finaling timestamps exist in DATA. The repair script encodes the MGO mappings for future rows with real dates.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_tx_sample.parquet` and walked unique `(JURISDICTION, STATE)` pairs in alphabetical order. **Elgin** was the first missing pair → `agent/scripts/tx/data_repair_tx_elgin.py`.

## DATA schema

All 2,000 rows parse as flat MGO project objects. Variants differ only by presence of `PaymentProcessorModule`:

| INFERRED_SCHEMA | n | Notes |
| --- | ---: | --- |
| `mgo_ppm` | 1,984 | includes `PaymentProcessorModule` (= `MGO`) |
| `mgo_base` | 16 | same key set without that field |

Canonical sources:

| Target field | Primary source | Notes |
| --- | --- | --- |
| STATUS_NORMALIZED | `ProjectStatus` | heuristic keyword fallback for unseen strings |
| FILE_DATE | `DateCreated` | — |
| PERMIT_DATE | `DateIssued` (non-sentinel only) | always `0001-01-01` in sample |
| FINAL_DATE | — | no finaled/CO timestamp in payload |

## Field assessment

### STATUS_NORMALIZED

Before/after: Final 963 / Active 617 / In Review 417 / Inactive 3 / missing 0.

| ProjectStatus | STATUS_ORIGINAL | STATUS_NORMALIZED | n |
| --- | --- | --- | ---: |
| Closed/Completed | closed/completed | Final | 963 |
| Issued | issued | Active | 617 |
| Pending (Under Review) | pending (under review) | In Review | 417 |
| Expired | expired | Inactive | 3 |

No missing values; 0 mismatches vs `ProjectStatus`. No FILLED/FIXED changes.

### FILE_DATE

Fully populated (0 missing). Every row’s FILE_DATE matches `DateCreated` at calendar-day resolution (including 6 `DateCreated` strings that omit fractional seconds). No FILLED or FIXED changes.

### PERMIT_DATE

Universally missing (2,000 / 2,000). `DateIssued` is `0001-01-01T00:00:00` on every row (MGO / .NET empty-date sentinel). No alternate issuance or approval timestamp appears in DATA (`ScheduledDueDate`, power-request dates, and `RequestInspections` are empty/false). Active (617) and Final (963) rows therefore remain without PERMIT_DATE.

### FINAL_DATE

Universally missing (2,000 / 2,000). `DateUpdated` is also always the .NET sentinel; no finaled / completion / certificate-of-occupancy field exists. Final rows (963) cannot be filled. No spurious FINAL_DATE values were present on non-Final rows.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 0 | 0 | 0 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 0 | 0 | 2,000 → 2,000 |
| FINAL_DATE | 0 | 0 | 2,000 → 2,000 |

After repair, by status:

- **FILE_DATE:** 100% for all statuses
- **PERMIT_DATE:** Active 0/617 (0%), Final 0/963 (0%)
- **FINAL_DATE:** Final 0/963 (0%); non-Final remain empty

Date-order violations: none (no PERMIT_DATE / FINAL_DATE values to compare).

## Not repairable

- All Active/Final rows lack a real `DateIssued` → PERMIT_DATE stays missing.
- All Final rows lack a finaling/completion timestamp → FINAL_DATE stays missing.
- The repair function still applies the MGO mappings so future rows with real `DateIssued` values (or new `ProjectStatus` strings) can be corrected when present.

## Artifacts

- Script: `agent/scripts/tx/data_repair_tx_elgin.py` (`data_repair`)
- Repaired sample: `AGENT_DATA_PATH/repaired/permits_tx_elgin_repaired.parquet`

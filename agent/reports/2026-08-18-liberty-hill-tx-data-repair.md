# Liberty Hill (TX) data repair

**Summary:** Liberty Hill was the first TX jurisdiction in `permits_tx_sample.parquet` without a repair script (2,000 rows; scripts already existed through North Richland Hills). DATA is a MyGovernmentOnline (MGO) project payload (`mgo_ppm` 1,999 / `mgo_base` 1). STATUS_NORMALIZED and FILE_DATE are already correct on every row (0 FILLED / 0 FIXED). PERMIT_DATE and FINAL_DATE remain universally missing because `DateIssued` / `DateUpdated` are the .NET sentinel `0001-01-01` and no other issuance or finaling timestamps exist in DATA.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_tx_sample.parquet` and walked unique `(JURISDICTION, STATE)` pairs in first-appearance order. Existing TX repair scripts covered Austin through North Richland Hills. **Liberty Hill** was the first missing pair → `agent/scripts/tx/data_repair_tx_liberty_hill.py`.

## DATA schema

All 2,000 rows parse as flat MGO project objects. One row lacks `PaymentProcessorModule`; the rest include it (`MGO`):

| INFERRED_SCHEMA | n | Notes |
| --- | ---: | --- |
| `mgo_ppm` | 1,999 | includes `PaymentProcessorModule` (= `MGO`) |
| `mgo_base` | 1 | same keys without `PaymentProcessorModule` |

Canonical sources:

| Target field | Primary source | Notes |
| --- | --- | --- |
| STATUS_NORMALIZED | `ProjectStatus` | heuristic keyword fallback for unseen strings |
| FILE_DATE | `DateCreated` | — |
| PERMIT_DATE | `DateIssued` (non-sentinel only) | always `0001-01-01` in sample |
| FINAL_DATE | — | no finaled/CO timestamp in payload |

## Field assessment

### STATUS_NORMALIZED

Before/after: Final 1,675 / Active 263 / In Review 45 / Inactive 17. No missing values. Every row already matches `ProjectStatus`:

| ProjectStatus | STATUS_ORIGINAL | STATUS_NORMALIZED | n | Notes |
| --- | --- | --- | ---: | --- |
| Project Closed/Complete | project closed/complete | Final | 1,675 | already correct |
| Permit Issued | permit issued | Active | 263 | already correct |
| Pending (Under Review) | pending (under review) | In Review | 45 | already correct |
| Withdrawn | withdrawn | Inactive | 17 | already correct |

### FILE_DATE

Fully populated (0 missing). Every row’s FILE_DATE matches `DateCreated` at calendar-day resolution (range ~2018–2025). No FILLED or FIXED changes.

### PERMIT_DATE

Universally missing (2,000 / 2,000). `DateIssued` is `0001-01-01T00:00:00` on every row (MGO / .NET empty-date sentinel). No alternate issuance or approval timestamp appears in DATA (`ScheduledDueDate` and power-request dates are empty). Active (263) and Final (1,675) rows therefore remain without PERMIT_DATE.

### FINAL_DATE

Universally missing (2,000 / 2,000). `DateUpdated` is also always the .NET sentinel; no finaled / completion / certificate-of-occupancy field exists. Final rows (1,675) cannot be filled. No spurious FINAL_DATE values were present on non-Final rows.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 0 | 0 | 0 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 0 | 0 | 2,000 → 2,000 |
| FINAL_DATE | 0 | 0 | 2,000 → 2,000 |

After repair, by status:

- **FILE_DATE:** 100% for all statuses
- **PERMIT_DATE:** Active 0/263 (0%), Final 0/1,675 (0%)
- **FINAL_DATE:** Final 0/1,675 (0%); non-Final remain empty

Date-order violations: none (no PERMIT_DATE / FINAL_DATE values to compare).

## Not repairable

- All Active/Final rows lack a real `DateIssued` → PERMIT_DATE stays missing.
- All Final rows lack a finaling/completion timestamp → FINAL_DATE stays missing.
- The repair function still applies the MGO mappings so future rows with real `DateIssued` values (or additional `ProjectStatus` strings) can be corrected when present.

## Artifacts

- Script: `agent/scripts/tx/data_repair_tx_liberty_hill.py` (`data_repair`)
- Repaired sample: `AGENT_DATA_PATH/repaired/permits_tx_liberty_hill_repaired.parquet`

# Leander (TX) data repair

**Summary:** Leander was the first TX jurisdiction in `permits_tx_sample.parquet` without a repair script (2,000 rows; scripts already existed through San Marcos). DATA is a MyGovernmentOnline (MGO) project payload (`mgo_ppm` 1,999 / `mgo_base` 1). STATUS_NORMALIZED and FILE_DATE are already correct on every row. PERMIT_DATE and FINAL_DATE remain universally missing because `DateIssued` / `DateUpdated` are the .NET sentinel `0001-01-01` and no other issuance or finaling timestamps exist in DATA.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_tx_sample.parquet` and walked unique `(JURISDICTION, STATE)` pairs in appearance order. Existing TX repair scripts covered Austin through San Marcos. **Leander** was the first missing pair → `agent/scripts/tx/data_repair_tx_leander.py`.

## DATA schema

All 2,000 rows parse as flat MGO project objects. The only key-set difference is presence of `PaymentProcessorModule`:

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

Before/after: Final 1,637 / Active 181 / Inactive 162 / In Review 20. Zero missing values; zero mismatches vs `ProjectStatus`.

| ProjectStatus | STATUS_ORIGINAL | STATUS_NORMALIZED | n |
| --- | --- | --- | ---: |
| Closed/Complete | closed/complete | Final | 1,637 |
| Permit Issued | permit issued | Active | 181 |
| Expired | expired | Inactive | 155 |
| Pending (Under Review) | pending (under review) | In Review | 20 |
| Cancelled/Withdrawn | cancelled/withdrawn | Inactive | 6 |
| Void | void | Inactive | 1 |

No FILLED or FIXED status changes on this sample. Leander uses the spelling `Closed/Complete` (no trailing “d”), which is included in the repair map for future robustness.

### FILE_DATE

Fully populated (0 missing). Every row’s FILE_DATE matches `DateCreated` at calendar-day resolution. No FILLED or FIXED changes.

### PERMIT_DATE

Universally missing (2,000 / 2,000). `DateIssued` is `0001-01-01T00:00:00` on every row (MGO / .NET empty-date sentinel). No alternate issuance or approval timestamp appears in DATA (`ScheduledDueDate`, power-request dates, and nested document fields are empty/null). Active (181) and Final (1,637) rows therefore remain without PERMIT_DATE.

### FINAL_DATE

Universally missing (2,000 / 2,000). `DateUpdated` is also always the .NET sentinel; no finaled / completion / certificate-of-occupancy field exists. Final rows (1,637) cannot be filled. No spurious FINAL_DATE values were present on non-Final rows.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 0 | 0 | 0 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 0 | 0 | 2,000 → 2,000 |
| FINAL_DATE | 0 | 0 | 2,000 → 2,000 |

After repair, by status:

- **FILE_DATE:** 100% for all statuses
- **PERMIT_DATE:** Active 0/181 (0%), Final 0/1,637 (0%)
- **FINAL_DATE:** Final 0/1,637 (0%); non-Final remain empty

Date-order violations: none (no PERMIT_DATE / FINAL_DATE values to compare).

## Not repairable

- All Active/Final rows lack a real `DateIssued` → PERMIT_DATE stays missing.
- All Final rows lack a finaling/completion timestamp → FINAL_DATE stays missing.
- The repair function still applies the MGO mappings so future rows with real `DateIssued` values (or additional `ProjectStatus` strings) can be corrected when present.

## Artifacts

- Script: `agent/scripts/tx/data_repair_tx_leander.py` (`data_repair`)
- Repaired sample: `AGENT_DATA_PATH/repaired/permits_tx_leander_repaired.parquet`

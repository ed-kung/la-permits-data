# Dripping Springs (TX) data repair

**Summary:** Dripping Springs was the first TX jurisdiction in `permits_tx_sample.parquet` without a repair script (2,000 rows). DATA is a MyGovernmentOnline (MGO) project payload (`mgo_ppm` / `mgo_base`). STATUS_NORMALIZED and FILE_DATE already match `ProjectStatus` and `DateCreated` 1:1. PERMIT_DATE and FINAL_DATE are universally missing because `DateIssued` / `DateUpdated` are the .NET sentinel `0001-01-01` and no other issuance or finaling timestamps exist in DATA. The repair script encodes the MGO mappings for future rows with real dates.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_tx_sample.parquet` and walked unique `(JURISDICTION, STATE)` pairs in appearance order. Existing TX scripts covered through Denton; **Dripping Springs** was the first missing pair → `agent/scripts/tx/data_repair_tx_dripping_springs.py`.

## DATA schema

All 2,000 rows parse as flat MGO project objects. Variants differ only by presence of `PaymentProcessorModule`:

| INFERRED_SCHEMA | n | Notes |
| --- | ---: | --- |
| `mgo_ppm` | 1,998 | includes `PaymentProcessorModule` (= `MGO`) |
| `mgo_base` | 2 | same key set without that field |

Canonical sources:

| Target field | Primary source | Notes |
| --- | --- | --- |
| STATUS_NORMALIZED | `ProjectStatus` | heuristic keyword fallback for unseen strings |
| FILE_DATE | `DateCreated` | — |
| PERMIT_DATE | `DateIssued` (non-sentinel only) | always `0001-01-01` in sample |
| FINAL_DATE | — | no finaled/CO timestamp in payload |

## Field assessment

### STATUS_NORMALIZED

Before/after: Active 836 / Final 795 / In Review 323 / Inactive 46 / missing 0.

| ProjectStatus | STATUS_ORIGINAL | STATUS_NORMALIZED | n |
| --- | --- | --- | ---: |
| Permit Issued (Construction) | permit issued (construction) | Active | 811 |
| Closed | closed | Final | 795 |
| Pending (Under Review) | pending (under review) | In Review | 211 |
| Pending (Payment Needed) | pending (payment needed) | In Review | 95 |
| Expired | expired | Inactive | 42 |
| Permit Issued | permit issued | Active | 25 |
| Pending (Review Complete) | pending (review complete) | In Review | 17 |
| Withdrawn by Applicant | withdrawn by applicant | Inactive | 4 |

No missing values; 0 mismatches vs `ProjectStatus`. No FILLED/FIXED changes.

### FILE_DATE

Fully populated (0 missing). Every row’s FILE_DATE matches `DateCreated` at calendar-day resolution (YYYY-MM-DD prefix). No FILLED or FIXED changes.

### PERMIT_DATE

Universally missing (2,000 / 2,000). `DateIssued` is `0001-01-01T00:00:00` on every row (MGO / .NET empty-date sentinel). No alternate issuance or approval timestamp appears in DATA (`ScheduledDueDate`, power-request dates, and nested document/inspection lists are empty). Active (836) and Final (795) rows therefore remain without PERMIT_DATE.

### FINAL_DATE

Universally missing (2,000 / 2,000). `DateUpdated` is also always the .NET sentinel; no finaled / completion / certificate-of-occupancy field exists. Final rows (795) cannot be filled. No spurious FINAL_DATE values were present on non-Final rows.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 0 | 0 | 0 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 0 | 0 | 2,000 → 2,000 |
| FINAL_DATE | 0 | 0 | 2,000 → 2,000 |

After repair, by status:

- **FILE_DATE:** 100% for all statuses
- **PERMIT_DATE:** Active 0/836 (0%), Final 0/795 (0%)
- **FINAL_DATE:** Final 0/795 (0%); non-Final remain empty

Date-order violations: none (no PERMIT_DATE / FINAL_DATE values to compare).

## Not repairable

- All Active/Final rows lack a real `DateIssued` → PERMIT_DATE stays missing.
- All Final rows lack a finaling/completion timestamp → FINAL_DATE stays missing.
- The repair function still applies the MGO mappings so future rows with real `DateIssued` values (or new `ProjectStatus` strings) can be corrected when present.

## Artifacts

- Script: `agent/scripts/tx/data_repair_tx_dripping_springs.py` (`data_repair`)
- Repaired sample: `AGENT_DATA_PATH/repaired/permits_tx_dripping_springs_repaired.parquet`

# Bee Cave (TX) data repair

**Summary:** Bee Cave was the first TX jurisdiction in `permits_tx_sample.parquet` without a repair script. All 2,000 rows are MyGovernmentOnline (MGO) project payloads (`mgo_ppm` / `mgo_base`). STATUS_NORMALIZED and FILE_DATE already match `ProjectStatus` and `DateCreated` 1:1. PERMIT_DATE and FINAL_DATE are universally missing because `DateIssued` / `DateUpdated` are the .NET sentinel `0001-01-01` and no other issuance or finaling timestamps exist in DATA.

## Scope

- Input: `MY_DATA_PATH/processed_data/permits_tx_sample.parquet`
- Jurisdiction: Bee Cave, TX (first pair lacking `agent/scripts/{state}/data_repair_{state}_{city}.py`)
- Script: `agent/scripts/tx/data_repair_tx_bee_cave.py`
- Artifact: `AGENT_DATA_PATH/repaired/permits_tx_bee_cave_repaired.parquet`

## DATA schema

Flat MGO project object with shared date/status keys. Variants differ only by presence of `PaymentProcessorModule`:

| INFERRED_SCHEMA | n |
| --- | ---: |
| mgo_ppm | 1,987 |
| mgo_base | 13 |

Canonical source fields:

| Target field | Primary source | Fallback |
| --- | --- | --- |
| STATUS_NORMALIZED | `ProjectStatus` | heuristic keyword map |
| FILE_DATE | `DateCreated` | — |
| PERMIT_DATE | `DateIssued` (non-sentinel only) | — |
| FINAL_DATE | — (none available) | — |

## Field assessment

### STATUS_NORMALIZED

| ProjectStatus | STATUS_ORIGINAL | STATUS_NORMALIZED | n |
| --- | --- | --- | ---: |
| Completed/Closed | completed/closed | Final | 1,209 |
| Pending (Under Review) | pending (under review) | In Review | 450 |
| Issued/Open | issued/open | Active | 274 |
| Cancelled/Withdrawn | cancelled/withdrawn | Inactive | 51 |
| Denied | denied | Inactive | 16 |

No missing values; 0 mismatches vs `ProjectStatus`. `ProjectStatusIsPermit` is True for Active / Final / In Review and False for Inactive (Cancelled/Withdrawn, Denied).

### FILE_DATE

Fully populated (0 missing). Every row’s FILE_DATE matches `DateCreated` at calendar-day resolution. No FILLED or FIXED changes.

### PERMIT_DATE

Universally missing (2,000 / 2,000). `DateIssued` is `0001-01-01T00:00:00` on every row (MGO / .NET empty-date sentinel). No alternate issuance or approval timestamp appears in DATA (`ScheduledDueDate`, power-request dates, nested lists are empty). Active (274) and Final (1,209) rows therefore remain without PERMIT_DATE.

### FINAL_DATE

Universally missing (2,000 / 2,000). `DateUpdated` is also always the .NET sentinel; no finaled / completion / certificate-of-occupancy field exists. Final rows (1,209) cannot be filled. No spurious FINAL_DATE values were present on non-Final rows.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 0 | 0 | 0 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 0 | 0 | 2,000 → 2,000 |
| FINAL_DATE | 0 | 0 | 2,000 → 2,000 |

After repair, by status:

- **FILE_DATE:** 100% for all statuses
- **PERMIT_DATE:** Active 0/274 (0%), Final 0/1,209 (0%)
- **FINAL_DATE:** Final 0/1,209 (0%); non-Final remain empty

## Not repairable

- All Active/Final rows lack a real `DateIssued` → PERMIT_DATE stays missing.
- All Final rows lack a finaling/completion timestamp → FINAL_DATE stays missing.
- The repair function still applies the MGO mappings so future rows with real `DateIssued` values (or new `ProjectStatus` strings) can be corrected when present.

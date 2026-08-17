# Cedar Park (TX) data repair

**Summary:** Cedar Park was the first TX jurisdiction in `permits_tx_sample.parquet` without a repair script. All 2,001 rows are MyGovernmentOnline (MGO) project payloads (`mgo_ppm` 2,000; `mgo_base` 1). STATUS_NORMALIZED and FILE_DATE already match `ProjectStatus` and `DateCreated` 1:1. PERMIT_DATE and FINAL_DATE are universally missing because `DateIssued` / `DateUpdated` are the .NET sentinel `0001-01-01` and no other issuance or finaling timestamps exist in DATA.

## Scope

- Input: `MY_DATA_PATH/processed_data/permits_tx_sample.parquet`
- Jurisdiction: Cedar Park, TX (first pair lacking `agent/scripts/{state}/data_repair_{state}_{city}.py`)
- Script: `agent/scripts/tx/data_repair_tx_cedar_park.py`
- Artifact: `AGENT_DATA_PATH/repaired/permits_tx_cedar_park_repaired.parquet`

## DATA schema

Flat MGO project object. Nearly all sample rows include `PaymentProcessorModule` = `MGO`; one row omits that key only:

| INFERRED_SCHEMA | n |
| --- | ---: |
| mgo_ppm | 2,000 |
| mgo_base | 1 |

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
| Closed | closed | Final | 1,720 |
| CO Issued | co issued | Final | 57 |
| TCO Issued | tco issued | Final | 1 |
| Issued (Construction) | issued (construction) | Active | 92 |
| Pending (Under Review) | pending (under review) | In Review | 39 |
| Approved/Not Issued | approved/not issued | In Review | 19 |
| NOV Sent | nov sent | In Review | 4 |
| 120 Notice Sent | 120 notice sent | In Review | 1 |
| Expired | expired | Inactive | 68 |

No missing values; 0 mismatches vs `ProjectStatus`. `Approved/Not Issued` correctly stays In Review (approved but not yet issued). CO/TCO Issued correctly stay Final rather than Active.

### FILE_DATE

Fully populated (0 missing). Every row’s FILE_DATE matches `DateCreated` at calendar-day resolution. No FILLED or FIXED changes.

### PERMIT_DATE

Universally missing (2,001 / 2,001). `DateIssued` is `0001-01-01T00:00:00` on every row (MGO / .NET empty-date sentinel). No alternate issuance or approval timestamp appears in DATA (`ScheduledDueDate`, power-request dates, and nested structures are empty or absent). Active (92) and Final (1,778) rows therefore remain without PERMIT_DATE.

### FINAL_DATE

Universally missing (2,001 / 2,001). `DateUpdated` is also always the .NET sentinel; no finaled / completion / certificate-of-occupancy field exists (including for CO Issued / TCO Issued). Final rows (1,778) cannot be filled. No spurious FINAL_DATE values were present on non-Final rows.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 0 | 0 | 0 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 0 | 0 | 2,001 → 2,001 |
| FINAL_DATE | 0 | 0 | 2,001 → 2,001 |

STATUS_NORMALIZED after repair: Final 1,778; Active 92; Inactive 68; In Review 63.

After repair, by status:

- **FILE_DATE:** 100% for all statuses
- **PERMIT_DATE:** Active 0/92 (0%), Final 0/1,778 (0%)
- **FINAL_DATE:** Final 0/1,778 (0%); non-Final remain empty

Date-order violations after repair: none (no PERMIT_DATE / FINAL_DATE pairs to check).

## Not repairable

- All Active/Final rows lack a real `DateIssued` → PERMIT_DATE stays missing.
- All Final rows lack a finaling/completion timestamp → FINAL_DATE stays missing.
- The repair function still applies the MGO mappings so future rows with real `DateIssued` values (or new `ProjectStatus` strings) can be corrected when present.

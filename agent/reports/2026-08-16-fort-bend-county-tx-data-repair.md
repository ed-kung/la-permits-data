# Fort Bend County (TX) data repair

**Summary:** Fort Bend County was the first TX jurisdiction in `permits_tx_sample.parquet` without a repair script. All 2,000 rows are MyGovernmentOnline (MGO) project payloads (`mgo_ppm` 1,999; `mgo_base` 1). STATUS_NORMALIZED and FILE_DATE are already correct vs DATA (`ProjectStatus` / `DateCreated`). PERMIT_DATE and FINAL_DATE remain universally missing because `DateIssued` / `DateUpdated` are the .NET sentinel `0001-01-01` and no other issuance or finaling timestamps exist in DATA. The repair script encodes the MGO mappings for future rows with real dates.

## Scope

- Input: `MY_DATA_PATH/processed_data/permits_tx_sample.parquet`
- Jurisdiction: Fort Bend County, TX (first pair lacking `agent/scripts/{state}/data_repair_{state}_{city}.py` after Missouri City / Baytown in the sample order)
- Script: `agent/scripts/tx/data_repair_tx_fort_bend_county.py`
- Artifact: `AGENT_DATA_PATH/repaired/permits_tx_fort_bend_county_repaired.parquet`

## DATA schema

Flat MGO project object. Nearly all rows include `PaymentProcessorModule` = `MGO`; 1 row omits that key only:

| INFERRED_SCHEMA | n |
| --- | ---: |
| mgo_ppm | 1,999 |
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
| Permit Issued | permit issued | Active | 1,431 |
| Closed/Complete | closed/complete | Final | 478 |
| Pending (Under Review) | pending (under review) | In Review | 80 |
| Project Withdrawn/Canceled | project withdrawn/canceled | Inactive | 7 |
| Expired | expired | Inactive | 4 |

No missing STATUS_NORMALIZED values. Every row’s normalized status matches the expected mapping from `ProjectStatus` (0 FILLED, 0 FIXED). `ProjectStatusIsPermit` is False for Pending (Under Review) and Project Withdrawn/Canceled; status text still drives normalization.

### FILE_DATE

Fully populated (0 missing). Every row’s FILE_DATE matches `DateCreated` at calendar-day resolution (range 2015-05-14 to 2025-10-01). No FILLED or FIXED changes.

### PERMIT_DATE

Universally missing (2,000 / 2,000). `DateIssued` is `0001-01-01T00:00:00` on every row (MGO / .NET empty-date sentinel). No alternate issuance or approval timestamp appears in DATA (`ScheduledDueDate` is null; nested document lists are empty). Active (1,431) and Final (478) rows therefore remain without PERMIT_DATE.

### FINAL_DATE

Universally missing (2,000 / 2,000). `DateUpdated` is also always the .NET sentinel; no finaled / completion field exists. Final rows (478) cannot be filled. No spurious FINAL_DATE values were present on non-Final rows.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 0 | 0 | 0 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 0 | 0 | 2,000 → 2,000 |
| FINAL_DATE | 0 | 0 | 2,000 → 2,000 |

STATUS_NORMALIZED after repair unchanged: Active 1,431; Final 478; In Review 80; Inactive 11.

After repair, by status:

- **FILE_DATE:** 100% for all statuses
- **PERMIT_DATE:** Active 0/1,431 (0%), Final 0/478 (0%)
- **FINAL_DATE:** Final 0/478 (0%); non-Final remain empty

Date-order violations after repair: none (no PERMIT_DATE / FINAL_DATE pairs exist).

## Not repairable

- All Active/Final rows lack a real `DateIssued` → PERMIT_DATE stays missing.
- All Final rows lack a finaling/completion timestamp → FINAL_DATE stays missing.
- The repair function still applies the MGO mappings so future rows with real `DateIssued` values (or new `ProjectStatus` strings) can be corrected when present.

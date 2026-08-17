# Bulverde (TX) data repair

**Summary:** Bulverde was the first TX jurisdiction in `permits_tx_sample.parquet` without a repair script. All 2,000 rows are MyGovernmentOnline (MGO) project payloads (`mgo_ppm` 1,985; `mgo_base` 15). The only correctable issue is 38 missing `STATUS_NORMALIZED` values for `Closed (Completed)`, which are filled as Final. FILE_DATE already matches `DateCreated` 1:1. PERMIT_DATE and FINAL_DATE remain universally missing because `DateIssued` / `DateUpdated` are the .NET sentinel `0001-01-01` and no other issuance or finaling timestamps exist in DATA.

## Scope

- Input: `MY_DATA_PATH/processed_data/permits_tx_sample.parquet`
- Jurisdiction: Bulverde, TX (first pair lacking `agent/scripts/{state}/data_repair_{state}_{city}.py` after Buda)
- Script: `agent/scripts/tx/data_repair_tx_bulverde.py`
- Artifact: `AGENT_DATA_PATH/repaired/permits_tx_bulverde_repaired.parquet`

## DATA schema

Flat MGO project object. Most rows include `PaymentProcessorModule` = `MGO`; 15 rows omit that key only:

| INFERRED_SCHEMA | n |
| --- | ---: |
| mgo_ppm | 1,985 |
| mgo_base | 15 |

Canonical source fields:

| Target field | Primary source | Fallback |
| --- | --- | --- |
| STATUS_NORMALIZED | `ProjectStatus` | heuristic keyword map |
| FILE_DATE | `DateCreated` | — |
| PERMIT_DATE | `DateIssued` (non-sentinel only) | — |
| FINAL_DATE | — (none available) | — |

## Field assessment

### STATUS_NORMALIZED

| ProjectStatus | STATUS_ORIGINAL | STATUS_NORMALIZED (before) | n |
| --- | --- | --- | ---: |
| Project Closed/Complete | project closed/complete | Final | 914 |
| Closed (Completed) | closed (completed) | *(missing)* | 38 |
| Permit Issued | permit issued | Active | 634 |
| Issued | issued | Active | 106 |
| Pending (Under Review) | pending (under review) | In Review | 204 |
| In Review | in review | In Review | 63 |
| Pending | pending | In Review | 23 |
| Awaiting Payment | awaiting payment | In Review | 14 |
| Withdrawn | withdrawn | Inactive | 4 |

Cause of the 38 missing values: upstream normalization mapped `project closed/complete` → Final but did not recognize the near-synonym `closed (completed)` / `Closed (Completed)`. Repair fills all 38 as Final. No other mismatches vs `ProjectStatus`. `ProjectStatusIsPermit` is True for every status except Withdrawn (False); status text drives normalization.

### FILE_DATE

Fully populated (0 missing). Every row’s FILE_DATE matches `DateCreated` at calendar-day resolution. No FILLED or FIXED changes.

### PERMIT_DATE

Universally missing (2,000 / 2,000). `DateIssued` is `0001-01-01T00:00:00` on every row (MGO / .NET empty-date sentinel). No alternate issuance or approval timestamp appears in DATA (`ScheduledDueDate`, power-request dates, and nested structures are empty or absent). Active (740) and Final (952 after repair) rows therefore remain without PERMIT_DATE.

### FINAL_DATE

Universally missing (2,000 / 2,000). `DateUpdated` is also always the .NET sentinel; no finaled / completion field exists. Final rows (952) cannot be filled. No spurious FINAL_DATE values were present on non-Final rows.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 38 | 0 | 38 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 0 | 0 | 2,000 → 2,000 |
| FINAL_DATE | 0 | 0 | 2,000 → 2,000 |

STATUS_NORMALIZED after repair: Final 952; Active 740; In Review 304; Inactive 4.

STATUS change detail: `closed (completed)` / missing → Final (38 FILLED).

After repair, by status:

- **FILE_DATE:** 100% for all statuses
- **PERMIT_DATE:** Active 0/740 (0%), Final 0/952 (0%)
- **FINAL_DATE:** Final 0/952 (0%); non-Final remain empty

Date-order violations after repair: none (no PERMIT_DATE / FINAL_DATE pairs exist).

## Not repairable

- All Active/Final rows lack a real `DateIssued` → PERMIT_DATE stays missing.
- All Final rows lack a finaling/completion timestamp → FINAL_DATE stays missing.
- The repair function still applies the MGO mappings so future rows with real `DateIssued` values (or new `ProjectStatus` strings) can be corrected when present.

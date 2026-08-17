# Burnet (TX) data repair

**Summary:** Burnet was the first TX jurisdiction in `permits_tx_sample.parquet` without a repair script. All 2,000 rows are MyGovernmentOnline (MGO) project payloads (`mgo_ppm`). FILE_DATE already matches `DateCreated` 1:1. One STATUS_NORMALIZED value was stale (Active while `ProjectStatus` is Closed) and was FIXED to Final. PERMIT_DATE and FINAL_DATE remain universally missing because `DateIssued` / `DateUpdated` are the .NET sentinel `0001-01-01` and no other issuance or finaling timestamps exist in DATA.

## Scope

- Input: `MY_DATA_PATH/processed_data/permits_tx_sample.parquet`
- Jurisdiction: Burnet, TX (first pair lacking `agent/scripts/{state}/data_repair_{state}_{city}.py`)
- Script: `agent/scripts/tx/data_repair_tx_burnet.py`
- Artifact: `AGENT_DATA_PATH/repaired/permits_tx_burnet_repaired.parquet`

## DATA schema

Flat MGO project object. Every sample row includes `PaymentProcessorModule` = `MGO`:

| INFERRED_SCHEMA | n |
| --- | ---: |
| mgo_ppm | 2,000 |

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
| Closed | closed | Final | 1,411 |
| Closed | permit issued | Active | 1 |
| Permit Issued | permit issued | Active | 362 |
| Pending (Under Review) | pending (under review) | In Review | 189 |
| Withdrawn | withdrawn | Inactive | 37 |

No missing STATUS_NORMALIZED values. One mismatch: permit `2023-2828` has `ProjectStatus` = Closed (ID 1498) but retained STATUS_ORIGINAL `permit issued` / STATUS_NORMALIZED Active. Repair FIXED that row to Final. `ProjectStatusIsPermit` is True for Closed / Permit Issued / Pending and False for Withdrawn; status text (not the boolean) drives normalization.

### FILE_DATE

Fully populated (0 missing). Every row’s FILE_DATE matches `DateCreated` at calendar-day resolution. No FILLED or FIXED changes. (Fourteen `DateCreated` strings lack fractional seconds; batch Series parsing can coerce them to NaT, but per-value parsing used by the repair function succeeds and confirms day equality.)

### PERMIT_DATE

Universally missing (2,000 / 2,000). `DateIssued` is `0001-01-01T00:00:00` on every row (MGO / .NET empty-date sentinel). No alternate issuance or approval timestamp appears in DATA (`ScheduledDueDate`, power-request dates, inspections, and document lists are empty or absent). Active and Final rows therefore remain without PERMIT_DATE.

### FINAL_DATE

Universally missing (2,000 / 2,000). `DateUpdated` is also always the .NET sentinel; no finaled / completion / certificate-of-occupancy field exists. Final rows cannot be filled. No spurious FINAL_DATE values were present on non-Final rows.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 0 | 1 | 0 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 0 | 0 | 2,000 → 2,000 |
| FINAL_DATE | 0 | 0 | 2,000 → 2,000 |

STATUS_NORMALIZED after repair: Final 1,412; Active 362; In Review 189; Inactive 37.

After repair, by status:

- **FILE_DATE:** 100% for all statuses
- **PERMIT_DATE:** Active 0/362 (0%), Final 0/1,412 (0%)
- **FINAL_DATE:** Final 0/1,412 (0%); non-Final remain empty

## Not repairable

- All Active/Final rows lack a real `DateIssued` → PERMIT_DATE stays missing.
- All Final rows lack a finaling/completion timestamp → FINAL_DATE stays missing.
- The repair function still applies the MGO mappings so future rows with real `DateIssued` values (or new `ProjectStatus` strings) can be corrected when present.

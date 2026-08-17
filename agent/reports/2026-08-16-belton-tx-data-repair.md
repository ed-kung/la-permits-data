# Belton (TX) data repair

**Summary:** Belton was the first TX jurisdiction in `permits_tx_sample.parquet` without a repair script. All 2,000 rows are MyGovernmentOnline (MGO) project payloads (`mgo_ppm` / `mgo_base`). FILE_DATE already matches `DateCreated` 1:1. The main correctness issue is STATUS_NORMALIZED: 165 `No Applicant Response - Closed` rows were labeled In Review and are FIXED to Inactive. PERMIT_DATE and FINAL_DATE remain universally missing because `DateIssued` / `DateUpdated` are the .NET sentinel `0001-01-01` and no other issuance or finaling timestamps exist in DATA.

## Scope

- Input: `MY_DATA_PATH/processed_data/permits_tx_sample.parquet`
- Jurisdiction: Belton, TX (first pair lacking `agent/scripts/{state}/data_repair_{state}_{city}.py`)
- Script: `agent/scripts/tx/data_repair_tx_belton.py`
- Artifact: `AGENT_DATA_PATH/repaired/permits_tx_belton_repaired.parquet`

## DATA schema

Flat MGO project object with shared date/status keys. Variants differ only by presence of `PaymentProcessorModule`:

| INFERRED_SCHEMA | n |
| --- | ---: |
| mgo_ppm | 1,991 |
| mgo_base | 9 |

Canonical source fields:

| Target field | Primary source | Fallback |
| --- | --- | --- |
| STATUS_NORMALIZED | `ProjectStatus` | heuristic keyword map |
| FILE_DATE | `DateCreated` | — |
| PERMIT_DATE | `DateIssued` (non-sentinel only) | — |
| FINAL_DATE | — (none available) | — |

## Field assessment

### STATUS_NORMALIZED

| ProjectStatus | STATUS_ORIGINAL | Before | After | n |
| --- | --- | --- | --- | ---: |
| Project Closed/Complete | project closed/complete | Final | Final | 1,020 |
| Permit Issued | permit issued | Active | Active | 444 |
| Pending (Under Review) | pending (under review) | In Review | In Review | 124 |
| No Inspections - Permit expired | no inspections - permit expired | Inactive | Inactive | 241 |
| Withdrawn | withdrawn | Inactive | Inactive | 6 |
| No Applicant Response - Closed | no applicant response - closed | In Review | **Inactive** | 165 |

No missing STATUS_NORMALIZED values. The 165 non-response closures were incorrectly left In Review; `ProjectStatusIsPermit` is False for these rows (same pattern as expired / withdrawn), and the portal status is a terminal non-completion closure. Repair FIXED them to Inactive.

### FILE_DATE

Fully populated (0 missing). Every row’s FILE_DATE matches `DateCreated` at calendar-day resolution. No FILLED or FIXED changes.

### PERMIT_DATE

Universally missing (2,000 / 2,000). `DateIssued` is `0001-01-01T00:00:00` on every row (MGO / .NET empty-date sentinel). Nested lists and alternate date fields (`ScheduledDueDate`, power-request dates) are empty. Active (444) and Final (1,020) rows therefore remain without PERMIT_DATE.

### FINAL_DATE

Universally missing (2,000 / 2,000). `DateUpdated` is also always the .NET sentinel; no finaled / completion / certificate-of-occupancy field exists. Final rows (1,020) cannot be filled. No spurious FINAL_DATE values were present on non-Final rows.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 0 | 165 | 0 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 0 | 0 | 2,000 → 2,000 |
| FINAL_DATE | 0 | 0 | 2,000 → 2,000 |

STATUS_NORMALIZED after repair: Final 1,020; Active 444; Inactive 412; In Review 124.

After repair, by status:

- **FILE_DATE:** 100% for all statuses
- **PERMIT_DATE:** Active 0/444 (0%), Final 0/1,020 (0%)
- **FINAL_DATE:** Final 0/1,020 (0%); non-Final remain empty

## Not repairable

- All Active/Final rows lack a real `DateIssued` → PERMIT_DATE stays missing.
- All Final rows lack a finaling/completion timestamp → FINAL_DATE stays missing.
- The repair function still applies the MGO mappings so future rows with real `DateIssued` values (or new `ProjectStatus` strings) can be corrected when present.

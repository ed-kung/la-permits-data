# Georgetown (TX) data repair

**Summary:** Georgetown was the first TX jurisdiction in `permits_tx_sample.parquet` without a repair script (after Waco). All 2,001 rows are MyGovernmentOnline (MGO) project payloads (`mgo_ppm` 1,998; `mgo_base` 3). STATUS_NORMALIZED and FILE_DATE are already correct vs DATA (`ProjectStatus` / `DateCreated`). PERMIT_DATE and FINAL_DATE remain universally missing because `DateIssued` / `DateUpdated` are the .NET sentinel `0001-01-01` and no other issuance or finaling timestamps exist in DATA. The repair script encodes the Georgetown MGO mappings for future rows with real dates.

## Scope

- Input: `MY_DATA_PATH/processed_data/permits_tx_sample.parquet`
- Jurisdiction: Georgetown, TX (first pair lacking `agent/scripts/{state}/data_repair_{state}_{city}.py`)
- Script: `agent/scripts/tx/data_repair_tx_georgetown.py`
- Artifact: `AGENT_DATA_PATH/repaired/permits_tx_georgetown_repaired.parquet`

## DATA schema

Flat MGO project object. Nearly all rows include `PaymentProcessorModule` = `MGO`; 3 rows omit that key only:

| INFERRED_SCHEMA | n |
| --- | ---: |
| mgo_ppm | 1,998 |
| mgo_base | 3 |

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
| Closed | closed | Final | 1,319 |
| Cond CO Issued | cond co issued | Final | 2 |
| Permit Issued | permit issued | Active | 245 |
| Ready to Issue | ready to issue | In Review | 40 |
| In Review | in review | In Review | 32 |
| Awaiting Revisions | awaiting revisions | In Review | 15 |
| Expired | expired | Inactive | 347 |
| Denied | denied | Inactive | 1 |

No missing STATUS_NORMALIZED values. Every row’s normalized status matches the expected mapping from `ProjectStatus` (0 FILLED, 0 FIXED). `STATUS_ORIGINAL` is the lowercased `ProjectStatus` text. `ProjectStatusIsPermit` is False for In Review, Expired, Denied, and Cond CO Issued; status text still drives normalization.

### FILE_DATE

Fully populated (0 missing). Every row’s FILE_DATE matches `DateCreated` at calendar-day resolution (range 2012-07-03 to 2025-10-01). No FILLED or FIXED changes.

### PERMIT_DATE

Universally missing (2,001 / 2,001). `DateIssued` is `0001-01-01T00:00:00` on every row (MGO / .NET empty-date sentinel). No alternate issuance or approval timestamp appears in DATA (`ScheduledDueDate`, `RequestPermanentPowerDate`, and `RequestTemporaryPowerDate` are null). Active (245) and Final (1,321) rows therefore remain without PERMIT_DATE.

### FINAL_DATE

Universally missing (2,001 / 2,001). `DateUpdated` is also always the .NET sentinel; no finaled / completion field exists. Final rows (1,321) cannot be filled. No spurious FINAL_DATE values were present on non-Final rows.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 0 | 0 | 0 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 0 | 0 | 2,001 → 2,001 |
| FINAL_DATE | 0 | 0 | 2,001 → 2,001 |

STATUS_NORMALIZED after repair unchanged: Final 1,321; Inactive 348; Active 245; In Review 87.

After repair, by status:

- **FILE_DATE:** 100% for all statuses
- **PERMIT_DATE:** Active 0/245 (0%), Final 0/1,321 (0%)
- **FINAL_DATE:** Final 0/1,321 (0%); non-Final remain empty

Date-order violations after repair: none (no PERMIT_DATE / FINAL_DATE pairs exist).

## Not repairable

- All Active/Final rows lack a real `DateIssued` → PERMIT_DATE stays missing.
- All Final rows lack a finaling/completion timestamp → FINAL_DATE stays missing.
- The repair function still applies the MGO mappings (including Georgetown-specific statuses `Cond CO Issued`, `Ready to Issue`, and `Awaiting Revisions`) so future rows with real `DateIssued` values can be corrected when present.

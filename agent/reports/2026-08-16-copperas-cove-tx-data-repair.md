# Copperas Cove (TX) data repair

**Summary:** Copperas Cove was the first TX jurisdiction in `permits_tx_sample.parquet` without a repair script (2,000 rows). DATA is a MyGovernmentOnline (MGO) project payload (`mgo_ppm` / `mgo_base`). STATUS_NORMALIZED and FILE_DATE were already complete and correct vs `ProjectStatus` / `DateCreated`. PERMIT_DATE and FINAL_DATE remain universally missing because `DateIssued` / `DateUpdated` are the .NET sentinel `0001-01-01` on every row and no alternate issuance or finaling timestamps exist in DATA. The repair script applies the MGO mappings for future rows with real dates or new statuses; on this sample it makes zero FILLED/FIXED changes.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_tx_sample.parquet` and walked unique `(JURISDICTION, STATE)` pairs in appearance order. Existing TX scripts covered through Chambers County / Missouri City and peers; **Copperas Cove** was the first missing pair → `agent/scripts/tx/data_repair_tx_copperas_cove.py`.

## DATA schema

All 2,000 rows parse. Flat MGO project object; two top-level key-set variants (same repair fields):

| INFERRED_SCHEMA | n |
| --- | ---: |
| `mgo_ppm` | 1,990 |
| `mgo_base` | 10 |

Canonical sources:

| Target field | Primary source | Notes |
| --- | --- | --- |
| STATUS_NORMALIZED | `ProjectStatus` | heuristic fallback for unseen strings |
| FILE_DATE | `DateCreated` | — |
| PERMIT_DATE | `DateIssued` (non-sentinel only) | always sentinel in sample |
| FINAL_DATE | — | none available |

`ScheduledDueDate`, `RequestPermanentPowerDate`, and `RequestTemporaryPowerDate` are null/empty on all sample rows. `DateUpdated` is always the .NET sentinel.

## Field assessment

### STATUS_NORMALIZED

Before: Final 1,254 / Active 597 / In Review 149 / missing 0 / Inactive 0.

Existing mappings matched `ProjectStatus` 1:1 (via `STATUS_ORIGINAL` lowercasing):

| ProjectStatus | STATUS_NORMALIZED | n |
| --- | --- | ---: |
| Project Closed/Complete | Final | 1,254 |
| Permit Issued | Active | 597 |
| Pending Payment | In Review | 90 |
| Pending (Under Review) | In Review | 59 |

No missing or incorrect STATUS_NORMALIZED values. After repair: unchanged.

### FILE_DATE

Already 2,000 / 2,000 populated; all match `DateCreated` at calendar-day resolution when parsed per-row (a few `DateCreated` strings lack fractional seconds; vectorized `to_datetime` can drop those, but the repair helper parses row-wise). No FILLED/FIXED changes.

### PERMIT_DATE

Universally missing (2,000 / 2,000). `DateIssued` is `0001-01-01T00:00:00` on every row. No alternate issuance timestamp exists. Active (597) and Final (1,254) rows therefore remain without PERMIT_DATE.

### FINAL_DATE

Universally missing (2,000 / 2,000). `DateUpdated` is also always the .NET sentinel; no finaled/completion/CO field exists. Final rows (1,254) cannot be filled. No spurious FINAL_DATE values were present on non-Final rows.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 0 | 0 | 0 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 0 | 0 | 2,000 → 2,000 |
| FINAL_DATE | 0 | 0 | 2,000 → 2,000 |

After repair, by status:

- **FILE_DATE:** 100% for all statuses
- **PERMIT_DATE:** Active 0/597 (0%); Final 0/1,254 (0%)
- **FINAL_DATE:** Final 0/1,254 (0%); non-Final remain empty

Date-order violations after repair: none (no PERMIT_DATE / FINAL_DATE pairs to check).

## Not repairable

- All Active/Final rows lack a real `DateIssued` → PERMIT_DATE stays missing.
- All Final rows lack a finaling/completion timestamp → FINAL_DATE stays missing.
- The repair function still applies the MGO mappings so future rows with real `DateIssued` values (or new `ProjectStatus` strings such as Expired/Withdrawn) can be corrected when present.

## Artifacts

- Script: `agent/scripts/tx/data_repair_tx_copperas_cove.py`
- Repaired sample: `AGENT_DATA_PATH/repaired/permits_tx_copperas_cove_repaired.parquet`

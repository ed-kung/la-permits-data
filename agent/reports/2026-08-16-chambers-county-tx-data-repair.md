# Chambers County (TX) data repair

**Summary:** Chambers County was the first TX jurisdiction in `permits_tx_sample.parquet` without a repair script (2,000 rows). DATA is a MyGovernmentOnline (MGO) project payload (`mgo_ppm` / `mgo_base`). STATUS_NORMALIZED had 133 nulls for uncommon waiting/schedule `ProjectStatus` values (now filled as In Review). FILE_DATE was already complete and matched `DateCreated`. PERMIT_DATE and FINAL_DATE remain universally missing because `DateIssued` / `DateUpdated` are the .NET sentinel `0001-01-01` on every row and no alternate issuance or finaling timestamps exist in DATA.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_tx_sample.parquet` and walked unique `(JURISDICTION, STATE)` pairs in appearance order. Existing TX scripts covered through Cedar Park; **Chambers County** was the first missing pair → `agent/scripts/tx/data_repair_tx_chambers_county.py`.

## DATA schema

All 2,000 rows parse. Flat MGO project object; two top-level key-set variants (same repair fields):

| INFERRED_SCHEMA | n |
| --- | ---: |
| `mgo_ppm` | 1,991 |
| `mgo_base` | 9 |

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

Before: Final 1,338 / In Review 369 / Active 140 / missing 133 / Inactive 20.

Existing non-null mappings matched `ProjectStatus` 1:1:

| ProjectStatus | STATUS_NORMALIZED | n |
| --- | --- | ---: |
| Project Closed/Complete | Final | 1,338 |
| Customer Request For Power | In Review | 213 |
| Permit Issued | Active | 107 |
| Pending (Under Review) | In Review | 85 |
| Waiting for Payment | In Review | 68 |
| Waiting for Drainage Certificate | Active | 17 |
| Permit Expired | Inactive | 16 |
| Waiting for Final Elevation Certificate | Active | 8 |
| Waiting for Elevation Certificate | Active | 7 |
| Withdrawn | Inactive | 4 |
| Plan Approval | In Review | 2 |
| Waiting for Certificate of Compliance | Active | 1 |
| Master Open | In Review | 1 |

The 133 nulls were unmapped waiting/schedule statuses (STATUS_ORIGINAL already held the raw text). Filled as In Review (inspection/approval/schedule gates distinct from certificate-collection waits, which the upstream normalizer already treated as Active):

| ProjectStatus | n | Repair |
| --- | ---: | --- |
| Waiting for Fire Inspection | 56 | In Review |
| Waiting for Septic Inspection | 48 | In Review |
| Waiting for Drainage Approval | 10 | In Review |
| Waiting for Septic Permit | 9 | In Review |
| Schedule Food Inspection | 6 | In Review |
| Waiting for Revisions | 3 | In Review |
| Schedule Fire Marshal Inspection | 1 | In Review |

After repair: Final 1,338 / In Review 502 / Active 140 / Inactive 20 / missing 0. No FIXED status changes.

### FILE_DATE

Already 2,000 / 2,000 populated; all match `DateCreated` at calendar-day resolution when parsed per-row (a few `DateCreated` strings lack fractional seconds; vectorized `to_datetime` can drop those, but the repair helper parses row-wise). No FILLED/FIXED changes.

### PERMIT_DATE

Universally missing (2,000 / 2,000). `DateIssued` is `0001-01-01T00:00:00` on every row. No alternate issuance timestamp exists. Active (140) and Final (1,338) rows therefore remain without PERMIT_DATE.

### FINAL_DATE

Universally missing (2,000 / 2,000). `DateUpdated` is also always the .NET sentinel; no finaled/completion/CO field exists. Final rows (1,338) cannot be filled. No spurious FINAL_DATE values were present on non-Final rows.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 133 | 0 | 133 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 0 | 0 | 2,000 → 2,000 |
| FINAL_DATE | 0 | 0 | 2,000 → 2,000 |

After repair, by status:

- **FILE_DATE:** 100% for all statuses
- **PERMIT_DATE:** Active 0/140 (0%); Final 0/1,338 (0%)
- **FINAL_DATE:** Final 0/1,338 (0%); non-Final remain empty

Date-order violations after repair: none (no PERMIT_DATE / FINAL_DATE pairs to check).

## Not repairable

- All Active/Final rows lack a real `DateIssued` → PERMIT_DATE stays missing.
- All Final rows lack a finaling/completion timestamp → FINAL_DATE stays missing.
- The repair function still applies the MGO mappings so future rows with real `DateIssued` values (or new `ProjectStatus` strings) can be corrected when present.

## Artifacts

- Script: `agent/scripts/tx/data_repair_tx_chambers_county.py`
- Repaired sample: `AGENT_DATA_PATH/repaired/permits_tx_chambers_county_repaired.parquet`

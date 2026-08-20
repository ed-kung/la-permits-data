# Olmos Park (TX) data repair

**Summary:** Olmos Park was the first `(JURISDICTION, STATE)` pair in `permits_tx_sample.parquet` without an existing repair script. Its DATA column is a flat MyGovernmentOnline (MGO) project payload (same family as Jonestown / Kendall County). Of 2,000 sample rows, STATUS_NORMALIZED and FILE_DATE are already correct against stripped `ProjectStatus` / `DateCreated`. PERMIT_DATE and FINAL_DATE remain universally missing — `DateIssued` and `DateUpdated` are the .NET sentinel `0001-01-01` on every row, and no other issuance or finaling timestamp exists.

## Jurisdiction selection

Went down `(JURISDICTION, STATE)` pairs in sample order. Existing TX scripts covered through Williamson County and earlier cities; **Olmos Park, TX** was the first missing (`agent/scripts/tx/data_repair_tx_olmos_park.py`). Remaining without scripts at selection time: Rollingwood, Shavano Park, Sunset Valley, Uhland, Universal City, West Lake Hills, Windcrest.

## DATA schema

Two top-level key-set variants (all include `PlacardFilename`):

| INFERRED_SCHEMA | n | Notes |
| --- | ---: | --- |
| mgo_ppm | 1,995 | Flat MGO payload with `PaymentProcessorModule` = `MGO` |
| mgo_base | 5 | Same fields without `PaymentProcessorModule` |

Canonical source fields:

| Target field | Primary source | Fallback |
| --- | --- | --- |
| STATUS_NORMALIZED | `ProjectStatus` (whitespace-stripped) | — |
| FILE_DATE | `DateCreated` | — |
| PERMIT_DATE | `DateIssued` (when not sentinel) | — (always sentinel in sample) |
| FINAL_DATE | — (none available) | — |

`ProjectStatus` values observed: Project Closed/Complete (1,203), Permit Issued with trailing space (657), Pending (Under Review) (138), Withdrawn (2).

## Findings by field

### STATUS_NORMALIZED

Before: Final 1,203, Active 657, In Review 138, Inactive 2. No missing values.

`ProjectStatus` × STATUS_NORMALIZED is exact 1:1 after stripping trailing whitespace on `Permit Issued `:

| ProjectStatus (stripped) | STATUS_ORIGINAL | STATUS_NORMALIZED | n |
| --- | --- | --- | ---: |
| Project Closed/Complete | project closed/complete | Final | 1,203 |
| Permit Issued | permit issued | Active | 657 |
| Pending (Under Review) | pending (under review) | In Review | 138 |
| Withdrawn | withdrawn | Inactive | 2 |

No incorrect or missing statuses. Repair strips portal whitespace and remaps for future variants, but makes **0 FILLED / 0 FIXED** changes on this sample.

### FILE_DATE

Fully populated before repair (0 missing). Every row matches `DateCreated` at calendar-day resolution (years 2014–2025). Ideal: populated for all records — **achieved (100%)**. **FILLED 0, FIXED 0.**

### PERMIT_DATE

Universally missing (2,000 / 2,000) before and after. `DateIssued` is `0001-01-01T00:00:00` on every row. Nested collections are empty; `ScheduledDue` is blank. No safe issuance proxy in DATA.

Ideal: populated for Active and Final — **not achievable from DATA** (0/657 Active, 0/1,203 Final).

### FINAL_DATE

Universally missing (2,000 / 2,000). `DateUpdated` is also the .NET sentinel; no completion / CO / signoff timestamp exists.

Ideal: populated for Final — **not achievable from DATA** (0/1,203).

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 0 | 0 | 0 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 0 | 0 | 2,000 → 2,000 |
| FINAL_DATE | 0 | 0 | 2,000 → 2,000 |

Post-repair coverage:

- Active: FILE 100%, PERMIT 0%, FINAL 0%
- Final: FILE 100%, PERMIT 0%, FINAL 0%
- In Review: FILE 100%, PERMIT 0%, FINAL 0%
- Inactive: FILE 100%, PERMIT 0%, FINAL 0%

Date-order violations: none (no PERMIT/FINAL dates to compare).

## Artifacts

- Script: `agent/scripts/tx/data_repair_tx_olmos_park.py` (`data_repair`)
- Repaired sample: `$AGENT_DATA_PATH/repaired/permits_tx_olmos_park_repaired.parquet`

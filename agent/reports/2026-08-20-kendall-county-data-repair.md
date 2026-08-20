# Kendall County (TX) data repair

**Summary:** Kendall County was the first `(JURISDICTION, STATE)` pair in `permits_tx_sample.parquet` without an existing repair script. Its DATA column is a flat MyGovernmentOnline (MGO) project payload (same family as Hays County). Of 2,000 sample rows, STATUS_NORMALIZED and FILE_DATE are already correct against `ProjectStatus` / `DateCreated`. PERMIT_DATE and FINAL_DATE remain universally missing — `DateIssued` and `DateUpdated` are the .NET sentinel `0001-01-01` on every row, and no other issuance or finaling timestamp exists.

## Jurisdiction selection

Went down `(JURISDICTION, STATE)` pairs in sample order. Existing TX scripts covered through Jonestown / Jarrell / etc.; **Kendall County, TX** was the first missing (`agent/scripts/tx/data_repair_tx_kendall_county.py`).

## DATA schema

Every record shares the same 89 top-level keys, including `PaymentProcessorModule` = `MGO`. Recorded in `INFERRED_SCHEMA`:

| INFERRED_SCHEMA | n | Notes |
| --- | ---: | --- |
| mgo_ppm | 2,000 | Flat MGO project payload with `PaymentProcessorModule` |

Canonical source fields:

| Target field | Primary source | Fallback |
| --- | --- | --- |
| STATUS_NORMALIZED | `ProjectStatus` | — |
| FILE_DATE | `DateCreated` | — |
| PERMIT_DATE | `DateIssued` (when not sentinel) | — (always sentinel in sample) |
| FINAL_DATE | — (none available) | — |

`ProjectStatus` values observed: Pending (901), Active (700), Permitted (334), Inactive (36), Closed (20), Expired (9).

## Findings by field

### STATUS_NORMALIZED

Before: Active 1,034, In Review 901, Inactive 45, Final 20. No missing values.

`ProjectStatus` × STATUS_NORMALIZED is exact 1:1:

| ProjectStatus | STATUS_ORIGINAL | STATUS_NORMALIZED | n |
| --- | --- | --- | ---: |
| Pending | pending | In Review | 901 |
| Active | active | Active | 700 |
| Permitted | permitted | Active | 334 |
| Inactive | inactive | Inactive | 36 |
| Closed | closed | Final | 20 |
| Expired | expired | Inactive | 9 |

No incorrect or missing statuses. Repair is idempotent for future portal variants (Transferred → Inactive, etc.) but makes **0 FILLED / 0 FIXED** changes on this sample.

### FILE_DATE

Fully populated before repair (0 missing). Every row matches `DateCreated` at calendar-day resolution (including 129 rows dated year 2000, which appear to be genuine historical `DateCreated` values, not sentinels). Ideal: populated for all records — **achieved (100%)**. **FILLED 0, FIXED 0.**

### PERMIT_DATE

Universally missing (2,000 / 2,000) before and after. `DateIssued` is `0001-01-01T00:00:00` on every row. Balance / placard / receipt / power-request date fields are empty or null and are not safe issuance proxies.

Ideal: populated for Active and Final — **not achievable from DATA** (0/1,034 Active, 0/20 Final).

### FINAL_DATE

Universally missing (2,000 / 2,000). `DateUpdated` is also the .NET sentinel; `RequestInspections` is a boolean only. No completion / CO / signoff timestamp exists.

Ideal: populated for Final — **not achievable from DATA** (0/20).

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

- Repair script: `agent/scripts/tx/data_repair_tx_kendall_county.py`
- Repaired sample parquet: `$AGENT_DATA_PATH/repaired/permits_tx_kendall_county_repaired.parquet`

# Mont Belvieu (TX) data repair

**Summary:** Mont Belvieu was the first `(JURISDICTION, STATE)` pair in `permits_tx_sample.parquet` without an existing repair script. Its DATA column is a flat MyGovernmentOnline (MGO) / MyPermitNow project payload (same family as Kerrville / Kendall County). Of 2,000 sample rows, STATUS_NORMALIZED and FILE_DATE are already correct against `ProjectStatus` and `DateCreated`. PERMIT_DATE and FINAL_DATE remain universally missing — `DateIssued` / `DateUpdated` are always the .NET sentinel `0001-01-01`, and no completion/sign-off timestamp exists in DATA.

## Jurisdiction selection

Went down `(JURISDICTION, STATE)` pairs in sample order. Existing TX scripts covered through Seagoville; **Mont Belvieu, TX** was the first missing (`agent/scripts/tx/data_repair_tx_mont_belvieu.py`).

## DATA schema

Every record is a JSON string with the same 89 top-level keys, including `PaymentProcessorModule` = `MGO`. Content variant recorded in `INFERRED_SCHEMA`:

| INFERRED_SCHEMA | n | Notes |
| --- | ---: | --- |
| mgo_ppm | 2,000 | Flat MGO project payload with `PaymentProcessorModule` |

Canonical source fields:

| Target field | Primary source | Fallback |
| --- | --- | --- |
| STATUS_NORMALIZED | `ProjectStatus` | heuristic on status text |
| FILE_DATE | `DateCreated` | — |
| PERMIT_DATE | `DateIssued` (non-sentinel) | — |
| FINAL_DATE | — (none available) | — |

## Findings by field

### STATUS_NORMALIZED

Before: Final 1,330, Active 335, In Review 250, Inactive 85. No missing values.

`ProjectStatus` × STATUS_NORMALIZED is **1:1** with no mismatches:

| ProjectStatus | STATUS_NORMALIZED | n |
| --- | --- | ---: |
| Closed/Complete | Final | 1,330 |
| Issued | Active | 335 |
| Pending (Under Review) | In Review | 250 |
| Cancelled/Withdrawn | Inactive | 85 |

`STATUS_ORIGINAL` matches `ProjectStatus` ignoring case. Alternate `ProjectStatusID` values (8932 for 3 Final rows, 8933 for 15 Active rows) share the same status labels as the primary IDs and do not change the mapping.

After: unchanged. **FILLED 0, FIXED 0.**

### FILE_DATE

Fully populated before repair (0 missing). Every row matches `DateCreated` at calendar-day resolution (years 2014–2025). No incorrect values to overwrite.

Ideal: populated for all records — **achieved (100%)**.

### PERMIT_DATE

Universally missing (2,000 / 2,000) before and after. `DateIssued` is the sentinel `0001-01-01T00:00:00` on every sample row, including all Active and Final permits. Nested inspection / document fields (`RequestInspections`, `CustomerUploadedDocuments`) are booleans with no timestamps. No other string fields contain real-looking issuance dates.

Ideal: populated for Active and Final — **not achievable from DATA** (0/335 Active, 0/1,330 Final).

### FINAL_DATE

Universally missing (2,000 / 2,000). `DateUpdated` is also the .NET sentinel on every row. No finaled / completion / CO / sign-off date exists in the payload. The repair clears FINAL_DATE only if a non-Final row somehow carries one (none in sample).

Ideal: populated for Final — **not achievable from DATA** (0/1,330).

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

Date-order violations after repair: none (no PERMIT/FINAL dates present).

## Artifacts

- Repair script: `agent/scripts/tx/data_repair_tx_mont_belvieu.py` (`data_repair`)
- Repaired sample parquet: `$AGENT_DATA_PATH/repaired/permits_tx_mont_belvieu_repaired.parquet`

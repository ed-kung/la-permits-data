# Lake Clarke Shores (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script was **Lake Clarke Shores**. DATA is a flat MyGovernmentOnline (MGO) project payload (`ProjectStatus` / `DateCreated` / `DateIssued`). `STATUS_NORMALIZED` already matched portal status on every row; `FILE_DATE` already matched `DateCreated` on all 510 rows. `DateIssued` and `DateUpdated` are the `.NET` sentinel `0001-01-01` on every row, and no completion/CO date exists, so `PERMIT_DATE` and `FINAL_DATE` remain universally missing. After repair: STATUS fully populated; FILE_DATE 100%; Active/Final PERMIT_DATE 0%; Final FINAL_DATE 0%.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` and walked `(JURISDICTION, STATE)` pairs in sorted order. Lake Clarke Shores was the first pair without `agent/scripts/fl/data_repair_fl_lake_clarke_shores.py`.

## DATA shape

| Schema | n |
| --- | ---: |
| `mgo_ppm` | 510 |

All rows include `PaymentProcessorModule` = `MGO`. Same flat MGO project object as peer cities (Juno Beach, Jupiter Inlet Colony, Sebastian, etc.).

Canonical sources:

| Field | DATA source |
| --- | --- |
| STATUS_NORMALIZED | `ProjectStatus` (whitespace-stripped) |
| FILE_DATE | `DateCreated` |
| PERMIT_DATE | `DateIssued` when not `0001-01-01` (never in sample) |
| FINAL_DATE | *(none — no completion / CO timestamp)* |

`STATUS_ORIGINAL` matches live `ProjectStatus` on all 510 rows (case-normalized).

## Field assessments

### STATUS_NORMALIZED

Before/after: Active 363; In Review 141; Final 6; **0 null**. No Inactive rows in sample.

| ProjectStatus | n | Upstream STATUS_NORMALIZED | Assessment |
| --- | ---: | --- | --- |
| Permit Issued | 363 | Active | Correct |
| Pending (Under Review) | 141 | In Review | Correct |
| Project Closed/Complete | 6 | Final | Correct |

Flags: **0 FILLED, 0 FIXED**.

### FILE_DATE

Missing on 0/510. Calendar day matches `DateCreated` on every row. Flags: **0 FILLED, 0 FIXED**.

### PERMIT_DATE

Missing on all 510 rows (including all 363 Active and 6 Final).

- Sole candidate `DateIssued` is the sentinel `0001-01-01T00:00:00` on every row.
- `DateUpdated` and scheduled/power-request dates are likewise null/sentinel.
- No nested inspection / issuance structures in DATA.
- Copying `FILE_DATE` / `DateCreated` into `PERMIT_DATE` was rejected (same pitfall repaired in peer MGO cities).

**Repair performance:** FILLED 0, FIXED 0; missing 510 → 510. Script will fill from a real `DateIssued` if present in future extracts. Active/Final coverage: 0%.

### FINAL_DATE

Missing on all 510 rows (including all 6 Final). No finaled / completion / CO field exists in the MGO payload; `DateUpdated` is always the `.NET` sentinel. Flags: **0 FILLED, 0 FIXED**. Ideal Final coverage remains 0%.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 0 | 0 | 0 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 0 | 0 | 510 → 510 |
| FINAL_DATE | 0 | 0 | 510 → 510 |

Coverage after repair: FILE_DATE 100% all statuses; Active/Final PERMIT_DATE 0/369; Final FINAL_DATE 0/6.

## Artifacts

- Repair script: `agent/scripts/fl/data_repair_fl_lake_clarke_shores.py` (`data_repair`)
- Repaired sample: `AGENT_DATA_PATH/repaired/permits_fl_lake_clarke_shores_repaired.parquet`

# Palm Beach Shores (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script was **Palm Beach Shores**. DATA is a flat MyGovernmentOnline (MGO) project payload (`ProjectStatus` / `DateCreated` / `DateIssued`). `STATUS_NORMALIZED` already matched portal status on every row; `FILE_DATE` already matched `DateCreated` on all 2,000 rows. `DateIssued` and `DateUpdated` are the `.NET` sentinel `0001-01-01` on every row, and no completion/CO date exists, so `PERMIT_DATE` and `FINAL_DATE` remain universally missing. After repair: STATUS fully populated; FILE_DATE 100%; Active/Final PERMIT_DATE 0%; Final FINAL_DATE 0%.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` and walked `(JURISDICTION, STATE)` pairs in file order. Palm Beach Shores was the first pair without `agent/scripts/fl/data_repair_fl_palm_beach_shores.py`.

## DATA shape

| Schema | n |
| --- | ---: |
| `mgo_ppm` | 1,228 |
| `mgo_base` | 772 |

Both are the same flat MGO project object; `mgo_ppm` adds `PaymentProcessorModule` (value `MGO`). All rows have `ProjectType` = `Permit`.

Canonical sources:

| Field | DATA source |
| --- | --- |
| STATUS_NORMALIZED | `ProjectStatus` (whitespace-stripped) |
| FILE_DATE | `DateCreated` |
| PERMIT_DATE | `DateIssued` when not `0001-01-01` (never in sample) |
| FINAL_DATE | *(none — no completion / CO timestamp)* |

`STATUS_ORIGINAL` matches live `ProjectStatus` on all 2,000 rows (case-normalized).

## Field assessments

### STATUS_NORMALIZED

Before/after: Final 1,046; Active 686; In Review 193; Inactive 75; **0 null**.

| ProjectStatus | n | Upstream STATUS_NORMALIZED | Assessment |
| --- | ---: | --- | --- |
| Project Closed/Complete | 1,046 | Final | Correct |
| Permit Issued | 686 | Active | Correct |
| Pending (Under Review) | 189 | In Review | Correct |
| Expired | 75 | Inactive | Correct |
| Stop Work Order | 4 | In Review | Correct (no real `DateIssued` to promote to Active) |

Flags: **0 FILLED, 0 FIXED**.

### FILE_DATE

Missing on 0/2,000. Calendar day matches `DateCreated` on every row. Flags: **0 FILLED, 0 FIXED**.

### PERMIT_DATE

Missing on all 2,000 rows (including all 686 Active and 1,046 Final).

- Sole candidate `DateIssued` is the sentinel `0001-01-01T00:00:00` on every row.
- `DateUpdated`, `ScheduledDueDate`, and power-request dates are likewise null/sentinel.
- Copying `FILE_DATE` / `DateCreated` into `PERMIT_DATE` was rejected (same pitfall repaired in peer MGO cities).

**Repair performance:** FILLED 0, FIXED 0; missing 2,000 → 2,000. Script will fill from a real `DateIssued` if present in future extracts. Active/Final coverage: 0%.

### FINAL_DATE

Missing on all 2,000 rows (including all 1,046 Final). No finaled / completion / CO field exists in the MGO payload; `DateUpdated` is always the `.NET` sentinel. Flags: **0 FILLED, 0 FIXED**. Ideal Final coverage remains 0%.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 0 | 0 | 0 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 0 | 0 | 2,000 → 2,000 |
| FINAL_DATE | 0 | 0 | 2,000 → 2,000 |

Coverage after repair: FILE_DATE 100% all statuses; Active/Final PERMIT_DATE 0/1,732; Final FINAL_DATE 0/1,046.

## Artifacts

- Repair script: `agent/scripts/fl/data_repair_fl_palm_beach_shores.py` (`data_repair`)
- Repaired sample: `AGENT_DATA_PATH/repaired/permits_fl_palm_beach_shores_repaired.parquet`

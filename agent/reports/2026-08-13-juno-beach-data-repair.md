# Juno Beach (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script was **Juno Beach**. DATA is a flat MyGovernmentOnline (MGO) project payload (`ProjectStatus` / `DateCreated` / `DateIssued`). `STATUS_NORMALIZED` already matched portal status on every row; `FILE_DATE` already matched `DateCreated` on all 2,000 rows. `DateIssued` and `DateUpdated` are the `.NET` sentinel `0001-01-01` on every row, and no completion/CO date exists, so `PERMIT_DATE` and `FINAL_DATE` remain universally missing. After repair: STATUS fully populated; FILE_DATE 100%; Active/Final PERMIT_DATE 0%; Final FINAL_DATE 0%.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` and walked `(JURISDICTION, STATE)` pairs in sorted order. Juno Beach was the first pair without `agent/scripts/fl/data_repair_fl_juno_beach.py`.

## DATA shape

| Schema | n |
| --- | ---: |
| `mgo_ppm` | 1,333 |
| `mgo_base` | 667 |

Both are the same flat MGO project object; `mgo_ppm` adds `PaymentProcessorModule` (value `MGO`).

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

Before/after: Final 1,784; Inactive 88; Active 70; In Review 58; **0 null**.

| ProjectStatus | n | Upstream STATUS_NORMALIZED | Assessment |
| --- | ---: | --- | --- |
| Closed | 1,784 | Final | Correct |
| Expired | 88 | Inactive | Correct |
| Issued | 70 | Active | Correct |
| In Review | 53 | In Review | Correct |
| Stop Work Order | 5 | In Review | Correct (no real `DateIssued` to promote to Active) |

Flags: **0 FILLED, 0 FIXED**.

### FILE_DATE

Missing on 0/2,000. Calendar day matches `DateCreated` on every row. Flags: **0 FILLED, 0 FIXED**.

### PERMIT_DATE

Missing on all 2,000 rows (including all 70 Active and 1,784 Final).

- Sole candidate `DateIssued` is the sentinel `0001-01-01T00:00:00` on every row.
- `DateUpdated` and scheduled/power-request dates are likewise null/sentinel.
- Copying `FILE_DATE` / `DateCreated` into `PERMIT_DATE` was rejected (same pitfall repaired in peer MGO cities).

**Repair performance:** FILLED 0, FIXED 0; missing 2,000 → 2,000. Script will fill from a real `DateIssued` if present in future extracts. Active/Final coverage: 0%.

### FINAL_DATE

Missing on all 2,000 rows (including all 1,784 Final). No finaled / completion / CO field exists in the MGO payload; `DateUpdated` is always the `.NET` sentinel. Flags: **0 FILLED, 0 FIXED**. Ideal Final coverage remains 0%.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 0 | 0 | 0 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 0 | 0 | 2,000 → 2,000 |
| FINAL_DATE | 0 | 0 | 2,000 → 2,000 |

Coverage after repair: FILE_DATE 100% all statuses; Active/Final PERMIT_DATE 0/1,854; Final FINAL_DATE 0/1,784.

## Artifacts

- Repair script: `agent/scripts/fl/data_repair_fl_juno_beach.py` (`data_repair`)
- Repaired sample: `AGENT_DATA_PATH/repaired/permits_fl_juno_beach_repaired.parquet`

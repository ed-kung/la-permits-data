# North Palm Beach (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script (in parquet appearance order) was **North Palm Beach**. DATA is a flat MyGovernmentOnline (MGO) project payload (`ProjectStatus` / `DateCreated` / `DateIssued`). `STATUS_NORMALIZED` already matched `ProjectStatus` on all 2,000 rows (including `STOP WORK ORDER` / `HOLD` → In Review and `Expired` → Inactive). `FILE_DATE` already matched `DateCreated` on every row. `DateIssued` and `DateUpdated` are the `.NET` sentinel `0001-01-01` on every row, and no completion/CO date exists, so `PERMIT_DATE` and `FINAL_DATE` remain universally missing. After repair: no value changes; STATUS fully populated; FILE_DATE 100%; Active/Final PERMIT_DATE 0%; Final FINAL_DATE 0%.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` and walked `(JURISDICTION, STATE)` pairs in first-appearance order. North Palm Beach was the first pair without `agent/scripts/fl/data_repair_fl_north_palm_beach.py`.

## DATA shape

| Schema | n |
| --- | ---: |
| `mgo_ppm` | 2,000 |

All rows include `PaymentProcessorModule` (value `MGO`). Single key-set; no nested inspections/reviews with usable timestamps.

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

Before/after: Active 838; In Review 673; Final 488; Inactive 1; **0 null**.

| ProjectStatus | n | Upstream STATUS_NORMALIZED | Assessment |
| --- | ---: | --- | --- |
| Permit Issued | 838 | Active | Correct |
| Pending (Under Review) | 663 | In Review | Correct |
| Project Closed/Complete | 488 | Final | Correct |
| STOP WORK ORDER | 5 | In Review | Correct (administrative stop; still open) |
| HOLD | 5 | In Review | Correct |
| Expired | 1 | Inactive | Correct |

Flags: **0 FILLED, 0 FIXED**. No incorrect or incorrectly missing statuses in the sample.

### FILE_DATE

Missing on 0/2,000. Calendar day matches `DateCreated` on every row. Flags: **0 FILLED, 0 FIXED**.

### PERMIT_DATE

Missing on all 2,000 rows (including all 838 Active and 488 Final).

- Sole candidate `DateIssued` is the sentinel `0001-01-01T00:00:00` on every row.
- `DateUpdated` and scheduled/power-request dates are likewise null/sentinel.
- No nested review/inspection completion stamps exist in the payload.
- Copying `FILE_DATE` / `DateCreated` into `PERMIT_DATE` was rejected (same pitfall as peer MGO cities).

**Repair performance:** FILLED 0, FIXED 0; missing 2,000 → 2,000. Script will fill from a real `DateIssued` if present in future extracts. Active/Final coverage: 0%.

### FINAL_DATE

Missing on all 2,000 rows (including all 488 Final). No finaled / completion / CO field exists in the MGO payload; `DateUpdated` is always the `.NET` sentinel. Flags: **0 FILLED, 0 FIXED**. Ideal Final coverage remains 0%.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 0 | 0 | 0 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 0 | 0 | 2,000 → 2,000 |
| FINAL_DATE | 0 | 0 | 2,000 → 2,000 |

Ideal-rule coverage after repair:

| Rule | Coverage |
| --- | --- |
| FILE_DATE populated (all rows) | 2,000 / 2,000 (100%) |
| PERMIT_DATE on Active/Final | 0 / 1,326 (0%) |
| FINAL_DATE on Final | 0 / 488 (0%) |

## Artifacts

- Repair script: `agent/scripts/fl/data_repair_fl_north_palm_beach.py` (`data_repair`)
- Repaired sample: `AGENT_DATA_PATH/repaired/permits_fl_north_palm_beach_repaired.parquet`

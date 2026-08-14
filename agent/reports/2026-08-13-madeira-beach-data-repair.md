# Madeira Beach (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script (in parquet appearance order) was **Madeira Beach**. DATA is a flat MyGovernmentOnline (MGO) project payload (`ProjectStatus` / `DateCreated` / `DateIssued`). Upstream left 64 `ProjectStatus` values unmapped (mostly `Substantial Damage Determination under review`), so `STATUS_NORMALIZED` was null; repair filled all 64 to In Review. `FILE_DATE` already matched `DateCreated` on all 2,000 rows. `DateIssued` and `DateUpdated` are the `.NET` sentinel `0001-01-01` on every row, and no completion/CO date exists, so `PERMIT_DATE` and `FINAL_DATE` remain universally missing. After repair: STATUS fully populated; FILE_DATE 100%; Active/Final PERMIT_DATE 0%; Final FINAL_DATE 0%.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` and walked `(JURISDICTION, STATE)` pairs in first-appearance order. Madeira Beach was the first pair without `agent/scripts/fl/data_repair_fl_madeira_beach.py`.

## DATA shape

| Schema | n |
| --- | ---: |
| `mgo_ppm` | 2,000 |

All rows include `PaymentProcessorModule` (value `MGO`). No nested inspections/reviews; no alternate key-set variants in the sample.

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

Before: In Review 848; Active 541; Final 510; null 64; Inactive 37.

After: In Review 912; Active 541; Final 510; Inactive 37; **0 null**.

| ProjectStatus | n | Upstream STATUS_NORMALIZED | Assessment |
| --- | ---: | --- | --- |
| Pending (Under Review) | 848 | In Review | Correct |
| Permit Issued | 541 | Active | Correct |
| Project Closed/Complete | 510 | Final | Correct |
| Substantial Damage Determination under review | 62 | null | Incorrectly missing → In Review |
| Expired | 37 | Inactive | Correct |
| Private Provider Under Review Pending | 1 | null | Incorrectly missing → In Review |
| Stop Work Order - Open | 1 | null | Incorrectly missing → In Review |

Flags: **64 FILLED, 0 FIXED**.

Cause of missing statuses: upstream normalizer lacked mappings for the three hurricane/private-provider/stop-work review labels; heuristic fallbacks in the repair script map any status containing `review`, `pending`, or `stop work` to In Review.

### FILE_DATE

Missing on 0/2,000. Calendar day matches `DateCreated` on every row. Flags: **0 FILLED, 0 FIXED**.

### PERMIT_DATE

Missing on all 2,000 rows (including all 541 Active and 510 Final).

- Sole candidate `DateIssued` is the sentinel `0001-01-01T00:00:00` on every row.
- `DateUpdated` and scheduled/power-request dates are likewise null/sentinel.
- No nested review/inspection completion stamps exist in the payload.
- Copying `FILE_DATE` / `DateCreated` into `PERMIT_DATE` was rejected (same pitfall repaired in peer MGO cities).

**Repair performance:** FILLED 0, FIXED 0; missing 2,000 → 2,000. Script will fill from a real `DateIssued` if present in future extracts. Active/Final coverage: 0%.

### FINAL_DATE

Missing on all 2,000 rows (including all 510 Final). No finaled / completion / CO field exists in the MGO payload; `DateUpdated` is always the `.NET` sentinel. Flags: **0 FILLED, 0 FIXED**. Ideal Final coverage remains 0%.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 64 | 0 | 64 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 0 | 0 | 2,000 → 2,000 |
| FINAL_DATE | 0 | 0 | 2,000 → 2,000 |

Ideal-rule coverage after repair:

| Rule | Coverage |
| --- | --- |
| FILE_DATE populated (all rows) | 2,000 / 2,000 (100%) |
| PERMIT_DATE on Active/Final | 0 / 1,051 (0%) |
| FINAL_DATE on Final | 0 / 510 (0%) |

## Artifacts

- Repair script: `agent/scripts/fl/data_repair_fl_madeira_beach.py` (`data_repair`)
- Repaired sample: `AGENT_DATA_PATH/repaired/permits_fl_madeira_beach_repaired.parquet`

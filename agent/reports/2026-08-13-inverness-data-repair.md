# Inverness (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script was Inverness. DATA splits into 1,491 legacy `converted` shells (uppercase `STATUS` / `APPLIC DATE` / `ACTUAL END DATE`) and 509 modern `city_portal*` shells (`Status` / `Permit Date` / inspections). Repair filled all 1,491 null `STATUS_NORMALIZED` values from converted `STATUS`, cleared 27 spurious `FINAL_DATE` values on converted Inactive shells, and filled 115 portal Final `FINAL_DATE` values from passed FINAL-ish inspections. `FILE_DATE` was already correct on every row. `PERMIT_DATE` remains missing on all 2,000 rows — DATA has no issuance stamp distinct from the application / `Permit Date` field.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` and walked `(JURISDICTION, STATE)` pairs in sorted order. Inverness was the first pair without `agent/scripts/fl/data_repair_fl_inverness.py`.

## DATA shape

| Schema | n |
| --- | ---: |
| `converted_finaled` | 1,491 |
| `city_portal_applied` | 346 |
| `city_portal_finaled` | 117 |
| `city_portal_record_type_applied` | 36 |
| `city_portal_plan_reviews_applied` | 10 |

Canonical sources:

| Field | DATA source |
| --- | --- |
| STATUS_NORMALIZED | converted `STATUS`; portal `Status` |
| FILE_DATE | converted `APPLIC DATE`; portal `Permit Date` |
| PERMIT_DATE | *(none — no Issued / Approved date in DATA)* |
| FINAL_DATE | converted `ACTUAL END DATE`; portal latest passed FINAL-ish `inspections[].completed_date` |

## Field assessments

### STATUS_NORMALIZED

Before: null 1,491; Final 350; In Review 153; Inactive 6.

Cause of nulls: all converted shells have blank `STATUS_ORIGINAL` and were never mapped from uppercase `STATUS` (`FINALED` 1,464; `WITHDRAWN` 14; `CLOSED APPLICATION` 9; `EXPIRED` 4).

Portal mapping already matched DATA: `CLOSED`→Final, `OPEN`/`PENDING`/`ONLINE SUBMISSION`→In Review, `WITHDRAWN`→Inactive.

After: Final 1,814; In Review 153; Inactive 33; **0 null**. Flags: **1,491 FILLED, 0 FIXED**.

### FILE_DATE

Missing on 0/2,000. Converted `FILE_DATE` equals `APPLIC DATE` on every row; portal equals `Permit Date` on every row. Flags: **0 FILLED, 0 FIXED**.

### PERMIT_DATE

Missing on all 2,000 rows before and after.

- Converted `Permit Date` always equals `APPLIC DATE` (same calendar day on 1,491/1,491) — not a distinct issuance stamp.
- Portal payloads expose no `Issued Date` / `ApprovedByDate`; nested fees/payments/reviews are empty in this sample.
- Copying `FILE_DATE` into `PERMIT_DATE` was rejected (same pitfall repaired in peer cities).

Flags: **0 FILLED, 0 FIXED**. Ideal Active/Final coverage remains 0/1,814.

### FINAL_DATE

Before: missing on all 509 portal rows; present on all 1,491 converted rows (exact match to `ACTUAL END DATE`).

Repairs:

- **115** portal `CLOSED` (Final) rows → FILLED from latest passed FINAL-ish inspection (`FINAL`, `ELECTRIC FINAL`, `MECHANICAL FINAL`, etc.)
- **27** converted Inactive rows (`WITHDRAWN` / `EXPIRED` / `CLOSED APPLICATION`) → FIXED clear of `ACTUAL END DATE` (close/withdraw stamp is not a Final completion date)

After: Final 1,579/1,814 (87.0%); non-Final 0. Remaining 235 Final gaps are portal `CLOSED` shells with empty inspections or no passed FINAL-ish inspection (72 have some non-final pass only — last-passed fallback rejected). Two `OPEN` shells carry a passed FINAL inspection in DATA but stay In Review without writing `FINAL_DATE`.

Flags: **115 FILLED, 27 FIXED**.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 1,491 | 0 | 1,491 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 0 | 0 | 2,000 → 2,000 |
| FINAL_DATE | 115 | 27 | 509 → 421 |

## Artifacts

- Repair script: `agent/scripts/fl/data_repair_fl_inverness.py` (`data_repair`)
- Repaired sample: `AGENT_DATA_PATH/inverness_repaired_sample.parquet`

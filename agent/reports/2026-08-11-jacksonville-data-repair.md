# Jacksonville (FL) data repair

Summary: Jacksonville was the first FL sample jurisdiction without a repair script. Two DATA schemas (`full_permit`, `mini_record`) drive status and dates. The repair fills all 559 missing `STATUS_NORMALIZED` values, brings Active/Final `PERMIT_DATE` to 100%, and recovers every available `FILE_DATE`/`FINAL_DATE` from `full_permit` detail payloads. Remaining date gaps are confined to `mini_record` rows, which lack application and finalization dates in DATA.

## Jurisdiction selected

- Sample file: `MY_DATA_PATH/processed_data/permits_fl_sample.parquet`
- First `(JURISDICTION, STATE)` without `agent/scripts/{state}/data_repair_{state}_{city}.py`: **Jacksonville, FL**
- Sample size: **1,995** records

## DATA schemas (`INFERRED_SCHEMA`)

| Schema | n | Status source | FILE_DATE source | PERMIT_DATE source | FINAL_DATE source |
| --- | ---: | --- | --- | --- | --- |
| `full_permit` | 808 | `StatusDescription` | `DateEntered` | `DateIssued` | `DateFinal` |
| `mini_record` | 1,187 | `obj.Status` | *(none)* | `obj.DateIssued` | *(none)* |

`mini_record` rows are lightweight associated-permit summaries (`CanDoOperation`, `description`, `obj`, …). They expose status and issuance only.

## Findings by field

### STATUS_NORMALIZED

- Before: Final 1,302; missing 559; Inactive 109; Active 22; In Review 3.
- Upstream normalizer left many statuses unmapped, especially **`Finalized-NIF`** (216 rows; always missing) and a large share of `full_permit` **`Finalized`** rows (288 missing).
- Non-null values already agreed with DATA wherever both were present (0 mismatches → no `FIXED`).
- Mapping used: Finalized / Finalized-NIF → Final; Active → Active; Expired / Void / Cancelled / Denied → Inactive; Not Submitted / Return for Corrections / Pending Payment / Suspended → In Review.

### FILE_DATE

- Before: 1,693 / 1,995 missing (84.9%).
- On `full_permit`, `DateEntered` is always present and agrees with existing `FILE_DATE` when populated (302 agree, 0 disagree) → **506 FILLED**.
- All remaining missing `FILE_DATE` are `mini_record` (1,187); DATA has no application/entered date there.

### PERMIT_DATE

- Before: 453 missing (22.7%).
- Existing values always matched `DateIssued` / `obj.DateIssued` at day resolution (0 disagree).
- After repair: **Active 23/23 (100%)**, **Final 1,806/1,806 (100%)**.
- Remaining 127 missing are Inactive (116) or In Review (11) without an issuance date — outside the ideal Active/Final rule.

### FINAL_DATE

- Before: 1,720 missing (86.2%); among status=Final, 80.2% missing.
- On `full_permit`, every Finalized / Finalized-NIF row has `DateFinal`; existing finals agreed (0 disagree) → **452 FILLED**.
- After repair: Final `FINAL_DATE` is **727/1,806 (40.3%)** overall, but **727/727 (100%)** on `full_permit`.
- The 1,079 Final rows still missing `FINAL_DATE` are all `mini_record` (no final date in schema).

## Repair performance

Script: `agent/scripts/fl/data_repair_fl_jacksonville.py` (`data_repair`)

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | ---: | ---: | ---: | ---: |
| STATUS_NORMALIZED | 559 | 0 | 559 | 0 |
| FILE_DATE | 506 | 0 | 1,693 | 1,187 |
| PERMIT_DATE | 326 | 0 | 453 | 127 |
| FINAL_DATE | 452 | 0 | 1,720 | 1,268 |

Status distribution after repair: Final 1,806; Inactive 154; Active 23; In Review 12.

## Not repairable from DATA

- `mini_record` `FILE_DATE` and `FINAL_DATE` (no `DateEntered` / `DateFinal` equivalents).
- Inactive / In Review rows never issued (`DateIssued` null) keep `PERMIT_DATE` missing by design.

## Artifacts

- Repair script: `agent/scripts/fl/data_repair_fl_jacksonville.py`
- No derived parquet written; run the script’s `__main__` block for live stats.

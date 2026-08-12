# Palm Beach County (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script (after Fort Lauderdale in list order) was **Palm Beach County**. DATA is a flat PZB payload (`StatusDescription`, `ApplicationDate`, `IssuedDate`, `CompletionDate`, `ProjDateInactive`). STATUS_NORMALIZED was filled on 3 unmapped `(Multiple)` labels and fixed on 113 rows — mainly 86 `Admin Closed` mislabeled as Final and 23 unissued `Approved` mislabeled as Active. FILE_DATE / PERMIT_DATE / FINAL_DATE already matched their DATA sources whenever present; no date fills or fixes were needed. After repair, FILE_DATE is 100%, Active PERMIT_DATE is 100%, Final PERMIT_DATE is 99.8%, and Final FINAL_DATE is 100%.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` and walked unique `(JURISDICTION, STATE)` pairs in file order. Existing FL repair scripts covered Jacksonville through Fort Lauderdale. **Palm Beach County** was the first without `agent/scripts/fl/data_repair_fl_palm_beach_county.py`.

Sample size: **1,999** records.

## DATA schemas

One portal family, split by which dates are populated:

| INFERRED_SCHEMA       | Count |
| --------------------- | ----: |
| `pbc_issued_finaled`  | 1,648 |
| `pbc_issued`          |   276 |
| `pbc_applied`         |    72 |
| `pbc_finaled`         |     3 |

Canonical source fields:

| Target field      | DATA source |
| ----------------- | ----------- |
| STATUS_NORMALIZED | `StatusDescription`; `Approved` / `Printed` / `Submitted` gated on `IssuedDate` |
| FILE_DATE         | `ApplicationDate` |
| PERMIT_DATE       | `IssuedDate` |
| FINAL_DATE        | `CompletionDate` (Final only; never `ProjDateInactive`) |

Optional detail blocks (`Contact`, `Contractor`, `Review - Summary`, `Inspection`) appear on a minority of rows but do not change the date/status sources.

## Field assessments

### STATUS_NORMALIZED

Before: Final 1,735 · Active 121 · Inactive 100 · In Review 40 · missing 3.

- `STATUS_ORIGINAL` matches `StatusDescription` case-insensitively on every row; defects are in the upstream normalize map, not stale portal labels.
- **3** missing rows: `Complete (Multiple)` → Final (2) and `Inactive (Multiple)` → Inactive (1) → **FILLED**.
- **86** `Admin Closed` rows were labeled Final but have null `CompletionDate` and a populated `ProjDateInactive` (administrative close / expiration, not a sign-off). Consistent with Daly City / San Luis Obispo County → **FIXED** to Inactive.
- **23** `Approved` rows without `IssuedDate` were labeled Active → **FIXED** to In Review (plans approved, not yet issued).
- **3** `Printed` rows with `IssuedDate` were labeled In Review → **FIXED** to Active.
- **1** `Submitted` row with `IssuedDate` was labeled In Review → **FIXED** to Active.
- Already-correct majority left alone: `Complete`/`Finished`→Final; `Active`/`Issued`/issued `Approved`→Active; `Draft`/`In Process`/`Ready for Issuance`/unissued `Submitted`→In Review; `Inactive`/`Permit Cancelled`/`Void`→Inactive.

After: Final 1,651 · Inactive 187 · Active 102 · In Review 59 · missing 0.  
Flags: **FILLED 3 · FIXED 113**.

### FILE_DATE

Before: 0 missing. Ideal: populated for all records.

- Upstream FILE_DATE matched `ApplicationDate` on every row (**0** day mismatches).
- Coverage remains **100%** for all statuses.

After: 0 missing.  
Flags: **FILLED 0 · FIXED 0**.

### PERMIT_DATE

Before: 75 missing. Ideal: populated for Active and Final.

- When present, PERMIT_DATE already matched `IssuedDate` (**0** mismatches); every missing PERMIT_DATE also has null `IssuedDate` in DATA.
- Status remaps moved unissued `Approved` rows out of Active, so Active coverage becomes complete without inventing dates.
- **3** Final rows still lack `IssuedDate` (`Finished` ×2, `Complete` ×1) while having `CompletionDate` → PERMIT_DATE not repairable from DATA.
- In Review / most Void rows correctly lack issuance.

After: 75 missing. Coverage: Active **100%**; Final **99.8%** (1,648 / 1,651).  
Flags: **FILLED 0 · FIXED 0**.

### FINAL_DATE

Before: 348 missing (86 of Final — all `Admin Closed`); 2 NaN-status `Complete (Multiple)` rows carried FINAL_DATE. Ideal: populated for Final.

- When present, FINAL_DATE already matched `CompletionDate` (**0** mismatches).
- Remapping `Admin Closed` → Inactive removes the Final FINAL_DATE gap without using `ProjDateInactive` (an expiration stamp, not a completion date).
- After status repair, every Final row has `CompletionDate` and FINAL_DATE; no non-Final row carries FINAL_DATE.

After: 348 missing (all non-Final, as expected). Coverage: Final **100%**; Active / In Review / Inactive **0%**.  
Flags: **FILLED 0 · FIXED 0**.

## Repair script

`agent/scripts/fl/data_repair_fl_palm_beach_county.py` — function `data_repair(df)`.

Adds `INFERRED_SCHEMA` plus `{STATUS_NORMALIZED,FILE_DATE,PERMIT_DATE,FINAL_DATE}_FLAG` (`FILLED` / `FIXED`).

## Artifacts

- Script: `agent/scripts/fl/data_repair_fl_palm_beach_county.py`
- Repaired sample: `AGENT_DATA_PATH/palm_beach_county_repaired_sample.parquet`

# Escambia County (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script (after Polk County in list order) was **Escambia County**. DATA is a single MyGovernmentOnline (MGO) project family (`ProjectStatus` / `DateCreated` / `DateIssued`, all 2,001 rows). STATUS_NORMALIZED had 2 nulls (`Closed - No Inspection` → Final) and 39 incorrect labels (37 `COC Issued` Active→Final; 2 `Contract Terminated` In Review→Inactive). FILE_DATE was already complete and matched `DateCreated`. `DateIssued` is always the `.NET` sentinel `0001-01-01`, and no completion/CO date field exists, so PERMIT_DATE and FINAL_DATE remain universally missing. After repair: STATUS fully populated; FILE_DATE 100%; Active/Final PERMIT_DATE 0%; Final FINAL_DATE 0%.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` and walked unique `(JURISDICTION, STATE)` pairs in appearance order. Existing FL repair scripts covered Jacksonville through Polk County (and other out-of-order cities). **Escambia County** was the first without `agent/scripts/fl/data_repair_fl_escambia_county.py`.

Sample size: **2,001** records.

## DATA schemas

| INFERRED_SCHEMA | Count |
| --------------- | ----: |
| `mgo_modern`    | 1,361 |
| `mgo_imported`  |   640 |

Both variants share the same MGO project key set; `mgo_imported` is identified by `TypeList` containing `Imported Fee`. Eleven rows omit `PaymentProcessorModule` but are otherwise the same family (not split out).

Canonical source fields:

| Target field      | DATA source                                      |
| ----------------- | ------------------------------------------------ |
| STATUS_NORMALIZED | `ProjectStatus` (whitespace-stripped)            |
| FILE_DATE         | `DateCreated`                                    |
| PERMIT_DATE       | `DateIssued` when not `0001-01-01` (never in sample) |
| FINAL_DATE        | *(no field in payload)*                          |

`STATUS_ORIGINAL` matches live `ProjectStatus` on all 2,001 rows (case/whitespace normalized).

## Field assessments

### STATUS_NORMALIZED

Before: Final 1,047 · Active 795 · In Review 92 · Inactive 65 · missing 2.

Upstream mapping was already correct for common labels:

| ProjectStatus             | Upstream STATUS_NORMALIZED |
| ------------------------- | -------------------------- |
| Closed                    | Final                      |
| CO Issued                 | Final                      |
| Temp CO Issued            | Final                      |
| Permit Issued             | Active                     |
| Pending (Under Review)    | In Review                  |
| Expired                   | Inactive                   |
| VOID-Nonpayment           | Inactive                   |

Issues repaired:

- **2 FILLED** nulls: `closed - no inspection` / `Closed - No Inspection` → Final.
- **37 FIXED**: `coc issued` / `COC Issued` (Certificate of Completion) labeled Active → Final.
- **2 FIXED**: `contract terminated` / `Contract Terminated` labeled In Review → Inactive.

After: Final 1,086 · Active 758 · In Review 90 · Inactive 67 · missing 0.  
Flags: **FILLED 2 · FIXED 39**.

### FILE_DATE

Before: 0 missing. Ideal: populated for all records.

- FILE_DATE already matched `DateCreated` on **2,001 / 2,001** rows (0 day mismatches).
- No fill or fix needed.

After: 0 missing (100% overall).  
Flags: **FILLED 0 · FIXED 0**.

### PERMIT_DATE

Before: 2,001 missing. Ideal: populated for Active and Final.

- `DateIssued` is the sentinel `0001-01-01T00:00:00` on every row, including Permit Issued / Closed / CO / COC.
- No other issuance timestamp exists in DATA.
- Gaps are not fillable from the sample payload.

After: 2,001 missing. Coverage: Active **0%** (0/758); Final **0%** (0/1,086).  
Flags: **FILLED 0 · FIXED 0**.

### FINAL_DATE

Before: 2,001 missing. Ideal: populated for Final.

- MGO payload has no finaled / completion / CO / sign-off date field (`RequestPermanentPowerDate`, `RequestTemporaryPowerDate`, and `ScheduledDueDate` are always null; `DateUpdated` is always the same sentinel).
- Gaps are not fillable from DATA.

After: 2,001 missing. Final coverage **0%** (0/1,086). Non-Final FINAL_DATE: **0**.  
Flags: **FILLED 0 · FIXED 0**.

## Repair performance

| Field             | FILLED | FIXED | Missing before → after |
| ----------------- | -----: | ----: | ---------------------- |
| STATUS_NORMALIZED |      2 |    39 | 2 → 0                  |
| FILE_DATE         |      0 |     0 | 0 → 0                  |
| PERMIT_DATE       |      0 |     0 | 2,001 → 2,001          |
| FINAL_DATE        |      0 |     0 | 2,001 → 2,001          |

Ideal-field coverage after repair:

- FILE_DATE: 100% of all records
- PERMIT_DATE: 0% of Active and Final (no issuance date in DATA)
- FINAL_DATE: 0% of Final (no completion date in DATA)

## Artifacts

| Path | Description |
| ---- | ----------- |
| `agent/scripts/fl/data_repair_fl_escambia_county.py` | `data_repair()` implementation |
| `AGENT_DATA_PATH/escambia_county_repaired_sample.parquet` | Repaired sample with flag + `INFERRED_SCHEMA` columns |

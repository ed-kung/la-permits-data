# Hillsboro Beach (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script was Hillsboro Beach. Its DATA is a city-portal payload (same family as Deerfield Beach / Gadsden County) with `Permit Information`, `Applications`, and `Inspections History`. `STATUS_NORMALIZED` already matched `StatusDesc` on every row. `FILE_DATE` already matched earliest `AppDate` except one empty-Applications Voided shell. `PERMIT_DATE` was a copy of `FILE_DATE` on all 1,517 populated rows; repair overwrote 250 rows from `ApprovedByDate` and cleared 3 spurious In Review issuance dates. `FINAL_DATE` was missing on all rows and was filled for 1,425 of 1,444 Final records from Passed FINAL inspections.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` and walked `(JURISDICTION, STATE)` in order. Hillsboro Beach was the first pair without `agent/scripts/fl/data_repair_fl_hillsboro_beach.py`.

## DATA shape

All 1,518 rows share the same top-level key set. `INFERRED_SCHEMA` content suffixes:

| Schema | n |
| --- | ---: |
| `city_portal_finaled` | 1,190 |
| `city_portal_issued_finaled` | 249 |
| `city_portal_applied` | 65 |
| `city_portal_issued` | 13 |
| `city_portal_empty_apps` | 1 |

Canonical sources:

| Field | DATA source |
| --- | --- |
| STATUS_NORMALIZED | `Permit Information[0].StatusDesc` |
| FILE_DATE | earliest `Applications[].AppDate` |
| PERMIT_DATE | earliest `Applications[].ApprovedByDate` |
| FINAL_DATE | latest Passed inspection with `FINAL` in `inspectiondesc` (`scheduleddate`) |

## Field assessments

### STATUS_NORMALIZED

Before/after: Final 1,444; Inactive 58; Active 13; In Review 3; **0 null**.

`STATUS_ORIGINAL` is a lowercased form of `StatusDesc` (`permit complete`, `permit issued`, `expired`, `voided`, `canceled permit`, `plan review`, `application`). Upstream mapping is already correct. Flags: **0 FILLED, 0 FIXED**.

### FILE_DATE

Missing on 1/1,518. For the other 1,517 rows, `FILE_DATE` already equals earliest `AppDate` (calendar day). The missing row is Voided permit `1914370-1` with an empty `Applications` list and no fees/inspections/plan-review history → not recoverable.

Flags: **0 FILLED, 0 FIXED**. Ideal coverage: 1,517/1,518 (99.9%).

### PERMIT_DATE

Before: missing on 1 row; present value equaled `FILE_DATE` on all 1,517 populated rows (upstream copied application date into issuance).

`ApprovedByDate` is present on only 262 shells. When present it is the real issuance stamp and usually differs from `FILE_DATE` / fee `DatePaid` (fee dates are not a reliable proxy here).

Repairs:

- **244** Active/Final rows → `PERMIT_DATE` FIXED from earliest `ApprovedByDate`
- **6** Inactive rows with `ApprovedByDate` → FIXED
- **3** In Review rows → spurious `PERMIT_DATE` (= `FILE_DATE`) cleared (FIXED)

After: Active 13/13; Final 1,444/1,444; In Review 0/3; Inactive 57/58. Missing count rises 1 → 4 solely from the In Review clears plus the empty-apps Voided shell.

Residual: **1,213** Active/Final rows still have `PERMIT_DATE == FILE_DATE` because `ApprovedByDate` is absent — left as-is (no better source). Five Final rows have `PERMIT_DATE` after `FINAL_DATE`; all five still carry the FILE_DATE copy (no ABD), so the inversion is an artifact of that residual copy vs. inspection history, not of the ABD overwrite.

Flags: **0 FILLED, 253 FIXED**.

### FINAL_DATE

Missing on all 1,518 rows before repair. Filled from latest Passed inspection whose description contains `FINAL`.

After: Final 1,425/1,444 (98.7%); non-Final 0 (correct — inspection close-out not written onto Active/Inactive/In Review).

Remaining 19 Final gaps: empty inspection history, FINAL inspections that never reached `Passed` (e.g. `Passed Partial` / failed only), or close-outs labeled without `FINAL` (e.g. window/door or power-for-testing only). Last-passed fallback was rejected — those dates are often not true finalization.

Flags: **1,425 FILLED, 0 FIXED**.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 0 | 0 | 0 → 0 |
| FILE_DATE | 0 | 0 | 1 → 1 |
| PERMIT_DATE | 0 | 253 | 1 → 4 |
| FINAL_DATE | 1,425 | 0 | 1,518 → 93 |

Ideal-coverage gaps remaining:

- FILE_DATE: **1** (empty `Applications` Voided shell)
- Active/Final with `PERMIT_DATE == FILE_DATE` (no ABD): **1,213**
- Final missing FINAL_DATE: **19**
- STATUS_NORMALIZED: **none**

## Artifacts

- Script: `agent/scripts/fl/data_repair_fl_hillsboro_beach.py` (`data_repair`)
- Repaired sample: `$AGENT_DATA_PATH/hillsboro_beach_repaired_sample.parquet`

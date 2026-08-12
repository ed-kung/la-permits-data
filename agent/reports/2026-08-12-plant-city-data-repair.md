# Plant City (FL) data repair

**Summary:** Plant City’s CityView/CentralSquare `DATA` payload maps cleanly via top-level `status` plus `details.created` / `issued` / `closed`. Upstream status followed only the top-level Open/Issued/Closed/Void labels, so 1,108 Open (and one Issued) rows were misclassified—especially historical BDMS shells with real close/issue stamps, Expired/Cancelled detail statuses, and 1899-11-30 sentinel `FINAL_DATE` values. The repair reclassifies those statuses, clears sentinel/spurious dates, and leaves `FILE_DATE` untouched (already 100% correct).

## Jurisdiction selected

First `(JURISDICTION, STATE)` in `permits_fl_sample.parquet` without an existing `agent/scripts/{state}/data_repair_{state}_{city}.py`: **Plant City, FL** (1,999 sample rows).

## DATA shape

CityView / CentralSquare community portal payload for all rows:

- Core keys: `id`, `type`, `number`, `status`, `details`, `timeline`, `customFields`, `contacts`
- Common extras: `lastUpdDate`, `canMakeOperations`, `entryForms`, `canUpdateCompositeDetails`, `isPrimaryContact`
- Canonical fields: top-level `status` (with `details.status` / `details.caseStatus` overrides), `details.created`, `details.issued`, `details.closed`
- Record types: BDMS (1,022), Building Permit (407), Legacy Building (370), Code Enf. (124), Legacy Planning (34), Planning (30), Permit (8), Engineering (3), Planning/Zoning (1)

`INFERRED_SCHEMA` labels are `cityview_portal_{date_suffix}` / `cityview_updated_{date_suffix}`:

| INFERRED_SCHEMA | n |
| --- | ---: |
| cityview_portal_issued_closed | 1,308 |
| cityview_portal_issued | 532 |
| cityview_portal_closed | 88 |
| cityview_portal_created | 67 |
| cityview_updated_created | 4 |

## Field assessment

### STATUS_NORMALIZED

Upstream mapping was a 1:1 fold of top-level `status` / `STATUS_ORIGINAL`:

| Top-level `status` | Upstream `STATUS_NORMALIZED` | n |
| --- | --- | ---: |
| Open | In Review | 1,172 |
| Closed | Final | 643 |
| Issued | Active | 168 |
| Approved | Active | 1 |
| Void | Inactive | 15 |

That ignored `details.caseStatus` / `details.status` and the presence of real issue/close stamps. Among Open rows:

- 704 had a real `details.closed` (mostly BDMS Historical Permits) → should be **Final**
- 338 had `details.issued` but no real closed (incl. 145 with 1899-11-30 sentinel closed) → **Active**
- 65 had Expired / Cancelled / Withdrawn detail status → **Inactive**
- 65 remain true In Review (In Process, Open Case, fees/intake, etc.)

One Active (`Issued` / `PROJECT RE`) row also had a real closed stamp → **Final**.

**1,108 FIXED**; no null statuses to fill.

### FILE_DATE

- Populated on all 1,999 rows; every value equals `details.created` at day resolution.
- No fills or fixes needed.

### PERMIT_DATE

- When present (1,840), always equals `details.issued`.
- Missing (159): Active 4, Final 73, In Review 71, Inactive 11 — and in every case `details.issued` is also blank (no fillable Active/Final gaps from DATA).
- After status overrides, 65 Inactive rows still carried an issuance stamp → **65 FIXED** (cleared).
- After repair: Active 502/506 (99.2%); Final 1,273/1,348 (94.4%); In Review / Inactive 0%.

### FINAL_DATE

- When present on Final rows (638/643), always equals `details.closed`.
- Final missing `FINAL_DATE`: 5 Legacy Building `COMPLETE` shells with blank `closed` / `customFields.Closed Date` → not fillable.
- Non-Final with `FINAL_DATE`: 903 (In Review 887, Inactive 15, Active 1). Of the In Review stamps, 145 are the 1899-11-30 SQL empty-date sentinel; the rest are mostly historical BDMS closes that belong on Final after reclassification, or cancel/expire closes that stay Inactive.
- **198 FIXED** by clearing sentinels and non-Final stamps (145 sentinel + 15 Void + 38 Expired/Cancelled-with-closed). Rows reclassified to Final already matched `details.closed` and needed no date rewrite.
- After repair: Final retains 1,343/1,348 (99.6%); Active / In Review / Inactive have 0%.

## Repair performance

Script: `agent/scripts/fl/data_repair_fl_plant_city.py`  
Artifact: `$AGENT_DATA_PATH/repaired/permits_fl_plant_city_repaired.parquet`

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 0 | 1,108 | 0 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 0 | 65 | 159 → 224 |
| FINAL_DATE | 0 | 198 | 458 → 656 |

Missing `PERMIT_DATE` / `FINAL_DATE` rise because clearing spurious non-target-status stamps outweighs fills (none available from DATA for those fields).

### Coverage after repair

| Status | n | FILE_DATE | PERMIT_DATE | FINAL_DATE |
| --- | ---: | ---: | ---: | ---: |
| Active | 506 | 100% | 99.2% | 0% |
| Final | 1,348 | 100% | 94.4% | 99.6% |
| In Review | 65 | 100% | 0% | 0% |
| Inactive | 80 | 100% | 0% | 0% |

### Status transitions

| Before | After | n |
| --- | --- | ---: |
| In Review | Final | 704 |
| In Review | Active | 338 |
| In Review | Inactive | 65 |
| Active | Final | 1 |

### Remaining gaps / source quirks

- 4 Active + ~75 Final rows: no `details.issued` in DATA (Permit timeline tasks lack timestamps; Code Enf. / Legacy Planning often never issued) → `PERMIT_DATE` stays missing.
- 5 Final Legacy Building COMPLETE rows: no `details.closed` → `FINAL_DATE` stays missing.
- 5 residual `FILE_DATE > PERMIT_DATE` and 1 `PERMIT_DATE > FINAL_DATE` inversions come from agency timestamps (not introduced by repair).
- 0 remaining `FINAL_DATE` years &lt; 1980 after sentinel clearing.

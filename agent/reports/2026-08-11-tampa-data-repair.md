# Tampa (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script (after Lake Mary, in parquet encounter order) was Tampa (1,998 records). DATA is a single Accela Civic Access payload shape, split into `accela_with_inspections` / `accela_no_inspections`. STATUS_NORMALIZED was based on a stale `STATUS_ORIGINAL` snapshot and often disagreed with live `DATA.status` and task history (72 FIXED, 2 FILLED; 0 null after repair). FILE_DATE was already complete and correct. PERMIT_DATE was corrected to Issuance Issued (18 FIXED, mostly new-construction rows where PERMIT had been near FINAL) and filled where Issuance existed (23 FILLED); 957 Final rows still lack any Issuance Issued event. FINAL_DATE coverage for Final rose from 35% to 93.7% (1,006 FILLED, mostly Closure Complete + final inspections). Post-repair: 0 PERMIT>FINAL inversions; 909/909 rows with Issuance Issued have matching PERMIT_DATE.

## Scope

- Input: `MY_DATA_PATH/processed_data/permits_fl_sample.parquet`
- Jurisdiction: Tampa, FL (first `(JURISDICTION, STATE)` lacking `agent/scripts/{state}/data_repair_{state}_{city}.py` after Lake Mary)
- Script: `agent/scripts/fl/data_repair_fl_tampa.py`
- Artifact: `AGENT_DATA_PATH/tampa_repaired_sample.parquet`

## DATA schemas (`INFERRED_SCHEMA`)

All rows share the same top-level Accela keys (`status`, `date`, `tasks`, `inspections`, `search_data`, `more_details`, …). Content variants:

| Schema | Count | Distinguishing feature |
| --- | ---: | --- |
| `accela_with_inspections` | 1,222 | non-empty `inspections` list |
| `accela_no_inspections` | 776 | inspections empty; dates from tasks / `date` only |

## Field assessment

### STATUS_NORMALIZED

- Before: Final 1,641; In Review 133; Inactive 116; Active 106; null 2
- Upstream mapping followed `STATUS_ORIGINAL` (search-list snapshot) 1:1, but live `DATA.status` differed on 74 rows, and task history lagged further on some “In Process” rows that already had Issuance Issued or Closure Complete.
- Mapping: Complete / Closed / Administrative Close(d) → Final; Issued / About to Expire → Active; In Process / In Progress / Awaiting Client Reply / Open / Revision / Client Scheduling Required / Site Plan Review Complete → In Review; Expired / Withdrawn → Inactive. Overrides: Closure Complete → Final; Issuance Issued → Active (unless Expired/Withdrawn).
- Incorrect / stale: 72 rows FIXED (e.g. Active←Complete→Final; In Review←Issued→Active; In Process with Closure→Final)
- Missing fillable: 2 nulls (Client Scheduling Required, Site Plan Review Complete) → FILLED as In Review
- After: Final 1,687; Inactive 124; Active 95; In Review 92; null 0

### FILE_DATE

- Ideal: populated for all records.
- Source: top-level `DATA.date` (= `search_data.Date` when present).
- Before/after: 0 missing; 100% match to `DATA.date`; 0 FILLED / 0 FIXED.

### PERMIT_DATE

- Ideal: populated for Active and Final.
- Canonical source: earliest Issuance task marked `Issued` or `Issued - No Inspection`.
- Before: Active 106/106; Final only 686/1,641 (41.8%). Among rows with both PERMIT and Issuance, 868 matched and **18 mismatched** — nearly all Residential New Construction, where ingested PERMIT_DATE sat near FINAL_DATE (often FINAL−1 day) instead of the true Issuance date.
- Repair: overwrite from Issuance; clear PERMIT on unissued In Review.
- **23 FILLED** + **18 FIXED**; In Review with PERMIT after repair: 0.
- After: Active 94/95 (98.9%); Final 729/1,687 (43.2%). Remaining Active gap: one About to Expire with Issuance Withdrawn only. Remaining Final gaps are mostly admin/license/utility/legacy rows (e.g. Add Contractor License, AACONV closures) with no Issuance Issued event in DATA.
- Chronology: 0 rows with PERMIT_DATE > FINAL_DATE after repair (was 4 before).

### FINAL_DATE

- Ideal: populated for Final.
- Before: 570/1,641 Final (34.7%); upstream usually matched first Inspection task `Complete` and/or approved Final-* inspections.
- Repair priority for Final: latest APPROVED inspection with “final” in title → first Inspection Complete/Finished/Closed → Closure Complete/Closed/Finished/Revision Complete → latest APPROVED inspection. Clear FINAL on non-Final.
- **1,006 FILLED** (≈631 Closure, ≈369 final insp, few other) + **30 FIXED**; 4 FINAL values cleared from non-Final rows (included in FIXED count with status moves).
- Not repairable: 106 Final rows (mostly utility applications / permit extensions / sparse `accela_no_inspections`) with no inspection, Inspection-Complete, or Closure-Complete signal.
- After: Final 1,581/1,687 (93.7%); non-Final FINAL_DATE all null.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 2 | 72 | 2 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 23 | 18 | 1,110 → 1,087 |
| FINAL_DATE | 1,006 | 30 | 1,419 → 417 |

Ideal-field coverage after repair:

- FILE_DATE: 100% of all records
- PERMIT_DATE: 98.9% of Active; 43.2% of Final
- FINAL_DATE: 93.7% of Final

Post-repair checks: 909/909 rows with an Issuance Issued event have PERMIT_DATE = that date; 1,998/1,998 FILE_DATE = `DATA.date`; 0 PERMIT>FINAL date inversions; 0 null STATUS_NORMALIZED.

## Artifacts

- `agent/scripts/fl/data_repair_fl_tampa.py`
- `AGENT_DATA_PATH/tampa_repaired_sample.parquet`

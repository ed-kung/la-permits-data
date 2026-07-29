# Goleta (CA) data repair — 2026-07-28

Goleta was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. City portal JSON under `DATA` is department-keyed (`Building & Safety`, `Planning Cases`, `Business License`, `Permits Cases`) with status and `Issued date` under a Details block (or flat on legacy Planning / Permits Cases). Main issues: 382 missing `STATUS_NORMALIZED` (blank `STATUS_ORIGINAL` on nested Planning + all Business License; unmapped `web created` / `web rejected`), all 2,000 `FILE_DATE` missing with no Applied/Filed field in `DATA`, 129 Active/Final rows missing `PERMIT_DATE` despite `Issued date` (121 fillable after status repair), nearly all `FINAL_DATE` missing despite 132 Final rows with passed final inspections, and 4 spurious `FINAL_DATE` values on Permits Cases copied from `Expiration Date`. Repair fills 382 statuses, 121 permit dates, and 132 final dates, and clears 4 bad final dates; `FILE_DATE` remains fully missing.

## Jurisdiction selection

Walked `(JURISDICTION, STATE)` pairs in sample order and compared against `agent/scripts/{state}/data_repair_{state}_{city}.py`. First missing: **Goleta, CA** → `agent/scripts/ca/data_repair_ca_goleta.py` (n=2,000).

## DATA schema

Each row has exactly one top-level department key. Status / issued / expiration live under `* Details` (Building & Safety, nested Planning, Business License) or flat (legacy Planning Cases, Permits Cases). Inspections (when present) are under `Inspections.Case Inspections` with `Inspection Type`, `Request Type` (Pass / Conditional / Fail), `Date Called In`, `Requested Date`. There is no Applied / Submitted / Filed date on any schema.

| Schema | n | Description |
| --- | ---: | --- |
| `building_safety_issued` | 1,245 | Building & Safety; Issued present, no usable final insp |
| `building_safety_issued_finalinsp` | 213 | Building & Safety; Issued + passed Final* inspection |
| `building_safety_no_dates` | 167 | Building & Safety; no Issued / final insp |
| `planning_nested_no_dates` | 125 | Planning Details nested; no Issued |
| `planning_nested_issued` | 75 | Planning Details nested; Issued present |
| `business_license_no_dates` | 71 | Business License; no Issued |
| `business_license_issued` | 54 | Business License; Issued present |
| `planning_flat_no_dates` | 22 | Flat Planning Cases; no Issued |
| `permits_cases_issued` | 17 | Flat Permits Cases; Issued present |
| `permits_cases_no_dates` | 8 | Flat Permits Cases; no Issued |
| `planning_flat_issued` | 3 | Flat Planning Cases; Issued present |

## Field assessment

### STATUS_NORMALIZED

- Missing on 382 / 2,000. Causes: (1) `STATUS_ORIGINAL` blank on all 200 nested Planning Details and all 125 Business License rows (pipeline never read nested `Status`); (2) 57 Building & Safety / flat rows with `web created` / `web rejected` left unmapped; (3) a few flat Permits / Planning rows with null original.
- When present, mapping from `STATUS_ORIGINAL` already matched `Details.Status` (0 incorrect): `closed`/`finaled`/`closed - approved`→Final, `issued`/`approved`→Active, review/created/pending→In Review, `expired`/`withdrawn`→Inactive.
- **Repair:** map `Details.Status` (including `Active` for Business License, `Web Created`→In Review, `Web Rejected`→Inactive, `Closed - Issued`/`Completed`→Final) → **382 FILLED**, **0 FIXED**. Missing after: 0.

Status fills: null→Final 168; null→Inactive 105; null→In Review 56; null→Active 53.

### FILE_DATE

- Missing on 2,000 / 2,000. `DATA` has no Applied / Submitted / Filed field on any department schema (only `Issued date`, `Expiration Date`, and inspection call-in dates).
- **Repair:** no changes (0 FILLED / 0 FIXED). Coverage remains 0%.

### PERMIT_DATE

- Missing on 522 / 2,000 (26.1%). When present, every value matches `Issued date` (0 incorrect).
- Among Active/Final before repair: Active 58/61 present (95.1%), Final 1,280/1,354 present (94.5%). After status fill, 121 Active/Final gaps have `Issued date` available.
- **Repair:** **121 FILLED** (Active 50, Final 71), **0 FIXED**. Missing after: 401.
- Post-repair Active PERMIT coverage: 108/114 (94.7%); Final: 1,351/1,522 (88.8%). Remaining Active/Final gaps (177) have blank `Issued date` in `DATA` (Closed 169, Closed - Approved 2, Approved 4, Issued 2).

### FINAL_DATE

- Missing on 1,996 / 2,000 (99.8%). The 4 present values are incorrect: Permits Cases rows with status Issued/Created where `FINAL_DATE` equals `Expiration Date` (not a completion date).
- Among Final before repair: 0/1,354 had a legitimate `FINAL_DATE`. 132 Final-like rows (`Closed` / `Finaled` / etc.) have a passed or conditional final inspection (`Final Building Inspection`, bare `Final`, trade Finals, Planning/Fire Department Final) with `Date Called In` / `Requested Date`.
- Goleta has no `PermitFinaledDate`-equivalent field; most Closed rows simply lack inspections in the export (1,390 Final-like with no usable final insp).
- **Repair:** **132 FILLED** from inspections, **4 FIXED** (cleared Expiration mislabels on non-Final). Missing after: 1,868.
- Post-repair Final FINAL coverage: 132/1,522 (8.7%). Remaining Final gaps lack any passed final inspection in `DATA`.

## Repair performance

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | ---: | ---: | ---: | ---: |
| STATUS_NORMALIZED | 382 | 0 | 382 | 0 |
| FILE_DATE | 0 | 0 | 2,000 | 2,000 |
| PERMIT_DATE | 121 | 0 | 522 | 401 |
| FINAL_DATE | 132 | 4 | 1,996 | 1,868 |

Status distribution after repair: Final 1,522 · Inactive 274 · Active 114 · In Review 90 · missing 0.

Post-repair completeness by status:

| Status | n | FILE_DATE | PERMIT_DATE | FINAL_DATE |
| --- | ---: | ---: | ---: | ---: |
| Active | 114 | 0% | 94.7% | 0% |
| Final | 1,522 | 0% | 88.8% | 8.7% |
| In Review | 90 | 0% | 0% | 0% |
| Inactive | 274 | 0% | 51.1% | 0% |

Overall FILE_DATE coverage: 0 / 2,000 (0%). Active+Final PERMIT_DATE: 1,459 / 1,636 (89.2%).

Chronology: 0 `PERMIT < FILE` and 0 `FINAL < PERMIT` after repair (FILE always missing; filled finals are on or after Issued when both present).

## Artifacts

- Repair script: `agent/scripts/ca/data_repair_ca_goleta.py`
- Repaired sample parquet: `/Users/ekung/Dropbox/projects/la-permits-data-bot/repaired/permits_ca_goleta_repaired.parquet`

# Monterey County (CA) data repair — 2026-07-28

Monterey County was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. Accela Citizen Access JSON under `DATA` is task-event driven (`Issue|Issued*`, `Inspection|Finaled` / `File Completed`) with `DATA.status` and `DATA.date`. Main issues: 33 missing `STATUS_NORMALIZED` from unmapped planning statuses, all 1,999 `FILE_DATE` already correct, 276 Active/Final rows missing `PERMIT_DATE` with no Issue* event in `DATA` (not fillable), 382 Final rows missing `FINAL_DATE` of which 142 are fillable from Final* inspections / Event Complete / Cleared planning marks, and 3 spurious `FINAL_DATE` values on Expired Permit. Repair fills 33 statuses and 142 final dates, and clears 3 bad final dates; `FILE_DATE` and `PERMIT_DATE` unchanged.

## Jurisdiction selection

Walked `(JURISDICTION, STATE)` pairs in sample order and compared against `agent/scripts/{state}/data_repair_{state}_{city}.py`. First missing: **Monterey County, CA** → `agent/scripts/ca/data_repair_ca_monterey_county.py` (n=1,999).

## DATA schema

Accela portal scrape. Task event keys often have leading/trailing spaces (`Marked as `, ` on `). Nearly all rows have the full key set (`tasks`, `inspections`, `fees_details`, `contacts`, `conditions`, …); 5 sparse rows omit some of those.

| Schema | n | Description |
| --- | ---: | --- |
| `accela_full_issued_finaled` | 912 | Issue* + Inspection Finaled/File Completed (or planning Cleared / Event Complete) |
| `accela_full_issued` | 496 | Dated Issue* events, no final marks |
| `accela_full_other_events` | 459 | Other dated workflow events (no Issue* / final marks) |
| `accela_full_empty_tasks` | 115 | Tasks present but no dated events |
| `accela_full_finaled_only` | 12 | Final marks without Issue* |
| `accela_partial_issued` | 2 | Sparse key set + Issue* |
| `accela_partial_other_events` | 2 | Sparse key set + other events |
| `accela_partial_empty_tasks` | 1 | Sparse key set, no dated events |

Canonical fields: `DATA.status` → status; `DATA.date` (≈ `search_data.Created Date`) → file date; `Issue|Issued` / `Issued Online` / `Issued-Revised` or `Permit Issuance|Permit Issued` → permit date; `Inspection|Finaled` / `File Completed`, else passed Final* inspection, else Event Complete / Cleared / Staff Action approve → final date. `Inspection|Closed` is a mass 2016-03-30 batch stamp (95 rows) and is ignored.

## Field assessment

### STATUS_NORMALIZED

- Missing on 33 / 1,999. Causes: unmapped `STATUS_ORIGINAL` values — `condition compliance` (16), `cleared` (7), `planner assigned` (5), `request` (2), `given out` (2), `comment` (1). `DATA.status` is present and matches the title-cased original on every row.
- When present, mapping from `STATUS_ORIGINAL` already matched `DATA.status` (0 incorrect): `finaled`/`closed`/`complete`/`event complete`/`finished`/`conditional final`/`superseded`→Final, `issued`/`active`/`extended permit`/`reinstated permit`→Active, review/applied/incomplete→In Review, expired/withdrawn/void→Inactive.
- **Repair:** map unmapped `DATA.status` → **33 FILLED**, **0 FIXED**. Missing after: 0.
- Fills: null→Active 16 (`Condition Compliance`); null→Final 7 (`Cleared`); null→In Review 10 (`Planner Assigned` / `Request` / `Given Out` / `Comment`).

### FILE_DATE

- Missing on 0 / 1,999. Every value equals `DATA.date` (and `search_data.Created Date` when present).
- **Repair:** no changes (0 FILLED / 0 FIXED). Coverage remains 100%.

### PERMIT_DATE

- Missing on 589 / 1,999 (29.5%). When present, every value matches an Issue* / Permit Issued task date (0 incorrect).
- Among Active/Final before repair: Active 200/223 present (89.7%), Final 1,041/1,294 present (80.4%). Gaps are Closed Building Permit Application shells (203, no Issue task), Library Active rows (21, Document Submittal TBD only), Finaled without Issue* (32), Event Complete / Complete / Finished planning (18), plus 2 Issued/Issued-Revised shells with empty Issue task.
- **Repair:** **0 FILLED**, **0 FIXED** — no Active/Final gap has a dated Issue* event in `DATA`. Missing after: 589.
- Post-repair Active PERMIT coverage: 200/239 (83.7%); Final: 1,041/1,301 (80.0%).

### FINAL_DATE

- Missing on 1,084 / 1,999 (54.2%). Among Final before repair: 912/1,294 present (70.5%), all matching `Inspection|File Completed` (799) or `Inspection|Finaled` (110) (plus 3 odd early workflow stamps already present).
- 3 spurious values on Inactive (`Expired Permit`) equal `Inspection|File Completed` while status is expired → cleared.
- Fillable Final gaps: 133 Finaled rows with passed Final* inspection (`Status=Approval`) and no prior FINAL_DATE; 2 Event Complete with dated `Event Complete` marks; 7 Cleared planning rows (filled after status→Final) from `Annual Review|Cleared` or `Staff Action|No Appeal Approve*`.
- Not used: `Inspection|Closed` (all 95 on 2016-03-30 mass closeout). Closed APP* / Complete / Finished Final shells lack usable completion marks.
- **Repair:** **142 FILLED**, **3 FIXED** (cleared on Expired Permit). Missing after: 945.
- Post-repair Final FINAL coverage: 1,054/1,301 (81.0%).

## Repair performance

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | ---: | ---: | ---: | ---: |
| STATUS_NORMALIZED | 33 | 0 | 33 | 0 |
| FILE_DATE | 0 | 0 | 0 | 0 |
| PERMIT_DATE | 0 | 0 | 589 | 589 |
| FINAL_DATE | 142 | 3 | 1,084 | 945 |

Status distribution after repair: Final 1,301 · Active 239 · In Review 237 · Inactive 222 · missing 0.

Post-repair completeness by status:

| Status | n | FILE_DATE | PERMIT_DATE | FINAL_DATE |
| --- | ---: | ---: | ---: | ---: |
| Active | 239 | 100% | 83.7% | 0% |
| Final | 1,301 | 100% | 80.0% | 81.0% |
| In Review | 237 | 100% | 3.0% | 0% |
| Inactive | 222 | 100% | 73.0% | 0% |

Overall FILE_DATE coverage: 1,999 / 1,999 (100%). Active+Final PERMIT_DATE: 1,241 / 1,540 (80.6%).

Chronology: 1 `PERMIT < FILE` and 1 `FINAL < PERMIT` after repair — both pre-existing upstream values, not introduced by the repair.

## Artifacts

- Script: `agent/scripts/ca/data_repair_ca_monterey_county.py`
- Repaired parquet: `$AGENT_DATA_PATH/repaired/permits_ca_monterey_county_repaired.parquet`

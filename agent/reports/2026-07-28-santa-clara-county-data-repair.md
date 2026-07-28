# Santa Clara County (CA) data repair — 2026-07-28

Santa Clara County was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. Accela Citizen Access JSON under `DATA` has correct `FILE_DATE` for all 1,999 rows. `STATUS_NORMALIZED` needed 13 stale-status fixes (45 Survey Review shells remain unmapped). The main damage was in dates: `PERMIT_DATE` was often set to Ready-to-Issue rather than Issuance, and most populated `FINAL_DATE` values were copies of the issuance date. Repair fills/fixes 199 permit dates and 639 final dates from task and inspection events; large gaps remain on Accela shells without dated workflow marks.

## Jurisdiction selection

Walked `(JURISDICTION, STATE)` pairs in sample order and compared against `agent/scripts/{state}/data_repair_{state}_{city}.py`. First missing: **Santa Clara County, CA** → `agent/scripts/ca/data_repair_ca_santa_clara_county.py` (n=1,999).

## DATA schema

All rows share Accela top-level keys (`status`, `date`, `tasks`, `inspections`, `search_data`, `more_details`, …). Content variants recorded in `INFERRED_SCHEMA`:

| Schema | n | Description |
| --- | ---: | --- |
| `accela_tasks` | 1,126 | Dated workflow events under `tasks` |
| `accela_shell` | 872 | Task list present, no dated events |
| `accela_search_only` | 1 | No tasks |

Event keys use Accela ACA padding (`Marked as `, ` on `). Issuance marks are primarily `Issuance` → `Issued - Construction` / `Issued` / `Issued - Operations`; online and minor permits use `Submittal` → `Issued`. Final marks are primarily `Inspections` → `Final Inspection Complete`, `Closeout` → `Project Complete`, plus survey `Map Recording` / `Final Review` events and `*FINAL*` inspections.

## Field assessment

### STATUS_NORMALIZED

- Missing on 45 / 1,999 (2.3%) — all blank-status Survey Review shells with empty task events and blank `search_data.Status`. Not fillable from `DATA`.
- When `STATUS_ORIGINAL` matches `DATA.status`, the existing normalization is consistent (Finaled/Final/Closed*/Recorded → Final; Issued/Active → Active; review statuses → In Review; Expired/Void/Withdrawn → Inactive).
- **Issue:** on 13 rows `STATUS_NORMALIZED` followed stale `STATUS_ORIGINAL` while `DATA.status` / `search_data.Status` had advanced (e.g. `Finaled`/`Closed` still Active or In Review; `Expired` still Active; `Issued` / `Issue OK` still In Review).
- **Repair:** overwrite from `DATA.status` → **13 FIXED**, **0 FILLED**. Missing after: 45.

### FILE_DATE

- Already populated for 100% of rows; equals top-level `DATA.date` on every sample row.
- **Repair:** no changes (0 FILLED / 0 FIXED).

### PERMIT_DATE

- Missing on 1,652 / 1,999 (82.6%). Among Active/Final before repair: Active 79/288 present, Final 226/1,306 present.
- When present, ~240/346 dates that also have an Issuance mark match it; **106** are wrong — typically equal to `Staff Determination` / `Ready to Issue` (or a nearby review date) a few days before the true `Issuance` / `Issued*` date.
- Online and Minor permits often lack an `Issuance` task but carry `Submittal` / `Issued` (91 such rows without Issuance marks).
- Most Construction Permit / Application Request / Survey / Fire shells lack any issuance event → cannot recover from `DATA`.
- **Repair:** **93 FILLED** (mostly Submittal/Issued on Active/Final), **106 FIXED** (Ready-to-Issue → Issuance). Missing after: 1,559.
- Post-repair Active PERMIT coverage: 118/284 (41.5%); Final: 278/1,316 (21.1%).

### FINAL_DATE

- Missing on 1,712 / 1,999 (85.6%). Only 284/1,306 Final rows had a value before repair.
- **Major issue:** among populated `FINAL_DATE` values, the large majority equal the issuance / permit date (~200 Final rows), not a completion mark. Only ~10 matched a true final source before repair.
- Recoverable from (1) `Inspections` / `Final Inspection Complete`, (2) `Closeout` / `Project Complete` or `Final Permit Issued`, (3) survey `Map Recording` / `Final Review` marks, else (4) latest inspection titled `*FINAL*` with Approved/Passed/etc. Floor on repaired `PERMIT_DATE` when known.
- Three non-Final rows carried a spurious `FINAL_DATE` → cleared.
- **Repair:** **362 FILLED**, **277 FIXED** (including 3 clears). Missing after: 1,353.
- Post-repair Final FINAL coverage: 646/1,316 (49.1%). Remaining Final gaps are mostly shells and closed application / public-record / survey records without final workflow marks.

## Repair performance

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | ---: | ---: | ---: | ---: |
| STATUS_NORMALIZED | 0 | 13 | 45 | 45 |
| FILE_DATE | 0 | 0 | 0 | 0 |
| PERMIT_DATE | 93 | 106 | 1,652 | 1,559 |
| FINAL_DATE | 362 | 277 | 1,712 | 1,353 |

Status distribution after repair: Final 1,315 · Active 284 · In Review 237 · Inactive 118 · missing 45.

Post-repair completeness by status:

| Status | FILE_DATE | PERMIT_DATE | FINAL_DATE |
| --- | ---: | ---: | ---: |
| Active | 100% | 41.5% | 0% |
| Final | 100% | 21.1% | 49.1% |
| In Review | 100% | 0% | 0% |
| Inactive | 100% | 37.6% | 0% |

## Artifacts

- Script: `agent/scripts/ca/data_repair_ca_santa_clara_county.py` (`data_repair`)
- Repaired sample: `$AGENT_DATA_PATH/santa_clara_county_repaired_sample.parquet`

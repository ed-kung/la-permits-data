# Downey data repair — field assessment

**Summary:** Downey’s 2,001 sample records use a single Accela Citizen Access `tasks` schema. `FILE_DATE` is already complete and correct. `STATUS_NORMALIZED` has 5 missing and 12 stale mismatches vs `DATA.status` (upstream used `STATUS_ORIGINAL`). `PERMIT_DATE` and `FINAL_DATE` gaps are largely driven by empty `Permit Issuance` / Inspection task events after ~2023; OTC Approval events and Building Final inspections recover most of them. Repair script: `agent/scripts/downey_data_repair.py`.

## Data source

- Input: `MY_DATA_PATH/processed_data/permits_la_sample.parquet`
- Filter: `JURISDICTION == "Downey"` (n=2,001)
- Schema: 100% Accela `tasks` (`date`, `status`, `tasks`, `inspections`, `search_data`, …)
- Task event keys use spaced names (`'Marked as '`, `' on '`)

## Field assessment

### STATUS_NORMALIZED

| Issue | Count | Cause |
| --- | --- | --- |
| Missing | 5 | `DATA.status` is `None` or `''`; early-stage records with no mapped status |
| Incorrect | 12 | Normalized from stale `STATUS_ORIGINAL` (e.g. `"permit issued"`) while `DATA.status` updated to `Closed` / `Finaled` / `Permit Issued` / `Final Inspection Complete` |

Mapping is otherwise consistent with `DATA.status` (e.g. `Closed`/`Finaled`→Final, `Permit Issued`→Active, `Expired`/`Withdrawn`→Inactive).

**Repair:** remap from `DATA.status`; blank/None → `In Review`.

### FILE_DATE

- Missing: 0 / 2,001
- Equals `DATA.date` for all records
- **No repair needed**

### PERMIT_DATE

| Status (before) | Present | Notes |
| --- | --- | --- |
| Active | 147 / 377 (39%) | Main quality gap |
| Final | 1,250 / 1,298 (96%) | Mostly OK |
| In Review / Inactive | sparse | Not required |

**Causes of missing/incorrect values:**
1. Primary source is `Permit Issuance` → `Issued` task event (matches existing `PERMIT_DATE` for 1,532 / 1,542 records with that event).
2. 10 records have `PERMIT_DATE` ≠ Issued date → **FIXED**.
3. From ~2023 onward, `Permit Issuance` events are often empty even when status is `Permit Issued` (0 Issued events in 2024–2025 sample years).
4. For those gaps, `OTC Approval` / `OTC Review Approved` on Application Submittal / Preliminary Plan Review / Plans Distribution is a strong proxy (historically agrees with Issued ~95%).
5. Remaining Active/Final gaps are plan-check permits with neither Issued nor OTC events — no reliable issuance date in `DATA` (left missing rather than incorrectly using `FILE_DATE`).

### FINAL_DATE

| Status (before) | Present | Notes |
| --- | --- | --- |
| Final | 1,147 / 1,298 (88%) | 151 missing |

**Causes / sources:**
1. Upstream values match Inspection-task finals markers: `Finals Complete No CofO Req`, `Finals Complete`, or `Finaled` (1,147 / 1,147 existing Final dates).
2. Newer records often lack those task events; Building Final / `* Final` approved rows under `inspections` (including coded titles like `195 Building Final`) recover most gaps.
3. Fallback: `Closed` → `Closed` task event, then CO Issued.
4. ~35 Final records remain unfillable (no finals task event, no approved final inspection).

## Repair results (`data_repair`)

| Field | FILLED | FIXED | Missing before → after |
| --- | --- | --- | --- |
| STATUS_NORMALIZED | 5 | 12 | 5 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 253 | 10 | 458 → 205 |
| FINAL_DATE | 127 | 0 | 838 → 711 |

After repair (by status):

| Status | n | PERMIT_DATE | FINAL_DATE |
| --- | --- | --- | --- |
| Active | 368 | 346 (94.0%) | 0 (0%) |
| Final | 1,309 | 1,304 (99.6%) | 1,274 (97.3%) |
| In Review | 111 | 4 (3.6%) | 0 |
| Inactive | 213 | 142 (66.7%) | 16 (7.5%) |

`INFERRED_SCHEMA` is `"tasks"` for all 2,001 records.

## Artifacts

- Repair function: `agent/scripts/downey_data_repair.py` (`data_repair`)

# Cutler Bay (FL) data repair

**Summary:** Cutler Bay’s Accela-style `DATA` payload already maps status and application dates cleanly (`main.Status` → `STATUS_NORMALIZED`, `main.Applied` → `FILE_DATE`). The main defects were missing `PERMIT_DATE` on approved/Final rows without `Issued`, missing `FINAL_DATE` on Final rows that still had a completed `final - FINALIZE PERMIT` action, spurious `FINAL_DATE` on canceled Inactive rows, and two canceled rows that had completed finalize actions and should be Final. The repair script fills/fixes those fields and clears non-Final final dates.

## Jurisdiction selected

First `(JURISDICTION, STATE)` in `permits_fl_sample.parquet` without an existing `agent/scripts/{state}/data_repair_{state}_{city}.py`: **Cutler Bay, FL** (2,000 sample rows).

## DATA shape

Single Accela-style schema for all rows:

- Top-level keys: `main`, `details`, `actions`, `fees`, `routing`, `conditions`, `contractors`, `address`, `parcel`, `permit_number`, `valuation`, `description`
- Canonical fields live under `main`: `Status`, `Applied`, `Approved`, `Issued`, `Final`
- `actions[]` carries workflow steps (`Action`, `Comp'd Code`, `Comp'd Date`), including `collissue - COLLECT FEES/ISSUE PERMIT` and `final - FINALIZE PERMIT`

`INFERRED_SCHEMA` labels are `accela_{status}_{date_suffix}` (e.g. `accela_final_issued_finaled`).

## Field assessment

### STATUS_NORMALIZED

| `main.Status` | Upstream `STATUS_NORMALIZED` | n |
| --- | --- | ---: |
| final | Final | 1,764 |
| issued | Active | 91 |
| approved | Active | 11 |
| pending | In Review | 39 |
| canceled | Inactive | 60 |
| expired | Inactive | 35 |

Upstream mapping matched `main.Status` 1:1. Two **canceled** rows also had a completed `FINALIZE PERMIT` action (and `main.Final`); those were **FIXED** to Final. No missing statuses.

### FILE_DATE

- Populated on all 2,000 rows; every value equals `main.Applied` at day resolution.
- No fills or fixes needed.

### PERMIT_DATE

- When present (1,904 rows), always equals `main.Issued`.
- Missing (96): Active 11, Final 4, In Review 39, Inactive 42.
- In Review correctly lack issuance dates.
- Fillable gaps: `Issued` blank but `Approved` (or a completed issue/collissue action) present → **15 FILLED** (10 Active approved, 1 Final, 4 Inactive).
- Remaining Active/Final missing after repair: **4** (no Issued/Approved/issue action in DATA).

### FINAL_DATE

- When present, always equals `main.Final`.
- Final missing `FINAL_DATE`: 49; of those, 30 have a completed `FINALIZE PERMIT` action → **30 FILLED**.
- Remaining Final missing after repair: **19** (blank `main.Final`, empty/non-finalize actions).
- Inactive canceled carried `FINAL_DATE` on 57 rows; 2 were upgraded to Final (date retained), **55 FIXED** by clearing cancel/close stamps on still-Inactive rows.
- Active / In Review correctly had no `FINAL_DATE`.

## Repair performance

Script: `agent/scripts/fl/data_repair_fl_cutler_bay.py`  
Artifact: `$AGENT_DATA_PATH/repaired/permits_fl_cutler_bay_repaired.parquet`

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 0 | 2 | 0 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 15 | 0 | 96 → 81 |
| FINAL_DATE | 30 | 55 | 228 → 253 |

Missing `FINAL_DATE` rises because clearing 55 non-Final cancel stamps outweighs the 30 Final fills (228 − 30 + 55 = 253).

### Coverage after repair

| Status | n | FILE_DATE | PERMIT_DATE | FINAL_DATE |
| --- | ---: | ---: | ---: | ---: |
| Active | 102 | 100% | 99.0% | 0% |
| Final | 1,766 | 100% | 99.8% | 98.9% |
| In Review | 39 | 100% | 0% | 0% |
| Inactive | 93 | 100% | 59.1% | 0% |

No `FILE_DATE > PERMIT_DATE` or `PERMIT_DATE > FINAL_DATE` inversions after repair.

### Status transitions

- Inactive → Final: 2 (canceled + completed finalize)

## Not repairable from DATA

- 19 Final rows with no `main.Final` and no finalize action date
- 4 Active/Final rows with no Issued / Approved / issue-action date
- Pending In Review rows naturally lack permit/final dates

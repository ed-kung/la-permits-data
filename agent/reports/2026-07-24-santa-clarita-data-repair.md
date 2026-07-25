# Santa Clarita (CA) data repair

**Summary:** Santa Clarita was the first jurisdiction in `permits_la_sample.parquet` without an existing repair script. Its 1,999 sample records are Accela Citizen Access payloads (`tasks` + `status` + `date`), in full and sparse key-set variants. Upstream status mostly matched `DATA.status`, but 8 rows used a stale `STATUS_ORIGINAL` (e.g. Finaled labeled Active; Issued labeled In Review). `FILE_DATE` was already complete and correct. `PERMIT_DATE` / `FINAL_DATE` were populated only when workflow events existed (~25% of Final rows); most older Finaled stubs have empty task events and cannot be filled. Repair script: `agent/scripts/data_repair_ca_santa_clarita.py`.

## Data & schemas

| INFERRED_SCHEMA | n | Notes |
| --- | ---: | --- |
| `tasks_full` | 1,918 | Full ACA detail: contacts, fees_details, inspections, conditions, etc. |
| `tasks_sparse` | 81 | Core keys only (no contacts/fees/inspections); mostly Finaled stubs with empty events |

Canonical sources:

| Field | Source in DATA |
| --- | --- |
| `STATUS_NORMALIZED` | `DATA.status` |
| `FILE_DATE` | `DATA.date` (fallback `search_data.Date`) |
| `PERMIT_DATE` | `Permit Issuance` / `Issue MEP Permit`, `Issue BLD Permit`, or `Issued` (not `Ready to Issue`) |
| `FINAL_DATE` | latest `Inspections` / `Finaled` (fallback `C of O` / `Approved`) |

## Field assessment

### STATUS_NORMALIZED

| | Before | After |
| --- | ---: | ---: |
| Missing | 8 | 8 |
| Final | 1,529 | 1,532 |
| Active | 195 | 196 |
| In Review | 60 | 55 |
| Inactive | 207 | 208 |

- **FIXED 8:** `DATA.status` disagreed with upstream normalization from stale `STATUS_ORIGINAL`:
  - Finaled → Active (3) → Final
  - Issued → In Review (2) → Active
  - X_Re-Activated → In Review (2) → Active
  - Expired → In Review (1) → Inactive
- **FILLED 0 / unfillable 8:** Special Inspector records with blank `DATA.status` and blank `search_data.Status`.

### FILE_DATE

Already populated for all 1,999 rows and matches `DATA.date` exactly. **FILLED 0 / FIXED 0.**

### PERMIT_DATE

| | Before | After |
| --- | ---: | ---: |
| Missing | 1,491 | 1,489 |

- 507 of 508 existing values matched the earliest `Permit Issuance` / Issue* event.
- **FIXED 1:** PERMIT_DATE was `Ready to Issue` (2021-09-01) instead of `Issue BLD Permit` (2021-09-20).
- **FILLED 2:** Issued rows remapped In Review → Active, filled from `Issue MEP Permit`.
- **Unfillable:** remaining Active/Final gaps (51 Active, 1,174 Final) have no Issue* events — mostly pre-2018 migrations and sparse stubs with empty `tasks` events. Fee invoice dates were not used as proxies.
- Coverage after repair: Active 145/196 (74.0%), Final 358/1,532 (23.4%).

### FINAL_DATE

| | Before | After |
| --- | ---: | ---: |
| Missing | 1,632 | 1,629 |

- 366 of 367 existing values matched the first `Inspections` / `Finaled` event.
- **FIXED 1:** row with two Finaled events kept the earlier date (2018-07-18); corrected to the latest (2021-06-23).
- **FILLED 3:** Finaled rows remapped Active → Final, filled from `Inspections` / `Finaled`.
- **Unfillable:** 1,162 Final rows lack Finaled / C of O Approved events (empty workflow history). One Finaled row has empty `tasks` but pre-populated dates with nothing in DATA to validate — left unchanged.
- Coverage after repair: Final 370/1,532 (24.2%); no spurious FINAL_DATE on non-Final rows.

## Repair performance

```
STATUS_NORMALIZED:  FILLED   0   FIXED  8   missing    8 → 8
FILE_DATE:          FILLED   0   FIXED  0   missing    0 → 0
PERMIT_DATE:        FILLED   2   FIXED  1   missing 1491 → 1489
FINAL_DATE:         FILLED   3   FIXED  1   missing 1632 → 1629
```

## Artifacts

- Script: `agent/scripts/data_repair_ca_santa_clarita.py` (`data_repair`)
- Input: `MY_DATA_PATH/processed_data/permits_la_sample.parquet` (Santa Clarita / CA)
- Output: `AGENT_DATA_PATH/processed_data/permits_ca_santa_clarita_repaired.parquet`

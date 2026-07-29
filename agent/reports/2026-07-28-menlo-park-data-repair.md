# Menlo Park (CA) data repair — 2026-07-28

Menlo Park was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. Accela Citizen Access JSON under `DATA` supports correcting 79 wrong statuses (69 plans-`Approved` previously Active → In Review; 3 `issued` originals already `Finaled` in DATA → Final; 3 Red Tag previously Final → Active; 3 Issued status-lag In Review → Active; 1 Void lagging Pending Resubmittal → Inactive), filling 9 missing statuses, fixing 2 `FILE_DATE` values where Accela re-open bumped the top-level date past the original submittal, fixing 68 `PERMIT_DATE` values that matched Issuance Preparation / Payment Received instead of Issued Completed-on (plus clearing 6 spurious stamps), filling 1 missing Issued `PERMIT_DATE`, and filling 361 previously blank `FINAL_DATE` values from Finaled / Close out / final inspection / Convert Complete.

## Jurisdiction selection

Walked `(JURISDICTION, STATE)` pairs in sample order and compared against `agent/scripts/{state}/data_repair_{state}_{city}.py`. First missing: **Menlo Park, CA** → `agent/scripts/ca/data_repair_ca_menlo_park.py` (n=2,000).

## DATA schema

All 2,000 rows share Accela portal JSON with the same top-level keys (`address`, `date`, `status`, `tasks`, `search_data`, `inspections`, `fees_details`, …). Events use Menlo Park’s Accela scrape shape (`as` / `Completed on` keys, with HTML fallback), not the Chino-style `Marked as` / `on` pair. Canonical fields:

| Source | Field |
| --- | --- |
| `DATA.status` / `search_data.Status` (+ Issued / Finaled workflow upgrades) | `STATUS_NORMALIZED` |
| Earliest of `DATA.date`, `search_data.Date`, Application Intake / Submittal first-touch marks | `FILE_DATE` |
| Earliest Issued / Issued Revision / Issued Deferred `Completed on` (any task, typically Ready to Issue) | `PERMIT_DATE` |
| Earliest Finaled mark (fallback: Close out Complete/Closed, final-titled inspection Pass*, Convert to Building Permit Complete) | `FINAL_DATE` |

`INFERRED_SCHEMA` content variants:

| Schema | n | Description |
| --- | ---: | --- |
| `portal_application_only` | 1,495 | Top-level / application dates only (many older Finaled/Issued shells with empty TBD tasks) |
| `portal_final_only` | 206 | Final date present, no Issued |
| `portal_issued_finaled` | 177 | Issued* + final date evidence |
| `portal_issued` | 122 | Issued present, no final date |

## Field assessment

### STATUS_NORMALIZED

- Missing on 9 / 2,000 before repair. Upstream mostly mapped from `STATUS_ORIGINAL`, which lags `DATA.status` on 18 rows.
- Mis-mapping: `Approved` (plans / admin approval, not permit issuance) was stored as Active (69). None have a dated Issued event → In Review.
- Status lag: 3 rows with `STATUS_ORIGINAL=issued` but `DATA.status=Finaled` stayed Active → Final; 3 `action required` / `pending resubmittal` rows already `Issued` in DATA stayed In Review → Active; 1 `pending resubmittal` already `Void` → Inactive.
- Red Tag (open code-enforcement) was mapped to Final (3) → Active.
- Fillable NaNs: Pending Fee Payment / Issuance Preparation → In Review (6); Expired (pending-expiration original) / No Violations/Damage → Inactive (3).
- Converted Building Pre-Application (181) correctly stays Final (pre-app completed via Convert to Building Permit).
- Issued portal status is **not** promoted to Final solely because a Construction Phase Finaled mark exists.
- **Repair:** 9 FILLED, 79 FIXED. Missing after: 0.

### FILE_DATE

- Present on all 2,000; every value matched `DATA.date` before repair.
- 2 rows had Accela re-open / later bump of `DATA.date` after an earlier Submittal Accepted (2019-09-17 vs FILE 2020-06-17) or Submitted (2020-01-15 vs FILE 2020-02-20).
- **Repair:** 0 FILLED, 2 FIXED. Coverage 2,000 / 2,000 (100%). Chronology clean after repair.

### PERMIT_DATE

- Missing on 1,696 / 2,000 (84.8%). When an Issued* `Completed on` exists, 230 already matched; 68 were wrong — current values matched Issuance Preparation / Payment Received / Incomplete / plan-stamp dates one or more days before the actual Issued completion.
- 6 rows carried PERMIT without any Issued event (Action Required / Expired / Pending Expiration) → cleared.
- 1 Issued workflow row missing PERMIT (status-lag In Review → Active) → FILLED.
- Active Issued shells without dated Ready to Issue Issued events (288) and most older Finaled shells have empty/TBD task history → not fillable from DATA.
- **Repair:** 1 FILLED, 74 FIXED. Missing after: 1,701.
- Post-repair Active PERMIT coverage: 126/451 (27.9%); Final: 163/1,001 (16.3%); Active+Final: 289/1,452 (19.9%); In Review: 0/326 by design.

### FINAL_DATE

- Missing on all 2,000 before repair.
- Final fillable: 361 — 177 from Construction Phase (or other) Finaled, 181 from Convert to Building Permit Complete (Converted pre-apps), 2 from Close out Complete, 1 from final-titled inspection Pass.
- Remaining 640 Final rows (mostly older Finaled/Closed shells with empty tasks and no final inspection) stay missing.
- **Repair:** 361 FILLED, 0 FIXED. Missing after: 1,639.
- Post-repair Final FINAL coverage: 361/1,001 (36.1%); Active / In Review / Inactive: 0% by design.

## Repair performance

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | ---: | ---: | ---: | ---: |
| STATUS_NORMALIZED | 9 | 79 | 9 | 0 |
| FILE_DATE | 0 | 2 | 0 | 0 |
| PERMIT_DATE | 1 | 74 | 1,696 | 1,701 |
| FINAL_DATE | 361 | 0 | 2,000 | 1,639 |

Status distribution:

| | Before | After |
| --- | ---: | ---: |
| Final | 1,001 | 1,001 |
| Active | 517 | 451 |
| In Review | 255 | 326 |
| Inactive | 218 | 222 |
| (null) | 9 | 0 |

Chronology after repair: `PERMIT < FILE` = 0; `FINAL < PERMIT` = 0.

## Artifacts

- Repair script: `agent/scripts/ca/data_repair_ca_menlo_park.py`
- Repaired sample parquet: `$AGENT_DATA_PATH/repaired/permits_ca_menlo_park_repaired.parquet`

# Cupertino (CA) data repair — 2026-07-28

Cupertino was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. Accela Citizen Access JSON under `DATA` supports correcting 26 lagged/wrong statuses and filling 1 blank status, fixing 5 `FILE_DATE` values where Accela re-open bumped the top-level date past the original Application Submittal, filling 7 missing `PERMIT_DATE` values from Permit Issuance Issued events, filling 7 missing `FINAL_DATE` values from Final Inspection Complete, and clearing 2 spurious `FINAL_DATE` values on still-Issued Active rows. Most older Finaled shells (especially pre-2019) have empty/TBD Permit Issuance and Inspection tasks, so `PERMIT_DATE` / `FINAL_DATE` remain largely unfillable.

## Jurisdiction selection

Walked `(JURISDICTION, STATE)` pairs in sample order and compared against `agent/scripts/{state}/data_repair_{state}_{city}.py`. First missing: **Cupertino, CA** → `agent/scripts/ca/data_repair_ca_cupertino.py` (n=2,000).

## DATA schema

All rows have non-null Accela portal JSON with core keys (`address`, `date`, `status`, `tasks`, `search_data`, `details`, …). A handful of sparse rows omit optional blocks (`inspections`, `fees_details`, `contacts`, `conditions`, `related_records`). Canonical fields:

| Source | Field |
| --- | --- |
| `DATA.status` / `search_data.Status` (+ Issued workflow upgrade) | `STATUS_NORMALIZED` |
| Earliest of `DATA.date`, `search_data.Date`, Application Submittal Accepted* | `FILE_DATE` |
| Earliest Permit Issuance `Issued` | `PERMIT_DATE` |
| Earliest Inspection `Final Inspection Complete` | `FINAL_DATE` |

`INFERRED_SCHEMA` content variants:

| Schema | n | Description |
| --- | ---: | --- |
| `portal_application_only` | 1,512 | Top-level / Application Submittal dates only (no Issued / Final Inspection) |
| `portal_issued_finaled` | 271 | Issued + Final Inspection Complete |
| `portal_issued` | 203 | Issued present, no Final Inspection date |
| `portal_final_insp_only` | 14 | Final Inspection Complete, no Issued |

## Field assessment

### STATUS_NORMALIZED

- Missing on 1 / 2,000 (`BLD-2024-2331`, blank `DATA.status` SolarApp shell with TBD-only tasks) → FILLED as In Review.
- Upstream mapped from `STATUS_ORIGINAL`, which lags `DATA.status` on 13 Issued/Finaled rows and mis-maps plans-approved:
  - Issued still In Review (ready to issue / plan review) → Active (6)
  - Finaled still Active / In Review → Final (7)
  - Approved previously Active → In Review (3; plans approved, not issued)
- Additional workflow upgrades: In Review (`Pending` / `Submitted` / `Plan Review` / `Ready to Issue`) with a dated Permit Issuance Issued event → Active (10 of the 16 In Review→Active fixes overlap the Issued-lag set above; remainder are status-label lag with Issued evidence).
- Final Inspection Complete alone does **not** promote Issued → Final when `DATA.status` is still Issued.
- **Repair:** 1 FILLED, 26 FIXED. Missing after: 0.

### FILE_DATE

- Present on all 2,000; every value matched `DATA.date` before repair.
- 5 rows had Accela re-open bump `DATA.date` after the original Application Submittal Accepted* mark (and after Permit Issuance), producing `PERMIT_DATE < FILE_DATE`.
- **Repair:** 0 FILLED, 5 FIXED (earliest of top-level date / search_data.Date / Application Submittal). Coverage 2,000 / 2,000 (100%). Chronology clean after repair.

### PERMIT_DATE

- Missing on 1,533 / 2,000 (76.7%). When present, every value matched the earliest Permit Issuance Issued mark (0 incorrect; earlier apparent mismatches were Accela `Due on` dates misread as `on`).
- Issued events exist on only ~474 rows; most Finaled shells—especially file years 2000–2018—have empty or TBD-only Permit Issuance tasks.
- Fillable gaps: 7 status-lagged Issued/Finaled rows that already had Issued events but missing `PERMIT_DATE`.
- **Repair:** 7 FILLED, 0 FIXED. Missing after: 1,526.
- Post-repair Active PERMIT coverage: 184/226 (81.4%); Final: 290/1,630 (17.8%); Active+Final: 474/1,856 (25.5%).

### FINAL_DATE

- Missing on 1,722 / 2,000 (86.1%). When present, values match the **earliest** Final Inspection Complete mark (0 incorrect vs that rule; later marks appear to be reopen / follow-up).
- Final Inspection Complete available on 285 rows; 7 Final (after status promotion) were missing FINAL and fillable; 2 Active Issued rows carried FINAL despite portal status still Issued → cleared.
- Unfillable: vast majority of Finaled shells lack dated Final Inspection Complete events.
- **Repair:** 7 FILLED, 2 FIXED (clear). Missing after: 1,717.
- Post-repair Final FINAL coverage: 283/1,630 (17.4%); Active / In Review / Inactive: 0% by design.

## Repair performance

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | ---: | ---: | ---: | ---: |
| STATUS_NORMALIZED | 1 | 26 | 1 | 0 |
| FILE_DATE | 0 | 5 | 0 | 0 |
| PERMIT_DATE | 7 | 0 | 1,533 | 1,526 |
| FINAL_DATE | 7 | 2 | 1,722 | 1,717 |

Status distribution:

| | Before | After |
| --- | ---: | ---: |
| Final | 1,623 | 1,630 |
| Active | 219 | 226 |
| In Review | 121 | 108 |
| Inactive | 36 | 36 |
| (missing) | 1 | 0 |

Post-repair completeness by status:

| Status | n | FILE_DATE | PERMIT_DATE | FINAL_DATE |
| --- | ---: | ---: | ---: | ---: |
| Active | 226 | 100% | 81.4% | 0% |
| Final | 1,630 | 100% | 17.8% | 17.4% |
| In Review | 108 | 100% | 0% | 0% |
| Inactive | 36 | 100% | 0% | 0% |

Chronology after repair: 0 `PERMIT < FILE`, 0 `FINAL < PERMIT`.

## Artifacts

- Script: `agent/scripts/ca/data_repair_ca_cupertino.py`
- Repaired parquet: `$AGENT_DATA_PATH/repaired/permits_ca_cupertino_repaired.parquet`

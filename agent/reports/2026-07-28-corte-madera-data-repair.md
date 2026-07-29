# Corte Madera (CA) data repair — 2026-07-28

Corte Madera was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. Accela Citizen Access JSON under `DATA` supports correcting 178 wrong statuses (dominated by agency `Finalled` mis-mapped to In Review) and filling 14 blank statuses, filling 2 missing `PERMIT_DATE` values from Permit Issuance Issued events, filling 2 missing `FINAL_DATE` values from building-final / Close events, and clearing 2 spurious `FINAL_DATE` values on Inactive Expired rows. `FILE_DATE` was already complete and correct. Most older Finaled / Expired shells have empty or TBD-only Permit Issuance and Inspection tasks, so `PERMIT_DATE` / `FINAL_DATE` remain largely unfillable.

## Jurisdiction selection

Walked `(JURISDICTION, STATE)` pairs in sample order and compared against `agent/scripts/{state}/data_repair_{state}_{city}.py`. First missing: **Corte Madera, CA** → `agent/scripts/ca/data_repair_ca_corte_madera.py` (n=2,000).

## DATA schema

Accela portal JSON with core keys (`address`, `date`, `status`, `tasks`, `search_data`, `details`, …). 1,138 rows omit attachment / unpaid-fee blocks; 853 include them; 9 TMP Residential Resale shells are `search_data`-only. Canonical fields:

| Source | Field |
| --- | --- |
| `DATA.status` / `search_data.Status` (+ Issued workflow upgrade) | `STATUS_NORMALIZED` |
| Earliest of `DATA.date`, `search_data.Date`, Application Submittal Accepted* | `FILE_DATE` |
| Earliest Permit Issuance `Issued` | `PERMIT_DATE` |
| Earliest Inspection `Bldg Final Inspection Complete` / `Final Inspection Complete` (fallback: Close `Closed`) | `FINAL_DATE` |

`INFERRED_SCHEMA` content variants:

| Schema | n | Description |
| --- | ---: | --- |
| `portal_application_only` | 1,626 | Top-level / Application Submittal dates only (no Issued / final-inspection) |
| `portal_issued_finaled` | 176 | Issued + final-inspection / Close date |
| `portal_issued` | 164 | Issued present, no final date |
| `portal_final_insp_only` | 24 | Final date present, no Issued |
| `search_data_only` | 9 | TMP shells with blank Status |
| `portal_empty_tasks` | 1 | Tasks present, no usable dates |

## Field assessment

### STATUS_NORMALIZED

- Missing on 14 / 2,000: 4 Comment Letter Sent, 1 Application Pending, and 9 blank-status TMP `search_data` shells → FILLED In Review.
- Dominant upstream bug: agency status `Finalled` (spelling variant of Finaled) was mapped via `STATUS_ORIGINAL=finalled` to **In Review** (160 rows). Those rows already carry `PERMIT_DATE` / `FINAL_DATE` from Accela workflow and should be Final.
- Other status lag / mis-maps:
  - Expired still Active → Inactive (7)
  - Finaled still Active → Final (2)
  - Issued still In Review / Inactive → Active (3)
  - In Review with dated Permit Issuance Issued → Active (1 additional beyond the Issued-lag set)
  - Approved previously Active → In Review (4; plans approved, not issued)
- Final inspection Complete alone does **not** promote Issued → Final when `DATA.status` is still Issued. Expired is sticky Inactive even when an Issued event exists.
- **Repair:** 14 FILLED, 178 FIXED. Missing after: 0.

### FILE_DATE

- Present on all 2,000 before repair; every value matched the earliest of `DATA.date` / `search_data.Date` / Application Submittal Accepted* (0 incorrect).
- **Repair:** 0 FILLED, 0 FIXED. Coverage 2,000 / 2,000 (100%).

### PERMIT_DATE

- Missing on 1,662 / 2,000 (83.1%). When present and an Issued event exists, values match the earliest Permit Issuance Issued mark (0 incorrect among 338 comparable rows).
- Issued events exist on only ~340 rows; most Finaled / Expired shells—especially older Accela conversions—have empty or TBD-only Permit Issuance tasks.
- Fillable gaps: 2 Active/Final rows with Issued events but missing `PERMIT_DATE`.
- After promoting Finalled → Final, those 142 already-populated permit dates become correctly associated with Final rather than In Review; no value change needed.
- **Repair:** 2 FILLED, 0 FIXED. Missing after: 1,660.
- Post-repair Active PERMIT coverage: 86/137 (62.8%); Final: 214/1,387 (15.4%); Active+Final: 300/1,524 (19.7%).

### FINAL_DATE

- Missing on 1,802 / 2,000 (90.1%). When present and a final-inspection event exists, values match the earliest `Bldg Final Inspection Complete` / `Final Inspection Complete` mark (0 incorrect among 198 comparable rows).
- Final-inspection / Close evidence available on ~200 rows. 2 Final rows (after status promotion / Close fallback) were missing FINAL and fillable; 2 Inactive Expired rows carried FINAL → cleared.
- Unfillable: vast majority of Finaled shells lack dated final-inspection events (TBD-only Inspection / Close tasks).
- **Repair:** 2 FILLED, 2 FIXED (clear). Missing after: 1,802 (net unchanged).
- Post-repair Final FINAL coverage: 198/1,387 (14.3%); Active / In Review / Inactive: 0% by design.

## Repair performance

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | ---: | ---: | ---: | ---: |
| STATUS_NORMALIZED | 14 | 178 | 14 | 0 |
| FILE_DATE | 0 | 0 | 0 | 0 |
| PERMIT_DATE | 2 | 0 | 1,662 | 1,660 |
| FINAL_DATE | 2 | 2 | 1,802 | 1,802 |

Status distribution:

| | Before | After |
| --- | ---: | ---: |
| Final | 1,225 | 1,387 |
| Inactive | 382 | 388 |
| Active | 145 | 137 |
| In Review | 234 | 88 |
| (missing) | 14 | 0 |

Chronology after repair: `PERMIT < FILE` = 0; `FINAL < PERMIT` = 0.

## Artifacts

- Script: `agent/scripts/ca/data_repair_ca_corte_madera.py`
- Repaired parquet: `$AGENT_DATA_PATH/repaired/permits_ca_corte_madera_repaired.parquet`

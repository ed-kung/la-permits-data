# Tehama County (CA) data repair — 2026-07-28

Tehama County was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. CitizenServe `main`/`extra`/`location` JSON already has complete `FILE_DATE` (from `dateCreated`) and complete `STATUS_NORMALIZED` mirrored from coarse `main.status` / `STATUS_ORIGINAL`, but legacy ASI status labels contradict that mapping on 133 rows, five rows have `STATUS_ORIGINAL` out of sync with `main.status`, `FILE_DATE` lags or leads `dateSubmitted` on 67 rows (including 10 bulk-migration shells), and `PERMIT_DATE` / `FINAL_DATE` are empty on all 2,000 rows. Repair fixes 138 statuses and 67 file dates, and fills 145 final dates from code-enforcement close ASI `17056`. No issuance timestamps exist in DATA, so `PERMIT_DATE` stays missing.

## Jurisdiction selection

Walked `(JURISDICTION, STATE)` pairs in sample order and compared against `agent/scripts/{state}/data_repair_{state}_{city}.py`. First missing: **Tehama County, CA** → `agent/scripts/ca/data_repair_ca_tehama_county.py` (n=2,000).

## DATA schema

All rows share CitizenServe top-level keys (`main`, `extra`, `location`). `main.status` codes map to portal lifecycle (`0=draft`, `1=active`, `2=complete`, `-1=stopped`). Migrated Accela families carry numeric ASI status / application-date fields; modern online forms mostly carry contractor / valuation / checklist fields without issuance or finaling timestamps. Variants recorded in `INFERRED_SCHEMA`:

| Schema | n | Description |
| --- | ---: | --- |
| `citizenserve_legacy_building_v1` | 1,020 | Building Permit v1; ASI status `16681`, app date `16674` |
| `citizenserve_modern_building` | 430 | Building Permit / solar / electrical / re-roof / HVAC / demo |
| `citizenserve_code_closed` | 145 | Code Enforcement with close date `17056` |
| `citizenserve_legacy_reroof` | 126 | Residential Re-Roofing; ASI `16701` / `16694` |
| `citizenserve_legacy_mh` | 120 | Manufactured Home; ASI `16691` / `16684` |
| `citizenserve_legacy_ag_exempt` | 69 | Agricultural Building Exemption; ASI `16711` / `16704` |
| `citizenserve_code` | 33 | Code Enforcement without close date |
| `citizenserve_plot_plan` | 28 | PPA / plot-plan shells |
| `citizenserve_empty_extra` | 12 | empty `extra` |
| `citizenserve_marijuana` | 10 | Marijuana Enforcement Case |
| `citizenserve_planning` | 5 | merger / lot line / use permit |
| `citizenserve_form_other` | 2 | remaining named forms |

## Field assessment

### STATUS_NORMALIZED

- Fully populated (0 missing). Upstream mapped 1:1 from `STATUS_ORIGINAL` (`complete`→Final, `active`→Active, `draft`→In Review, `stopped`→Inactive), which almost always matches `main.status`.
- **Incorrect vs DATA:**
  - Legacy ASI labels (`16681` / `16701` / `16691` / `16711` / `17062`) often finer-grained than `main.status=2` (complete):
    - `EXPIRED` (62) / `CANCELLED` (27) / `VOID` (1) left Final → FIXED to Inactive
    - `ACTIVE` (33) / `APPROVED` (2) / `AVTIVE` typo (1) left Final → FIXED to Active
    - `FINALED` (2) left Active → FIXED to Final
    - `PEND ISSUE` (3) left Active/Final/Inactive → FIXED to In Review
    - CE `ACTIVE` (1) left Inactive → FIXED to Active
  - Five rows where `STATUS_ORIGINAL` disagrees with `main.status` (no ASI): four Building Permit rows with `status=2` but `STATUS_ORIGINAL=active` → FIXED to Final; one with `status=1` but `stopped` → FIXED to Active.
- `RENEWED` (25) already Final via `main.status=2`; left as Final.
- **Repair:** 0 FILLED, 138 FIXED. Missing after: 0.

### FILE_DATE

- Fully populated; every value equals `main.dateCreated` calendar day (0 missing).
- Prefer `dateSubmitted` when present: 67 calendar-day disagreements → FIXED.
  - 57 late online submits (`dateSubmitted` after `dateCreated`)
  - 10 bulk-migration shells stamped `2020-08-21` on create, with historical `dateSubmitted` matching ASI application dates (`16674`)
- When both present, ASI app/open dates (`16674` / `16694` / `16684` / `16704` / `17058`) always match `dateSubmitted` (0 conflicts).
- **Repair:** 0 FILLED, 67 FIXED. Coverage 2,000 / 2,000 (100%).

### PERMIT_DATE

- Missing on 2,000 / 2,000. No `Date Issued`, `Permit Issuance Date`, or equivalent in `extra` (modern or legacy). Workers-comp and NOV/hearing dates are not issuance.
- **Repair:** 0 FILLED, 0 FIXED. Missing after: 2,000.
- Post-repair Active+Final PERMIT coverage: 0 / 1,852 (0%).

### FINAL_DATE

- Missing on 2,000 / 2,000.
- Fillable: Code Enforcement ASI `17056` (close date) present on all 145 `CLOSED` rows; after status repair these remain Final → FILLED.
- Unfillable: legacy `FINALED` building / reroof / MH / ag rows and modern building / plot-plan / planning / marijuana shells have no finaling timestamp.
- No spurious FINAL_DATE values to clear (column was empty).
- **Repair:** 145 FILLED, 0 FIXED. Missing after: 1,855.
- Post-repair Final FINAL coverage: 145 / 1,604 (9.0%). Active / In Review / Inactive: 0% by design.

## Repair performance

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | ---: | ---: | ---: | ---: |
| STATUS_NORMALIZED | 0 | 138 | 0 | 0 |
| FILE_DATE | 0 | 67 | 0 | 0 |
| PERMIT_DATE | 0 | 0 | 2,000 | 2,000 |
| FINAL_DATE | 145 | 0 | 2,000 | 1,855 |

Status distribution:

| | Before | After |
| --- | ---: | ---: |
| Final | 1,726 | 1,604 |
| Active | 217 | 248 |
| In Review | 37 | 41 |
| Inactive | 20 | 107 |
| (missing) | 0 | 0 |

Post-repair completeness by status:

| Status | n | FILE_DATE | PERMIT_DATE | FINAL_DATE |
| --- | ---: | ---: | ---: | ---: |
| Active | 248 | 100% | 0% | 0% |
| Final | 1,604 | 100% | 0% | 9.0% |
| In Review | 41 | 100% | 0% | 0% |
| Inactive | 107 | 100% | 0% | 0% |

## Artifacts

- Repair script: `agent/scripts/ca/data_repair_ca_tehama_county.py`
- Function: `data_repair(df)` → adds `INFERRED_SCHEMA` and `{FIELD}_FLAG` columns (`FILLED` / `FIXED`)

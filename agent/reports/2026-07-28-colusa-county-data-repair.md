# Colusa County (CA) data repair — 2026-07-28

Colusa County was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. CitizenServe/OpenGov JSON under `DATA` supports correcting 7 Active→Final status lags (final-inspection evidence), filling 1 VOID null status as Inactive, fixing 395 `FILE_DATE` values (316 legacy ASI application dates earlier than system entry/issuance, 45 `dateCreated`→`dateSubmitted`, 34 sentinel `1900-01-01` EH facility stamps), filling 236 missing `FILE_DATE` values (mostly historical building ASI `24954`), filling 670 previously blank `PERMIT_DATE` values (legacy `24958`/`24954`, well `Date Approved`, EH `Permit Active Date`, modern `Permit Issuance Date`), and filling 89 `FINAL_DATE` values from final-inspection / code-resolution fields.

## Jurisdiction selection

Walked `(JURISDICTION, STATE)` pairs in sample order and compared against `agent/scripts/{state}/data_repair_{state}_{city}.py`. First missing: **Colusa County, CA** → `agent/scripts/ca/data_repair_ca_colusa_county.py` (n=2,000).

## DATA schema

All 2,000 rows share CitizenServe / OpenGov JSON with top-level keys `main`, `extra`, and `location`. `extra` mixes numeric ASI field IDs (legacy building / planning / well / EH migrations) and named modern form fields. Content variants:

| Schema | n | Description |
| --- | ---: | --- |
| `citizenserve_building_legacy` | 572 | Numeric ASI dates `24954` / `24958` |
| `citizenserve_form_other` | 424 | Other named/numeric forms |
| `citizenserve_planning` | 343 | Universal Planning Application |
| `citizenserve_employee_daily` | 318 | Employee Daily Template |
| `citizenserve_well` | 151 | Water Well Application |
| `citizenserve_eh_facility` | 81 | Environmental Health facility permits |
| `citizenserve_building_finaled` | 59 | `Final Inspection Date` present |
| `citizenserve_code` | 50 | Code Compliance Complaint |
| `citizenserve_building_issued` | 1 | `Permit Issuance Date` only (no final inspection) |
| `citizenserve_empty_extra` | 1 | Empty `extra` |

Canonical fields:

| Source | Field |
| --- | --- |
| `main.status` (0/1/2/-1) + final-inspection / VOID upgrades | `STATUS_NORMALIZED` |
| `dateSubmitted` else `dateCreated`; else earliest ASI/form application (`24954`, `25014`, `25044`, …); reject `1900-01-01` | `FILE_DATE` |
| `Permit Issuance Date` / `24958` / `Date Approved` / `Permit Active Date` / `24954` fallback | `PERMIT_DATE` |
| `Final Inspection Date` / `Date of Final Inspection` / code `24981` when Final | `FINAL_DATE` |

## Field assessment

### STATUS_NORMALIZED

- Missing on 1 / 2,000 before repair: VOID water-well shell (`streetName`/`extra` all VOID, `main.status` null) → FILLED as Inactive.
- Upstream mapping from `STATUS_ORIGINAL` (`draft`/`active`/`complete`/`stopped`) already matched `main.status` (0/1/2/-1) on 1,999 rows.
- 7 Active rows already had `Final Inspection Date` or `Date of Final Inspection` → FIXED to Final.
- `Primary Status` (`CLEAR`) is a bond/contractor flag, not lifecycle — ignored.
- **Repair:** 1 FILLED, 7 FIXED. Missing after: 0.

### FILE_DATE

- Missing on 250 / 2,000; plus 34 EH facility rows stored sentinel `1900-01-01` (treated as incorrect).
- When present, FILE almost always matched `dateCreated` (1,750); 45 rows had a later `dateSubmitted` → FIXED to submittal date (OpenGov convention).
- Legacy building ASI `24954` is an earlier paper/application date than system `dateCreated`/`24958` on 316 rows → FIXED FILE to `24954`.
- Historical building shells with no system dates: 231 FILLED from `24954`; 5 more from alternate stamp `24960`.
- EH sentinel `1900-01-01` → FIXED from `Permit Active Date` (prefer over period-start `25007`).
- Residual: 14 empty building shells still lack any application date.
- **Repair:** 236 FILLED, 395 FIXED. Coverage 1,986 / 2,000 (99.3%).

### PERMIT_DATE

- Missing on all 2,000 before repair.
- Fills: legacy issuance `24958` (341), single-date legacy `24954` on Active/Final (231), well `Date Approved` (37), EH `Permit Active Date` (33), modern `Permit Issuance Date` (22), `24960` (5), `25007` (1).
- Stale planning `Approval Date` values that predate FILE are skipped (would invert chronology).
- Active coverage after repair: 55/368 (14.9%). Final: 612/1,492 (41.0%). Most modern building / employee-daily / planning shells have no issuance field.
- **Repair:** 670 FILLED, 0 FIXED. Missing after: 1,330.
- Chronology: 0 `PERMIT < FILE` after repair.

### FINAL_DATE

- Missing on all 2,000 before repair.
- Fills when effective Final: `Final Inspection Date` (59), well `Date of Final Inspection` (16), code-compliance resolution `24981` (14).
- Residual Final without final-inspection evidence stay missing (legacy complete shells rarely store a close-out date).
- **Repair:** 89 FILLED, 0 FIXED. Missing after: 1,911.
- Post-repair Final FINAL coverage: 89/1,492 (6.0%); Active / In Review / Inactive: 0% by design.

## Repair performance

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | ---: | ---: | ---: | ---: |
| STATUS_NORMALIZED | 1 | 7 | 1 | 0 |
| FILE_DATE | 236 | 395 | 284* | 14 |
| PERMIT_DATE | 670 | 0 | 2,000 | 1,330 |
| FINAL_DATE | 89 | 0 | 2,000 | 1,911 |

\*FILE missing-before counts 250 nulls + 34 sentinel `1900-01-01` rows.

Status distribution:

| | Before | After |
| --- | ---: | ---: |
| Final | 1,485 | 1,492 |
| Active | 375 | 368 |
| In Review | 105 | 105 |
| Inactive | 34 | 35 |
| (null) | 1 | 0 |

## Artifacts

- Repair script: `agent/scripts/ca/data_repair_ca_colusa_county.py`
- Repaired sample parquet: `$AGENT_DATA_PATH/repaired/permits_ca_colusa_county_repaired.parquet`

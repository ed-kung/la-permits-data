# Cypress (CA) data repair — 2026-07-28

Cypress was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. CitizenServe `main`/`extra`/`location` JSON has complete `FILE_DATE` (from `dateCreated`) and mostly correct `STATUS_NORMALIZED` from `STATUS_ORIGINAL`, but 11 `complete` (`main.status=2`) rows were still labeled Active, `FILE_DATE` lagged `dateSubmitted` on 249 rows, and `PERMIT_DATE` / `FINAL_DATE` are empty on all 2,000 rows. Repair fixes 11 statuses and 249 file dates, and fills 5 final dates from `Inspection Final Date`. No reliable issuance field exists in DATA.

## Jurisdiction selection

Walked `(JURISDICTION, STATE)` pairs in sample order and compared against `agent/scripts/{state}/data_repair_{state}_{city}.py`. First missing: **Cypress, CA** → `agent/scripts/ca/data_repair_ca_cypress.py` (n=2,000).

## DATA schema

All rows share CitizenServe top-level keys (`main`, `extra`, `location`). `main.status` codes map to `STATUS_ORIGINAL` (`0=draft`, `1=active`, `2=complete`, `-1=stopped`). Unlike Buena Park, Cypress forms do not carry named `Status` / `Date Issued` / `Date Finaled` ASI fields. A handful of Tenant Improvement rows expose `Inspection Final Date`. Variants recorded in `INFERRED_SCHEMA`:

| Schema | n | Description |
| --- | ---: | --- |
| `citizenserve_building_trade` | 941 | Building / trade / ADU / TI / tract forms |
| `citizenserve_solar` | 213 | Solar / SolarAPP+ |
| `citizenserve_debris` | 182 | Construction Debris Disposal (C&D) |
| `citizenserve_public_works` | 169 | Public Works |
| `citizenserve_daily_activity` | 102 | Building and Safety Daily Activity |
| `citizenserve_records_request` | 96 | Request a Copy of a Building Permit |
| `citizenserve_transport` | 93 | Transportation / oversize parking |
| `citizenserve_fog` | 92 | Fats, Oils, and Grease (FOG) |
| `citizenserve_form_other` | 55 | Other named forms |
| `citizenserve_stormwater` | 52 | Stormwater quality / requirements |
| `citizenserve_inspection_final` | 5 | Parseable `Inspection Final Date` |

## Field assessment

### STATUS_NORMALIZED

- Missing on 0 / 2,000. Upstream map from `STATUS_ORIGINAL` matches `main.status` on 1,989 rows (Active 839 · Final 723 · In Review 401 · Inactive 26 for the aligned subset).
- **Incorrect:** 11 rows have live `main.status=2` (complete) but `STATUS_ORIGINAL=active` / `STATUS_NORMALIZED=Active` (mostly Tract New Home, plus reroof / solar / HVAC / mechanical). Root cause: normalization keyed off lagged `STATUS_ORIGINAL` rather than numeric `main.status`.
- **Repair:** map `main.status` → **0 FILLED**, **11 FIXED** (Active→Final). Missing after: 0.

### FILE_DATE

- Present on 2,000 / 2,000. Every value matched the UTC calendar day of `main.dateCreated`.
- **Issue:** 249 rows have `dateSubmitted` on a later calendar day than `dateCreated` (median gap 3 days; max 924). Application/submittal date should prefer submitted. Drafts (`status=0`, n=401) correctly lack `dateSubmitted` and keep `dateCreated`.
- **Repair:** prefer `dateSubmitted`, else `dateCreated` → **0 FILLED**, **249 FIXED**. Coverage remains 100%.

### PERMIT_DATE

- Missing on 2,000 / 2,000 (100%). No previously populated values to validate.
- Should be populated for Active and Final (1,573 after status repair). DATA has no issuance/approval field.
- Rejected proxies: `expirationDate` (~180/365-day validity window), `lastUpdatedDate` (later edits), unlabeled numeric ASI dates (`26368` / `26796`, co-occur with TCO fields), `TCO Expiration Date`, Public Works / Transportation `extra['Date']` (mirrors submittal).
- **Repair:** **0 FILLED**, **0 FIXED**. Missing after: 2,000.
- Post-repair Active+Final PERMIT coverage: 0 / 1,573 (0%).

### FINAL_DATE

- Missing on 2,000 / 2,000 (100%).
- Recoverable source: `extra['Inspection Final Date']` on Final Tenant Improvement rows (5).
- Rejected proxies: `lastUpdatedDate`, TCO dates, numeric ASI stamps (appear on Active as well as Final).
- **Repair:** **5 FILLED**, **0 FIXED**. Missing after: 1,995.
- Post-repair Final FINAL coverage: 5 / 734 (0.7%). No FINAL_DATE written on non-Final rows.

## Repair performance

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | ---: | ---: | ---: | ---: |
| STATUS_NORMALIZED | 0 | 11 | 0 | 0 |
| FILE_DATE | 0 | 249 | 0 | 0 |
| PERMIT_DATE | 0 | 0 | 2,000 | 2,000 |
| FINAL_DATE | 5 | 0 | 2,000 | 1,995 |

Status distribution:

| | Before | After |
| --- | ---: | ---: |
| Active | 850 | 839 |
| Final | 723 | 734 |
| In Review | 401 | 401 |
| Inactive | 26 | 26 |

Status transitions (FIXED): Active→Final 11.

Post-repair completeness by status:

| Status | n | FILE_DATE | PERMIT_DATE | FINAL_DATE |
| --- | ---: | ---: | ---: | ---: |
| Active | 839 | 100% | 0% | 0% |
| Final | 734 | 100% | 0% | 0.7% |
| In Review | 401 | 100% | 0% | 0% |
| Inactive | 26 | 100% | 0% | 0% |

Chronology after repair: `PERMIT < FILE` = 0; `FINAL < PERMIT` = 0.

## Artifacts

- Repair script: `agent/scripts/ca/data_repair_ca_cypress.py` (`data_repair` entry point)
- Repaired sample: `AGENT_DATA_PATH/repaired/permits_ca_cypress_repaired.parquet`

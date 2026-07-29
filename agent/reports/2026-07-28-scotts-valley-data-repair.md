# Scotts Valley (CA) data repair

**Summary:** For the first sample jurisdiction lacking a repair script (Scotts Valley, CA; 2,000 rows), CitizenServe `main.status` lagged `STATUS_ORIGINAL` on **272** rows → FIXED. `FILE_DATE` matched `dateCreated` while a later `dateSubmitted` existed on **229** rows → FIXED; **1** null FILE_DATE was FILLED from `dateSubmitted`. **25** pre-portal shells keep an earlier FILE_DATE that does not match `dateCreated` (no `dateSubmitted`) and were left as-is. `PERMIT_DATE` / `FINAL_DATE` have no usable stamps in DATA and remain empty on all rows. After repair, FILE_DATE is 100%; Active/Final PERMIT_DATE and Final FINAL_DATE coverage stay 0%.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_ca_sample.parquet` and walked `(JURISDICTION, STATE)` in order. The first pair without `agent/scripts/{state}/data_repair_{state}_{city}.py` was **Scotts Valley, CA**.

## DATA schemas (`INFERRED_SCHEMA`)

All rows share CitizenServe top-level keys (`main`, `extra`, `location`). `main.status` codes map to lifecycle labels (`0=draft`, `1=active`, `2=complete`, `-1=stopped`). Variants are classified by `recordTypeName`:

| Schema | n |
| --- | ---: |
| `citizenserve_residential_building` | 889 |
| `citizenserve_electrical` | 467 |
| `citizenserve_mechanical` | 200 |
| `citizenserve_plumbing` | 160 |
| `citizenserve_commercial_building` | 151 |
| `citizenserve_solar` | 94 |
| `citizenserve_encroachment` | 30 |
| `citizenserve_practice` | 7 |
| `citizenserve_address` | 2 |

Canonical fields: `main.status`; `dateSubmitted` / `dateCreated`. No Issued / Finaled companion dates or ASI pairs appear in `extra`.

## Field assessment

### STATUS_NORMALIZED

Before: Active 867 / In Review 551 / Final 502 / Inactive 80 / missing 0.

Upstream mapped 1:1 from `STATUS_ORIGINAL` (`active` / `draft` / `complete` / `stopped`), which lags live `main.status` on 272 rows:

| main.status | STATUS_ORIGINAL | was | expected | n |
| --- | --- | --- | --- | ---: |
| 2 | active | Active | Final | 103 |
| -1 | active | Active | Inactive | 91 |
| 1 | complete | Final | Active | 65 |
| 0 | active | Active | In Review | 11 |
| 0 | complete | Final | In Review | 2 |

Transitions: Active→Final 103; Active→Inactive 91; Final→Active 65; Active→In Review 11; Final→In Review 2.

After: Active 727 / In Review 564 / Final 538 / Inactive 171.

### FILE_DATE

Nearly fully populated (1 missing). Most values equaled `main.dateCreated` at calendar-day resolution. Prefer `dateSubmitted` when present: **229** disagreements (submitted 1–468 days later; median 3) → FIXED. One Final shell (`BP-23-256`) had null FILE_DATE / null `dateCreated` but a `dateSubmitted` → FILLED.

**25** early shells (mostly 2021–2022 trade permits) carry a FILE_DATE earlier than portal `dateCreated` with null `dateSubmitted` — likely pre-migration application dates. Those are preserved (not overwritten with the import stamp). Drafts without `dateSubmitted` keep `dateCreated`. Coverage after repair: 2,000 / 2,000.

### PERMIT_DATE

Missing on all 2,000 rows. No `Permit Issued` / `Issue` / `Approval Date`, no Issued ASI companion pairs, and no Accela-style status+date fields. `extra['Primary Status']` is a contractor CLEAR/Susp flag. `expirationDate` and `lastUpdatedDate` are not safe issuance proxies. Left as-is (0 fills).

### FINAL_DATE

Missing on all 2,000 rows. No `Permit Finaled` / `Inspection Final` / `Completion Date`. Department “Final Sign Off” checkboxes are application attestations, not completion stamps. Left as-is (0 fills).

## Repair performance

Script: `agent/scripts/ca/data_repair_ca_scotts_valley.py` (`data_repair`).

Artifact: `AGENT_DATA_PATH/repaired/permits_ca_scotts_valley_repaired.parquet`

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 0 | 272 | 0 → 0 |
| FILE_DATE | 1 | 229 | 1 → 0 |
| PERMIT_DATE | 0 | 0 | 2,000 → 2,000 |
| FINAL_DATE | 0 | 0 | 2,000 → 2,000 |

After repair:

- FILE_DATE: 2,000 / 2,000 (100%)
- PERMIT_DATE: Active 0%; Final 0%; In Review / Inactive 0%
- FINAL_DATE: Final 0%; absent on non-Final
- Remaining ideal gaps: 1,265 Active/Final missing PERMIT_DATE; 538 Final missing FINAL_DATE; 0 missing FILE_DATE

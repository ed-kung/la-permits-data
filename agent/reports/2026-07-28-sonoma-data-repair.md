# Sonoma (CA) data repair

**Summary:** For the first sample jurisdiction lacking a repair script (Sonoma, CA; 2,000 rows), CitizenServe `main.status` lagged `STATUS_ORIGINAL` on 113 rows and form Withdrawn/Expired/Completed labels required 19 further overrides (**132** status FIXED). `FILE_DATE` was everywhere equal to `dateCreated`; **326** rows were FIXED to later `dateSubmitted`. `PERMIT_DATE` / `FINAL_DATE` were empty on all rows; **313** issuance fills came from Issued ASI/named-Status companion dates, and **17** final fills from encroachment Completed / Decision Date. After repair, FILE_DATE is 100%; Active/Final PERMIT_DATE coverage is ~20% (most shells lack Issued stamps); Final FINAL_DATE remains sparse (~3%).

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_ca_sample.parquet` and walked `(JURISDICTION, STATE)` in first-appearance order. The first pair without `agent/scripts/{state}/data_repair_{state}_{city}.py` was **Sonoma, CA**.

## DATA schemas (`INFERRED_SCHEMA`)

All rows share CitizenServe top-level keys (`main`, `extra`, `location`). `main.status` codes map to `STATUS_ORIGINAL` (`0=draft`, `1=active`, `2=complete`, `-1=stopped`). Building / encroachment / fire forms carry numeric ASI status+date pairs; building and design-change forms also use named `Status`.

| Schema | n |
| --- | ---: |
| `citizenserve_lsbp` | 440 |
| `citizenserve_building` | 439 |
| `citizenserve_encroachment` | 386 |
| `citizenserve_planning` | 266 |
| `citizenserve_plaza_event` | 176 |
| `citizenserve_design_change` | 100 |
| `citizenserve_home_occ` | 60 |
| `citizenserve_other` | 57 |
| `citizenserve_solar` | 28 |
| `empty_extra` | 25 |
| `citizenserve_fire` | 23 |

Canonical fields: `main.status`; `dateSubmitted` / `dateCreated`; Issued pairs `(26607→26608)`, `(26800→26801)`, `(26940→26941)`, named `Status=Issued`→`26854`/`26895`; Completed→`26941`; `Decision Date`.

## Field assessment

### STATUS_NORMALIZED

Before: Active 1,047 / Final 538 / In Review 404 / Inactive 11 / missing 0.

Upstream mapped 1:1 from `STATUS_ORIGINAL`, which lags live `main.status` on 113 rows (68 Active←complete, 40 Final←active, 3 Active←stopped, 2 Inactive←complete). Form overrides add 19 more corrections (Withdrawn / Expired / Application Expired → Inactive; encroachment Completed → Final).

Transitions: Active→Final 74; Final→Active 40; Active→Inactive 11; Final→Inactive 7.

### FILE_DATE

Fully populated. Every value equaled `main.dateCreated` at calendar-day resolution. Prefer `dateSubmitted` when present: **326** disagreements (submitted 1–427 days later; median 3) → FIXED. Drafts (`status=0`, n=404) correctly lack `dateSubmitted` and keep `dateCreated`. Coverage remains 2,000 / 2,000.

### PERMIT_DATE

Missing on all 2,000 rows. Filled only when a companion status is explicitly `Issued` (review / Approved stamps are status-change or plan-approval dates, not issuance):

| Source | n filled |
| --- | ---: |
| LSBP ASI 26607=Issued → 26608 | 199 |
| Building `Status=Issued` → 26854 | 74 |
| Design Change `Status=Issued` → 26895 | 24 |
| Encroachment 26940=Issued → 26941 | 12 |
| Fire 26800=Issued → 26801 | 4 |

After repair: Active 212 / 1,002 (21.2%); Final 101 / 565 (17.9%). Remaining Active/Final gaps are mostly Encroachment / LSBP / Building shells without an Issued stamp, plus Express / Solar / planning / plaza types with no issuance field.

One chronology quirk left as-is: LSBP-23-46 has Issued date 2023-09-08 before portal `dateSubmitted` 2023-09-13.

### FINAL_DATE

Missing on all 2,000 rows. Sparse sources only: encroachment `26940=Completed` → `26941` (**13**, including promotions to Final), plus `Decision Date` on Temporary Use / New Address Final rows (**4**). After repair: Final 17 / 565 (3.0%). No building finaling / CO / inspection-final timestamps exist in this extract; `lastUpdatedDate` and `expirationDate` are not used.

## Repair performance

Script: `agent/scripts/ca/data_repair_ca_sonoma.py` (`data_repair`).

Artifact: `AGENT_DATA_PATH/repaired/permits_ca_sonoma_repaired.parquet`

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 0 | 132 | 0 → 0 |
| FILE_DATE | 0 | 326 | 0 → 0 |
| PERMIT_DATE | 313 | 0 | 2,000 → 1,687 |
| FINAL_DATE | 17 | 0 | 2,000 → 1,983 |

After repair:

- FILE_DATE: 2,000 / 2,000 (100%)
- PERMIT_DATE: Active 21.2%; Final 17.9%; In Review / Inactive 0%
- FINAL_DATE: Final 3.0%; cleared/absent on non-Final
- Remaining ideal gaps: 1,254 Active/Final missing PERMIT_DATE; 548 Final missing FINAL_DATE; 0 missing FILE_DATE

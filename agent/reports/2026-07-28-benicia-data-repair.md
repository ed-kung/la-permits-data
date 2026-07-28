# Benicia (CA) data repair — 2026-07-28

Benicia was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. CitizenServe `main`/`extra`/`location` JSON already has complete `FILE_DATE` (from `dateCreated`) and consistent `STATUS_NORMALIZED` from `main.status`, but Accela-migrated Past Records often disagree with Accela `Status` (Expired/Withdrawn left Final; Issued left Final), modern form statuses leave Active rows that are still in review, `FILE_DATE` lags `dateSubmitted` on 52 rows, and `PERMIT_DATE` / `FINAL_DATE` are empty on all 2,001 rows. Repair fixes 82 statuses and 52 file dates, and fills 137 permit dates and 105 final dates from Accela ASI fields (plus one modern Date Completed).

## Jurisdiction selection

Walked `(JURISDICTION, STATE)` pairs in sample order and compared against `agent/scripts/{state}/data_repair_{state}_{city}.py`. First missing: **Benicia, CA** → `agent/scripts/ca/data_repair_ca_benicia.py` (n=2,001).

## DATA schema

All rows share CitizenServe top-level keys (`main`, `extra`, `location`). Historical Accela imports live under `Past Record - *` types with named `File Date` / `Status` plus numeric ASI date fields; modern online forms use named Permit Status fields and rarely carry issuance/final timestamps. Variants recorded in `INFERRED_SCHEMA`:

| Schema | n | Description |
| --- | ---: | --- |
| `past_building_file_only` | 862 | Migrated building; File Date only |
| `past_business` | 278 | Migrated business license |
| `citizenserve_modern` | 228 | Modern form, no status fields |
| `past_building_accela_dates` | 179 | Migrated building with Status and/or 28084/28061 |
| `citizenserve_with_status` | 166 | Modern form with Permit/Current Status |
| `past_planning` | 128 | Migrated planning |
| `past_public_works_file_only` | 112 | Migrated PW; File Date only |
| `past_public_works_accela_dates` | 39 | Migrated PW with Status and/or 29411 |
| `past_fire` | 5 | Migrated fire |
| `past_enforcement` | 4 | Migrated enforcement |

## Field assessment

### STATUS_NORMALIZED

- Missing on 0 / 2,001. `main.status` maps cleanly: `0→In Review`, `1→Active`, `2→Final`, `-1→Inactive`, matching `STATUS_ORIGINAL` (`draft`/`active`/`complete`/`stopped`).
- Accela/form `Status` / `Permit Status` / `Current Permit Status` often conflict with that mapping on migrated and modern rows.
- **Issues:**
  - Past Record Expired (34) / Withdrawn (7) / EXPIRED (1) left as Final because `main.status=2`.
  - Past/modern Issued left as Final (13) when Accela Status is Issued.
  - Active modern rows with Need More Information / Correction List Generated / Payment Pending / In Review / Submitted / Awaiting Applicant Response (18) should be In Review.
  - Active rows with Expired/EXPIRED/Declined (3) should be Inactive.
  - One Inactive Finaled Accela row upgraded to Final.
  - Five Final rows with Accela In Review / Submitted / Payment Pending / Courtesy Notice Sent → In Review.
- **Repair:** Past Records take Accela Status as authoritative; modern rows keep `main.status` except Inactive overrides, Active→In Review form refinements, and Inactive→Final when Accela says Finaled. **0 FILLED**, **82 FIXED**. Missing after: 0.

Status transitions: Final→Inactive 42; Active→In Review 18; Final→Active 13; Final→In Review 5; Active→Inactive 3; Inactive→Final 1.

### FILE_DATE

- Missing on 0 / 2,001. Every value matched `main.dateCreated` (UTC date); when present, `extra['File Date']` agreed on all 1,607 historical rows.
- **Issue:** 52 modern rows have `dateSubmitted` on a later calendar day than `dateCreated`; application/submittal date should prefer submitted.
- **Repair:** prefer `dateSubmitted`, else `dateCreated`, else `File Date` → **0 FILLED**, **52 FIXED**. Coverage remains 100%.

### PERMIT_DATE

- Missing on 2,001 / 2,001 (100%). No previously populated values to validate.
- Recoverable sources: Accela building `28084` when Status is Issued/Finaled (skip when Finaled and `28084` > `28061`); Accela PW `29411` when Status is Issued; `28084` on COMPLETE rows lacking Status.
- **Repair:** **137 FILLED**, **0 FIXED**. Missing after: 1,864.
- Post-repair Active PERMIT coverage: 21/144 (14.6%); Final: 116/1,714 (6.8%). Remaining gaps are almost all Past Record file-only shells and modern forms with no issuance timestamp.

### FINAL_DATE

- Missing on 2,001 / 2,001 (100%).
- Recoverable sources: Accela building `28061` when Status is Finaled; Accela PW `29411` when Status is Finaled (no `28084`); modern `* Date Completed` fields (1 Final Pre-Application filled).
- **Repair:** **105 FILLED**, **0 FIXED**. Missing after: 1,896.
- Post-repair Final FINAL coverage: 105/1,714 (6.1%). No FINAL_DATE written on non-Final rows.

## Repair performance

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | ---: | ---: | ---: | ---: |
| STATUS_NORMALIZED | 0 | 82 | 0 | 0 |
| FILE_DATE | 0 | 52 | 0 | 0 |
| PERMIT_DATE | 137 | 0 | 2,001 | 1,864 |
| FINAL_DATE | 105 | 0 | 2,001 | 1,896 |

Status distribution after repair: Final 1,714 · Active 144 · Inactive 75 · In Review 68.

Post-repair completeness by status:

| Status | FILE_DATE | PERMIT_DATE | FINAL_DATE |
| --- | ---: | ---: | ---: |
| Active | 100% | 14.6% | 0% |
| Final | 100% | 6.8% | 6.1% |
| In Review | 100% | 0% | 0% |
| Inactive | 100% | 0% | 0% |

Chronology after repair: `PERMIT_DATE < FILE_DATE` = 0; `FINAL_DATE < PERMIT_DATE` = 0; `FINAL_DATE < FILE_DATE` = 0. Three Finaled building rows with inverted ASI dates (`28084` after `28061`) skip PERMIT fill but keep FINAL from `28061`.

## Artifacts

- Repair script: `agent/scripts/ca/data_repair_ca_benicia.py` (`data_repair`)

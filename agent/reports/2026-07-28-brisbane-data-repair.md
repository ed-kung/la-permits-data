# Brisbane (CA) data repair — 2026-07-28

Brisbane was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. Flat city-portal JSON under `DATA` has a uniform key set (`Status`, `Date In`, `Check-List`, plus address/project fields) but **no issuance or finaled date fields**. Main issues: 44 missing `STATUS_NORMALIZED` (blank `STATUS_ORIGINAL`), 46 stale statuses where `STATUS_ORIGINAL` lagged `DATA.Status` (e.g. Finaled still Active, Expired still Active), and 100% missing `PERMIT_DATE` / `FINAL_DATE` with nothing in JSON to fill them. `FILE_DATE` was already complete and matched `Date In`. Repair fills/fixes all 90 status gaps (missing after: 0); date fields are unchanged.

## Jurisdiction selection

Walked `(JURISDICTION, STATE)` pairs in sample order and compared against `agent/scripts/{state}/data_repair_{state}_{city}.py`. First missing: **Brisbane, CA** → `agent/scripts/ca/data_repair_ca_brisbane.py` (n=2,000).

## DATA schema

Every row shares the same top-level keys. Workflow progress lives in `Check-List` (five stages: Fee, Plan Check, Permit Issuance, Inspections, Permit Finaled), each with `Stage` / `Status` / `Progress` only — no date stamps. The only calendar date in `DATA` is `Date In` (application/intake). `Permit Issuance` status text sometimes embeds an expiration date (`Permit Issued (Expires MM/DD/YYYY)`); that is not an issuance date and is not used for `PERMIT_DATE`.

| Schema | n | Description |
| --- | ---: | --- |
| `portal_finaled` | 1,041 | `Status` = Permit Finaled. |
| `portal_expired` | 527 | `Status` = Permit Expired. |
| `portal_in_review` | 198 | Pending / plan review / fees / ready to issue / skipped plan review |
| `portal_issued_active` | 103 | Inspections in process / Ready for inspections |
| `portal_inactive_other` | 92 | Cancelled / Voided / On Hold |
| `portal_no_status` | 39 | Blank `Status`; infer from Check-List |

## Field assessment

### STATUS_NORMALIZED

- Missing on 44 / 2,000. All 44 also have blank `STATUS_ORIGINAL`. Of these, 37 have blank `DATA.Status` (mostly fee Balance Due / early shells with all later stages Not Available); 7 have usable `DATA.Status` (`Ready for inspections.`, `Ready to Issue Permit`, `Inspections in process.`).
- When present, most rows already matched a correct map from `STATUS_ORIGINAL`, but **46** lagged behind `DATA.Status`: Finaled still Active (20) / In Review (3) / Inactive (1); Expired still Active (11); Ready for inspections / Inspections in process still In Review (11).
- Root cause: upstream normalization keyed off stale `STATUS_ORIGINAL` instead of current portal `Status`, and never mapped blank-status shells via Check-List.
- **Repair:** map `DATA.Status` (fallback: Check-List Finaled → Final, Permit Issued → Active, inspection stages → Active, else In Review) → **44 FILLED** (39 In Review, 5 Active), **46 FIXED**. Missing after: 0.

### FILE_DATE

- Present on 2,000 / 2,000. Every value matches `Date In` at day resolution (0 mismatches).
- **Repair:** no changes (0 FILLED / 0 FIXED). Coverage remains 100%.

### PERMIT_DATE

- Missing on 2,000 / 2,000. Ideal coverage: should be populated for Active and Final.
- All Active (118) and Final (1,017) rows have a Check-List `Permit Issuance` stage starting with `Permit Issued`, confirming issuance occurred, but `DATA` has no Issued / Approved date field — only optional expiration text.
- **Repair:** no changes (0 FILLED / 0 FIXED). Coverage remains 0%. Cannot invent issuance dates from `Date In` or expiration dates without conflating distinct events.

### FINAL_DATE

- Missing on 2,000 / 2,000. Ideal coverage: should be populated for Final.
- All Final rows (and 1,041 portal_finaled) have Check-List `Permit Finaled` = `Permit Finaled.`, confirming completion, but `DATA` has no Finaled / completion / signoff date.
- **Repair:** no changes (0 FILLED / 0 FIXED). Coverage remains 0%.

## Repair performance

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | ---: | ---: | ---: | ---: |
| STATUS_NORMALIZED | 44 | 46 | 44 | 0 |
| FILE_DATE | 0 | 0 | 0 | 0 |
| PERMIT_DATE | 0 | 0 | 2,000 | 2,000 |
| FINAL_DATE | 0 | 0 | 2,000 | 2,000 |

Status distribution after repair: Final 1,041 · Inactive 619 · In Review 237 · Active 103 · missing 0.

FIXED transitions: Active→Final 20; Active→Inactive 11; In Review→Active 11; In Review→Final 3; Inactive→Final 1.

Post-repair completeness by status:

| Status | n | FILE_DATE | PERMIT_DATE | FINAL_DATE |
| --- | ---: | ---: | ---: | ---: |
| Active | 103 | 100% | 0% | 0% |
| Final | 1,041 | 100% | 0% | 0% |
| In Review | 237 | 100% | 0% | 0% |
| Inactive | 619 | 100% | 0% | 0% |

Overall FILE_DATE coverage: 2,000 / 2,000 (100%). Active+Final PERMIT_DATE: 0 / 1,144 (0%). Final FINAL_DATE: 0 / 1,041 (0%).

## Artifacts

- Repair script: `agent/scripts/ca/data_repair_ca_brisbane.py` (`data_repair` entry point)
- No derived datasets written under `AGENT_DATA_PATH`

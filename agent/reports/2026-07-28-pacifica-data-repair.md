# Pacifica (CA) data repair — 2026-07-28

Pacifica was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. Flat city-portal JSON under `DATA` has a uniform key set (`Status`, `Date In`, `Check-List`, plus address/project fields) but **no issuance or finaled date fields**. Main issues: 3 missing `STATUS_NORMALIZED` (blank `STATUS_ORIGINAL` / `DATA.Status`), 10 stale statuses where `STATUS_ORIGINAL` lagged `DATA.Status` (e.g. Finaled still Active, Expired still Active), and 100% missing `PERMIT_DATE` / `FINAL_DATE` with nothing in JSON to fill them. `FILE_DATE` was already complete and matched `Date In`. Repair fills/fixes all 13 status gaps (missing after: 0); date fields are unchanged.

## Jurisdiction selection

Walked `(JURISDICTION, STATE)` pairs in sample order and compared against `agent/scripts/{state}/data_repair_{state}_{city}.py`. First missing: **Pacifica, CA** → `agent/scripts/ca/data_repair_ca_pacifica.py` (n=2,000).

## DATA schema

Every row shares the same top-level keys. Workflow progress lives in `Check-List` (five stages: Fee, Plan Check, Permit Issuance, Inspections, Permit Finaled), each with `Stage` / `Status` / `Progress` only — no date stamps. The only calendar date in `DATA` is `Date In` (application/intake). `Permit Issuance` status text sometimes embeds an expiration date (`Permit Issued (Expires MM/DD/YYYY)`); that is not an issuance date and is not used for `PERMIT_DATE`.

| Schema | n | Description |
| --- | ---: | --- |
| `portal_expired` | 1,179 | `Status` = Permit Expired. |
| `portal_finaled` | 616 | `Status` = Permit Finaled. |
| `portal_in_review` | 108 | Pending / plan review / fees / ready to issue |
| `portal_issued_active` | 55 | Inspections in process / Ready for inspections |
| `portal_inactive_other` | 39 | Cancelled / Voided / On Hold |
| `portal_no_status` | 3 | Blank `Status`; infer from Check-List |

## Field assessment

### STATUS_NORMALIZED

Before repair: Inactive 1,217 / Final 610 / In Review 110 / Active 60 / missing 3.

| DATA.Status | Before STATUS_NORMALIZED | n |
| --- | --- | ---: |
| Permit Expired. | Inactive | 1,178 |
| Permit Finaled. | Final | 610 |
| Ready to Issue Permit | In Review | 35 |
| Plan Review in Process | In Review | 34 |
| Ready for inspections. | Active | 33 |
| Cancelled Permit. | Inactive | 28 |
| Fees are due. | In Review | 26 |
| Inspections in process. | Active | 20 |
| Pending Application | In Review | 13 |
| Permit On Hold. | Inactive | 8 |
| Permit Finaled. | **Active (wrong)** | 6 |
| (null) | missing | 3 |
| Permit Voided. | Inactive | 2 |
| Ready for inspections. | **In Review (wrong)** | 1 |
| Inspections in process. | **Inactive (wrong)** | 1 |
| Permit Expired. | **Active (wrong)** | 1 |
| Cancelled Permit. | **In Review (wrong)** | 1 |

- **3** rows with blank `STATUS_ORIGINAL` / `DATA.Status` (early shells: fees Balance Due or Paid, later stages Not Available) → FILLED as In Review via Check-List.
- **10** rows where upstream normalization lagged portal `Status` → FIXED.
- Root cause: upstream keyed off stale `STATUS_ORIGINAL` instead of current `DATA.Status`, and never mapped blank-status shells via Check-List.

### FILE_DATE

- Present on 2,000 / 2,000. Every value matches `Date In` at day resolution (0 mismatches).
- **Repair:** no changes (0 FILLED / 0 FIXED). Coverage remains 100%.

### PERMIT_DATE

- Missing on 2,000 / 2,000. Ideal coverage: should be populated for Active and Final.
- All Active (55) and Final (616) rows after repair have a Check-List `Permit Issuance` stage starting with `Permit Issued`, confirming issuance occurred, but `DATA` has no Issued / Approved date field — only optional expiration text (median Expire − Date In = 180 days; not a reliable proxy for issuance).
- **Repair:** no changes (0 FILLED / 0 FIXED). Coverage remains 0%.

### FINAL_DATE

- Missing on 2,000 / 2,000. Ideal coverage: should be populated for Final.
- All Final rows have Check-List `Permit Finaled` = `Permit Finaled.`, confirming completion, but `DATA` has no Finaled / completion / signoff date.
- **Repair:** no changes (0 FILLED / 0 FIXED). Coverage remains 0%.

## Repair performance

Script: `agent/scripts/ca/data_repair_ca_pacifica.py`  
Artifact: `$AGENT_DATA_PATH/repaired/permits_ca_pacifica_repaired.parquet`

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | ---: | ---: | ---: | ---: |
| STATUS_NORMALIZED | 3 | 10 | 3 | 0 |
| FILE_DATE | 0 | 0 | 0 | 0 |
| PERMIT_DATE | 0 | 0 | 2,000 | 2,000 |
| FINAL_DATE | 0 | 0 | 2,000 | 2,000 |

Status distribution after repair: Inactive 1,218 · Final 616 · In Review 111 · Active 55 · missing 0.

FIXED / FILLED transitions: Active→Final 6; nan→In Review 3; In Review→Active 1; Inactive→Active 1; Active→Inactive 1; In Review→Inactive 1.

Post-repair completeness by status:

| Status | n | FILE_DATE | PERMIT_DATE | FINAL_DATE |
| --- | ---: | ---: | ---: | ---: |
| Active | 55 | 100% | 0% | 0% |
| Final | 616 | 100% | 0% | 0% |
| In Review | 111 | 100% | 0% | 0% |
| Inactive | 1,218 | 100% | 0% | 0% |

Overall FILE_DATE coverage: 2,000 / 2,000 (100%). Active+Final PERMIT_DATE: 0 / 671 (0%). Final FINAL_DATE: 0 / 616 (0%).

## Not repaired

- **PERMIT_DATE** and **FINAL_DATE** cannot be recovered from this portal export: no issuance or finaled timestamps exist in `DATA`. Expiration dates in `Permit Issuance` text are not used as issuance proxies.
- Same structural limitation as Brisbane (identical portal payload shape).

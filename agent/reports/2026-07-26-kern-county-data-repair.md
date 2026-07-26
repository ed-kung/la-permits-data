# Kern County data repair

**Summary:** First jurisdiction without an existing repair script in the CA sample was Kern County (CA). Its Accela Citizen Access `DATA` payloads share one top-level key set but five workflow variants (`building_permit`, `code_enforcement`, `planning`, `otc_simple`, `other`). STATUS_NORMALIZED had 29 unmapped values plus 43 stale STATUS_ORIGINAL mislabels; FILE_DATE was already complete and correct; PERMIT_DATE gained 106 fills and 35 fixes (C of O dates replaced with Permit Issuance / Issued); FINAL_DATE gained 440 fills from Finaled / Close Case / Case Closed events and 5 fixes (including clearing 2 spurious Active finals). After repair, status is fully populated, FILE_DATE remains 100%, Active PERMIT_DATE is 87.2%, and Final FINAL_DATE is 99.0%.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_ca_sample.parquet` and walked `(JURISDICTION, STATE)` in first-seen order. First pair lacking `agent/scripts/{state}/data_repair_{state}_{city}.py` was **Kern County, CA** (`agent/scripts/ca/data_repair_ca_kern_county.py`). Sample size: **1,999** rows.

## DATA schema

All 1,999 rows share the same Accela top-level keys (`date`, `status`, `tasks`, `inspections`, `search_data`, `details`, `more_details`, `contacts`, `fees_details`, …). Task event keys use leading/trailing spaces (`Marked as `, ` on `).

`INFERRED_SCHEMA` distinguishes workflow variants:

| Schema | n | Notes |
| --- | ---: | --- |
| building_permit | 1,361 | Has `Permit Issuance` |
| code_enforcement | 358 | Has `Case Intake` / `Close Case` |
| planning | 114 | Has `Issuance` + `Review Cycle` (mostly O&G) |
| otc_simple | 112 | Intake + Inspections, no Permit Issuance |
| other | 54 | Remaining Accela shells |

## Field assessments

### STATUS_NORMALIZED

| Before | Count |
| --- | ---: |
| Final | 1,423 |
| Active | 251 |
| Inactive | 159 |
| In Review | 137 |
| missing | 29 |

- Canonical source: `DATA.status` (more current than `STATUS_ORIGINAL`).
- **Missing (29):** unmapped enforcement / edge statuses — `Notice and Order` (17), `Pending Initial Inspection` (5), `Closed` (2), `Pending County Abatement`, `Immediate Response`, `Breakdown`, `Vehicle Notice & Order`, blank (1).
- **Incorrect (43):** stale labels from `STATUS_ORIGINAL` while `DATA.status` had advanced — `Finaled` labeled Active (21) or In Review (9); `Issued` labeled In Review (6); `Canceled` labeled Active (5) or In Review (1); `Approved` labeled In Review (1).

### FILE_DATE

- **0 missing**; every row matches `DATA.date` at calendar-day resolution.
- No repair needed.

### PERMIT_DATE

- **689 missing** before repair.
- Canonical source: `Permit Issuance` / `Issued` (1,221 rows have this event; after repair all populated PERMIT_DATE values with an Issued event match it).
- **Incorrect (35):** PERMIT_DATE stored the later `C of O Issuance` / `C of O Issued` date instead of Permit Issuance / Issued.
- **Fillable gaps:** 15+ building rows with Issued but blank PERMIT_DATE; ~89 OTC `Accepted No PC` Active/Final rows with no Permit Issuance task; planning rows already matched `Issuance` / `Issued` when present.
- Remaining Active/Final gaps are mostly Closed code-enforcement cases (no issuance workflow) plus a few Approved/Closed shells without an issuance-style event.

### FINAL_DATE

- **997 missing** before; **423 of 1,423 Final** rows lacked FINAL_DATE (almost all `Closed` code-enforcement / planning).
- Canonical source: `Inspections` / `Finaled` (matches 998 existing values at latest Finaled).
- Additional sources for Closed shells: `Close Case` / `Close*` (Owner/County Abated, Duplicate, Expungement), `Inspections` / `Close`, `Closed` / `Closed`, investigation `Case Closed`.
- **Spurious:** 2 Active (`Approved`) rows carried FINAL_DATE → cleared.
- **Day fixes:** 3 Final rows had FINAL_DATE earlier than the latest Finaled event → corrected to latest.

## Repair performance

Script: `agent/scripts/ca/data_repair_ca_kern_county.py`  
Artifact: `AGENT_DATA_PATH/processed_data/permits_ca_kern_county_repaired.parquet`

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 29 | 43 | 29 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 106 | 35 | 689 → 583 |
| FINAL_DATE | 440 | 5 | 997 → 559 |

Status after repair: Final 1,455 · Active 258 · Inactive 165 · In Review 121 · missing 0.

Coverage after repair:

| | Active | Final | In Review | Inactive |
| --- | ---: | ---: | ---: | ---: |
| PERMIT_DATE | 225/258 (87.2%) | 1,096/1,455 (75.3%) | 0/121 | 95/165 |
| FINAL_DATE | 0/258 | 1,440/1,455 (99.0%) | 0/121 | 0/165 |
| FILE_DATE | 1,999/1,999 (100%) | | | |

## Not repairable from DATA

- ~392 Active/Final rows (mostly Closed code-enforcement, plus some planning / OTC / Approved shells) have no Permit Issuance, planning Issuance, or Accepted No PC event → PERMIT_DATE left missing.
- 15 Final rows lack any dated Finaled / Close Case / Case Closed event (Withdrawn shells, sparse Closed records) → FINAL_DATE left missing.

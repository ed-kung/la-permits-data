# Camarillo (CA) data repair — 2026-07-28

Camarillo was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. Portal JSON under `DATA` supports filling all 9 missing statuses, correcting 263 wrong ones (mostly EXPIRED/CANCELED mislabeled Active, plus lagging permit-number status), rewriting ~1,402 `PERMIT_DATE` values from the overwritten `Permit Date` field to true `Issue Date`, clearing 61 spurious In Review issuance dates, and filling 15 missing `FINAL_DATE` values on rows promoted to Final. Post-repair: FILE 100% everywhere; Active/Final PERMIT 100% and matching Issue Date; Final FINAL 100%.

## Jurisdiction selection

Walked `(JURISDICTION, STATE)` pairs in sample order and compared against `agent/scripts/{state}/data_repair_{state}_{city}.py`. First missing: **Camarillo, CA** → `agent/scripts/ca/data_repair_ca_camarillo.py` (n=2,000).

## DATA schema

Same permit-portal scrape family as Bakersfield / Oxnard / Davis. Two structural schemas recorded in `INFERRED_SCHEMA`:

| Schema | n | Description |
| --- | ---: | --- |
| `permit_status` | 1,991 | `detail` + `fees` + `permit_status` / `insp_status` (+ `_detail` blocks) |
| `detail_only` | 9 | `detail` + `fees` / `fees_total` only (no permit or inspection blocks) |

Canonical fields:
- `detail['Application Status']` / `permit_status_detail['Status for Permit Number']` → status
- `detail['Application Date']` → `FILE_DATE`
- `permit_status_detail['Issue Date']` (not `Permit Date`) → `PERMIT_DATE`
- Latest APPROVED `*FINAL*` inspection (else latest APPROVED) → `FINAL_DATE`

## Field assessment

### STATUS_NORMALIZED

- Missing on 9 / 2,000 (all `detail_only`, null `STATUS_ORIGINAL`): APPROVED (6), IN PLAN CHECK (2), ON HOLD (1) → FILLED as In Review (no issuance evidence).
- Upstream mapped exclusively from `STATUS_ORIGINAL` / Status for Permit Number, ignoring terminal Application Status:
  - EXPIRED (206) and CANCELED (41) labeled Active / In Review / Final → FIXED to Inactive (247 total Fixed, of which 229 Active→Inactive, 17 In Review→Inactive, 1 Final→Inactive).
  - 15 rows with Status for Permit Number `FINAL INSPECTION COMPLETE` but lagging `STATUS_ORIGINAL` `permit printed` → FIXED to Final.
  - 1 In Review row with `PERMIT PRINTED` → FIXED to Active.
- `PERMIT FINALED` + `PERMIT PRINTED` without final-inspection status (154) left Active: Status for Permit Number is canonical; Application Status alone is not treated as finaling evidence (and none have `FINAL_DATE`).
- **Repair:** 9 FILLED, 263 FIXED. Missing after: 0.

### FILE_DATE

- Missing on 0 / 2,000. Every value matches `detail['Application Date']` (0 incorrect).
- **Repair:** 0 FILLED, 0 FIXED. Coverage 2,000 / 2,000 (100%).

### PERMIT_DATE

- Missing on 9 / 2,000 (the `detail_only` stubs). When present, 99.2% matched `Permit Date`, but only 27.4% matched `Issue Date`.
- Root cause: on finaled rows, `Permit Date` is overwritten to the finalization / last-activity date (1,142 rows where `Permit Date == FINAL_DATE`). Canonical issuance is `Issue Date`.
- All Active/Final `permit_status` rows have Issue Date → FIXED overwrite to Issue Date (1,402).
- Spurious PERMIT on In Review plan-check / to-be-issued shells with blank Issue Date → cleared (61 FIXED).
- Inactive EXPIRED/CANCELED that previously issued keep Issue Date; 17 never-issued (PLAN CHECK / TO BE ISSUED) stay missing.
- **Repair:** 0 FILLED, 1,463 FIXED (1,402 overwrite + 61 clear). Missing after: 70.
- Post-repair Active PERMIT: 285/285 (100%); Final: 1,415/1,415 (100%); Active+Final Issue Date match: 1,700/1,700.

### FINAL_DATE

- Missing on 599 / 2,000 before repair. All 1,401 pre-repair Final rows already had FINAL_DATE matching the latest APPROVED inspection on/after FILE_DATE (100%).
- 15 rows promoted Active→Final → FILLED from APPROVED final-named (or latest APPROVED) inspections.
- 1 Final→Inactive EXPIRED row carried a FINAL_DATE → cleared (FIXED).
- Non-Final rows correctly have no FINAL_DATE after repair.
- **Repair:** 15 FILLED, 1 FIXED (clear). Missing after: 585.
- Post-repair Final FINAL coverage: 1,415/1,415 (100%).

## Repair performance

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | ---: | ---: | ---: | ---: |
| STATUS_NORMALIZED | 9 | 263 | 9 | 0 |
| FILE_DATE | 0 | 0 | 0 | 0 |
| PERMIT_DATE | 0 | 1,463 | 9 | 70 |
| FINAL_DATE | 15 | 1 | 599 | 585 |

Status distribution:

| | Before | After |
| --- | ---: | ---: |
| Final | 1,401 | 1,415 |
| Active | 528 | 285 |
| In Review | 62 | 53 |
| Inactive | 0 | 247 |
| (missing) | 9 | 0 |

Post-repair completeness by status:

| Status | n | FILE_DATE | PERMIT_DATE | FINAL_DATE |
| --- | ---: | ---: | ---: | ---: |
| Active | 285 | 100% | 100% | 0% |
| Final | 1,415 | 100% | 100% | 100% |
| In Review | 53 | 100% | 0% | 0% |
| Inactive | 247 | 100% | 93.1% | 0% |

## Artifacts

- Repair script: `agent/scripts/ca/data_repair_ca_camarillo.py`
- Repaired sample: `$AGENT_DATA_PATH/camarillo_repaired_sample.parquet`

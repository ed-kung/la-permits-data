# Calistoga (CA) data repair — 2026-07-28

Calistoga was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. Portal JSON under `DATA` already has correct `STATUS_NORMALIZED` (maps 1:1 from `Status:`) and correct `PERMIT_DATE` whenever both the field and `Permit Details['Issue Date:']` are present. Main issues were inconsistent `FILE_DATE` (often a mid-stream review Start/Completion instead of earliest `Reviews[].Start`), near-total missing `FILE_DATE` on Migrated shells with no Reviews, and **every** row missing `FINAL_DATE` despite passed Final* inspections on 360 Closed permits. Repair fills 7 and fixes 181 file dates, and fills 360 final dates; residual gaps lack Reviews / Issue Date / Final inspection evidence in `DATA`.

## Jurisdiction selection

Walked `(JURISDICTION, STATE)` pairs in sample order and compared against `agent/scripts/{state}/data_repair_{state}_{city}.py`. First missing: **Calistoga, CA** → `agent/scripts/ca/data_repair_ca_calistoga.py` (n=2,000).

## DATA schema

All rows share civic-portal top-level keys (`Status:`, `Permit #:`, `Permit Details`, `Inspections`, `Reviews`, `Issue Date` [always null at top level], …). Many Migrated building permits also carry long form-field key sets (`Owner:migrated`, etc.). Canonical status/dates:

| Source | Field |
| --- | --- |
| `DATA['Status:']` | STATUS_NORMALIZED |
| Earliest `Reviews[].Start` | FILE_DATE |
| `Permit Details['Issue Date:']` | PERMIT_DATE |
| Latest passed inspection with type containing `Final` | FINAL_DATE |

Content variants recorded in `INFERRED_SCHEMA`:

| Schema | n | Description |
| --- | ---: | --- |
| `portal_migrated` | 1,496 | Sub Type Migrated / migrated form fields |
| `portal_inspections` | 238 | Nonempty Inspections, no Reviews |
| `portal_reviews_inspections` | 141 | Nonempty Reviews + Inspections |
| `portal_basic` | 63 | Status / Permit Details shell only |
| `portal_reviews` | 62 | Nonempty Reviews only |

## Field assessment

### STATUS_NORMALIZED

- Distribution: Final 1,544 · Active 353 · In Review 54 · Inactive 48 · missing 1.
- Map from `DATA['Status:']` is already correct for every populated row: Closed→Final, Issued→Active, Under Review / Ready to Issue / Online Application Received→In Review, Expired / Void / Withdrawn / Refunded→Inactive.
- Missing on 1 / 2,000: blank `Status:` encroachment shell `ENC20-000001` (empty Issue Date, Reviews, Inspections) → not fillable.
- **Repair:** no changes (**0 FILLED**, **0 FIXED**). Missing after: 1.

### FILE_DATE

- Missing on 1,748 / 2,000 (87.4%). Only 259 rows have any `Reviews[].Start`; 1,741 have no review-start source (almost all Migrated historical shells).
- When present, `FILE_DATE` often matched a later review Start or Completion (Permit Review, Review Complete, Bureau Veritas, …) rather than the earliest Start. Median lag vs earliest Start among disagreements ≈ 2 weeks.
- **Repair:** set to earliest `Reviews[].Start` → **7 FILLED**, **181 FIXED**. Missing after: 1,741.
- Post-repair coverage: 259 / 2,000 (13.0%). Remaining gaps have no application date in `DATA`.

### PERMIT_DATE

- Missing on 144 / 2,000. When present, every value equals `Permit Details['Issue Date:']` (0 incorrect), including 619 Migrated Jan-1 year-only placeholders that match the source Issue Date and are left as-is.
- Among Active/Final before repair: Active 301/353 present; Final 1,529/1,544 present. All 67 Active/Final gaps have empty `Issue Date:` (mostly Migrated; a few modern Closed shells with Reviews but no issuance date).
- **Repair:** no changes (**0 FILLED**, **0 FIXED**). Missing after: 144.
- Post-repair Active PERMIT coverage: 301/353 (85.3%); Final: 1,529/1,544 (99.0%).

### FINAL_DATE

- Missing on 2,000 / 2,000 (100%). No pre-populated values to validate.
- Passed Final / Occupancy - Final / Final Fire* inspections provide dated finalization for 360 Closed rows. Remaining Closed records are mostly empty Migrated shells (no Inspections).
- **Repair:** **360 FILLED**, **0 FIXED**. Missing after: 1,640.
- Post-repair Final FINAL coverage: 360/1,544 (23.3%). Remaining Final gaps lack a dated passed Final* inspection in `DATA`.

## Repair performance

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | ---: | ---: | ---: | ---: |
| STATUS_NORMALIZED | 0 | 0 | 1 | 1 |
| FILE_DATE | 7 | 181 | 1,748 | 1,741 |
| PERMIT_DATE | 0 | 0 | 144 | 144 |
| FINAL_DATE | 360 | 0 | 2,000 | 1,640 |

Status distribution unchanged: Final 1,544 · Active 353 · In Review 54 · Inactive 48 · missing 1.

Post-repair completeness by status:

| Status | n | FILE_DATE | PERMIT_DATE | FINAL_DATE |
| --- | ---: | ---: | ---: | ---: |
| Active | 353 | 13.0%* | 85.3% | 0% |
| Final | 1,544 | (mostly Migrated) | 99.0% | 23.3% |
| In Review | 54 | high among review-bearing rows | 0% | 0% |
| Inactive | 48 | low | 54.2% | 0% |

\*Overall FILE coverage is 259/2,000; nearly all fillable rows are modern non-Migrated permits with Reviews.

## Artifacts

- Repair script: `agent/scripts/ca/data_repair_ca_calistoga.py`
- Repaired sample parquet: `$AGENT_DATA_PATH/calistoga_repaired_sample.parquet`

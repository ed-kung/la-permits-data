# Carlsbad (CA) data repair — 2026-07-28

Carlsbad was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. EnerGov JSON under `DATA` already has correct `STATUS_NORMALIZED` (vs `CaseStatus`), correct `FILE_DATE` (vs `ApplyDate`), and correct `PERMIT_DATE` / `FINAL_DATE` whenever those were populated from `IssueDate` / `FinalDate`. The only incorrect field values are 22 spurious `FINAL_DATE` stamps on Active / Inactive rows (Withdrawn, Error, Expired, Issued - Active) copied from `entity.FinalDate` as a case-closure date. Repair clears those 22 finals; residual Active/Final date gaps lack `IssueDate` / `FinalDate` in `DATA`.

## Jurisdiction selection

Walked `(JURISDICTION, STATE)` pairs in sample appearance order and compared against `agent/scripts/{state}/data_repair_{state}_{city}.py`. First missing: **Carlsbad, CA** → `agent/scripts/ca/data_repair_ca_carlsbad.py` (n=2,000).

## DATA schema

All rows share Tyler EnerGov top-level keys (`entity`, `details`, `contacts`, `processing_status`). Canonical dates/status live under `entity` with `details` fallbacks (`CaseStatus`, `ApplyDate`, `IssueDate`, `FinalDate` / `FinalizeDate`). `entity.FinalDate` and `details.FinalizeDate` agree on every sample row. `processing_status` is always null in this sample. Content variants recorded in `INFERRED_SCHEMA`:

| Schema | n | Description |
| --- | ---: | --- |
| `entity_basic` | 1,858 | entity + details + contacts + processing_status |
| `entity_fees` | 118 | entity_basic plus fees |
| `entity_fees_reviews` | 24 | plus reviews / holds / attachments / more_info |

## Field assessment

### STATUS_NORMALIZED

- No missing values (0 / 2,000). Upstream mapping from `CaseStatus` / `STATUS_ORIGINAL` is correct for every row:
  - `Closed - Finaled` / `Completed` / `Completed - In Warranty` → Final
  - `Issued - Active` → Active
  - `Under Review - Active` / `Approved - Ready to Issue` / `Pending` → In Review
  - `Closed - Expired` / `Error` / `Withdrawn` / `Denied` / `Revoked` / `Issued - Inactive` → Inactive
- **Repair:** 0 FILLED, 0 FIXED. Missing after: 0.

### FILE_DATE

- Missing on 0 / 2,000. Present values match `entity.ApplyDate` on all 2,000 rows (0 incorrect).
- **Repair:** no changes (0 FILLED / 0 FIXED). Coverage 100%.

### PERMIT_DATE

- Missing on 344 / 2,000 (17.2%). When present, every value matches `IssueDate` (0 incorrect).
- Active: 3 missing; Final: 47 missing. In all 50 cases `details.Issued=False` and `IssueDate` is null in `DATA` (mostly LDE agreements / easements / ROW / fire / migrated shells and a few `Completed` records without issuance).
- Unfillable from `DATA`; no alternative issuance field.
- **Repair:** 0 FILLED, 0 FIXED. Missing after: 344.
- Post-repair Active PERMIT coverage: 357/360 (99.2%); Final: 1,221/1,268 (96.3%).

### FINAL_DATE

- Missing on 833 / 2,000 (41.6%). When present and status is Final, values match `FinalDate` / `FinalizeDate` (0 incorrect vs those fields).
- Among Final: 123 missing FINAL_DATE all lack `FinalDate` in `DATA` (no fill path; `processing_status` empty).
- **Spurious FINAL_DATE:** 22 non-Final rows carried `entity.FinalDate` as a case-closure stamp:
  - Active (`Issued - Active`): 5 (mostly LDE Right of Way / Water Meter)
  - Inactive (`Closed - Withdrawn`): 10
  - Inactive (`Closed - Error`): 5
  - Inactive (`Closed - Expired`): 2
  → cleared.
- One In Review row (`SE2025-0025`) has `FinalDate` in `DATA` but correctly null `FINAL_DATE`; left as-is.
- **Repair:** 0 FILLED, 22 FIXED (clears). Missing after: 855 (increase is intentional clearing of non-Final stamps).
- Post-repair Final FINAL coverage: 1,145/1,268 (90.3%). Active / In Review / Inactive: 0% by design.

## Repair performance

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | ---: | ---: | ---: | ---: |
| STATUS_NORMALIZED | 0 | 0 | 0 | 0 |
| FILE_DATE | 0 | 0 | 0 | 0 |
| PERMIT_DATE | 0 | 0 | 344 | 344 |
| FINAL_DATE | 0 | 22 | 833 | 855 |

Status distribution unchanged: Final 1,268 · Active 360 · Inactive 191 · In Review 181.

Post-repair completeness by status:

| Status | n | FILE_DATE | PERMIT_DATE | FINAL_DATE |
| --- | ---: | ---: | ---: | ---: |
| Active | 360 | 100% | 99.2% | 0% |
| Final | 1,268 | 100% | 96.3% | 90.3% |
| In Review | 181 | 100% | 2.8% | 0% |
| Inactive | 191 | 100% | 38.2% | 0% |

Overall FILE_DATE coverage: 2,000 / 2,000 (100%). Active+Final PERMIT_DATE: 1,578 / 1,628 (96.9%).

Chronology: 12 `FILE > PERMIT` and 5 `PERMIT > FINAL` cases remain; all mirror inverted Apply/Issue/Final timestamps already present in `entity` before repair (often same-calendar-day UTC offset or re-apply / migrated shells), not introduced by repair.

## Artifacts

- Repair script: `agent/scripts/ca/data_repair_ca_carlsbad.py`
- Repaired sample parquet: `$AGENT_DATA_PATH/repaired/permits_ca_carlsbad_repaired.parquet`

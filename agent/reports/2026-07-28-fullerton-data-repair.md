# Fullerton (CA) data repair — 2026-07-28

Fullerton was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. EnerGov JSON under `DATA` already has correct `FILE_DATE` (all rows) and, when populated, correct `PERMIT_DATE` / `FINAL_DATE` matching `entity.IssueDate` / `entity.FinalDate`. Main issues were unmapped / stale `STATUS_NORMALIZED` (9 missing Invoiced/Pre-Issuance; 33 wrong — mostly Expired lagged as Active and Complete lagged as Active/In Review), 8 missing `PERMIT_DATE`/`FINAL_DATE` after status catch-up, and 16 spurious `FINAL_DATE` values on non-Final Issued/Expired/Cancelled/In Review shells.

## Jurisdiction selection

Walked `(JURISDICTION, STATE)` pairs in sample order and compared against `agent/scripts/{state}/data_repair_{state}_{city}.py`. First missing: **Fullerton, CA** → `agent/scripts/ca/data_repair_ca_fullerton.py` (n=2,000).

## DATA schema

All rows share Tyler EnerGov top-level keys (`entity`, `details`, `contacts`, `fees`, `processing_status`). 77 rows also carry a reviews bundle (`reviews` / `holds` / `attachments` / `more_info`). Canonical dates/status live under `entity` (`CaseStatus`, `ApplyDate`, `IssueDate`, `FinalDate`) with `details` fallbacks (`PermitStatus`, `ApplyDate`, `IssueDate`, `FinalizeDate`). `CaseStatus` and `PermitStatus` agree on every sample row. Recorded in `INFERRED_SCHEMA`:

| Schema | n | Description |
| --- | ---: | --- |
| `entity_fees` | 1,923 | Base EnerGov payload |
| `entity_fees_reviews` | 77 | Base + reviews/holds/attachments/more_info |

## Field assessment

### STATUS_NORMALIZED

- Missing on 9 / 2,000 (0.4%): 7 `Invoiced - Pending Payment`, 2 `Pre-Issuance Status` (unmapped upstream).
- When `STATUS_ORIGINAL` matches `DATA.entity.CaseStatus`, existing normalization is mostly consistent (Complete → Final; Issued → Active; Expired/Void/Cancelled/Withdrawn → Inactive; In Review / Received / Ready to Issue / With Applicant → In Review).
- **Issues (stale STATUS_ORIGINAL vs current CaseStatus):**
  - 17 `Expired` rows still mapped as Active → should be Inactive.
  - 8 `Complete` rows lagged as Active (5), In Review (2), or Inactive (1) → should be Final.
  - 6 `Issued` rows lagged as In Review → should be Active.
  - 1 `Cancelled` lagged as In Review → Inactive; 1 `In Review` lagged as Inactive → In Review.
- **Repair:** map from CaseStatus / PermitStatus → **9 FILLED**, **33 FIXED**. Missing after: 0.

### FILE_DATE

- Missing on 0 / 2,000. Present values match `entity.ApplyDate` on all 2,000 rows (calendar-day).
- `details.ApplyDate` mismatches on 11 / 2,000 (timezone day-boundary diffs); entity is authoritative.
- **Repair:** no changes (0 FILLED / 0 FIXED). Coverage 100%.

### PERMIT_DATE

- Missing on 348 / 2,000 (17.4%). When present, every value matches `entity.IssueDate` (0 incorrect).
- Among Active/Final before repair: Active 197/198 present; Final 1,004/1,039 present.
- Eight rows with IssueDate but null `PERMIT_DATE` were In Review while CaseStatus was Issued (6) or Complete (2) → filled after status fix.
- **Repair:** **8 FILLED**, **0 FIXED**. Missing after: 340.
- Post-repair Active PERMIT coverage: 181/182 (99.5%); Final: 1,012/1,047 (96.7%). Remaining gaps lack IssueDate in `DATA` (26 Plan Revision, 8 Miscellaneous, 1 Tenant Improvement; plus 1 Issued Plan Revision with `Issued=False`).

### FINAL_DATE

- Missing on 945 / 2,000 (47.2%). When present vs `entity.FinalDate`, every value matches (0 incorrect vs that field). `FinalDate` ≡ `details.FinalizeDate` on all rows.
- Among Final before repair: 1,039/1,039 had `FINAL_DATE`. All 1,047 Complete rows have FinalDate in DATA.
- **Spurious FINAL_DATE:** 16 non-Final rows carried `FINAL_DATE` equal to `entity.FinalDate` — Issued (4), Expired (5), Cancelled (3), In Review (4). These are not treated as permit finaled dates and are cleared; FinalDate alone does not promote status to Final.
- After status fixes, 8 Complete rows previously missing `FINAL_DATE` were filled.
- **Repair:** **8 FILLED**, **16 FIXED** (clears). Missing after: 953.
- Post-repair Final FINAL coverage: 1,047/1,047 (100%). Non-Final statuses have 0% FINAL_DATE by design.

## Repair performance

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | ---: | ---: | ---: | ---: |
| STATUS_NORMALIZED | 9 | 33 | 9 | 0 |
| FILE_DATE | 0 | 0 | 0 | 0 |
| PERMIT_DATE | 8 | 0 | 348 | 340 |
| FINAL_DATE | 8 | 16 | 945 | 953 |

Status distribution after repair: Final 1,047 · Inactive 597 · Active 182 · In Review 174.

Post-repair completeness by status:

| Status | FILE_DATE | PERMIT_DATE | FINAL_DATE |
| --- | ---: | ---: | ---: |
| Active | 100% | 99.5% | 0% |
| Final | 100% | 96.7% | 100% |
| In Review | 100% | 2.3% | 0% |
| Inactive | 100% | 77.6% | 0% |

Chronology: 3 `PERMIT < FILE` and 3 `FINAL < PERMIT` cases remain; all mirror inverted dates already present in `entity` (not introduced by repair).

## Artifacts

- Script: `agent/scripts/ca/data_repair_ca_fullerton.py` (`data_repair`)
- Repaired sample: `$AGENT_DATA_PATH/repaired/permits_ca_fullerton_repaired.parquet`

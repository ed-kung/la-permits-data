# Clovis (CA) data repair — 2026-07-28

Clovis was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. EnerGov JSON under `DATA` already has correct `FILE_DATE` (all rows) and, when populated, correct `PERMIT_DATE` / `FINAL_DATE` matching `entity.IssueDate` / `entity.FinalDate`. Main issues were unmapped / stale `STATUS_NORMALIZED` (3 missing Applied for Online; 85 wrong — mostly Nullified→In Review and Finaled lagged as Active), missing `FINAL_DATE` on 9–10 Final rows after status catch-up, and 406 spurious `FINAL_DATE` values on Application Approved (and a few Nullified/Comments Out) shells whose `FinalDate` is an application-close timestamp, not a permit finaled date.

## Jurisdiction selection

Walked `(JURISDICTION, STATE)` pairs in sample order and compared against `agent/scripts/{state}/data_repair_{state}_{city}.py`. First missing: **Clovis, CA** → `agent/scripts/ca/data_repair_ca_clovis.py` (n=2,000).

## DATA schema

All rows share Tyler EnerGov top-level keys (`entity`, `details`, `contacts`, `fees`, `processing_status`). 114 rows also carry a reviews bundle (`reviews` / `holds` / `attachments` / `more_info`). Canonical dates/status live under `entity` (`CaseStatus`, `ApplyDate`, `IssueDate`, `FinalDate`) with `details` fallbacks (`PermitStatus`, `ApplyDate`, `IssueDate`, `FinalizeDate`). Recorded in `INFERRED_SCHEMA`:

| Schema | n | Description |
| --- | ---: | --- |
| `entity_fees` | 1,886 | Base EnerGov payload |
| `entity_fees_reviews` | 114 | Base + reviews/holds/attachments/more_info |

## Field assessment

### STATUS_NORMALIZED

- Missing on 3 / 2,000 (0.2%): all `Applied for Online` (unmapped upstream).
- When `STATUS_ORIGINAL` matches `DATA.entity.CaseStatus`, existing normalization is mostly consistent (Finaled → Final; Issued → Active; Expired/Refunded → Inactive; Application Approved / Submitted / Plan Check / Comments / Payment Pending / Under Review → In Review).
- **Issues:**
  - 74 `Nullified` rows mapped to In Review → should be Inactive.
  - 9 `Finaled` rows where `STATUS_ORIGINAL` lagged (`issued` / `submitted`) → Active (8) or In Review (1) instead of Final.
  - 1 `Expired` with `STATUS_ORIGINAL` = `issued` → Active instead of Inactive.
  - 1 `Issued` / `PermitStatus` = `Finaled` disagreement → Active; prefer Final.
- **Repair:** map from CaseStatus / PermitStatus (prefer higher-rank mapping) → **3 FILLED**, **85 FIXED**. Missing after: 0.

### FILE_DATE

- Missing on 0 / 2,000. Present values match `entity.ApplyDate` on all 2,000 rows (calendar-day).
- `details.ApplyDate` matches on 1,991 / 2,000 (9 timezone day-boundary diffs); entity is authoritative.
- **Repair:** no changes (0 FILLED / 0 FIXED). Coverage 100%.

### PERMIT_DATE

- Missing on 524 / 2,000 (26.2%). When present, every value matches `entity.IssueDate` (0 incorrect).
- Among Active/Final before repair: Active 131/131 present; Final 1,168/1,177 present (9 Finaled with `Issued=False` and null IssueDate).
- One Finaled row lagged as In Review had IssueDate but null PERMIT_DATE → filled after status fix.
- **Repair:** **1 FILLED**, **0 FIXED**. Missing after: 523.
- Post-repair Active PERMIT coverage: 121/121 (100%); Final: 1,178/1,187 (99.2%). Remaining Final gaps lack IssueDate in `DATA` (water meters, fireworks operational, older custom SF dwellings).

### FINAL_DATE

- Missing on 419 / 2,000 (20.9%). When present vs `entity.FinalDate`, every value matches (0 incorrect vs that field).
- Among Final before repair: 1,175/1,177 had `FINAL_DATE`. Two older Finaled custom SF dwellings lack FinalDate/FinalizeDate entirely.
- **Major issue:** 406 non-Final rows carried `FINAL_DATE` equal to `entity.FinalDate` — almost all **Application Approved** residential/multi-family *permit applications* (381 Residential Permit Application + 19 Multi-Family/Non-Residential), where FinalDate is an application-close timestamp, not a building-permit finaled date. Also 5 Nullified and 1 Comments Out.
- After status fixes, 10 Final rows with FinalDate/FinalizeDate but null `FINAL_DATE` were filled (9 lagged Finaled + 1 Issued/Finaled disagreement using `details.FinalizeDate`).
- **Repair:** **10 FILLED**, **406 FIXED** (clears). Missing after: 815 (driven by clearing spurious Application Approved finals).
- Post-repair Final FINAL coverage: 1,185/1,187 (99.8%). Non-Final statuses have 0% FINAL_DATE by design.

## Repair performance

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | ---: | ---: | ---: | ---: |
| STATUS_NORMALIZED | 3 | 85 | 3 | 0 |
| FILE_DATE | 0 | 0 | 0 | 0 |
| PERMIT_DATE | 1 | 0 | 524 | 523 |
| FINAL_DATE | 10 | 406 | 419 | 815 |

Status distribution after repair: Final 1,187 · In Review 455 · Inactive 237 · Active 121.

Post-repair completeness by status:

| Status | FILE_DATE | PERMIT_DATE | FINAL_DATE |
| --- | ---: | ---: | ---: |
| Active | 100% | 100% | 0% |
| Final | 100% | 99.2% | 99.8% |
| In Review | 100% | 0% | 0% |
| Inactive | 100% | 75.1% | 0% |

Chronology: 1 `PERMIT < FILE` and 2 `FINAL < PERMIT` cases remain; all mirror inverted dates already present in `entity` (not introduced by repair).

## Artifacts

- Script: `agent/scripts/ca/data_repair_ca_clovis.py` (`data_repair`)
- Repaired sample: `$AGENT_DATA_PATH/repaired/permits_ca_clovis_repaired.parquet`

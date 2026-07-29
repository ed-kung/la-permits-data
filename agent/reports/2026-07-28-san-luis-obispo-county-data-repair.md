# San Luis Obispo County (CA) data repair — 2026-07-28

San Luis Obispo County was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script (Los Altos already had one). EnerGov JSON under `DATA` already has correct `FILE_DATE` for every row and correct `PERMIT_DATE` / `FINAL_DATE` whenever those were populated from `IssueDate` / `FinalDate`. Main issues were `STATUS_ORIGINAL` lagging `CaseStatus` (22 rows), 145 `Administrative Close` shells incorrectly labeled Final (mostly unissued Septic Inspection cases), 4 issued `Monitoring` cases kept as In Review, missing `PERMIT_DATE` / `FINAL_DATE` after status catch-up when Issue/Final dates exist in `DATA`, and 113+ spurious `FINAL_DATE` values on Void / Withdrawn / Expired / Issued / Monitoring shells. Repair fixes 167 statuses, fills 6 permit dates and 8 final dates, and clears 115 spurious finals; residual Active/Final gaps lack `IssueDate` in `DATA`.

## Jurisdiction selection

Walked `(JURISDICTION, STATE)` pairs in sample order and compared against `agent/scripts/{state}/data_repair_{state}_{city}.py`. First missing: **San Luis Obispo County, CA** → `agent/scripts/ca/data_repair_ca_san_luis_obispo_county.py` (n=2,000). Prior pair (Los Altos) already had a repair script.

## DATA schema

All rows share Tyler EnerGov top-level keys (`entity`, `details`, `contacts`, `fees`, `processing_status`). Canonical dates/status live under `entity` with `details` fallbacks (`CaseStatus` / `PermitStatus`, `ApplyDate`, `IssueDate`, `FinalDate` / `FinalizeDate`). Content variants recorded in `INFERRED_SCHEMA`:

| Schema | n | Description |
| --- | ---: | --- |
| `entity_fees` | 1,920 | entity + details + fees (+ contacts, processing_status) |
| `entity_fees_reviews` | 80 | plus reviews / holds / attachments / more_info |

`CaseStatus` and `details.PermitStatus` agree on every sample row. `processing_status` is almost always empty (1 non-empty list in the sample).

## Field assessment

### STATUS_NORMALIZED

- No missing values (0 / 2,000). Upstream mapping from `STATUS_ORIGINAL` is correct when it matches `CaseStatus`: `finaled`/`completed`→Final, `issued`→Active, `expired`/`withdrawn`/`void`→Inactive, `in review`/`intake`/`ready for issuance`/`on hold`/`submitted online`→In Review.
- **Issue (status lag):** 22 rows where `STATUS_ORIGINAL` lags `CaseStatus` (e.g. `issued` still Active while DATA is Finaled; `ready for issuance` still In Review while DATA is Issued; `expired` still Inactive while DATA is Finaled/Issued).
- **Issue (mislabel):** 145 `Administrative Close` rows were mapped to Final. These are mostly Septic Inspection shells (`Issued=False` on 125/145; FinalDate on only 2/145). Treat as Inactive, consistent with Riverside County `Administratively Closed` / Daly City `Admin Closed`.
- **Issue (Monitoring):** 4 issued condition-compliance `Monitoring` rows were In Review → Active.
- **Repair:** map from `CaseStatus` / `PermitStatus` → **0 FILLED**, **167 FIXED**. Missing after: 0.

Status transitions: Final→Inactive 145; In Review→Active 9; Active→Final 6; In Review→Inactive 3; Inactive→Final 1; In Review→Final 1; Active→Inactive 1; Inactive→Active 1.

### FILE_DATE

- Missing on 0 / 2,000. Present values match `entity.ApplyDate` on all 2,000 rows (0 incorrect).
- **Repair:** no changes (0 FILLED / 0 FIXED). Coverage 100%.

### PERMIT_DATE

- Missing on 394 / 2,000 (19.7%). When present, every value matches `IssueDate` (0 incorrect).
- Among Active/Final before repair: most Issued/Finaled rows already had `PERMIT_DATE`. Recoverable after status catch-up: 5 Issued (was In Review) + 1 Finaled intake→Final with IssueDate.
- Unfillable: 125 Administrative Close (now Inactive), 2 Completed without IssueDate, 1 Finaled Express panel replacement with `Issued=False`.
- **Repair:** **6 FILLED**, **0 FIXED**. Missing after: 388.
- Post-repair Active PERMIT coverage: 234/234 (100%); Final: 1,275/1,278 (99.8%). Remaining Final gaps lack `IssueDate` in `DATA`.

### FINAL_DATE

- Missing on 615 / 2,000 (30.8%). When present and status is true Finaled/Completed, values match `FinalDate` / `FinalizeDate` (0 incorrect vs those fields).
- Among Final before repair: 143 missing FINAL_DATE were almost all Administrative Close (no FinalDate available). Eight Finaled rows that were status-lagged (Active/Inactive/In Review) had FinalDate with null `FINAL_DATE` → FILLED after promotion to Final.
- **Spurious FINAL_DATE:** 113+ non-Final rows (Void, Withdrawn, Expired, Issued, Monitoring, On Hold) carried `entity.FinalDate` as a case-closure stamp → cleared. After Admin Close→Inactive, any residual FinalDate stamp is also cleared.
- **Repair:** **8 FILLED**, **115 FIXED** (clears). Missing after: 722 (increase is intentional clearing of non-Final stamps).
- Post-repair Final FINAL coverage: 1,278/1,278 (100%). Active / In Review / Inactive: 0% by design.

## Repair performance

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | ---: | ---: | ---: | ---: |
| STATUS_NORMALIZED | 0 | 167 | 0 | 0 |
| FILE_DATE | 0 | 0 | 0 | 0 |
| PERMIT_DATE | 6 | 0 | 394 | 388 |
| FINAL_DATE | 8 | 115 | 615 | 722 |

Status distribution after repair: Final 1,278 · Inactive 328 · Active 234 · In Review 160.

Post-repair completeness by status:

| Status | n | FILE_DATE | PERMIT_DATE | FINAL_DATE |
| --- | ---: | ---: | ---: | ---: |
| Active | 234 | 100% | 100% | 0% |
| Final | 1,278 | 100% | 99.8% | 100% |
| In Review | 160 | 100% | 5.6% | 0% |
| Inactive | 328 | 100% | 28.7% | 0% |

Overall FILE_DATE coverage: 2,000 / 2,000 (100%). Active+Final PERMIT_DATE: 1,509 / 1,512 (99.8%).

Chronology: 16 `FILE > PERMIT` and 4 `PERMIT > FINAL` cases remain; all mirror inverted Apply/Issue/Final timestamps already present in `entity` before repair (often same-calendar-day UTC offset artifacts), not introduced by repair.

## Artifacts

- Repair script: `agent/scripts/ca/data_repair_ca_san_luis_obispo_county.py`
- Repaired sample parquet: `$AGENT_DATA_PATH/repaired/permits_ca_san_luis_obispo_county_repaired.parquet`

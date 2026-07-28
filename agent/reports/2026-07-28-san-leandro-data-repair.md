# San Leandro (CA) data repair — 2026-07-28

San Leandro was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. Accela Citizen Access JSON under `DATA` already has correct `FILE_DATE` on every row and correct `PERMIT_DATE` / `FINAL_DATE` when those fields were previously populated. Main issues were wrong `STATUS_NORMALIZED` when `STATUS_ORIGINAL` lagged `DATA.status` (Finaled left Active/Inactive; Ready for Inspection left In Review; Expired / Permit Expired left In Review/Active; Approved address requests mapped to Active), plus missing `PERMIT_DATE` on Active/Final OTC rows with `Application Submittal|Issued`, and missing `FINAL_DATE` on five Finaled rows carrying `Inspection|Final Inspection Complete`. Repair fixes 18 statuses, fills 186 permit dates and 5 final dates.

## Jurisdiction selection

Walked `(JURISDICTION, STATE)` pairs in sample order and compared against `agent/scripts/{state}/data_repair_{state}_{city}.py`. First missing: **San Leandro, CA** → `agent/scripts/ca/data_repair_ca_san_leandro.py` (n=2,000).

## DATA schema

All rows share Accela top-level keys (`status`, `date`, `tasks`, `inspections`, `search_data`, `more_details`, …). `inspections` is always null in this sample; dates come from `DATA.date` / `search_data.Date` and dated `tasks[].events` (`Marked as` / `on`). Content variants recorded in `INFERRED_SCHEMA`:

| Schema | n | Description |
| --- | ---: | --- |
| `accela_shell` | 1,317 | Task list present, no dated events |
| `accela_tasks` | 645 | At least one dated workflow event |
| `unknown` | 38 | No usable tasks (blank/ERR shells) |

## Field assessment

### STATUS_NORMALIZED

- Missing on 39 / 2,000 (blank `DATA.status` / `ERR` historical shells with no events).
- When `STATUS_ORIGINAL` matches `DATA.status`, common mappings are consistent (Finaled → Final; Issued/Active/Ready for Inspection → Active; Received/In Review/… → In Review; Expired/Cancelled/Void → Inactive).
- **Issues:**
  - 5 rows with `DATA.status=Finaled` but `STATUS_ORIGINAL=ready for inspection` left as Active (all have `Inspection|Final Inspection Complete`).
  - 1 Finaled row (`B18-2220`) with `STATUS_ORIGINAL=expired` left as Inactive.
  - 4 Ready for Inspection rows left as In Review despite `Permit Issuance|Issued`.
  - 2 Expired + 2 Permit Expired rows left as In Review / Active → should be Inactive.
  - 4 Approved address-request rows mapped to Active with no issuance → In Review.
- **Repair:** map from `DATA.status` (plus Final upgrade when non-inactive final-inspection evidence present) → **0 FILLED**, **18 FIXED**. Missing after: 39 (unrecoverable blank/ERR shells).

Status transitions: Active→Final 5; Inactive→Final 1; In Review→Active 4; Active→In Review 4; In Review→Inactive 2; Active→Inactive 2.

### FILE_DATE

- Missing on 0 / 2,000. Every value matches `DATA.date` (and `search_data.Date`).
- **Repair:** no changes (0 FILLED / 0 FIXED). Coverage 100%.

### PERMIT_DATE

- Missing on 1,680 / 2,000 (84.0%). When present (320), every value matches either `Ready to Issue|Issued` (190) or `Permit Issuance|Issued` (130) — 0 incorrect vs those sources.
- Among Active/Final before repair: Active 87/263 present, Final 202/1,098 present.
- Recoverable gaps: mostly Finaled OTC combo permits with `Application Submittal|Issued` but no Ready-to-Issue / Permit-Issuance task; plus 4 Ready-for-Inspection rows promoted to Active.
- **Repair:** **186 FILLED** (4 from Permit Issuance, 182 from Application Submittal Issued), **0 FIXED**. Missing after: 1,494.
- Post-repair Active PERMIT coverage: 93/256 (36.3%); Final: 381/1,104 (34.5%). Remaining gaps are almost all `accela_shell` rows with no issuance marks in `DATA` (Active gaps: 163/163 no dated events; Final gaps: 713 shells + 10 task rows without Issued marks).

### FINAL_DATE

- Missing on 1,779 / 2,000 (89.0%). When present (221), every value matches `Inspections|Finaled` or `Inspection|Final Inspection Complete` (0 incorrect).
- Among Final before repair: 221/1,098 had `FINAL_DATE`. No spurious `FINAL_DATE` on non-Final rows.
- After status repair, 5 Finaled→Final upgrades fill `FINAL_DATE` from `Inspection|Final Inspection Complete`.
- **Repair:** **5 FILLED**, **0 FIXED**. Missing after: 1,774.
- Post-repair Final FINAL coverage: 226/1,104 (20.5%). Remaining gaps: 713 shells with empty inspection events + 165 Finaled task rows whose Inspections events are only `TBD` (no Finaled / Final Inspection Complete mark).

## Repair performance

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | ---: | ---: | ---: | ---: |
| STATUS_NORMALIZED | 0 | 18 | 39 | 39 |
| FILE_DATE | 0 | 0 | 0 | 0 |
| PERMIT_DATE | 186 | 0 | 1,680 | 1,494 |
| FINAL_DATE | 5 | 0 | 1,779 | 1,774 |

Status distribution after repair: Final 1,104 · In Review 324 · Inactive 277 · Active 256 · missing 39.

Post-repair completeness by status:

| Status | FILE_DATE | PERMIT_DATE | FINAL_DATE |
| --- | ---: | ---: | ---: |
| Active | 100% | 36.3% | 0% |
| Final | 100% | 34.5% | 20.5% |
| In Review | 100% | 0.6% | 0% |
| Inactive | 100% | 10.8% | 0% |

Chronology after repair: `PERMIT_DATE < FILE_DATE` = 0; `FINAL_DATE < PERMIT_DATE` = 0.

## Artifacts

- Repair script: `agent/scripts/ca/data_repair_ca_san_leandro.py` (`data_repair`)
- Repaired sample: `$AGENT_DATA_PATH/san_leandro_repaired_sample.parquet`

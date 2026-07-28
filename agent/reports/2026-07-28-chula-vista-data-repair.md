# Chula Vista (CA) data repair — 2026-07-28

Chula Vista was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. Accela JSON under `DATA` already has correct `FILE_DATE` for all 2,000 rows. `STATUS_NORMALIZED` missed several workflow statuses and lagged `DATA.status` on Issued/Closed/Approved rows; `PERMIT_DATE` often used Ready-To-Issue instead of Issued and was missing on many Final rows that still had KEY DATES Issued; `FINAL_DATE` was fillable from Closed / final-inspection events and KEY DATES Final, with spurious finals cleared on non-Final rows.

## Jurisdiction selection

Walked `(JURISDICTION, STATE)` pairs in sample order and compared against `agent/scripts/{state}/data_repair_{state}_{city}.py`. First missing: **Chula Vista, CA** → `agent/scripts/ca/data_repair_ca_chula_vista.py` (n=2,000).

## DATA schema

Accela Citizen Access scrape. All rows share the same top-level keys (`status`, `date`, `tasks`, `inspections`, `search_data`, `more_details`, …). Content variants recorded in `INFERRED_SCHEMA`:

| Schema | n | Description |
| --- | ---: | --- |
| `accela_tasks` | 1,490 | Dated workflow events under `tasks` |
| `accela_shell` | 506 | Task shells present but no dated events (often KEY DATES-only) |
| `accela_search_only` | 4 | No tasks list |

Canonical fields: `DATA.status` / `search_data.Status` → status; `DATA.date` → file; `Permit Issuance`/`Issuance` Marked as Issued (else KEY DATES `Issued`) → permit; `Closed` / final-inspection marks / KEY DATES `Final` → final.

## Field assessment

### STATUS_NORMALIZED

- Missing on 28 / 2,000 (1.4%) before repair. Fifteen blank-`DATA.status` shells (mostly contractor-info / micro-cell records) remain unmapped; the other 13 are statuses the upstream mapper never handled (`Primary Review`, `No Comment`, `Final Letter Sent`, `Securities Released`, `Public Notice Sent`, `Meeting Complete`, `Hold`, `CONVERTD`).
- Mapping from `DATA.status` is clean once expanded: Closed / Final Inspection Complete / Finaled / Complete → Final; Issued / Active → Active; Expired / Void / Withdrawn / TEST → Inactive; pre-issuance including Approved and Open → In Review.
- **Issues:** (1) Approved/APPROVED (21 rows) were labeled Active with no issuance evidence — should be In Review. (2) STATUS_ORIGINAL lagged DATA on Issued-still-In-Review (3), Closed-still-Active (4), Withdrawn/TEST still In Review (2). (3) One Ready to Issue row already had Permit Issuance Marked as Issued → promote to Active.
- **Repair:** overwrite from DATA (+ issuance promotion) → **13 FILLED**, **31 FIXED**. Missing after: 15 (blank status shells).

### FILE_DATE

- Already populated for 100% of rows; equals `DATA.date` on every sample row (also matches `search_data.Date` on 1,993 / 2,000).
- `KEY DATES.Applied` can differ from `DATA.date` when later resubmittals update Applied; top-level `date` is the application/opened date and is authoritative.
- **Repair:** no changes (0 FILLED / 0 FIXED).

### PERMIT_DATE

- Missing on 712 / 2,000 (35.6%) before repair. Among Active/Final with a date, most matched Permit Issuance Issued; ~200 rows used Ready To Issue (typically one day earlier) or C of O Issued instead of the true Issued date.
- Active/Final missing PERMIT_DATE were largely `accela_shell` rows with KEY DATES `Issued` but no dated Issued task event (270 fillable from KEY DATES).
- After repair, Active is 98.0% issued (6 Issued/Active shells lack any Issued source — mostly Residential Utility Citizen Access). Final is 93.6% issued.
- **Repair:** **274 FILLED**, **236 FIXED** (232 value corrections + 4 clears of spurious In Review permits). Missing after: 442.

### FINAL_DATE

- Missing on 962 / 2,000 before repair; among labeled Final, 290 lacked FINAL_DATE.
- When present, usually matched Closed + Final Inspection Complete task marks. KEY DATES Final covered many older shells without dated Closed events.
- **Issues:** (1) 284 Final rows fillable from Closed / KEY DATES Final / inspection marks; (2) 57 non-Final rows carried FINAL_DATE (Active Issued, Expired) — cleared; (3) 55 Final rows had a date that disagreed with the best DATA source (often off vs KEY DATES Final) → corrected.
- Ten Final rows remain without a recoverable date (Grading Permit Closed shells, Preliminary Review Complete, Final Letter Sent without dates).
- **Repair:** **284 FILLED**, **112 FIXED** (55 value corrections + 57 clears). Missing after: 735; among Final, 99.2% have FINAL_DATE.

## Repair performance

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | ---: | ---: | ---: | ---: |
| STATUS_NORMALIZED | 13 | 31 | 28 | 15 |
| FILE_DATE | 0 | 0 | 0 | 0 |
| PERMIT_DATE | 274 | 236 | 712 | 442 |
| FINAL_DATE | 284 | 112 | 962 | 735 |

Status distribution after repair: Final 1,275 · Active 306 · In Review 202 · Inactive 202 · null 15.

Post-repair completeness by status:

| Status | FILE_DATE | PERMIT_DATE | FINAL_DATE |
| --- | ---: | ---: | ---: |
| Active | 100% | 98.0% | 0% |
| Final | 100% | 93.6% | 99.2% |
| In Review | 100% | 0% | 0% |
| Inactive | 100% | 32.2% | 0% |

One FILE>PERMIT and one PERMIT>FINAL day inversion remain in source Accela dates; dates are left as in DATA.

## Artifacts

- Script: `agent/scripts/ca/data_repair_ca_chula_vista.py` (`data_repair`)
- Repaired sample: `$AGENT_DATA_PATH/chula_vista_repaired_sample.parquet`

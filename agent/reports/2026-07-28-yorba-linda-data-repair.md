# Yorba Linda (CA) data repair — 2026-07-28

Yorba Linda was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. DATA is an Accela Citizen Access scrape (`status`, `date`, `tasks`, …). Repair corrects mis-mapped statuses (Approved→In Review; Transfer/Code Enforcement→Active; Expired/Issued/Transfer with Final Inspection Complete→Final), fills 1,745 missing file dates from `search_data.Date` / Application Submittal|Accepted, fills 8 missing final dates from Close / Final Inspection marks, upgrades final dates on multi-cycle finals, and clears 4 spurious Pre-Site finals on still-Issued/Transfer rows. `PERMIT_DATE` already matched `Permit Issuance|Issued` wherever both were present.

## Jurisdiction selection

Walked `(JURISDICTION, STATE)` pairs in sample order and compared against `agent/scripts/{state}/data_repair_{state}_{city}.py`. First missing: **Yorba Linda, CA** → `agent/scripts/ca/data_repair_ca_yorba_linda.py` (n=2,000).

## DATA schema

All rows are Accela payloads. Content variants recorded in `INFERRED_SCHEMA`:

| Schema | n | Description |
| --- | ---: | --- |
| `accela_tasks` | 1,986 | Dated workflow events under `tasks` |
| `accela_shell` | 8 | Task shells present but no dated events |
| `accela_search_only` | 6 | Only `search_data` (incl. 4 blank-status TMP solar shells) |

Canonical fields: `DATA.status` → status; `search_data.Date` / Application Submittal|Accepted → file date; `Permit Issuance|Issued` → permit date; `Inspections|Final Inspection Complete` (else `Complete|Close` for Finaled/Closed) → final date.

Note: top-level `DATA.date` is usually a record id (`YL-*`), not a calendar date.

## Field assessment

### STATUS_NORMALIZED

- Missing on **4 / 2,000** (TMP solar shells with blank `DATA.status` / `search_data.Status`) — unfillable.
- Existing mappings vs `DATA.status` were mostly correct (`Finaled→Final`, `Issued→Active`, `Expired/Void/Withdrawn→Inactive`, `In Plan Check/Pending→In Review`).
- Incorrect / incomplete mappings repaired:
  - **Approved → Active** (3): plan approval without issuance; should be In Review.
  - **Transfer → In Review** (15): all have Permit Issuance|Issued; 1 also has Final Inspection Complete → Final; remaining → Active.
  - **Code Enforcement → In Review** (9): all issued → Active.
  - **Expired / Issued** with Final Inspection Complete (5): should be Final.
- **Repair:** **0 FILLED**, **32 FIXED**. Missing after: 4.

### FILE_DATE

- Missing on **1,757 / 2,000**. Nearly all have Application Submittal|Accepted (or `Accepted - No Pre-App`); 245 also have `search_data.Date`.
- Prefer `search_data.Date` (opened/submitted) over staff Accepted when both exist — Accepted often lags 1–7 days. Of 243 rows with both FILE and search Date, 241 already matched.
- 2 rows had FILE disagreeing with `search_data.Date` → FIXED to search Date.
- 12 shells lack any usable opened/Accepted date → remain missing.
- **Repair:** **1,745 FILLED**, **2 FIXED**. Missing after: 12.

### PERMIT_DATE

- Missing on **89 / 2,000**. Existing values matched `Permit Issuance|Issued` / `Permit Issued` on 1,911 / 1,911 comparable rows (0 mismatches).
- After status repair, Active has PERMIT_DATE on 67/68 (98.5%); Final on 1,570/1,575 (99.7%). Remaining gaps are Accela shells with no Issued event (and Approved rows now correctly In Review).
- No fillable Active/Final gaps remained after status remapping.
- **Repair:** **0 FILLED**, **0 FIXED**. Missing after: 89.

### FINAL_DATE

- Missing on **441 / 2,000**. Among Final rows, 19 lacked FINAL_DATE before repair; 8 of those have `Complete|Close` (often paired with Inspections|Expired) and were filled; 11 Finaled shells have only TBD inspections → unfillable.
- Prefer latest `Inspections|Final Inspection Complete` over administrative Close. 5 multi-cycle Finaled rows had FINAL set to an earlier cycle → FIXED to latest.
- Spurious FINAL on non-Final rows: 3 Issued + 1 Transfer used Pre-Site Inspection Completed (often FINAL < PERMIT) → cleared. 4 Expired and 1 Transfer/Issued with true Final Inspection Complete were upgraded to Final (FINAL retained).
- `Complete|Close` alone is **not** used to upgrade status — it fires on expired Issued permits and sometimes before issuance.
- **Repair:** **8 FILLED**, **9 FIXED**. Missing after: 437 (12 still-Final rows lack any final workflow mark).

## Repair performance

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | ---: | ---: | ---: | ---: |
| STATUS_NORMALIZED | 0 | 32 | 4 | 4 |
| FILE_DATE | 1,745 | 2 | 1,757 | 12 |
| PERMIT_DATE | 0 | 0 | 89 | 89 |
| FINAL_DATE | 8 | 9 | 441 | 437 |

Status distribution after repair: Final 1,575 · Inactive 343 · Active 68 · In Review 10 · null 4.

Post-repair completeness by status:

| Status | FILE_DATE | PERMIT_DATE | FINAL_DATE |
| --- | ---: | ---: | ---: |
| Active | 100% | 98.5% | 0% |
| Final | 99.8% | 99.7% | 99.2% |
| In Review | 100% | 0% | 0% |
| Inactive | 97.4% | 79.9% | 0% |

Chronology: 0 `PERMIT < FILE`; 1 `FINAL < PERMIT` (source anomaly: Final Inspection Complete 1999-07-29 precedes Issued 1999-08-05 — inspection date retained).

## Artifacts

- Repair script: `agent/scripts/ca/data_repair_ca_yorba_linda.py`
- Repaired sample: `$AGENT_DATA_PATH/yorba_linda_repaired_sample.parquet`

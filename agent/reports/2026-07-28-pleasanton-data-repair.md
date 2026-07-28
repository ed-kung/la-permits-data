# Pleasanton (CA) data repair — 2026-07-28

Pleasanton was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. DATA is an Accela Citizen Access scrape (`status`, `date`, `tasks`, …). Repair corrects STATUS_ORIGINAL-driven mismatches (Finaled→Active, Issued→In Review), remaps Approved-without-issuance to In Review, fills 10 previously unmapped statuses, fills 20 missing permit dates from Issue / Construction Permit / ZC-Business License marks (and fixes 1 Pending Issue date), and fills 1,312 missing final dates from Construction|Finaled / Complete|Complete / Closeout|Complete. `FILE_DATE` already matched `DATA.date` / `search_data.Date` on all 2,001 rows.

## Jurisdiction selection

Walked `(JURISDICTION, STATE)` pairs in sample order and compared against `agent/scripts/{state}/data_repair_{state}_{city}.py`. First missing: **Pleasanton, CA** → `agent/scripts/ca/data_repair_ca_pleasanton.py` (n=2,001).

## DATA schema

All rows are Accela payloads. Content variants recorded in `INFERRED_SCHEMA`:

| Schema | n | Description |
| --- | ---: | --- |
| `accela_tasks` | 1,859 | Dated workflow events under `tasks` |
| `accela_shell` | 142 | Task shells present but no dated events (incl. ~90 blank-status Oversize Load / Encroachment shells) |

Canonical fields: `DATA.status` → status; `search_data.Date` / `DATA.date` → file date; `Issue Permit|Issued` (or `Issue|Issue`, `Construction Permit|Issue`, `Zoning Certificate - Business License|Issued`) → permit date; `Construction|Finaled` (else `Closeout|Complete`, `Complete|Complete`, `Approved|Closed`, `Improvements|Completed`) → final date.

## Field assessment

### STATUS_NORMALIZED

- Missing on **100 / 2,001**. Of those, 90 have blank `DATA.status` / `search_data.Status` (mostly Oversize Load shells with `Issue|TBD` only) — unfillable. 10 have usable Accela statuses that were never mapped (`Approved w/ Conditions`, `Scheduled PC`, `Accepted Plan Check`, `Accepted OTC`, `Improvements Complete`, `Improvements Accepted`, `Conditions Met`) → FILLED.
- Existing mappings were mostly correct (`Finaled/Complete/Closed→Final`, `Issued→Active`, `Expired/Void/Withdrawn/Cancelled→Inactive`, review-stage labels→In Review).
- Incorrect / incomplete mappings repaired:
  - **Finaled → Active** (4): `STATUS_ORIGINAL=issued` overrode `DATA.status=Finaled` (all have Construction|Finaled) → Final.
  - **Issued → In Review** (8): `STATUS_ORIGINAL` lagged Accela header status; all have Issue Permit|Issued → Active.
  - **Approved → Active** (4): plan approval without issuance → In Review; 1 Approved with Issue Permit|Issued stays Active.
  - **Closed → In Review** (1), **Denied/Withdrawn → In Review** (2), **Expired → Active** (1) → FIXED from `DATA.status`.
- **Repair:** **10 FILLED**, **20 FIXED**. Missing after: 90.

### FILE_DATE

- Missing on **0 / 2,001**. Every row's `FILE_DATE` already matches top-level `DATA.date`; 1,998 also match `search_data.Date`.
- **Repair:** **0 FILLED**, **0 FIXED**. Missing after: 0.

### PERMIT_DATE

- Missing on **620 / 2,001**. Existing values matched `Issue Permit|Issued` / `Issue|Issue` on 1,380 / 1,381 comparable rows.
- 1 mismatch (`E21-0224`): `PERMIT_DATE` taken from `Pending Issue` (2021-04-06) instead of later `Issue` (2021-04-09) → FIXED.
- After status repair, Active has PERMIT_DATE on 271/272 (99.6%). The one gap (`B22-0375`) is `DATA.status=Issued` with no Issue event in tasks.
- Final has PERMIT_DATE on 977/1,395 (70.0%). The ~418 gaps are almost entirely `Complete` Zoning Certificate / design-review / KIVA records with no Issue workflow — administrative completions, not issued building permits.
- 20 Active/Final gaps filled from Issue / Construction Permit / ZC-Business License marks (incl. Improvements Complete/Accepted).
- **Repair:** **20 FILLED**, **1 FIXED**. Missing after: 600.

### FINAL_DATE

- Missing on **1,997 / 2,001**. Only 4 Complete rows already carried FINAL (matching `Complete|Complete`).
- Among Final rows after status repair, 1,316 / 1,395 (94.3%) gained or already had a final date from Construction|Finaled (932), Complete|Complete (~289), Closeout|Complete (~87), Approved|Closed (2), or Improvements|Completed (1).
- 79 Final rows remain without FINAL_DATE: 40 empty KIVA FILE shells, 30 Oversize Load Finaled with only `Issue|Issue`, plus a handful of Closed/Complete planning records with no Closeout/Complete mark.
- No spurious FINAL_DATE on non-Final rows to clear. Chronology: 0 `FINAL < PERMIT`.
- **Repair:** **1,312 FILLED**, **0 FIXED**. Missing after: 685.

## Repair performance

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | ---: | ---: | ---: | ---: |
| STATUS_NORMALIZED | 10 | 20 | 100 | 90 |
| FILE_DATE | 0 | 0 | 0 | 0 |
| PERMIT_DATE | 20 | 1 | 620 | 600 |
| FINAL_DATE | 1,312 | 0 | 1,997 | 685 |

Status distribution after repair: Final 1,395 · Active 272 · Inactive 172 · In Review 72 · null 90.

Post-repair completeness by status:

| Status | FILE_DATE | PERMIT_DATE | FINAL_DATE |
| --- | ---: | ---: | ---: |
| Active | 100% | 99.6% | 0% |
| Final | 100% | 70.0% | 94.3% |
| In Review | 100% | 2.8% | 0% |
| Inactive | 100% | 87.8% | 0% |

Chronology: 0 `PERMIT < FILE`; 0 `FINAL < PERMIT`.

## Artifacts

- Repair script: `agent/scripts/ca/data_repair_ca_pleasanton.py`
- Repaired sample: `$AGENT_DATA_PATH/pleasanton_repaired_sample.parquet`

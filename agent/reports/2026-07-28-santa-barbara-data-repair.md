# Santa Barbara (CA) data repair — 2026-07-28

Santa Barbara city was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script (`data_repair_ca_santa_barbara_county.py` covers the county only). Accela JSON under `DATA` already has correct `FILE_DATE` on 1,999 / 2,000 rows and mostly correct `STATUS_NORMALIZED`. Date gaps are structural: most Historic Permits / older Completed and Issued rows are `accela_minimal` shells with no dated tasks or inspections, so `PERMIT_DATE` / `FINAL_DATE` cannot be recovered from DATA for ~80% of Final rows. Where dated workflow exists, issuance already matched; finals often used the first Final Inspection Complete instead of the latest Closed / FI / passed-final inspection.

## Jurisdiction selection

Walked `(JURISDICTION, STATE)` pairs in sample order and compared against `agent/scripts/{state}/data_repair_{state}_{city}.py`. First missing: **Santa Barbara, CA** → `agent/scripts/ca/data_repair_ca_santa_barbara.py` (n=2,000).

## DATA schema

Accela Citizen Access scrape. Variants recorded in `INFERRED_SCHEMA`:

| Schema | n | Description |
| --- | ---: | --- |
| `accela_minimal` | 1,343 | Address / contacts / details; tasks empty/null (Historic Permits, older Completed/Issued) |
| `accela_full` | 324 | Dated tasks plus inspections / conditions / fees_details |
| `accela_tasks` | 275 | Dated workflow events under `tasks` |
| `accela_shell` | 57 | Task shells present but no dated events |
| `search_only` | 1 | Only `search_data` (blank status temp record) |

Canonical fields: `DATA.status` / `search_data.Status` → status; `DATA.date` / `search_data.Date` → file; `Permit Issuance` Marked as Issued → permit; latest among Closed / Final Inspection Complete / passed final-titled inspections → final.

## Field assessment

### STATUS_NORMALIZED

- Missing on 5 / 2,000 before repair. Four are unmapped review statuses (`Documents Received`, `Corrections Incomplete`, `Responses Required`×2) → In Review. One blank-status temp record (`25TMP-006911`) stays null.
- Existing mappings from `DATA.status` are otherwise consistent (Completed/Complete/Finaled/Closed → Final; Issued/Permit Issued/Code Mod Approved → Active; expired/void/withdrawn/canceled → Inactive; plan-review / applicant-action statuses → In Review).
- **Issues:** (1) nulls above; (2) `Hold Placed On Record` (2) labeled Inactive — these are review holds → In Review.
- **Repair:** **4 FILLED**, **2 FIXED**. Missing after: 1.

### FILE_DATE

- Populated for 1,999 / 2,000; equals `DATA.date` or `search_data.Date` on every parseable row.
- The single miss (`BLD2016-11111`) is a test record whose top-level `date` is a non-date dict template and has no usable search Date.
- **Repair:** no changes (0 FILLED / 0 FIXED). Missing after: 1.

### PERMIT_DATE

- Missing on 1,516 / 2,000 (75.8%) before repair. When present alongside a Permit Issuance / Issued event, values already matched (0 value mismatches).
- Active missing PERMIT_DATE (119): status is Issued / Permit Issued / Code Mod Approved, but 97 have no tasks and 22 have empty Permit Issuance events — not fillable from DATA.
- Final missing PERMIT_DATE (1,045): almost all `accela_minimal` Completed shells with no Issued event.
- **Issues:** one In Review `Fees Paid` row carried PERMIT_DATE from Fees Paid / Fees Due (not issuance) → cleared.
- **Repair:** **0 FILLED**, **1 FIXED** (clear). Missing after: 1,517.
- Post-repair among rich schemas: `accela_full` Final 100% issued; `accela_tasks` Final 83.3% issued; Active overall 65.5% issued.

### FINAL_DATE

- Missing on 1,735 / 2,000 before repair; among Final, 1,030 lacked FINAL_DATE (mostly `accela_minimal` with neither Closed/FI events nor inspections).
- When present, usually matched the *first* Final Inspection Complete (and often the first Closed). Reopened records with a later Closed / FI / passed final inspection were wrong.
- **Issues:** (1) 8 Final rows corrected to the latest finaling candidate; (2) 3 Final rows with inspections but no Closed/FI task dates filled from passed final-titled inspections; (3) no spurious FINAL_DATE on non-Final rows.
- After repair, Final overall is only 20.7% dated, but `accela_full` Final is 96.2% and `accela_tasks` Final is 99.3%.
- **Repair:** **3 FILLED**, **8 FIXED**. Missing after: 1,732.

## Repair performance

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | ---: | ---: | ---: | ---: |
| STATUS_NORMALIZED | 4 | 2 | 5 | 1 |
| FILE_DATE | 0 | 0 | 1 | 1 |
| PERMIT_DATE | 0 | 1 | 1,516 | 1,517 |
| FINAL_DATE | 3 | 8 | 1,735 | 1,732 |

Status distribution after repair: Final 1,295 · Active 345 · In Review 97 · Inactive 262 · null 1.

Post-repair completeness by status:

| Status | FILE_DATE | PERMIT_DATE | FINAL_DATE |
| --- | ---: | ---: | ---: |
| Active | 100% | 65.5% | 0% |
| Final | 99.9% | 19.3% | 20.7% |
| In Review | 100% | 0% | 0% |
| Inactive | 100% | 2.7% | 0% |

No FILE>PERMIT or PERMIT>FINAL day inversions after repair. Remaining Active/Final date gaps are Accela shells without dated issuance or finaling events in DATA.

## Artifacts

- Script: `agent/scripts/ca/data_repair_ca_santa_barbara.py` (`data_repair`)
- Repaired sample: `$AGENT_DATA_PATH/santa_barbara_repaired_sample.parquet`

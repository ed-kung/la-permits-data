# Ventura County (CA) data repair — 2026-07-28

Ventura County was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. DATA is an Accela Citizen Access scrape (`status`, `date`, `tasks`, …). Repair corrects mis-mapped statuses (Estimate→Final, Approved→Active), fills 93 previously null statuses, fills 65 missing permit dates and 116 missing final dates from workflow events, and upgrades 6 Issued/Inspection Pending rows that already carry final marks. `FILE_DATE` already matched `DATA.date` on every sample row.

## Jurisdiction selection

Walked `(JURISDICTION, STATE)` pairs in sample order and compared against `agent/scripts/{state}/data_repair_{state}_{city}.py`. First missing: **Ventura County, CA** → `agent/scripts/ca/data_repair_ca_ventura_county.py` (n=2,000).

## DATA schema

All rows are Accela payloads. Content variants recorded in `INFERRED_SCHEMA`:

| Schema | n | Description |
| --- | ---: | --- |
| `accela_tasks` | 1,550 | Dated workflow events under `tasks` |
| `accela_shell` | 450 | Task shells present but no dated events |

Canonical fields: `DATA.status` → status; `DATA.date` → file date; `Plans Approved` / `Permit Issuance` / OTC marks → permit date; `Inspections` Work Complete / Finaled (else `Close` / Certificate of Occupancy) → final date.

## Field assessment

### STATUS_NORMALIZED

- Missing on **207 / 2,000**. Of those, 114 have blank `DATA.status` (mostly Public Records shells) and stay unfillable; 93 are unmapped review/billing/enforcement strings.
- Incorrect mappings vs `DATA.status`:
  - **Estimate → Final** (48): fee estimates with no issuance; should be In Review.
  - **Approved → Active** (80): planning / plan-check approval without an Issued mark; should be In Review.
  - **Approved OTC → In Review** (2): fire OTC ready for inspection; should be Active.
  - **Exempt → In Review** (4): recycling-plan exempt; should be Inactive.
  - **Abated → Inactive** (2): resolved compliance; should be Final.
  - **Issued / Inspection Pending** with Work Complete / Finaled / Close (6): stale Active; should be Final.
- **Repair:** **93 FILLED**, **142 FIXED**. Missing after: 114.

### FILE_DATE

- Missing on **0 / 2,000**. Every row’s `FILE_DATE` matches `DATA.date` (and `search_data.Date`) at day resolution.
- Applied-task dates sometimes differ from opened date; Accela top-level `date` is treated as the application/opened date.
- **Repair:** **0 FILLED**, **0 FIXED**. Missing after: 0.

### PERMIT_DATE

- Missing on **903 / 2,000**. Existing values matched workflow issuance marks wherever both were present (0 mismatches).
- Fillable gaps: Plans Approved|Issued, Permit Issuance|Issued, Permit Status|Issued, Application Submittal|Issued / OTC - No Plan Check, Plan Check|Approved OTC (Active/Final only), Permit Issuance|To Be Billed (encroachment OTC).
- After status repair, Active has PERMIT_DATE on 312/334 (93.4%); Final on 786/1,042 (75.4%). Remaining gaps are Accela shells / Final/Closed records with no issuance event, plus NOV/NOI and some Inspection Pending / Permit Issued shells.
- **Repair:** **65 FILLED**, **0 FIXED**. Missing after: 838.

### FINAL_DATE

- Missing on **1,288 / 2,000**. Among Final rows, 377 lacked FINAL_DATE before repair.
- Prefer `Inspections`/`Inspection` marks (`Work Complete`, `Finaled`, `Work Complete - C of O Needed`, …) and Certificate of Occupancy|Complete over administrative `Close|Closed` (which can lag). When C of O was still needed, FINAL moves to CoO Complete / Close.
- 116 Final rows filled from Close / inspection marks; 17 corrected (later Work Complete, CoO after “C of O Needed”, or status upgraded to Final); one spurious FINAL on an In Review shell cleared.
- **Repair:** **116 FILLED**, **17 FIXED**. Missing after: 1,173 (215 still-Final rows lack any final workflow mark).

## Repair performance

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | ---: | ---: | ---: | ---: |
| STATUS_NORMALIZED | 93 | 142 | 207 | 114 |
| FILE_DATE | 0 | 0 | 0 | 0 |
| PERMIT_DATE | 65 | 0 | 903 | 838 |
| FINAL_DATE | 116 | 17 | 1,288 | 1,173 |

Status distribution after repair: Final 1,042 · In Review 392 · Active 334 · Inactive 118 · null 114.

Post-repair completeness by status:

| Status | FILE_DATE | PERMIT_DATE | FINAL_DATE |
| --- | ---: | ---: | ---: |
| Active | 100% | 93.4% | 0% |
| Final | 100% | 75.4% | 79.4% |
| In Review | 100% | 0% | 0% |
| Inactive | 100% | 54.2% | 0% |

Chronology: 0 `PERMIT < FILE` and 0 `FINAL < PERMIT` cases after repair.

## Artifacts

- Repair script: `agent/scripts/ca/data_repair_ca_ventura_county.py`
- Repaired sample: `$AGENT_DATA_PATH/ventura_county_repaired_sample.parquet`

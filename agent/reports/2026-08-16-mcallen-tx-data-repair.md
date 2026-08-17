# McAllen (TX) data repair

**Summary:** McAllen was the first TX jurisdiction in `permits_tx_sample.parquet` without a repair script. All 2,001 rows use an Accela Civic Platform payload (`status` + `date` + `tasks` / `inspections`). STATUS_NORMALIZED was mostly correct but missing on 16 unmapped agency statuses and wrong on 14 rows where `STATUS_ORIGINAL` lagged `DATA.status`. FILE_DATE was already complete and matched `date`. The main date gaps were PERMIT_DATE (upstream ignored Issue Permit marked Online Permit) and FINAL_DATE (sparse Finaled/CofO stamps; many historical Completed shells have empty task events).

## Scope

- Input: `MY_DATA_PATH/processed_data/permits_tx_sample.parquet`
- Jurisdiction: McAllen, TX (first pair lacking `agent/scripts/{state}/data_repair_{state}_{city}.py`)
- Script: `agent/scripts/tx/data_repair_tx_mcallen.py`
- Artifact: `AGENT_DATA_PATH/repaired/permits_tx_mcallen_repaired.parquet`

## DATA schema

Every record has Accela top-level keys (`status`, `date`, `tasks`, `search_data`, `more_details`, `record_type`, …). Content variants in `INFERRED_SCHEMA`:

| INFERRED_SCHEMA | n |
| --- | ---: |
| accela_full | 1,998 |
| accela_lean | 3 |

Canonical source fields:

| Target field | Primary source | Fallback |
| --- | --- | --- |
| STATUS_NORMALIZED | `DATA.status` | Issue Permit Issued/Online Permit → Active; Inspection Finaled → Final |
| FILE_DATE | `DATA.date` | — |
| PERMIT_DATE | Issue Permit marked `Issued` | Issue Permit marked `Online Permit` |
| FINAL_DATE | Inspection / Inspect / Final marked `Finaled` | Certificate of Occupancy `Issued CofO`; Certificate of Completion `Issued Cof C`; Temp Occ* / Working Clearance `Finaled`; Final* inspection Passed |

## Field assessment

### STATUS_NORMALIZED

Before repair: Active 1,208 / Final 622 / Inactive 97 / In Review 58 / null 16.

`DATA.status` categories (top): Issued (1,194), Completed (213), Closed (139), Finaled (121), Certificate of Occupancy (102), Expired (74), Complete (49), Under Review (28), Never Finaled (16), plus smaller workflow labels.

Issues:
- **Null status (16):** upstream left Conditions Acknowledged, Working Clearance, Released, Acknowledge Conditions unmapped; some rows also had `STATUS_ORIGINAL=working clearance` while `DATA.status` was already Finaled/Issued. Repair FILLED 14 from `DATA.status`.
- **Incorrect labels (14 FIXED):** Temporary Occupancy kept as Final → Active; CO_Issued / Certificate of Occupancy / Closed kept as Active → Final; Issued kept as In Review or Final → Active; Finaled kept as Inactive (Never Finaled lag) → Final.
- **Not repairable:** 2 rows with null `DATA.status` and only TBD task marks.

After repair: Active 1,207 / Final 633 / Inactive 96 / In Review 63 / null 2.

### FILE_DATE

Fully populated (0 missing). Where both present, FILE_DATE matched `DATA.date` 2,001 / 2,001 at day resolution (0 mismatches). No FILLED/FIXED changes.

After repair: FILE_DATE present for 100% of rows.

### PERMIT_DATE

Missing on 970 / 2,001 before repair. Where Issue Permit was marked `Issued`, PERMIT_DATE matched that event date exactly (970 matches, 0 mismatches among compared rows). Upstream never captured Issue Permit marked `Online Permit` (251 events), so those issuance dates were always missing.

Repair FILLED 252 from Issued / Online Permit task marks (mostly Issued status + Online Permit). Remaining Active/Final gaps are almost entirely:
- Issued shells with an empty Issue Permit `events` list (299)
- Completed / Complete historical shells with empty task events (262)
- Approved / CO_Issued with no issuance event

After repair by status: Active 902/1,207 (74.7%); Final 351/633 (55.5%); Inactive 21/96 (21.9%); In Review 9/63 (14.3%).

### FINAL_DATE

Missing on 1,708 / 2,001 before repair. When present on Final rows, FINAL_DATE almost always matched Inspection marked Finaled (272 / 274). Two Final rows incorrectly used an Inspection `Never Finaled` stamp; 15 Inactive Never Finaled rows and 4 Active rows also carried that spurious FINAL_DATE.

Repair FILLED 128 (CofO, Finaled, Completed Final* Passed inspections, CO_Issued). FIXED 42: 23 replaced with a later true Finaled/CofO date; 19 cleared on non-Final (or non-repairable) rows.

After repair: Final 402/633 (63.5%); other statuses 0%. Remaining Final gaps are mostly Completed (179) and Complete (48) shells with empty task events and no usable Final* Passed inspection.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 14 | 14 | 16 → 2 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 252 | 0 | 970 → 718 |
| FINAL_DATE | 128 | 42 | 1,708 → 1,599 |

After repair, by status:

| Status | n | FILE_DATE | PERMIT_DATE | FINAL_DATE |
| --- | ---: | ---: | ---: | ---: |
| Active | 1,207 | 100% | 74.7% | 0% |
| Final | 633 | 100% | 55.5% | 63.5% |
| In Review | 63 | 100% | 14.3% | 0% |
| Inactive | 96 | 100% | 21.9% | 0% |
| null | 2 | 100% | — | — |

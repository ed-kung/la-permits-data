# Galveston (TX) data repair

**Summary:** Galveston was the first TX jurisdiction in `permits_tx_sample.parquet` without a repair script. All 2,000 rows use a uniform Accela Civic Platform payload (`status` + `date` + `tasks`; `inspections` empty in this extract). STATUS_NORMALIZED was missing on 179 code-complaint / commission statuses and wrong on 1 Issued row still labeled In Review. FILE_DATE was already complete and matched `date`. PERMIT_DATE matched Issue Permit Issued when present (only 2 fillable gaps). FINAL_DATE was entirely missing; about a quarter of Final rows could be filled from Inspection Passed, Reinspection/Court/Abatement Complied, Closure Complete, Onsite Compliance, or commission Results stamps.

## Scope

- Input: `MY_DATA_PATH/processed_data/permits_tx_sample.parquet`
- Jurisdiction: Galveston, TX (first pair lacking `agent/scripts/{state}/data_repair_{state}_{city}.py`)
- Script: `agent/scripts/tx/data_repair_tx_galveston.py`
- Artifact: `AGENT_DATA_PATH/repaired/permits_tx_galveston_repaired.parquet`

## DATA schema

Every record has Accela top-level keys (`status`, `date`, `tasks`, `search_data`, `more_details`, `record_type`, …). Content variant in `INFERRED_SCHEMA`:

| INFERRED_SCHEMA | n |
| --- | ---: |
| accela | 2,000 |

Canonical source fields:

| Target field | Primary source | Fallback |
| --- | --- | --- |
| STATUS_NORMALIZED | `DATA.status` | Issue* Issued → Active; Inspection Passed / Closure Complete / Reinspection Complied → Final |
| FILE_DATE | `DATA.date` | — |
| PERMIT_DATE | Issue Permit marked `Issued` | Issue Certificate marked `Issued` |
| FINAL_DATE | Inspection `Passed`; Reinspection / Court / Abatement `Complied`; Closure `Complete` | Review Complaint `Onsite Compliance`; Landmark/Planning/City Council `*Results` (non-Pending) |

## Field assessment

### STATUS_NORMALIZED

Before repair: Final 1,012 / Active 475 / Inactive 243 / In Review 91 / null 179.

`DATA.status` categories (top): Closed (520), Complete (430), Issued (230), Void (192), Permit Issued (152), Active (81), Completed (62), In Progress (50), Case Created (43), Unfounded (42), Duplicate (39), blank/null (41), plus smaller workflow labels.

Issues:
- **Null status (179):** upstream left Case Created, Unfounded, Referred Out, Onsite Compliance, Unable To Locate, Commission Completed, and Pending Commission unmapped (plus 41 blank/null `DATA.status` shells). Repair FILLED 138 from `DATA.status`.
- **Incorrect label (1 FIXED):** FEN2024-00160 had `DATA.status=Issued` and Issue Permit Issued on 2024-08-14, but STATUS_ORIGINAL/NORMALIZED stayed In Review → Active.
- **Not repairable:** 41 rows with blank/null `DATA.status` and empty useful task events (37 Contractor Renewal, 2 Online Application, 1 Code Compliance, 1 Beach Front).

After repair: Final 1,036 / Active 476 / Inactive 313 / In Review 134 / null 41.

### FILE_DATE

Fully populated (0 missing). Where both present, FILE_DATE matched `DATA.date` 2,000 / 2,000 at day resolution (0 mismatches). No FILLED/FIXED changes.

After repair: FILE_DATE present for 100% of rows.

### PERMIT_DATE

Missing on 1,148 / 2,000 before repair. Where Issue Permit was marked `Issued`, PERMIT_DATE matched that event date exactly (848 matches, 0 mismatches among compared rows). Four Certificate of Zoning Compliance rows correctly used Issue Certificate Issued (already populated).

Repair FILLED 2 from Issue Permit Issued (the lagged In Review row above and COM2024-00046). Remaining Active/Final gaps are almost entirely:
- Active open code cases with no issuance task (81)
- Approved ready-to-issue shells (13)
- Permit Issued / Issued with empty Issue Permit `events` (14)
- Final Complete / Completed / Closed shells without Issue* Issued (code cases and historical Completed water-tap / BFP rows)

After repair by status: Active 368/476 (77.3%); Final 335/1,036 (32.3%); Inactive 151/313 (48.2%); In Review 0/134 (0%).

### FINAL_DATE

Missing on 2,000 / 2,000 before repair (universally null). No spurious FINAL_DATE values to clear on non-Final rows.

Repair FILLED 259 on Final rows from:
- Reinspection Complied (code Closed cases)
- Inspection Passed (building Complete)
- Review Complaint Onsite Compliance (newly mapped Final)
- Closure Complete / Court Complied / commission Results

After repair: Final 259/1,036 (25.0%); other statuses 0%. Remaining Final gaps are Closed (375), Complete (340), and Completed (62) shells without Passed / Complied / Closure / commission stamps (many Closed rows stop at Initial Inspection Orders Issued; Completed water-tap / BFP rows only have Pay Fees).

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 138 | 1 | 179 → 41 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 2 | 0 | 1,148 → 1,146 |
| FINAL_DATE | 259 | 0 | 2,000 → 1,741 |

After repair, by status:

| Status | n | FILE_DATE | PERMIT_DATE | FINAL_DATE |
| --- | ---: | ---: | ---: | ---: |
| Active | 476 | 100% | 77.3% | 0% |
| Final | 1,036 | 100% | 32.3% | 25.0% |
| In Review | 134 | 100% | 0% | 0% |
| Inactive | 313 | 100% | 48.2% | 0% |
| null | 41 | 100% | — | — |

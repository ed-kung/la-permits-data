# Hollywood (FL) data repair — STATUS_NORMALIZED and date fields

**Summary:** Among Florida sample jurisdictions missing a repair script, Hollywood was first. Its DATA mixes a legacy `project.Permit Detail` portal (1,910 rows) with a newer Accela-style payload (88 rows) plus one empty `search_data` shell. STATUS_NORMALIZED was already correct except one Accela `Closed - Complete` row mislabeled Active → FIXED to Final. FILE_DATE and PERMIT_DATE already matched Application Date / Permit Date (project) and Accela issuance events wherever those sources exist (118 FILE gaps and 10 Final PERMIT gaps remain unfillable). The main defect was FINAL_DATE: 698 project Finals carried a plan-approval / Notice of Commencement date (477 before PERMIT_DATE), and 729 were blank despite PASS FINAL inspections — repair FILLED 730 and FIXED 700, lifting Final FINAL_DATE coverage from 50.0% to 99.2% with zero PERMIT>FINAL inversions.

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_fl_sample.parquet`
- Jurisdiction: **Hollywood, FL** (1,999 rows) — first `(JURISDICTION, STATE)` pair without `agent/scripts/{state}/data_repair_{state}_{city}.py`
- Script: `agent/scripts/fl/data_repair_fl_hollywood.py` (`data_repair`)
- Artifact: `AGENT_DATA_PATH/hollywood_repaired_sample.parquet`

## DATA schema

| INFERRED_SCHEMA prefix | n | Notes |
| --- | ---: | --- |
| `project_*` | 1,910 | Legacy portal: `project.Permit Detail` + inspections / reviews / approvals |
| `accela_*` | 88 | Accela-style: `status`, `tasks`, `inspections`, `search_data`, `date` |
| `search_only_*` | 1 | `search_data` only; empty Status |

Canonical mappings:

| Field | project source | accela source |
| --- | --- | --- |
| STATUS_NORMALIZED | Permit Detail `Status:` | top-level `status` |
| FILE_DATE | `Application Date:` | `date` / `search_data.Date` |
| PERMIT_DATE | `Permit Date:` | Permit Issuance task marked `Issued` (earliest) |
| FINAL_DATE | `CO/CC Date:` else latest PASS inspection with `FINAL` in Description | Inspection task `Final Inspection Complete` (latest); else Passed Final inspection |

## Field assessments

### STATUS_NORMALIZED

Ideal values: Active / Final / In Review / Inactive.

**Project** status → normalized (all 1,910 rows already matched):

| Permit Detail Status | STATUS_NORMALIZED | n |
| --- | --- | ---: |
| CLOSED | Final | 1,430 |
| ISSUED | Active | 96 |
| CREATED / APPLIED / READY | In Review | 172 |
| CANCELLED / NULL AND VOID / EXPIRED | Inactive | 212 |

**Accela** status → normalized:

| status | expected | n | issue |
| --- | --- | ---: | --- |
| Closed - Complete | Final | 42 | 1 was Active → FIXED |
| Closed - Approved | Final | 10 | OK (admin / amendment close) |
| Inspection Phase | Active | 16 | OK |
| Closed - Withdrawn | Inactive | 7 | OK |
| Revisions Required / In Review / Pending / Ready to Issue / Plans Received | In Review | 13 | OK |

**1 FIXED** (Active → Final). **0 FILLED.** Remaining null: **1** `search_only_none` with empty Status.

After repair: Final 1,482; Inactive 219; In Review 185; Active 112; null 1.

### FILE_DATE

Ideal: populated for all records.

- Project: among 1,792 rows with a non-empty Application Date, FILE_DATE already matched exactly (0 mismatches).
- Accela: all 88 rows already had FILE_DATE equal to top-level `date` / search Date.
- **0 FILLED / 0 FIXED.**
- Remaining: **118** — project CREATED (91) and CANCELLED (27) shells with blank Application Date; no alternate filing stamp in DATA.

Coverage after repair: Active 100%; Final 100%; In Review 50.8%; Inactive 87.7%.

### PERMIT_DATE

Ideal: populated for Active and Final.

- Project: whenever Permit Date is non-empty, PERMIT_DATE already matched (0 mismatches). Active/Final project rows are fully covered.
- Accela: all 58 rows with a Permit Issuance / Issued event already matched that date; **0 FILLED / 0 FIXED.**
- Remaining Final gaps: **10** Accela `Closed - Approved` rows with no Issued event (plan/admin approval close, not a traditional issuance).
- In Review correctly has 0 PERMIT_DATE; Inactive keeps Permit Date only when the portal recorded one (41/219).

Coverage after repair: Active 100%; Final 99.3%; In Review 0%; Inactive 18.7%.

### FINAL_DATE

Ideal: populated for Final; absent otherwise.

**Root cause of incorrect values:** for project Finals, upstream FINAL_DATE was frequently copied from `approvals[].Date` (e.g. Broward County Notice of Commencement / plan approval), not from completion. Of 700 Finals that already had FINAL_DATE, 698 equaled an approval date; 477 were strictly before PERMIT_DATE.

Repair performance:

| Action | n | Notes |
| --- | ---: | --- |
| FILLED | 730 | 729 project (CO/CC or PASS FINAL insp) + 1 Accela Closed-Complete (was Active) |
| FIXED | 700 | 698 project approval-date → true final; 1 unsupported NOC-only stamp cleared; 1 Accela latest Final Inspection Complete |

After repair:

- Final FINAL_DATE coverage: **1,470 / 1,482 (99.2%)** (was 741 / 1,481 ≈ 50.0%).
- Non-Final rows: 0 FINAL_DATE.
- PERMIT_DATE > FINAL_DATE inversions: **0** (was 477 FINAL < PERMIT).

Remaining Final gaps (**12**): 10 Accela `Closed - Approved` (no final-inspection signal) + 2 project CLOSED with blank/failed inspection dates and no CO/CC Date.

## Repair script performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 0 | 1 | 1 → 1 |
| FILE_DATE | 0 | 0 | 118 → 118 |
| PERMIT_DATE | 0 | 0 | 374 → 374 |
| FINAL_DATE | 730 | 700 | 1,258 → 529 |

## Artifacts

- Script: `agent/scripts/fl/data_repair_fl_hollywood.py`
- Repaired sample: `AGENT_DATA_PATH/hollywood_repaired_sample.parquet`

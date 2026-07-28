# Sunnyvale (CA) data repair — 2026-07-28

Sunnyvale was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. EnerGov JSON under `DATA` already has correct `FILE_DATE` for all 1,999 rows; `STATUS_NORMALIZED` was null for 113 pre-issuance statuses the upstream mapper missed and stale on 6 Finaled rows; `PERMIT_DATE` / `FINAL_DATE` mostly already match `IssueDate` / `FinalDate`, with a few fills after status repair and clearing of spurious finals on Inactive/Active.

## Jurisdiction selection

Walked `(JURISDICTION, STATE)` pairs in sample order and compared against `agent/scripts/{state}/data_repair_{state}_{city}.py`. First missing: **Sunnyvale, CA** → `agent/scripts/ca/data_repair_ca_sunnyvale.py` (n=1,999).

## DATA schema

Tyler EnerGov-style payload. All rows have `entity`, `details`, `contacts`, `fees`, `processing_status`. Content variants recorded in `INFERRED_SCHEMA`:

| Schema | n | Description |
| --- | ---: | --- |
| `entity_fees` | 1,901 | Core entity/details/fees (+ contacts, processing_status) |
| `entity_fees_reviews` | 98 | Plus `reviews` / `holds` / `attachments` / `more_info` (reviews always empty in sample) |

Canonical fields: `entity.CaseStatus` / `details.PermitStatus` → status; `entity.ApplyDate` → file; `entity.IssueDate` → permit; `entity.FinalDate` else `details.FinalizeDate` → final. When CaseStatus and PermitStatus disagree, the more advanced mapped status wins (Finaled over Active - Issued).

## Field assessment

### STATUS_NORMALIZED

- Missing on 113 / 1,999 (5.7%) before repair — all `STATUS_ORIGINAL` in `{active - pending review, active - returned to applicant}` (upstream mapper never mapped these).
- Mapping from CaseStatus/PermitStatus is clean: `Finaled` → Final; `Active - Issued` → Active; `Expired`/`Cancelled`/`Void` → Inactive; pending/returned/submitted/incomplete → In Review.
- **Issue:** `STATUS_NORMALIZED` tracks `STATUS_ORIGINAL`, which lags `DATA` on 6 rows (Active while PermitStatus and/or CaseStatus is Finaled). Four of those have CaseStatus still `Active - Issued` but PermitStatus `Finaled` with `FinalizeDate` and a passed Building Final inspection.
- **Repair:** overwrite from DATA → **113 FILLED**, **6 FIXED**. No missing after.

### FILE_DATE

- Already populated for 100% of rows; equals `entity.ApplyDate` on every sample row.
- `details.ApplyDate` differs by one calendar day on 32 rows (timezone day-boundary); entity date is authoritative.
- **Repair:** no changes (0 FILLED / 0 FIXED).

### PERMIT_DATE

- Missing on 188 / 1,999 (9.4%) before repair. When present, always matches `entity.IssueDate`.
- Four rows had IssueDate but null PERMIT_DATE because STATUS_ORIGINAL still said pending review while CaseStatus had advanced to Issued/Finaled.
- After status repair, Active is 100% issued; Final is 99.5% issued. Eight Finaled Engineering Project shells have `Issued=False` and null IssueDate → not recoverable.
- **Repair:** **4 FILLED**, **0 FIXED**. Missing after: 184 (mostly In Review + those shells + Inactive without issuance).

### FINAL_DATE

- Missing on 388 / 1,999 before repair; among labeled Final, only 8 lacked FINAL_DATE.
- When present, matches `entity.FinalDate` / `details.FinalizeDate` exactly.
- **Issues:** (1) seven Final rows (after status fix) had FinalDate/FinalizeDate but null FINAL_DATE; (2) 135 non-Final rows carried FinalDate (134 Expired/Cancelled, 1 Active Engineering with FinalDate one day before IssueDate) — not treated as permit sign-off under our schema.
- Eight Finaled Engineering shells lack FinalDate, FinalizeDate, and usable final inspections → stay missing.
- **Repair:** **7 FILLED**, **135 FIXED** (cleared). Missing after rises to 516 because of clears; among Final, 99.5% have FINAL_DATE.

## Repair performance

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | ---: | ---: | ---: | ---: |
| STATUS_NORMALIZED | 113 | 6 | 113 | 0 |
| FILE_DATE | 0 | 0 | 0 | 0 |
| PERMIT_DATE | 4 | 0 | 188 | 184 |
| FINAL_DATE | 7 | 135 | 388 | 516 |

Status distribution after repair: Final 1,491 · Inactive 233 · In Review 146 · Active 129.

Post-repair completeness by status:

| Status | FILE_DATE | PERMIT_DATE | FINAL_DATE |
| --- | ---: | ---: | ---: |
| Active | 100% | 100% | 0% |
| Final | 100% | 99.5% | 99.5% |
| In Review | 100% | 0% | 0% |
| Inactive | 100% | 87.1% | 0% |

Eight FILE>PERMIT and two PERMIT>FINAL day inversions remain in source EnerGov dates (mostly one-day UTC boundary artifacts); dates are left as in DATA.

## Artifacts

- Script: `agent/scripts/ca/data_repair_ca_sunnyvale.py` (`data_repair`)
- Repaired sample: `$AGENT_DATA_PATH/sunnyvale_repaired_sample.parquet`

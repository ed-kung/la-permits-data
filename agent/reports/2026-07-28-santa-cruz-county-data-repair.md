# Santa Cruz County (CA) data repair — 2026-07-28

Santa Cruz County was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. The county portal JSON under `DATA` is a single flat schema; every sample row had null `STATUS_NORMALIZED`, `FILE_DATE`, `PERMIT_DATE`, and `FINAL_DATE`. Repair fills all 2,001 statuses from `Application Status`, 1,994 file dates from `Application Date`, and 1,733 permit dates from `Issued Date` on Active/Final rows. No finaled/completion timestamp exists in `DATA`, so `FINAL_DATE` remains entirely missing.

## Jurisdiction selection

Walked `(JURISDICTION, STATE)` pairs in sample order and compared against `agent/scripts/{state}/data_repair_{state}_{city}.py`. First missing: **Santa Cruz County, CA** → `agent/scripts/ca/data_repair_ca_santa_cruz_county.py` (n=2,001).

## DATA schema

All rows share the same top-level keys (`APN`, `Review`, `Issued Date`, `Expiration Date`, `Application Date`, `Master Permit No`, `Primary Applicant`, `Application Number`, `Application Status`, `Project Description`). Content variants recorded in `INFERRED_SCHEMA`:

| Schema | n | Description |
| --- | ---: | --- |
| `flat_app_issued` | 1,800 | Application Date + Issued Date present |
| `flat_app_not_issued` | 194 | Application Date present; Issued blank / "Not Yet Issued" |
| `flat_empty_dates` | 4 | Neither Application nor Issued usable |
| `flat_issued_no_app` | 3 | Issued Date present; Application Date blank |

## Field assessment

### STATUS_NORMALIZED

- Missing on **2,001 / 2,001** (`STATUS_ORIGINAL` also entirely null). Root cause: upstream normalization never mapped this jurisdiction’s `Application Status`.
- Mapping from `Application Status`:

  | Application Status | n | → STATUS_NORMALIZED |
  | --- | ---: | --- |
  | Complete | 1,470 | Final |
  | Inspections | 284 | Active |
  | Prior to Final | 5 | Active |
  | Issue Children Permit | 1 | Active |
  | Ready to Issue / Resubmittal / Routing / Waiting on MasterApp / Collect Fees / Consolidation-Evaluation | 93 | In Review |
  | VOID / Withdrawn / Surrender | 148 | Inactive |

- **Repair:** **2,001 FILLED**, **0 FIXED**. Missing after: 0.

### FILE_DATE

- Missing on **2,001 / 2,001**. `Application Date` is present and parseable on 1,994 rows (1985–2025); 7 rows have a blank Application Date (Withdrawn / VOID / Surrender / Complete shells).
- Chronology vs Issued Date: 0 cases of Issued < Application among rows with both dates.
- **Repair:** **1,994 FILLED**, **0 FIXED**. Missing after: 7.

### PERMIT_DATE

- Missing on **2,001 / 2,001**. `Issued Date` is either a parseable date or the sentinel `"Not Yet Issued"` (198 unparseable including blanks).
- Among post-repair Active/Final: Active 290/290 have Issued; Final 1,443/1,470 have Issued (27 Complete rows still say "Not Yet Issued").
- In Review / Inactive correctly left without PERMIT_DATE even when some Inactive rows carry an Issued Date (Surrender / VOID / Withdrawn after issuance) — guideline requires PERMIT_DATE for Active and Final only.
- **Repair:** **1,733 FILLED**, **0 FIXED**. Missing after: 268 (27 Final + 93 In Review + 148 Inactive).

### FINAL_DATE

- Missing on **2,001 / 2,001**. No finaled, completion, or signoff field exists in `DATA`.
- `Review[].Last Rev` timestamps are plan-review activity and typically fall on or before `Issued Date` (not usable as final dates). `Expiration Date` is a permit validity end, not a finalization date.
- **Repair:** **0 FILLED**, **0 FIXED**. Missing after: 2,001. All 1,470 Final rows lack FINAL_DATE.

## Repair performance

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | ---: | ---: | ---: | ---: |
| STATUS_NORMALIZED | 2,001 | 0 | 2,001 | 0 |
| FILE_DATE | 1,994 | 0 | 2,001 | 7 |
| PERMIT_DATE | 1,733 | 0 | 2,001 | 268 |
| FINAL_DATE | 0 | 0 | 2,001 | 2,001 |

Status distribution after repair: Final 1,470 · Active 290 · Inactive 148 · In Review 93.

Post-repair completeness by status:

| Status | FILE_DATE | PERMIT_DATE | FINAL_DATE |
| --- | ---: | ---: | ---: |
| Active | 100% | 100% | 0% |
| Final | 99.9% | 98.2% | 0% |
| In Review | 100% | 0% | 0% |
| Inactive | 96.6% | 0% | 0% |

Chronology: 0 `PERMIT < FILE` and 0 `FINAL < PERMIT` cases after repair.

## Artifacts

- Script: `agent/scripts/ca/data_repair_ca_santa_cruz_county.py`
- Function: `data_repair(df)` — adds `INFERRED_SCHEMA` and `{FIELD}_FLAG` columns (`FILLED` / `FIXED`)

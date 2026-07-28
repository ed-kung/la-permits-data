# San Clemente (CA) data repair — 2026-07-28

San Clemente was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. The city uses the Hemet / Mendocino civic-portal `permit_info` schema. `FILE_DATE` was already correct on every row; repairs focus on stale `STATUS_NORMALIZED` (FINALED / finaled-but-OPENED rows, blank TRANSPORTATION statuses, STOP WORK), filling `PERMIT_DATE` from `PermitApprovedDate` when Issued is blank, and filling a handful of missing `FINAL_DATE` values from `PermitFinaledDate` or final inspections.

## Jurisdiction selection

Walked `(JURISDICTION, STATE)` pairs in sample order and compared against `agent/scripts/{state}/data_repair_{state}_{city}.py`. First missing: **San Clemente, CA** → `agent/scripts/ca/data_repair_ca_san_clemente.py` (n=2,000).

## DATA schema

All 2,000 rows share top-level keys `search_data`, `permit_info`, `inspections`, `fees`, `contacts`, `site_info`. Canonical status/dates live under `permit_info`. Content variants recorded in `INFERRED_SCHEMA`:

| Schema | n | Description |
| --- | ---: | --- |
| `permit_info_issued_finaled` | 1,562 | Issued + Finaled present |
| `permit_info_issued` | 189 | Issued present, Finaled blank |
| `permit_info_applied_only` | 132 | Only Applied populated |
| `permit_info_approved_only` | 82 | Approved present, Issued/Finaled blank |
| `permit_info_finaled_only` | 27 | Finaled present, Issued blank |
| `legacy_no_status` | 8 | Blank `PermitStatus`, dates present |

Legacy single-letter `PermitStatus` values (P/G/I/O/N) appear on older CRW-converted rows and are mapped consistently with upstream labels.

## Field assessment

### STATUS_NORMALIZED

- Missing on 8 / 2,000 (blank `PermitStatus` TRANSPORTATION permits with Issued dates).
- Otherwise largely correct vs `PermitStatus`, with these exceptions:
  - **6** rows: `PermitStatus=FINALED` but `STATUS_ORIGINAL=issued` → labeled Active (stale scrape of original status).
  - **1** row: `APPROVED` with `PermitFinaledDate` → labeled Active; finaled date overrides to Final.
  - **2** rows: `OPENED` with `PermitFinaledDate` → labeled In Review; override to Final.
  - **5** rows: `STOP WORK` labeled In Review → remapped to Inactive.
- Letter codes kept as upstream: P/G/I → In Review, O → Final, N → Inactive.
- **Repair:** **8 FILLED**, **14 FIXED**. Missing after: 0.

### FILE_DATE

- Populated for 100% of rows; equals `permit_info.PermitAppliedDate` on every sample row.
- **Repair:** no changes (0 FILLED / 0 FIXED).

### PERMIT_DATE

- Missing on 241 / 2,000 before repair. Where present, always matches `PermitIssuedDate` (never Approved-only mismatches).
- 59 Active/Final rows have blank Issued but a usable `PermitApprovedDate` → FILLED.
- Remaining gaps are mostly CLOSED / letter-O Final rows with neither Issued nor Approved in `DATA`.
- In Review rows that carry an Issued date (legacy P/I) retain `PERMIT_DATE`; status is left In Review per CRW mapping.
- **Repair:** **59 FILLED**, **0 FIXED**. Missing after: 182.

### FINAL_DATE

- Missing on 417 / 2,000 before repair. Where present, always equals `PermitFinaledDate` (0 mismatches).
- After status fixes, 6 previously-Active FINALED rows gain a fillable FinaledDate; 1 Final row fills from a FINAL inspection result (`E17-0285`).
- ~83 Final rows (mostly CLOSED / letter O) still lack FinaledDate and a usable final inspection → not repairable from `DATA`.
- Spurious FINAL on non-Final rows is cleared in principle; after status overrides, the former OPENED/APPROVED finaled rows become Final and keep their dates (0 clears in this sample).
- **Repair:** **7 FILLED**, **0 FIXED**. Missing after: 410.

## Repair performance

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | ---: | ---: | ---: | ---: |
| STATUS_NORMALIZED | 8 | 14 | 8 | 0 |
| FILE_DATE | 0 | 0 | 0 | 0 |
| PERMIT_DATE | 59 | 0 | 241 | 182 |
| FINAL_DATE | 7 | 0 | 417 | 410 |

Status distribution after repair: Final 1,673 · Active 121 · Inactive 104 · In Review 102.

Post-repair completeness by status:

| Status | FILE_DATE | PERMIT_DATE | FINAL_DATE |
| --- | ---: | ---: | ---: |
| Active | 100% | 100% | 0% |
| Final | 100% | 97.1% | 95.0% |
| In Review | 100% | 23.5% | 0% |
| Inactive | 100% | 47.1% | 0% |

Chronology: 3 rows have PERMIT &lt; FILE and 4 have FINAL &lt; PERMIT after repair — these mirror source `permit_info` dates, not introduced by the repair.

## Artifacts

- Script: `agent/scripts/ca/data_repair_ca_san_clemente.py` (`data_repair`)
- Repaired sample: `$AGENT_DATA_PATH/repaired/permits_ca_san_clemente_repaired.parquet`

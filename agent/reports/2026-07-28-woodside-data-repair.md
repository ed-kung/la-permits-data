# Woodside (CA) data repair — 2026-07-28

Woodside was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. Civic-portal JSON under `DATA` (all 2,000 rows) supports filling 108 missing statuses and correcting 5 wrong ones, filling 68 missing `PERMIT_DATE` values from `PermitIssuedDate` / `PermitApprovedDate`, and clearing 2 spurious `FINAL_DATE` values on Inactive expired/void permits. `FILE_DATE` gaps (135) have no Applied date in JSON and cannot be filled.

## Jurisdiction selection

Walked `(JURISDICTION, STATE)` pairs in sample order and compared against `agent/scripts/{state}/data_repair_{state}_{city}.py`. First missing: **Woodside, CA** → `agent/scripts/ca/data_repair_ca_woodside.py` (n=2,000).

## DATA schema

All rows share civic-portal top-level keys (`fees`, `contacts`, `site_info`, `inspections`, `permit_info`, `search_data`). Canonical dates/status live under `permit_info` (`PermitStatus`, `PermitAppliedDate`, `PermitIssuedDate` / `PermitApprovedDate`, `PermitFinaledDate`), with `search_data.Application` / `Issued` / `FINALED` as redundant mirrors. Content variants recorded in `INFERRED_SCHEMA`:

| Schema | n | Description |
| --- | ---: | --- |
| `permit_info_issued_finaled` | 942 | Issued + Finaled |
| `permit_info_issued` | 701 | Issued present, Finaled blank |
| `permit_info_applied_only` | 166 | Applied only |
| `legacy_no_status` | 108 | blank `PermitStatus` but dates present |
| `permit_info_approved_only` | 69 | Approved present, no Issued/Finaled |
| `permit_info_finaled_only` | 13 | Finaled present, Issued blank |
| `permit_info_empty_dates` | 1 | `UNKNOWN` status, no usable dates |

## Field assessment

### STATUS_NORMALIZED

- Missing on 108 / 2,000 (5.4%), all blank-`PermitStatus` legacy shells (104 `REVISION`, plus a few electrical/septic/remodel). Upstream left them unmapped despite usable dates:
  - Issued (81) → FILLED Active
  - Finaled (3) → FILLED Final
  - Applied only (24) → FILLED In Review
- Incorrect mappings / lag vs `PermitStatus` / `PermitFinaledDate`:
  - ISSUED still Active despite `PermitFinaledDate` (4) → FIXED to Final
  - `UNKNOWN` mapped upstream to Final with no dates (1) → FIXED to Inactive
- Mapped statuses (`FINALED`, `ISSUED`, `APPROVED`, `ACTIVE`, `UNDER REVIEW`, `ON HOLD`, `PAID ONLINE`, `EXPIRED`, `VOID`) otherwise already match the intended normalized values.
- **Repair:** 108 FILLED, 5 FIXED. Missing after: 0.

### FILE_DATE

- Missing on 135 / 2,000. When both present, every `FILE_DATE` matches `PermitAppliedDate` (0 incorrect).
- All 135 gaps also lack `PermitAppliedDate` and `search_data.Application` (mostly 1980s–early-1990s `FINALED`/`ISSUED` shells that still have Issued/Finaled).
- **Repair:** 0 FILLED, 0 FIXED. Coverage 1,865 / 2,000 (93.2%).

### PERMIT_DATE

- Missing on 273 / 2,000. When present with Issued, every value matches `PermitIssuedDate` (0 incorrect).
- Fillable gaps: Active/Final rows with `PermitApprovedDate` but blank Issued (68), mostly `APPROVED` tree/revision/encroachment permits plus a few `FINALED` finaled-only rows that still have Approved.
- Unfillable (10 Active/Final after status repair): 6 `ACTIVE` applied-only shells, 1 `APPROVED` without Approved date (`TREE2009-0032`), 3 `FINALED` finaled-only without Issued/Approved.
- **Repair:** 68 FILLED, 0 FIXED. Missing after: 205.
- Post-repair Active PERMIT coverage: 794/801 (99.1%); Final: 953/956 (99.7%); Active+Final: 1,747/1,757 (99.4%).

### FINAL_DATE

- Missing on 1,042 / 2,000. When present with `DATA`, values match `PermitFinaledDate` (0 incorrect vs that field).
- After status repair, every Final row has `FINAL_DATE` (956/956): the prior lone Final gap was the `UNKNOWN` shell, which was reclassified Inactive.
- **Spurious FINAL_DATE:** 2 Inactive rows (`EXPIRED` `BLDG2010-0061`, `VOID` `ENCR2003025`) carried `PermitFinaledDate` as a close stamp → cleared. Four ISSUED rows that had Finaled were promoted to Final, so their FINAL_DATE became correct rather than cleared; three blank-status Finaled shells were likewise promoted.
- **Repair:** 0 FILLED, 2 FIXED (clear). Missing after: 1,044.
- Post-repair Final FINAL coverage: 956/956 (100%). Active / In Review / Inactive: 0% by design.

## Repair performance

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | ---: | ---: | ---: | ---: |
| STATUS_NORMALIZED | 108 | 5 | 108 | 0 |
| FILE_DATE | 0 | 0 | 135 | 135 |
| PERMIT_DATE | 68 | 0 | 273 | 205 |
| FINAL_DATE | 0 | 2 | 1,042 | 1,044 |

Status distribution:

| | Before | After |
| --- | ---: | ---: |
| Final | 950 | 956 |
| Active | 724 | 801 |
| In Review | 72 | 96 |
| Inactive | 146 | 147 |
| (missing) | 108 | 0 |

Post-repair completeness by status:

| Status | n | FILE_DATE | PERMIT_DATE | FINAL_DATE |
| --- | ---: | ---: | ---: | ---: |
| Active | 801 | 92.4% | 99.1% | 0.0% |
| Final | 956 | 92.4% | 99.7% | 100.0% |
| In Review | 96 | 100.0% | 0.0% | 0.0% |
| Inactive | 147 | 99.3% | 32.7% | 0.0% |

Chronology quirks in source dates (unchanged by repair; no flags): 7 rows with `PERMIT_DATE` < `FILE_DATE`, 2 with `FINAL_DATE` < `PERMIT_DATE`.

## Artifacts

- Repair script: `agent/scripts/ca/data_repair_ca_woodside.py`
- Repaired sample parquet: `$AGENT_DATA_PATH/repaired/permits_ca_woodside_repaired.parquet`

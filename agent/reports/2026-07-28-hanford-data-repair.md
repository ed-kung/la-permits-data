# Hanford (CA) data repair — 2026-07-28

Hanford was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. All 2,000 sample rows carry civic-portal JSON under `DATA`. Status is already mostly correct; repairs focus on 14 blank-status legacy shells, 10 stale statuses (including FINALED mislabeled Active and APPROVED/ACTIVE/HOLD rows with `PermitFinaledDate`), filling 10 missing `PERMIT_DATE` values from `PermitApprovedDate`, filling 5 missing `FINAL_DATE` values from final inspections, and clearing 6 spurious `FINAL_DATE` values on Inactive EXPIRED/VOID rows.

## Jurisdiction selection

Walked `(JURISDICTION, STATE)` pairs in sample order and compared against `agent/scripts/{state}/data_repair_{state}_{city}.py`. First missing: **Hanford, CA** → `agent/scripts/ca/data_repair_ca_hanford.py` (n=2,000).

## DATA schema

All rows share civic-portal top-level keys (`fees`, `contacts`, `site_info`, `inspections`, `permit_info`, `search_data`). Canonical dates/status live under `permit_info` (`PermitStatus`, `PermitAppliedDate`, `PermitIssuedDate` / `PermitApprovedDate`, `PermitFinaledDate`). `search_data` only has `Address` / `RECORDID` / `Permit Number` (no Application/Issued mirrors). Content variants recorded in `INFERRED_SCHEMA`:

| Schema | n | Description |
| --- | ---: | --- |
| `permit_info_issued_finaled` | 1,638 | Issued + Finaled |
| `permit_info_issued` | 251 | Issued present, Finaled blank |
| `permit_info_applied_only` | 60 | Applied only |
| `permit_info_approved_only` | 30 | Approved present, no Issued/Finaled |
| `legacy_no_status` | 11 | blank `PermitStatus` but dates present |
| `permit_info_finaled_only` | 6 | Finaled present, Issued blank |
| `permit_info_empty` | 3 | blank status, no usable dates |
| `permit_info_empty_dates` | 1 | status text, no usable dates |

## Field assessment

### STATUS_NORMALIZED

- Missing on 14 / 2,000 (blank `PermitStatus`). Upstream left empty portal labels unmapped.
  - 6 with `PermitFinaledDate` → FILLED Final
  - 2 with Issued/Approved → FILLED Active
  - 2 with Applied only → FILLED In Review
  - 2 VOID-address / VOID shells → FILLED Inactive
  - 2 empty shells (no status, no dates, blank address) → unfillable
- Incorrect / stale vs `PermitStatus` / `PermitFinaledDate`:
  - 1 FINALED labeled Active (`STATUS_ORIGINAL=active`, empty FinaledDate) → FIXED to Final
  - 7 APPROVED / 1 ACTIVE with `PermitFinaledDate` (mostly COZONING / NEWSFD) → FIXED to Final
  - 1 HOLD with `PermitFinaledDate` → FIXED to Final
- EXPIRED / VOID / WITHDRAWN kept Inactive even when `PermitFinaledDate` is present (close stamp, not a true Final).
- **Repair:** 12 FILLED, 10 FIXED. Missing after: 2.

### FILE_DATE

- Missing on 5 / 2,000. When both present, every `FILE_DATE` matches `PermitAppliedDate` (0 incorrect).
- All 5 gaps also have empty `PermitAppliedDate` (and no search Application field) → unfillable.
- **Repair:** 0 FILLED, 0 FIXED. Coverage 1,995 / 2,000 (99.8%).

### PERMIT_DATE

- Missing on 103 / 2,000. When present, every value matches `PermitIssuedDate` (0 incorrect).
- Fillable gaps among Active/Final: Issued blank but Approved present → 10 FILLED (7 promoted/Active APPROVED + 3 Final).
- Unfillable Active/Final: 2 Active APPROVED and 5 Final FINALED with neither Issued nor Approved.
- In Review / Inactive missing PERMIT left alone by design (field expected for Active/Final).
- **Repair:** 10 FILLED, 0 FIXED. Missing after: 93.
- Post-repair Active PERMIT coverage: 145/147 (98.6%); Final: 1,653/1,658 (99.7%).

### FINAL_DATE

- Missing on 350 / 2,000. When present, values match `PermitFinaledDate` (0 incorrect vs that field).
- Among Final after status repair: 5 missing FINAL filled from passed `**FINAL` / `FIRE-FINAL` inspections; 9 FINALED rows still lack FinaledDate and a usable finaling inspection (TEMPPOWERPOLE / HVAC / COMPLIANCE / GRADING / empty shells).
- **Spurious FINAL_DATE:** 6 Inactive EXPIRED/VOID rows carried `PermitFinaledDate` as a close stamp → cleared. The other non-Final rows that had Finaled were promoted to Final, so their FINAL_DATE became correct rather than cleared.
- **Repair:** 5 FILLED, 6 FIXED (clear). Missing after: 351.
- Post-repair Final FINAL coverage: 1,649/1,658 (99.5%). Active / In Review / Inactive: 0% by design.

## Repair performance

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | ---: | ---: | ---: | ---: |
| STATUS_NORMALIZED | 12 | 10 | 14 | 2 |
| FILE_DATE | 0 | 0 | 5 | 5 |
| PERMIT_DATE | 10 | 0 | 103 | 93 |
| FINAL_DATE | 5 | 6 | 350 | 351 |

Status distribution:

| | Before | After |
| --- | ---: | ---: |
| Final | 1,642 | 1,658 |
| Active | 154 | 147 |
| In Review | 39 | 40 |
| Inactive | 151 | 153 |
| (missing) | 14 | 2 |

Post-repair completeness by status:

| Status | n | FILE_DATE | PERMIT_DATE | FINAL_DATE |
| --- | ---: | ---: | ---: | ---: |
| Active | 147 | 147 (100%) | 145 (98.6%) | 0 (0%) |
| Final | 1,658 | 1,655 (99.8%) | 1,653 (99.7%) | 1,649 (99.5%) |
| In Review | 40 | 40 (100%) | 19 (47.5%) | 0 (0%) |
| Inactive | 153 | 151 (98.7%) | 90 (58.8%) | 0 (0%) |

Source-data chronology quirks retained (portal Issued before Applied on 5 rows; Finaled before Issued on 3 rows). Values match `permit_info` fields as-is.

## Artifacts

- Repair script: `agent/scripts/ca/data_repair_ca_hanford.py`
- Repaired sample: `$AGENT_DATA_PATH/repaired/permits_ca_hanford_repaired.parquet`

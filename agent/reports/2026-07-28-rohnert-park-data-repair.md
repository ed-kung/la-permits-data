# Rohnert Park (CA) data repair — 2026-07-28

Assessed STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for 2,000 Rohnert Park sample permits against the raw DATA JSON. Wrote `agent/scripts/ca/data_repair_ca_rohnert_park.py`. After repair: status nulls drop 23→14; Active/Final PERMIT_DATE coverage reaches 95.5%/97.4%; Final FINAL_DATE coverage reaches 99.4%; FILE_DATE unchanged at 98.6% (28 empty shells unfillable).

## Data shape

All 2,000 rows share one top-level key set: `fees`, `contacts`, `site_info`, `inspections`, `permit_info`, `search_data` (same civic-portal family as Foster City / Brentwood). Canonical fields are under `permit_info`, with `search_data` as fallback for Status / Applied / ISSUED.

INFERRED_SCHEMA (content variants by which dates are populated):

| Schema | n |
| --- | ---: |
| permit_info_issued_finaled | 1,341 |
| permit_info_issued | 420 |
| permit_info_applied_only | 107 |
| permit_info_finaled_only | 69 |
| permit_info_approved_only | 28 |
| permit_info_empty | 14 |
| permit_info_empty_dates | 14 |
| legacy_no_status | 7 |

## Findings by field

### STATUS_NORMALIZED

Upstream distribution: Final 1,244 / Inactive 405 / Active 247 / In Review 81 / null 23.

Issues found:
- **Unmapped label** `APPROVED - WAITING FOR SIGNATURE` (3 rows) left STATUS null despite Issued dates → map to Active.
- **Blank PermitStatus** with Applied date only (6 rows) left null → In Review.
- **Stale non-Final with PermitFinaledDate**: 5 Active (ISSUED/APPROVED) and 2 In Review (ALMOST THERE!/PENDING) already finaled → Fixed to Final.
- **MASTER PLAN** (2 rows) upstream-mapped to Final with no Finaled date → Fixed to Active.
- Inactive labels (EXPIRED, VOID, WITHDRAWN, etc.) correctly kept Inactive even when `PermitFinaledDate` is present (close/retention stamp, not open Final work).
- 14 empty shells (`permit_info_empty`) remain null — no status or dates in DATA.

Repair: **FILLED 9 / FIXED 9**. After: Final 1,249 / Inactive 405 / Active 247 / In Review 85 / null 14.

### FILE_DATE

Whenever `PermitAppliedDate` is present, FILE_DATE already matches (1,971/1,971). **28 missing** FILE_DATE rows have blank Applied in both `permit_info` and `search_data` (VOID / TEMPLATE / empty shells) → not fillable. **FILLED 0 / FIXED 0**. Coverage 1,972/2,000 (98.6%).

### PERMIT_DATE

Ideal: populated for Active and Final.

Before: 90 Active/Final rows missing PERMIT_DATE.
- 1 had `PermitIssuedDate` present but PERMIT_DATE null (ISSUED business-license row) → FILLED.
- 48 had Issued blank but `PermitApprovedDate` present → FILLED from Approved.
- 1 row had blank `PermitIssuedDate` but `search_data.ISSUED` disagreeing with PERMIT_DATE (12/17 vs 12/19) → FIXED to search ISSUED.
- Remaining ~43 Active/Final shells have neither Issued nor Approved in DATA → left missing.

Repair: **FILLED 49 / FIXED 1**. After coverage: Active 236/247 (95.5%), Final 1,217/1,249 (97.4%).

### FINAL_DATE

Ideal: populated for Final; not required on other statuses.

Before: 15 Final missing FINAL_DATE; 183 non-Final rows carried FINAL_DATE (176 Inactive/EXPIRED with real Finaled stamps, 5 Active, 2 In Review).

Repair logic:
- Prefer `PermitFinaledDate`; else latest passed final-type inspection (`Result` APPROVED/PASS*, `Type` matching final / admin final / C of O).
- On Final: fill/fix from preferred source → **FILLED 6** (all from approved final inspections).
- On non-Final: clear spurious FINAL_DATE → **FIXED 176** (mostly Expired).

After: Final FINAL_DATE 1,242/1,249 (99.4%); Active/In Review/Inactive all 0%. Seven remaining Final gaps have status FINALED but empty Finaled date and no usable passed final inspection (corrections/partial/empty results).

## Repair performance summary

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 9 | 9 | 23 → 14 |
| FILE_DATE | 0 | 0 | 28 → 28 |
| PERMIT_DATE | 49 | 1 | 238 → 189 |
| FINAL_DATE | 6 | 176 | 588 → 758 |

FINAL_DATE missing count rises because Expired/Inactive Finaled stamps are cleared; among Final rows, missing drops 15 → 7.

Chronology inversions remain in source dates (PERMIT &lt; FILE: 38; FINAL &lt; PERMIT: 8); the repair does not invent chronology fixes beyond overwriting from DATA.

## Artifacts

- Script: `agent/scripts/ca/data_repair_ca_rohnert_park.py`
- Repaired sample: `$AGENT_DATA_PATH/repaired/permits_ca_rohnert_park_repaired.parquet`

# Frisco (TX) data repair — STATUS_NORMALIZED and dates

**Summary:** Among TX sample jurisdictions in first-appearance order, Frisco is the first without an existing repair script. Frisco’s portal scrape uses one top-level keyset (`permit_info` / `search_data` / `inspections` / …). Main defects: 23 null `STATUS_NORMALIZED` values (20 fillable from uncommon `PermitStatus` values or Issued/Approved/Finaled dates), 13 missing `FILE_DATE` (2 fillable from `PermitAppliedDate`), 206 missing `PERMIT_DATE` values fillable from `PermitApprovedDate` when Issued is blank, 29 missing Final completion dates fillable from approved inspection `Completed` dates, and 32 spurious `FINAL_DATE` values on non-Final rows. After repair, Active has 99.1% `PERMIT_DATE` coverage and Final has 97.4% / 98.0% for `PERMIT_DATE` / `FINAL_DATE`.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_tx_sample.parquet` (193,630 rows). Walking unique `(JURISDICTION, STATE)` in first-appearance order, existing TX scripts cover Austin, Fort Worth, Houston, San Antonio, Dallas, Harris County, El Paso, and Plano. **Frisco** is the first gap → `agent/scripts/tx/data_repair_tx_frisco.py`.

Sample size: **2,002** Frisco records.

## DATA schemas (`INFERRED_SCHEMA`)

All rows share the same top-level keys. Variants reflect whether `permit_info.PermitStatus` is populated:

| Schema | n | Notes |
| --- | ---: | --- |
| `permit_info` | 1,992 | `PermitStatus` non-empty |
| `permit_info_unstated` | 10 | Blank status; mostly late-1990s / 2000 legacy rows |

Repair uses `permit_info` date fields (with `inspections` fallback for Final) in both variants. `search_data` has no applied-date key for Frisco (only `RECORDID`, `PERMIT NO`, address, contractor, parent project).

## Field assessment (before repair)

### STATUS_NORMALIZED

| Value | n |
| --- | ---: |
| Final | 995 |
| Active | 455 |
| Inactive | 425 |
| In Review | 104 |
| (null) | 23 |

Upstream mapping from `PermitStatus` / `STATUS_ORIGINAL` is correct for all common statuses (`COMPLETED`, `ISSUED`, `APPROVED`, `EXPIRED`, etc.). No incorrect non-null values found.

**Incorrectly missing (23):**

| Cause | n | Repair |
| --- | ---: | --- |
| Unmapped `PermitStatus` (`PRESCREEN`, `RES LETTER *`, `FINAL ACCEPTANC`, `REVIEW - REV RESUB`, `APPROVED AS NOT`, `Referred to Code`) | 11 | Map to In Review / Final / Inactive |
| Blank `PermitStatus` with Issued (and no Applied) | 7 | Infer Active from IssuedDate |
| `WITHDRAWN` / `COMPLETE` with null `STATUS_ORIGINAL` | 2 | Map to Inactive / Final |
| Blank status with no usable dates (or Applied only) | 3 | Not fillable |

### FILE_DATE

- Missing: **13 / 2,002**
- Present values all match `permit_info.PermitAppliedDate` at calendar-day resolution (no mismatches)
- **2** missing rows have `PermitAppliedDate` → fillable
- **11** have blank AppliedDate (mostly unstated legacy Issued-only rows) → not fillable from DATA

### PERMIT_DATE

- Present values (**1,591**): all match `PermitIssuedDate` when Issued is present (no mismatches)
- Missing: **411**
- **206** of the missing have `PermitApprovedDate` (approval without recorded issuance) → fillable; of Active/Final gaps, 153 Active and 17 Final are fillable this way
- Ideal gap before repair: **199** Active/Final rows lack `PERMIT_DATE` (157 Active + 42 Final)

### FINAL_DATE

- Present values on Final (**950**): all match `PermitFinaledDate` (no mismatches)
- **45** Final rows lack `FINAL_DATE` and lack FinaledDate; **27** of those have an APPROVED inspection `Completed` date → usable fallback
- **Spurious on non-Final:** Active/ISSUED (12), Inactive (20: EXPIRED / VOID / CANCELLED / WITHDRAWN / EXPIRED PERMIT) — all carry `PermitFinaledDate` in DATA while status is not Final → clear

## Repair behavior

Canonical mappings:

- `PermitStatus` → `STATUS_NORMALIZED` (blank status inferred from Finaled/Issued/Approved dates)
- `PermitAppliedDate` → `FILE_DATE`
- `PermitIssuedDate` → `PERMIT_DATE` (fallback: `PermitApprovedDate`)
- `PermitFinaledDate` → `FINAL_DATE` for Final only (fallback: latest APPROVED inspection `Completed`); clear otherwise

Flags: `FILLED` for former missings; `FIXED` for corrected or cleared values. `INFERRED_SCHEMA` set per row.

## Performance (after repair)

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 20 | 0 | 23 → 3 |
| FILE_DATE | 2 | 0 | 13 → 11 |
| PERMIT_DATE | 206 | 0 | 411 → 205 |
| FINAL_DATE | 29 | 32 | 1,019 → 1,022 |

Overall `FINAL_DATE` missing count rises slightly because 32 non-Final spurious dates were cleared while only 29 Final gaps were filled; Final-status coverage improves sharply.

### Coverage by status (after)

| Status | PERMIT_DATE | FINAL_DATE |
| --- | --- | --- |
| Active | 458 / 462 (99.1%) | 0 / 462 (cleared) |
| Final | 974 / 1,000 (97.4%) | 980 / 1,000 (98.0%) |
| In Review | 11 / 109 (10.1%) | 0 / 109 |
| Inactive | 354 / 428 (82.7%) | 0 / 428 (cleared) |

### Remaining gaps

- **3** unstated rows still null status (no Issued/Approved/Finaled; one has Applied only)
- **4** Active rows still missing `PERMIT_DATE` (APPROVED/ISSUED with blank Issued and Approved dates)
- **26** Final rows still missing `PERMIT_DATE` (no Issued/Approved in DATA)
- **20** Final rows still missing `FINAL_DATE` (no FinaledDate and no APPROVED inspection Completed date; mostly `CLOSED`)
- **11** rows still missing `FILE_DATE` (blank `PermitAppliedDate`)

## Artifacts

| Path | Description |
| --- | --- |
| `agent/scripts/tx/data_repair_tx_frisco.py` | Repair function `data_repair` |
| `AGENT_DATA_PATH/repaired/permits_tx_frisco_repaired.parquet` | Repaired Frisco sample output |

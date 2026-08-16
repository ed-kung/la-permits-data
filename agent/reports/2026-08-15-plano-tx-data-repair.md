# Plano (TX) data repair — STATUS_NORMALIZED and dates

**Summary:** Among TX sample jurisdictions in first-appearance order, Plano is the first without an existing repair script. Plano’s portal scrape uses one top-level keyset (`permit_info` / `search_data` / `inspections` / …). Main defects: 142 blank `PermitStatus` rows (75 fillable from Issued/Approved/Finaled dates), one `CLOSED` row wrongly stored as Inactive because `STATUS_ORIGINAL` was `expired`, 1,089 missing `PERMIT_DATE` values fillable from `PermitApprovedDate` when Issued is blank, 521 missing Final completion dates fillable from `PermitFinaledDate` or approved inspection `Completed` dates, and 2 spurious `FINAL_DATE` values on non-Final rows. After repair, Active has 100% `PERMIT_DATE` coverage and Final has 96.7% / 63.3% for `PERMIT_DATE` / `FINAL_DATE`.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_tx_sample.parquet` (193,630 rows). Walking unique `(JURISDICTION, STATE)` in first-appearance order, existing TX scripts cover Austin, Fort Worth, Houston, San Antonio, Dallas, Harris County, and El Paso. **Plano** is the first gap → `agent/scripts/tx/data_repair_tx_plano.py`.

Sample size: **2,001** Plano records.

## DATA schemas (`INFERRED_SCHEMA`)

All rows share the same top-level keys. Variants reflect whether `permit_info.PermitStatus` is populated:

| Schema | n | Notes |
| --- | ---: | --- |
| `permit_info` | 1,859 | `PermitStatus` non-empty |
| `permit_info_unstated` | 142 | Blank status; mostly 1990s legacy rows |

Repair uses `permit_info` date fields (with `search_data` / `inspections` fallbacks) in both variants.

## Field assessment (before repair)

### STATUS_NORMALIZED

| Value | n |
| --- | ---: |
| Final | 1,561 |
| Inactive | 169 |
| (null) | 142 |
| Active | 89 |
| In Review | 40 |

Upstream mapping from `PermitStatus` / `STATUS_ORIGINAL` is correct for all non-empty statuses except one mismatch:

| PermitStatus | Was | Should be | Reason |
| --- | --- | --- | --- |
| CLOSED | Inactive | Final | `STATUS_ORIGINAL` was `expired` while DATA says CLOSED (BLD17-09566) |

**Incorrectly missing (142):** blank `PermitStatus`. Of these, 75 have Issued / Approved / Finaled dates and can be inferred (Issued/Approved→Active, Finaled→Final). Remaining 67 have only `PermitAppliedDate` → not fillable.

### FILE_DATE

- Missing: **0 / 2,001**
- All values match `permit_info.PermitAppliedDate` (and `search_data['APPLICATION APPLIED DATE']`) at calendar-day resolution
- No fill or fix needed

### PERMIT_DATE

- Present values (**737**): all match `PermitIssuedDate`
- Missing: **1,264** — none have IssuedDate available
- **1,089** of the missing have `PermitApprovedDate` (approval without recorded issuance) — fillable; Approved usually equals Issued when both exist (499/587 same day)
- Ideal gap: **1,130** Active/Final rows lack `PERMIT_DATE` before repair (1,105 CLOSED + 24 APPROVED + 1 FINALED)

### FINAL_DATE

- Present values (**470**): all match `PermitFinaledDate`
- **1** FinaledDate present but `FINAL_DATE` missing (on the CLOSED→Inactive anomaly; FinaledDate should apply once status is Final)
- **1,094** Final (`CLOSED`/`FINALED`/`CERTIFICATE ISSUED`) rows lack `FINAL_DATE` and lack FinaledDate; **520** of those have an APPROVED inspection `Completed` date (matches FinaledDate on 391/393 rows when both exist) → usable fallback
- **Spurious on non-Final:** EXPIRED (1), ISSUED (1); one unstated row with FinaledDate becomes Final after status fill (kept)

## Repair behavior

Canonical mappings:

- `PermitStatus` → `STATUS_NORMALIZED` (blank status inferred from Finaled/Issued/Approved dates)
- `PermitAppliedDate` → `FILE_DATE` (fallback: search applied date)
- `PermitIssuedDate` → `PERMIT_DATE` (fallback: `PermitApprovedDate`)
- `PermitFinaledDate` → `FINAL_DATE` for Final only (fallback: latest APPROVED inspection `Completed`); clear otherwise

Flags: `FILLED` for former missings; `FIXED` for corrected or cleared values. `INFERRED_SCHEMA` set per row.

## Performance (after repair)

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 75 | 1 | 142 → 67 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 1,089 | 0 | 1,264 → 175 |
| FINAL_DATE | 521 | 2 | 1,531 → 1,012 |

Status distribution after: Final 1,563, Active 163, Inactive 168, In Review 40, null 67.

Date coverage after repair:

| Status | PERMIT_DATE | FINAL_DATE |
| --- | --- | --- |
| Active | 163 / 163 (100%) | 0 / 163 |
| Final | 1,512 / 1,563 (96.7%) | 989 / 1,563 (63.3%) |
| In Review | 8 / 40 | 0 / 40 |
| Inactive | 143 / 168 | 0 / 168 |

`FILE_DATE`: 2,001 / 2,001.

Remaining gaps are DATA-limited: 67 unstated applied-only rows (no status), 51 Final rows with neither Issued nor Approved, and 574 Final rows with neither FinaledDate nor approved inspection completion.

## Artifacts

- Script: `agent/scripts/tx/data_repair_tx_plano.py`
- Repaired sample: `AGENT_DATA_PATH/repaired/permits_tx_plano_repaired.parquet`

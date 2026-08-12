# Arcadia (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script (after Alachua County through Apopka in sort order) was **Arcadia**. DATA is Tyler EnerGov JSON (`entity` / `details` / `processing_status`). STATUS_NORMALIZED was FIXED on 65 rows: 28 mislabeled `Estimate`→Final cases, 36 Issued/Approved rows with `FinalDate` still labeled Active, and 1 In Review row with `IssueDate`. FILE_DATE and PERMIT_DATE already matched ApplyDate / IssueDate wherever present (no fills). FINAL_DATE was cleared on 27 Inactive rows that incorrectly retained a closure stamp; Final coverage is 99.9% (1 Complete row has an implausible year-8200 `FinalDate`).

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` and walked unique `(JURISDICTION, STATE)` pairs in sort order. Existing FL repair scripts covered Alachua County, Altamonte Springs, Anna Maria, and Apopka. **Arcadia** was the first without `agent/scripts/fl/data_repair_fl_arcadia.py`.

Sample size: **1,999** records.

Note: location fields in DATA commonly show Arcadia, CA ZIP codes; repair uses DATA timestamps/status only and does not depend on address state.

## DATA schemas

All rows share top-level keys `entity`, `details`, `fees`, `contacts`, `processing_status` (18 also have `reviews` / `holds` / `attachments` / `more_info`). Content variants by which dates are set:

| INFERRED_SCHEMA            | Count |
| -------------------------- | ----: |
| `energov_issued_finaled`   | 1,667 |
| `energov_issued`           |   236 |
| `energov_applied`          |    81 |
| `energov_finaled`          |    15 |

Canonical source fields:

| Target field      | DATA source                                                                 |
| ----------------- | --------------------------------------------------------------------------- |
| STATUS_NORMALIZED | `entity.CaseStatus` / `details.PermitStatus`; FinalDate on Active/In Review → Final; In Review + IssueDate → Active |
| FILE_DATE         | `entity.ApplyDate` (details fallback)                                       |
| PERMIT_DATE       | `entity.IssueDate` (details fallback)                                       |
| FINAL_DATE        | `FinalDate` / `FinalizeDate`; else latest Passed final-ish / any inspection |

## Field assessments

### STATUS_NORMALIZED

Before: Final 1,648 · Inactive 212 · Active 126 · In Review 13 · missing 0.

- Most CaseStatus values already mapped correctly (`Complete`→Final, `Issued`/`Approved`→Active, `In Review`→In Review, `Expired`/`Void`/`Withdrawn`/`Plan * Expired`→Inactive).
- **28** `Estimate` rows were upstream-normalized as Final. Estimates are pre-permit fee/quote shells (usually no IssueDate) → **FIXED** to In Review; the 1 Estimate with IssueDate was further promoted to Active.
- **35** `Issued` and **1** `Approved` rows carried a plausible `FinalDate` while labeled Active → **FIXED** to Final (portal status lag). Inactive statuses with `FinalDate` were left Inactive (closure stamp ≠ successful final).
- **1** `In Review` row had IssueDate → **FIXED** to Active.

After: Final 1,656 · Inactive 212 · Active 92 · In Review 39 · missing 0.  
Flags: **FILLED 0 · FIXED 65**.

### FILE_DATE

Before/after: **0 missing**. Ideal: populated for all records.

- Upstream FILE_DATE matched `ApplyDate` on every row (**0** day mismatches).
- Coverage after repair: **100%** for all statuses.

Flags: **FILLED 0 · FIXED 0**.

### PERMIT_DATE

Before/after: **96 missing**. Ideal: populated for Active and Final.

- When present, PERMIT_DATE already matched `IssueDate` (**0** mismatches).
- No Active/Final row has a blank PERMIT_DATE while IssueDate is present → nothing to fill.
- After status repair, Active/Final missing PERMIT_DATE: **21** (blank IssueDate / `Issued=False` Completes and Approveds). Not repairable from DATA.
- Coverage after: Active **90.2%**; Final **99.3%**.

Flags: **FILLED 0 · FIXED 0**.

### FINAL_DATE

Before: 317 missing (29 of Final); 36 Active and 27 Inactive rows incorrectly carried FinalDate. Ideal: populated for Final.

- When present and year-plausible, FINAL_DATE already matched `FinalDate` (**0** mismatches).
- Status repair moved 36 Active+FinalDate rows into Final; their FINAL_DATE values become appropriate (no clear).
- **27** Inactive rows (Expired / Void / Withdrawn) still carried FINAL_DATE → **FIXED** cleared.
- Among Final rows, **1** Complete has `FinalDate`/`FinalizeDate` year **8200** (rejected by year filter) and empty `processing_status` → cannot fill.
- The 28 Estimate rows no longer count as Final, so their missing FINAL_DATE is no longer a gap against the ideal.

After: 344 missing. Coverage: Final **99.9%** (1,655 / 1,656); Active / In Review / Inactive **0%**.  
Flags: **FILLED 0 · FIXED 27** (clears).

Chronology quirks already present in agency DATA (preserved, not invented): 7 rows with IssueDate calendar-day before ApplyDate; 4 with FinalDate before IssueDate.

## Repair script

- Path: `agent/scripts/fl/data_repair_fl_arcadia.py`
- Entry point: `data_repair(df)`
- Adds `INFERRED_SCHEMA` and `{FIELD}_FLAG` (`FILLED` / `FIXED`) for STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, FINAL_DATE.

## Performance summary

| Field             | FILLED | FIXED | Missing before | Missing after |
| ----------------- | -----: | ----: | -------------: | ------------: |
| STATUS_NORMALIZED |      0 |    65 |              0 |             0 |
| FILE_DATE         |      0 |     0 |              0 |             0 |
| PERMIT_DATE       |      0 |     0 |             96 |            96 |
| FINAL_DATE        |      0 |    27 |            317 |           344 |

## Artifacts

- Repaired sample: `AGENT_DATA_PATH/arcadia_repaired_sample.parquet`

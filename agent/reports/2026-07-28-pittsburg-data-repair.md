# Pittsburg (CA) data repair

**Summary:** Pittsburg was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script (La Cañada Flintridge already has `data_repair_ca_la_canada_flintridge.py`). Accela Citizen Access DATA is present on all 2,000 sample rows (1,989 full portal; 11 `search_data`-only TMP shells). Status blanks and portal CaseStatus lag (Active/Issued with Final Inspection Complete) are the main defects. Repair fills all 105 null statuses, promotes 357 Active→Final on completion evidence, fills 159 missing `PERMIT_DATE` values (mostly Renewed license rows), and raises Final/`FINAL_DATE` coverage to 99.7%. Script: `agent/scripts/ca/data_repair_ca_pittsburg.py`.

## Jurisdiction selection

First `(JURISDICTION, STATE)` in appearance order without `agent/scripts/{state}/data_repair_{state}_{city}.py` (ñ-normalized slug `la_canada_flintridge` already exists): **Pittsburg, CA**.

## DATA schema

| Schema | N | Notes |
| --- | ---: | --- |
| `portal_issued_finaled` | 787 | Issued + final-inspection / closure evidence |
| `portal_issued` | 519 | Issued present, no finaling date |
| `portal_final_insp_only` | 459 | Final evidence, no Issued |
| `portal_application_only` | 224 | Application / top-level date only |
| `search_data_only` | 11 | Blank-status TMP shells |

Canonical sources: `DATA.status` / `search_data.Status`; `DATA.date` / `search_data.Date` / Application Intake Accepted*; Permit Issuance / Issuance / License Renewal Issued|Renewed; Inspection(s) Final Inspection Complete (fallback Closure / admin Closed - Owner Occupied|Exempt; Passed final `inspections[]`).

## Findings by field

### STATUS_NORMALIZED

Before: Active 875, Final 833, Inactive 139, In Review 48, **null 105**.

Nulls are mostly `Closed - Exempt` / `Closed-Exempt` (70), en-dash `Closed – No Activity` (9), blank TMP shells (13), plus fee / lien / exempt-sold shells. Existing mapping errors: `Notice Issued` and `Inspection Required` (code-violation) labeled Final; Active/Issued shells with Final Inspection Complete or Passed final inspection left Active (portal lag).

Repair: **105 FILLED, 370 FIXED**; missing after: **0**.

After: Final 1,181, Active 531, Inactive 223, In Review 65.

Main transitions: Active→Final 357 (270 `active` + 87 `issued`); null→Inactive 84 (exempt / no-activity / lien / exempt-sold); Final→Active 6 (`notice issued`); Final→In Review 3 (`inspection required`).

### FILE_DATE

Before: **0 missing**. Matches `DATA.date` / `search_data.Date` on every row. Four rows have an earlier Application Intake Accepted stamp than the portal `date` field (revision / reopen date on `date`); FILE_DATE is corrected to the Accepted date.

Repair: **0 FILLED, 4 FIXED**. Coverage: **100%**.

### PERMIT_DATE

Before: **848 missing**. Present values match Permit Issuance Issued when that event exists. Fillable gaps are mostly `renewed` Active shells whose License Renewal Issued stamp was never copied (158), plus a few Issued rows.

After status repair, Active coverage is **464 / 531 (87.4%)**; Final **791 / 1,181 (67.0%)**. Remaining Active/Final gaps (457) are mostly `STATUS_ORIGINAL=active` rental/inspection records with no Issued task, or Issued with Permit Issuance TBD / empty events.

Repair: **159 FILLED, 0 FIXED**. Spurious PERMIT_DATE on In Review after repair: **0**.

### FINAL_DATE

Before: **915 missing**; 304 Active rows carried Final Inspection Complete dates (status lag); 19 Inactive withdrawn rows carried Closed - Withdrawn stamps as FINAL_DATE.

Repair promotes lagging Active shells to Final (keeping their completion dates) and clears FINAL_DATE on non-Final. Fills Closure Closed - Complete, Application Intake Closed - Owner Occupied / Closed - Exempt, and Passed final `inspections[]` where workflow Marked-as was TBD.

Repair: **125 FILLED, 34 FIXED** (clears). Final coverage after: **1,177 / 1,181 (98.7% → 99.7%)**. Four Final rows remain unfilled (Closed - Complete / Closed / Final Inspection Complete with no dated completion mark).

## Repair script

`agent/scripts/ca/data_repair_ca_pittsburg.py` — `data_repair(df)` overwrites incorrect/missing fields, adds `{FIELD}_FLAG` (`FILLED` / `FIXED`) and `INFERRED_SCHEMA`.

### Performance (n=2,000)

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | ---: | ---: | ---: | ---: |
| STATUS_NORMALIZED | 105 | 370 | 105 | 0 |
| FILE_DATE | 0 | 4 | 0 | 0 |
| PERMIT_DATE | 159 | 0 | 848 | 689 |
| FINAL_DATE | 125 | 34 | 915 | 823 |

### Coverage after repair

| Check | Result |
| --- | --- |
| FILE_DATE present | 2,000 / 2,000 (100%) |
| PERMIT_DATE on Active | 464 / 531 (87.4%) |
| PERMIT_DATE on Final | 791 / 1,181 (67.0%) |
| FINAL_DATE on Final | 1,177 / 1,181 (99.7%) |
| FINAL_DATE on non-Final | 0 |

Ideal-coverage gaps that cannot be closed from DATA: 457 Active/Final rows without a dated Issued mark; 4 Final rows without any completion stamp.

## Artifacts

- Script: `agent/scripts/ca/data_repair_ca_pittsburg.py`
- Repaired sample: `$AGENT_DATA_PATH/repaired/permits_ca_pittsburg_repaired.parquet`

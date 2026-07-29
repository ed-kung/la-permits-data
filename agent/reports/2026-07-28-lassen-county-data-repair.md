# Lassen County (CA) data repair

**Summary:** Lassen County was the first sample jurisdiction lacking a repair script (2,000 rows). DATA is a custom portal payload (`My Project` / `Build Status`). Upstream left 605 statuses null (mostly null Build Status with usable Closed/Issued/Approved dates), mis-tagged 8 rows (Closed→Active/Inactive, Ready To Issue with Issued, Incomplete Application with Closed), and left 4 FILE_DATE and many Active/Final PERMIT_DATE / Final FINAL_DATE gaps fillable from `My Project`. Repair fills/fixes 610 statuses (3 empty shells remain null), fills 4 FILE_DATE and 267 PERMIT_DATE values, fills 9 FINAL_DATE on promoted Final rows, and clears 59 junk FINAL_DATE values on non-Final rows. After repair: FILE_DATE 99.9%, Active PERMIT_DATE 100%, Final FINAL_DATE 98.6%; 106 Final shells still lack Issued/Approved so PERMIT_DATE stays missing; 13 `FINAL` Build Status rows have no Closed stamp.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_ca_sample.parquet` and walked `(JURISDICTION, STATE)` in first-appearance order (accent-normalized city slugs). The first pair without `agent/scripts/{state}/data_repair_{state}_{city}.py` was **Lassen County, CA**.

## DATA schemas (`INFERRED_SCHEMA`)

Custom county portal payload. Core keys: `Department`, `My Project`, `Permit Type`, `Build Status`, `Permit Number`, `Permit Details`, contacts/fees/inspections arrays. Optional `Parcel Number` and `ProjectDescription` distinguish variants; empty shells have `My Project: {}` and null status/type.

| Schema | n |
| --- | ---: |
| `my_project_with_description` | 1,222 |
| `my_project_with_parcel` | 756 |
| `empty_shell` | 13 |
| `my_project_basic` | 9 |

Canonical fields: `Build Status` (+ Closed/Issued/Approved/Submitted date overrides); `My Project.Submitted` → FILE_DATE; `My Project.Issued` (fallback `Approved`) → PERMIT_DATE; `My Project.Closed` → FINAL_DATE.

## Field assessment

### STATUS_NORMALIZED

Before: Inactive 847 / missing 605 / Final 523 / Active 15 / In Review 10.

| DATA signal | Upstream | Repair |
| --- | --- | --- |
| Null Build Status + Closed (373) | null | FILLED → Final |
| Null Build Status + Issued, no Closed (173) | null | FILLED → Active |
| Null Build Status + Submitted/Approved only (43) | null | FILLED → In Review |
| Expired without STATUS_ORIGINAL (13) | null | FILLED → Inactive |
| Application is under review / AUDITED / etc. (13) | null | FILLED via map / Issued |
| Closed tagged Inactive (STATUS_ORIGINAL expired) (4) | Inactive | FIXED → Final |
| Incomplete Application + Closed (2) | In Review | FIXED → Inactive |
| Ready To Issue + Issued (1) | In Review | FIXED → Active |
| Closed tagged Active (1) | Active | FIXED → Final |

All other Build Status labels (`Closed`, `FINAL`, `Issued`, `Approved`, `Expired*`, `Ready To Issue`, `Pending`, `Incomplete Application` without Closed) already mapped correctly when STATUS_ORIGINAL was present.

After: Final 901 / Inactive 858 / Active 188 / In Review 50 / missing 3 (empty shells with no dates or status).

### FILE_DATE

Almost complete before repair (7 missing). Every populated FILE_DATE already matched `My Project.Submitted` at calendar-day resolution. Filled 4 Closed rows that had Submitted but null FILE_DATE. Remaining 3 gaps are blank empty shells. Coverage: 1,997 / 2,000 (99.9%).

Two source chronology quirks remain: Submitted after Issued on Expired rows (FILE > PERMIT); left as-is.

### PERMIT_DATE

Wherever `Issued` exists (1,536 rows), PERMIT_DATE already matched at calendar-day resolution. Filled 267 Active/Final gaps from Issued or Approved (Approved used when Issued is blank ` - -`, common on Closed wells). Active coverage is 100%. Final coverage is 795 / 901 (88.2%); the 106 gaps are Closed / null-Build-Status finals with neither Issued nor Approved in DATA.

### FINAL_DATE

`Closed` is the true finaling stamp when status is Final (928 rows already matched before repair). After promoting Closed mis-tags and null-Build-Status Closed shells, 9 missing FINAL_DATE values were filled from Closed.

Junk FINAL_DATE on non-Final rows was cleared (FIXED 59):

- Expired with Closed case-closure stamps (54)
- Incomplete Application closures (2)
- Inactive empty shells with upstream FINAL_DATE only (3)

After repair: Final 888 / 901 (98.6%); absent on all non-Final. The 13 gaps are Build Status `FINAL` with blank Closed (legacy finals with no completion stamp in DATA).

## Repair performance

Script: `agent/scripts/ca/data_repair_ca_lassen_county.py` (`data_repair`).

Artifact: `AGENT_DATA_PATH/repaired/permits_ca_lassen_county_repaired.parquet`

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 602 | 8 | 605 → 3 |
| FILE_DATE | 4 | 0 | 7 → 3 |
| PERMIT_DATE | 267 | 0 | 454 → 187 |
| FINAL_DATE | 9 | 59 | 1,062 → 1,112 |

After repair:

- FILE_DATE: 1,997 / 2,000 (99.9%)
- PERMIT_DATE: Active 100%; Final 88.2% (106 without Issued/Approved)
- FINAL_DATE: Final 98.6% (13 `FINAL` without Closed); absent on non-Final

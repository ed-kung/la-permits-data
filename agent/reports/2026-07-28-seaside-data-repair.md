# Seaside (CA) data repair

**Summary:** Seaside was the first sample jurisdiction lacking a repair script (2,000 rows; La Cañada Flintridge already has `data_repair_ca_la_canada_flintridge.py`). DATA is a SmartGov portal payload (`Build Status` + `My Project` dates). Upstream left 1,332 statuses null (149 unmapped `Pending Initial Application Review`; ~1,177 null-Build-Status scrapes with usable dates), mis-tagged 12 In Review rows that already had Issued/Closed, and left Active/Final PERMIT_DATE and Finaled FINAL_DATE gaps fillable from `My Project` / Final inspections. Repair fills/fixes 1,338 statuses (6 empty shells remain null), fills 17 PERMIT_DATE and 2 FINAL_DATE values, and clears 3 spurious PERMIT_DATE values on empty-shell In Review rows. After repair: FILE_DATE 99.8%, Active PERMIT_DATE 100%, Final PERMIT_DATE 99.6%, Final FINAL_DATE 99.2%.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_ca_sample.parquet` and walked `(JURISDICTION, STATE)` in first-appearance order. The first pair without `agent/scripts/{state}/data_repair_{state}_{city}.py` was **Seaside, CA** (La Cañada Flintridge maps to the existing `la_canada_flintridge` slug).

## DATA schemas (`INFERRED_SCHEMA`)

SmartGov community portal payload. Core keys: `Department`, `My Project`, `Permit Type`, `Build Status`, `Permit Number`, `Permit Details`, contacts/fees/inspections arrays. Optional `Parcel Number` and `ProjectDescription` distinguish variants; empty shells have `My Project: {}` and null status/type. Blank portal dates appear as `" - -"`.

| Schema | n |
| --- | ---: |
| `smartgov_no_desc` | 922 |
| `smartgov_full` | 687 |
| `smartgov_minimal` | 377 |
| `empty_shell` | 14 |

Canonical fields: `Build Status` (+ Closed/Issued date overrides; null Build Status → date inference); `My Project.Submitted` (fallback `Created`) → FILE_DATE; `My Project.Issued` (fallback `Approved`) → PERMIT_DATE; `My Project.Closed` (fallback latest passed/completed Final inspection) → FINAL_DATE.

## Field assessment

### STATUS_NORMALIZED

Before: missing 1,332 / In Review 395 / Inactive 184 / Final 74 / Active 15.

| DATA signal | Upstream | Repair |
| --- | --- | --- |
| Null Build Status + Issued, no Closed (874) | null | FILLED → Active |
| Null Build Status + Closed (178) | null | FILLED → Final |
| Pending Initial Application Review (149) | null | FILLED → In Review |
| Null Build Status + Submitted/Approved only (125) | null | FILLED → In Review |
| Technically Completed / Ready To Issue + Issued (10) | In Review | FIXED → Active |
| Technically Completed + Closed (2) | In Review | FIXED → Final |

Already-correct mappings left alone: `Closed`/`Finaled` → Final, `Approved` → Active, `Expired:*` → Inactive, `Open`/`Pending`/`Ready To Issue`/`Technically Completed`/`Under Review` (no Issued/Closed) → In Review.

After: Active 899 / In Review 657 / Final 254 / Inactive 184 / missing 6 (empty shells with no Build Status or My Project dates; one retains `STATUS_ORIGINAL` but no DATA to validate).

### FILE_DATE

Almost complete before repair (5 missing). Every populated FILE_DATE already matched `My Project.Submitted` at calendar-day resolution (1,986/1,986). No FILLED/FIXED. Remaining 5 gaps are blank empty shells. Coverage: 1,995 / 2,000 (99.8%).

### PERMIT_DATE

Wherever `Issued` exists (1,319 rows), PERMIT_DATE already matched at calendar-day resolution (1,318 match; 1 fillable). Filled 17 Active/Final gaps from Issued or Approved (Approved used when Issued is blank ` - -`, common on `Approved` Active and a few Closed/Final shells). Cleared 3 spurious PERMIT_DATE values on empty-shell In Review rows with no Issued in DATA.

After repair: Active 899 / 899 (100%); Final 253 / 254 (99.6%); In Review 0 / 657; Inactive 184 / 184 (historical issuance on Expired). The 1 Final gap is an empty-shell row with upstream Final/`closed` but empty `My Project`.

### FINAL_DATE

`Closed` is the true finaling stamp when status is Final (248 rows already matched before repair). Two `Finaled` rows with blank Closed were filled from passed Roof Final inspections. Two other `Finaled` rows stay missing (one has no inspections; one has only a generic Completed `Inspection` without "Final" in the name).

No junk FINAL_DATE clearing was needed after status promotion: the 2 In Review rows that carried FINAL_DATE also had Closed and were FIXED to Final.

After repair: Final 252 / 254 (99.2%); absent on all non-Final.

## Repair performance

Script: `agent/scripts/ca/data_repair_ca_seaside.py` (`data_repair`).

Artifact: `AGENT_DATA_PATH/repaired/permits_ca_seaside_repaired.parquet`

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 1,326 | 12 | 1,332 → 6 |
| FILE_DATE | 0 | 0 | 5 → 5 |
| PERMIT_DATE | 17 | 3 | 678 → 664 |
| FINAL_DATE | 2 | 0 | 1,750 → 1,748 |

After repair:

- FILE_DATE: 1,995 / 2,000 (99.8%)
- Active PERMIT_DATE: 100%
- Final PERMIT_DATE: 99.6%
- Final FINAL_DATE: 99.2%
- Chronology inversions retained as portal truth: FILE > PERMIT (4), PERMIT > FINAL (20)

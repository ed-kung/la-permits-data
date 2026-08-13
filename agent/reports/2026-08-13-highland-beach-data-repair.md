# Highland Beach (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script was **Highland Beach**. DATA is a SmartGov community portal payload (`My Project` / `Build Status` / optional `Parcel Number` + `ProjectDescription`). 1,965 of 2,000 rows are empty scraped shells with no usable status or dates. Among the 35 non-empty rows, upstream left 8 statuses null (4 `Expired*` → Inactive, 4 application-stage null Build Status → In Review) and 2 Expired shells missing `PERMIT_DATE` despite a usable `Approved` stamp. Repair FILLED 8 STATUS and 2 PERMIT_DATE values; FILE_DATE already matched `Submitted` on all non-empty rows; no Final records exist (all `Closed` blank).

## Jurisdiction selection

`(JURISDICTION, STATE)` pairs in `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` were checked against `agent/scripts/{state}/data_repair_{state}_{city}.py`. First missing: **Highland Beach, FL** → `agent/scripts/fl/data_repair_fl_highland_beach.py` (2,000 sample rows).

## DATA schemas (`INFERRED_SCHEMA`)

| Schema | n | Notes |
| --- | ---: | --- |
| `smartgov_empty` | 1,965 | SmartGov keyset present; Build Status / Permit Number / Permit Type / My Project dates all blank |
| `smartgov_full` | 31 | + `ProjectDescription` (and usually `Parcel Number`) |
| `smartgov_no_desc` | 4 | + `Parcel Number`, no `ProjectDescription` |

Canonical fields:

| Target field | Source in DATA |
| --- | --- |
| STATUS_NORMALIZED | `Build Status` (`Expired*` sticky Inactive; `Issued` → Active); else My Project dates (Closed → Final, Issued → Active, Submitted/Created → In Review) |
| FILE_DATE | `My Project.Submitted` (fallback `Created`) |
| PERMIT_DATE | `My Project.Issued` (fallback `Approved`) for Active / Final / Inactive |
| FINAL_DATE | `My Project.Closed` → latest passed Final/COO `Permit Inspections`; Final only |

A few non-empty rows are cross-tagged (`Gulf Stream Permits`, `Public Works`) but share the same SmartGov shape and are repaired identically.

## Field assessments

### STATUS_NORMALIZED

| Build Status | n | Upstream STATUS_NORMALIZED | Assessment |
| --- | ---: | --- | --- |
| Expired* | 30 | Inactive 26 / null 4 | 4 unmapped nulls |
| Issued | 1 | Active 1 | Correct |
| null (with Submitted) | 4 | null 4 | Application-stage; unmapped |
| (empty shells) | 1,965 | null 1,965 | No DATA signal |

**Root causes:**
- **Partial Expired mapping:** Upstream mapped most `expired: M/D/YYYY` STATUS_ORIGINAL values to Inactive but left 4 null despite `Build Status` = `Expired: …` and issued dates present.
- **Unmapped null Build Status:** Four pre-issuance applications have blank Build Status and blank Issued/Approved, but populated Submitted/Created → should be In Review.
- **Empty shells:** 1,965 rows carry no status string in DATA or STATUS_ORIGINAL → not repairable.

**Repair performance:** FILLED 8, FIXED 0; missing 1,973 → 1,965. After (non-empty): Inactive 30; In Review 4; Active 1. Remaining nulls are exclusively `smartgov_empty`.

### FILE_DATE

Ideal: populated for all records.

- Non-empty (35): **0 missing** before/after; all equal `My Project.Submitted` at calendar-day resolution (**0 FILLED / 0 FIXED**).
- Empty shells (1,965): no Submitted/Created → remain missing.
- Coverage after repair among rows with a status: **100%**. FILE > PERMIT inversions: 0.

### PERMIT_DATE

Ideal: populated for Active and Final.

- Existing non-empty values matched `Issued` whenever both present (**0 calendar mismatches**).
- **2 FILLED** on Expired Inactive shells (`18-1084`, `17-0136`) with blank `Issued` but usable `Approved` (1/3/2023 and 3/3/2017).
- In Review applications correctly keep PERMIT_DATE null (blank Issued/Approved).
- Active 1/1 (100%); Inactive 30/30 (100%); In Review 0/4; no Final rows.

### FINAL_DATE

Ideal: populated for Final; absent otherwise.

- Every non-empty `My Project.Closed` is the SmartGov placeholder ` - -`.
- No `Closed` / `Finaled` Build Status values in the sample → **0 Final** records.
- Some Expired/Issued shells have passed final-named inspections, but without Closed/Finaled status those dates are not treated as completion for STATUS_NORMALIZED, so FINAL_DATE stays empty (correct under the Final-only rule).
- **0 FILLED / 0 FIXED**; all 2,000 FINAL_DATE remain missing.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 8 | 0 | 1,973 → 1,965 |
| FILE_DATE | 0 | 0 | 1,965 → 1,965 |
| PERMIT_DATE | 2 | 0 | 1,971 → 1,969 |
| FINAL_DATE | 0 | 0 | 2,000 → 2,000 |

Among the 35 non-empty payloads, status/date ideals are met: every Active/Inactive has FILE_DATE + PERMIT_DATE; In Review has FILE_DATE only; no Final cohort to score. The dominant limitation is empty SmartGov shells with no recoverable agency fields.

## Artifacts

- Script: `agent/scripts/fl/data_repair_fl_highland_beach.py`
- Repaired sample: `AGENT_DATA_PATH/repaired/permits_fl_highland_beach_repaired.parquet`

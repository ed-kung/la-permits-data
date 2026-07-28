# San Mateo County (CA) data repair

**Summary:** San Mateo County was the first `(JURISDICTION, STATE)` pair without an existing repair script. Assessed and repaired `STATUS_NORMALIZED`, `FILE_DATE`, `PERMIT_DATE`, and `FINAL_DATE` from the Accela Citizen Access `DATA` JSON (`status` / `date` / `tasks` / `inspections` / `search_data`). Status missingness fell **81 → 0** (**FILLED 81 · FIXED 23**): blank Confirmation shells and unmapped Accela statuses filled; `Finaled`/`Issued`/`Expired` mislabels corrected; Active/In Review rows with finalization task signals upgraded to Final. `FILE_DATE` already matched `DATA.date` for all 2,000 rows (**FILLED/FIXED 0**). `PERMIT_DATE` missingness fell **1,583 → 1,269** (**FILLED 314 · FIXED 1**) via Ready-to-Issue issuance events plus DPW `Application Submitted`/`Permit Issued` and OTC `Application Submittal`/`Issued`. `FINAL_DATE` missingness fell **1,575 → 1,412** (**FILLED 163 · FIXED 7**) from Inspections Finaled / Final Processing closeout / Workflow Closed, with 7 rows corrected to the latest finalization event.

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_ca_sample.parquet`
- Jurisdiction: **San Mateo County, CA** (n=2,000)
- Script: `agent/scripts/ca/data_repair_ca_san_mateo_county.py` (`data_repair`)
- Artifact: `AGENT_DATA_PATH/repaired/permits_ca_san_mateo_county_repaired.parquet`

## DATA schema (`INFERRED_SCHEMA`)

All records share Accela top-level keys `status`, `date`, `tasks`, `search_data`, `inspections`, `more_details`, etc. Sub-schemas reflect workflow shape:

| Schema | n | Description |
| --- | ---: | --- |
| `tasks_ready_to_issue` | 1,091 | Building workflow with Ready to Issue* tasks |
| `tasks_dpw` | 413 | Application Submitted + Final Processing (DPW) |
| `tasks_other` | 398 | Other task trees with dated events |
| `tasks_empty_events` | 85 | Tasks present but no usable dated events |
| `header_only` | 13 | status/date/search_data only |

Canonical fields:

| Field | Source |
| --- | --- |
| `STATUS_NORMALIZED` | `DATA.status` / `search_data.Status` (upgrade to Final on finalization signals; empty Confirmation shells → In Review) |
| `FILE_DATE` | `DATA.date` (fallback: `search_data` Date Submitted / Date) |
| `PERMIT_DATE` | Ready to Issue* / Issued\|Permit Issued\|Re-Issued\|Revision Issued; else Application Submitted / Permit Issued; else Application Submittal / Issued; else Enforcement / Permit Issued |
| `FINAL_DATE` | Inspections / Finaled\|Final Processing\|Final Certificate of Occupancy (latest); else Final Processing / Project Close Out closeout marks; else Workflow Closed; else Enforcement/Investigation Finaled; else Final* inspection Pass |

## Field assessment

### STATUS_NORMALIZED

**Before:** Final 1,319 · Active 231 · Inactive 208 · In Review 161 · missing 81

`DATA.status` is usually well-mapped already (`Finaled`/`Closed`/`Permit Finaled`/`Recorded`→Final, `Issued`/`Permit Issued`/`Approved`→Active, `Cancelled`/`Expired`/`Withdrawn`→Inactive, `Received`/`In Review`/`Submitted`→In Review). Repairable problems:

1. **Missing status (81).** 42 blank Confirmation shells (`Status=""`, TBD-only events) → In Review. Remaining 39 map from Accela labels previously left null (`ACA Update`, `Map Check`, `Project Analysis`, `Agency Referrals`, `Project Closeout`, `Violation Notice Sent`, `Approved`, `Issued`, …).
2. **Stale vs DATA.status (23 FIXED).** Includes Finaled mislabeled Active/In Review/Inactive; Issued/Permit Issued/Approved mislabeled In Review; Expired mislabeled Active; Additional Info Required mislabeled Active; plus Active/In Review upgraded to Final when Inspections Finaled / Final Processing Closed signals exist.

| Change | n | Reason |
| --- | ---: | --- |
| null → In Review | 69 | Confirmation shells + review Accela statuses |
| null → Inactive | 5 | Violation Notice Sent / Reinstatement Declined |
| null → Final | 4 | Project Closeout |
| null → Active | 3 | Approved / Issued |
| Active → Final | 8 | Finaled label or finalization signal |
| In Review → Active | 7 | Issued / Permit Issued / Approved |
| In Review → Final | 2 | Closed / Finaled |
| Active → In Review | 2 | Additional Info Required |
| Active → Inactive | 2 | Expired |
| Final → Active | 1 | Permit Issued |
| Inactive → Final | 1 | Finaled |

**After:** Final 1,333 · Active 230 · In Review 223 · Inactive 214 · missing 0  
Flags: **FILLED 81 · FIXED 23**

### FILE_DATE

**Before:** 0 missing (100%).

- Every row’s `FILE_DATE` equals `DATA.date` at day resolution.
- `search_data` carries `Date Submitted` (1,559) or legacy `Date` (432); both agree with the header date when present.

**After:** still 0 missing.  
Flags: **FILLED 0 · FIXED 0**

### PERMIT_DATE

**Before:** 1,583 missing (79.2%). Among Active/Final: 163 / 1,045 missing.

Root causes:
1. Upstream only copied Ready to Issue* / Issued events. DPW rows use `Application Submitted` / `Permit Issued`, and OTC building rows use `Application Submittal` / `Issued` — both left null.
2. One Issued building row had `PERMIT_DATE` set to a Ready Letter / plan-prep date (2023-03-28) while the later `Ready to Issue Permit` / `Permit Issued` event was 2024-07-22 → FIXED.
3. Hundreds of Finaled lean shells have empty task event lists → not fillable from DATA.

Repairs (Active / Final after status repair; also correct mismatched issuance dates on any status):
1. Prefer Ready to Issue* issuance marks (including Permit Re-Issued / Revision Issued).
2. Else DPW `Application Submitted` / `Permit Issued`.
3. Else OTC `Application Submittal` / `Issued` (often same-day as FILE for water heater / HVAC / reroof OTC permits — still a true issuance mark).
4. Else `Enforcement` / `Permit Issued`.

**After:** 1,269 missing. Active 111/230 (48.3%) · Final 546/1,333 (41.0%) have PERMIT_DATE.  
Flags: **FILLED 314 · FIXED 1**

One chronology quirk remains: SWN2014-00025 has Enforcement `Permit Issued` (2014-02-07) before `FILE_DATE` (2014-02-25) — agency event ordering on a stop-work record; left as filled from DATA.

### FINAL_DATE

**Before:** 1,575 missing (78.8%). Among Final: 898 / 1,319 missing. Four Active rows carried a FINAL_DATE (all had finalization signals and were upgraded to Final).

Root causes:
1. Upstream used Inspections / Finaled when present, but missed Final Processing `Recorded`/`Closed`, `Workflow Closed` on violation closeouts, and DPW `Inspections` / `Final Processing`.
2. Seven Final rows used an earlier Finaled event instead of a later Finaled / Final Certificate of Occupancy → FIXED to latest.
3. Large share of Finaled building shells have empty Inspections / Project Close Out events → not fillable.

**After:** 1,412 missing. Final 588/1,333 (44.1%) have FINAL_DATE; non-Final have 0.  
Flags: **FILLED 163 · FIXED 7**

## Repair performance

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | ---: | ---: | ---: | ---: |
| STATUS_NORMALIZED | 81 | 23 | 81 | 0 |
| FILE_DATE | 0 | 0 | 0 | 0 |
| PERMIT_DATE | 314 | 1 | 1,583 | 1,269 |
| FINAL_DATE | 163 | 7 | 1,575 | 1,412 |

Chronology after repair: `FILE>PERMIT` = 1 (SWN2014-00025), `PERMIT>FINAL` = 0.

## Not repairable / left as-is

- ~745 Final rows lack any finalization task/inspection date (mostly `tasks_ready_to_issue` / `tasks_dpw` shells with empty events).
- ~787 Final rows lack issuance task events → `PERMIT_DATE` stays missing.
- Confirmation shells stay In Review with no issuance/final dates.
- Do not invent FILE_DATE / PERMIT_DATE / FINAL_DATE from unrelated review milestones (Ready Letter, plan prep, Approved-only marks).

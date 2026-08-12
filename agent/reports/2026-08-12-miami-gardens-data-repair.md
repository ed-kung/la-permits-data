# Miami Gardens (FL) data repair — STATUS_NORMALIZED and date fields

**Summary:** Among Florida sample jurisdictions missing a repair script, Miami Gardens was first. Its DATA is a Tyler EnerGov payload (`entity.CaseStatus` / `ApplyDate` / `IssueDate` / `FinalDate`). FILE_DATE already matched ApplyDate on every row. The main defects were (1) STATUS_ORIGINAL lagging CaseStatus (69 wrong + 17 null), (2) 22 Approved shells labeled Active despite no IssueDate, (3) 87 non-Final rows carrying cancel/spurious FinalDate as FINAL_DATE, and (4) a handful of missing IssueDate/FinalDate stamps after status remaps. After repair: STATUS 17 FILLED / 69 FIXED (0 null); PERMIT_DATE 13 FILLED / 3 FIXED; FINAL_DATE 14 FILLED / 87 FIXED (clears). Coverage: FILE 100%; Active PERMIT 100%; Final PERMIT 99.8%; Final FINAL 100%.

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_fl_sample.parquet`
- Jurisdiction: **Miami Gardens, FL** (1,999 rows) — first `(JURISDICTION, STATE)` pair without `agent/scripts/{state}/data_repair_{state}_{city}.py`
- Script: `agent/scripts/fl/data_repair_fl_miami_gardens.py` (`data_repair`)
- Artifact: `AGENT_DATA_PATH/repaired/permits_fl_miami_gardens_repaired.parquet`

## DATA schema

All rows are Tyler EnerGov payloads with top-level `entity`, `details`, `contacts`, `fees`, `processing_status`. A minority (74) also carry `reviews` / `holds` / `attachments` / `more_info` → `energov_full_*`.

`INFERRED_SCHEMA` is `energov{,_full}_{date_profile}`:

| INFERRED_SCHEMA | n |
| --- | ---: |
| energov_issued_finaled | 1,235 |
| energov_issued | 367 |
| energov_applied | 254 |
| energov_finaled | 69 |
| energov_full_applied | 39 |
| energov_full_issued | 31 |
| energov_full_issued_finaled | 3 |
| energov_full_finaled | 1 |

Canonical mappings:

| Field | Source |
| --- | --- |
| STATUS_NORMALIZED | `entity.CaseStatus` (+ IssueDate for Approved) |
| FILE_DATE | `entity.ApplyDate` |
| PERMIT_DATE | `entity.IssueDate` (Active / Final / Inactive); cleared for In Review |
| FINAL_DATE | `entity.FinalDate` for Final only; cleared otherwise |

CaseStatus → STATUS_NORMALIZED:

| CaseStatus | STATUS_NORMALIZED | n |
| --- | --- | ---: |
| Final | Final | 1,221 |
| Issued | Active | 333 |
| Stop Work Order | Active | 8 |
| Approved (no IssueDate) | In Review | 22 |
| Applied / Applied - Online / In Review / Fees Due / Fees Paid / On Hold | In Review | 180 |
| Canceled / Denied / Denied - Closed / Expired / Void / Plan Approval Expired | Inactive | 235 |

## Field assessments

### STATUS_NORMALIZED

17 nulls (`Applied - Online`, `Denied - Closed`) and 69 mismatches where STATUS_ORIGINAL lagged `entity.CaseStatus` (e.g. STATUS_ORIGINAL `issued` while CaseStatus is Final / Canceled).

Notable remaps:

- **22** Approved (no IssueDate) Active → In Review (plan approved, not issued)
- **14** CaseStatus Final mislabeled Active / In Review / Inactive → Final
- **9** Issued mislabeled In Review / Inactive → Active
- **8** Stop Work Order (issued) In Review → Active
- **10** Canceled / Plan Approval Expired mislabeled Active / In Review → Inactive
- **17** null → FILLED (14 In Review, 2 Inactive, 1 Active)

**17 FILLED / 69 FIXED.** After: Final 1,221; Active 341; Inactive 235; In Review 202; **0 null**.

### FILE_DATE

Ideal: populated for all records.

- All 1,999 rows already match `ApplyDate` at calendar-day resolution (**0 FILLED / 0 FIXED**).
- Coverage after repair: **100%** for every status.

### PERMIT_DATE

Ideal: populated for Active and Final.

- When IssueDate present, PERMIT_DATE already matched for nearly all rows.
- **13 FILLED** from IssueDate after status remaps (10 Issued → Active, 3 Final).
- **3 FIXED** (cleared): Fees Due In Review rows that incorrectly carried IssueDate as PERMIT_DATE.
- Remaining Active/Final gap: **3 Final** shells with `Issued=False` and null IssueDate (have FinalDate only) — not fillable from DATA.

Coverage after repair: Active 341/341 (100%); Final 1,218/1,221 (99.8%); In Review 0/202; Inactive 74/235 (issued-then-canceled/expired). **0** FILE_DATE > PERMIT_DATE inversions.

### FINAL_DATE

Ideal: populated for Final; absent otherwise.

- All CaseStatus=Final rows have `entity.FinalDate` — after remapping 14 mislabeled rows to Final, **14 FILLED**.
- **87 FIXED** (all clears): spurious FinalDate on Inactive (Canceled 68, Void 14, Plan Approval Expired 2, Denied - Closed 2) plus 1 Active Issued stamp. Missing FINAL_DATE count rises 705 → 778 because those clears are correct.
- Final coverage after repair: **1,221 / 1,221 (100%)**; Active / In Review / Inactive 0%. **0** PERMIT_DATE > FINAL_DATE inversions.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 17 | 69 | 17 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 13 | 3 | 376 → 366 |
| FINAL_DATE | 14 | 87 | 705 → 778 |

Not repairable from DATA: 3 Final rows with null IssueDate (PERMIT_DATE stays missing); Approved without IssueDate correctly become In Review (no PERMIT_DATE).

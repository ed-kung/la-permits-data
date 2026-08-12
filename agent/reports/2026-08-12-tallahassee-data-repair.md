# Tallahassee (FL) data repair — STATUS_NORMALIZED and date fields

**Summary:** Among Florida sample jurisdictions missing a repair script, Tallahassee was first. Its DATA is a single EnerGov-style case payload (`Case Status`, `Date Issued`, `Tasks`, `Workflow`, `Case Group`). Upstream left **107** STATUS_NORMALIZED null (unmapped statuses, mainly `OP ISSUED`) and mislabeled **149** rows (chiefly **132** `COMPLIED` as In Review). FILE_DATE gaps (**66**) are empty shells with no task/workflow dates and cannot be filled. PERMIT_DATE already tracked `Date Issued` on 1,272/1,279 rows; **7** mismatches (inspection dates copied in) were FIXED. FINAL_DATE gained **676** FILLED from complete/closed/complied task milestones and FINAL AP inspections. After repair: status complete; Final FINAL_DATE 1,434/1,436 (99.9%); remaining Active/Final PERMIT gaps lack `Date Issued` and ISSUE tasks in DATA.

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_fl_sample.parquet`
- Jurisdiction: **Tallahassee, FL** (2,000 rows) — first `(JURISDICTION, STATE)` pair without `agent/scripts/{state}/data_repair_{state}_{city}.py`
- Script: `agent/scripts/fl/data_repair_fl_tallahassee.py` (`data_repair`)
- Artifact: `AGENT_DATA_PATH/repaired/permits_fl_tallahassee_repaired.parquet`

## DATA schema

All 2,000 rows share the same portal family. Top-level keys: `Fees`, `Tasks`, `People`, `Street`, `Comments`, `Location`, `Payments`, `Workflow`, `Case Group`, `Case Number`, `Case Status`, `Date Issued`, plus optional `Case Type` / `Case Type Description` / `Project Name`.

Case Groups: Building Inspection Division (1,402), Code Enforcement Division (292), Land Use and Environmental Services (141), Administration Division (GM) (97), Code Enforcement (51), Fire Department (17).

`INFERRED_SCHEMA` = Case Group family × date evidence:

| INFERRED_SCHEMA | n | Notes |
| --- | ---: | --- |
| `tlh_building_issued_finalinsp` | 753 | Issued + FINAL AP inspection |
| `tlh_building_issued` | 428 | Issued, no FINAL AP |
| `tlh_code_tasks` | 333 | Code enforcement with task dates |
| `tlh_building_tasks` | 179 | Building tasks, no Date Issued |
| `tlh_admin_tasks` | 95 | Admin / GM |
| `tlh_land_use_issued` | 83 | Land use with Date Issued |
| `tlh_land_use_tasks` | 49 | Land use tasks only |
| `tlh_*_shell` | 65 | No usable dates (mostly VOID) |
| `tlh_fire_*` | 17 | Fire Department |

Canonical mappings:

| Field | Source |
| --- | --- |
| STATUS_NORMALIZED | `Case Status` |
| FILE_DATE | earliest `Tasks[].Date Completed`, else earliest `Workflow[].Assigned Date` (**fill only**) |
| PERMIT_DATE | `Date Issued`, else earliest ISSUE / OP_ISSUED task |
| FINAL_DATE | last `FINAL AP` inspection → COMPLETE/COFOCOMP/CLOSED task → passed final-ish inspection → last completed task (Final only) |

Case Status → normalized (high level): COMPLETE / CLOSED / COMPLIED / CERTOFOCC / *-FINE → Final; ISSUED / APPROVED / OP ISSUED / NOC HOLD / CONSTR → Active; PENDING / PLANCHECK / ELIGIBLE / INVOICED2 / CE notices / OP PENDING / SWO / LEGAL → In Review; VOID / EXPIRED / WITHDRAWN / CANCELLED / DENIED → Inactive.

## Field assessments

### STATUS_NORMALIZED

**107 missing** before repair — unmapped `Case Status` values:

| Case Status | n | Expected |
| --- | ---: | --- |
| OP ISSUED | 40 | Active |
| ELIGIBLE | 9 | In Review |
| NOC HOLD | 8 | Active |
| INVOICED2 | 7 | In Review |
| COMPLIED | 6 | Final |
| CERTOFOCC / COMP-FINE / MOW-FINE / CM-FINE / CLOSED | 12 | Final |
| CE notices (NOTICE*, NOV, VCN, CM-HEAR, ORDERS, SWO, …) | 19 | In Review |
| Other (CONSTR, OP PENDING, CANCELLED, LEGAL) | 6 | Active / In Review / Inactive |

**149 FIXED**, dominated by:

| Transition | n |
| --- | ---: |
| COMPLIED: In Review → Final | 132 |
| COMPLETE: Active → Final | 7 |
| VOID: In Review → Inactive | 6 |
| CERTOFOCC / OP ISSUED / EXPIRED / CANCELLED mislabels | 4 |

**107 FILLED / 149 FIXED.** After: Final 1,436; Active 238; Inactive 246; In Review 80; **0 null**.

### FILE_DATE

Ideal: populated for all records.

- Before: **66 missing**. All are shells with empty/undated Tasks and Workflow (mostly VOID/CANCELLED/PENDING); **0 FILLED**.
- When both present, FILE_DATE equals earliest task date on ~1,782 rows. On **152** rows FILE_DATE is later than the first automated task (median +13 days) — a true applied date not stored separately in DATA — so mismatches are **not** overwritten (**0 FIXED**).
- Coverage after repair: Active 100%; Final 99.9%; In Review 96.2%; Inactive 75.2%.

### PERMIT_DATE

Ideal: populated for Active and Final.

- When `Date Issued` present (1,279 rows), PERMIT_DATE already matched on 1,272. **7 FIXED** where PERMIT_DATE had been set to an inspection/activity date instead of `Date Issued` (e.g. TCB220770, TCB210448).
- **0 FILLED** — every row with a usable issuance stamp already had PERMIT_DATE; Active/Final gaps (**506**) are CLOSED/COMPLIED/shell cases with blank `Date Issued` and no ISSUE task.
- Nine In Review rows retain PERMIT_DATE because `Date Issued` is set (CITY / INVOICED2 / OP PENDING).

Coverage after repair: Active 177/238 (74.4%); Final 991/1,436 (69.0%); In Review 9/80; Inactive 102/246. **0** PERMIT_DATE ≠ `Date Issued` when Issued present. **5** FILE_DATE > PERMIT_DATE inversions remain on legacy rows where upstream FILE_DATE post-dates `Date Issued` (not altered).

### FINAL_DATE

Ideal: populated for Final; absent otherwise.

- When present pre-repair, FINAL_DATE matched last `FINAL AP` inspection.
- **676 FILLED**: CLOSED 288, COMPLETE 240, COMPLIED 138, CERTOFOCC 5, fine/complied variants 5 — from COMPLETE/COFOCOMP/CLOSED tasks, FINAL AP, or last completed task.
- **1 FIXED**: cleared FINAL_DATE on a non-Final EXPIRED row.
- Remaining Final gap: **2** empty Code Enforcement shells (`CLOSED` / `COMP-FINE`) with no tasks.

Coverage after repair: Final 1,434/1,436 (99.9%); Active / In Review / Inactive 0%. **1** PERMIT_DATE > FINAL_DATE inversion (TBE230267: portal `Date Issued` after COMPLETE task stamp; values match DATA).

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 107 | 149 | 107 → 0 |
| FILE_DATE | 0 | 0 | 66 → 66 |
| PERMIT_DATE | 0 | 7 | 721 → 721 |
| FINAL_DATE | 676 | 1 | 1,241 → 566 |

Post-repair validation against DATA: 0 status nulls; 0 PERMIT mismatches vs `Date Issued`; 0 Final FINAL mismatches vs repair candidate; 676 Final FINAL fills from task/inspection milestones; remaining FILE/PERMIT/FINAL gaps lack issuance or completion stamps in DATA.

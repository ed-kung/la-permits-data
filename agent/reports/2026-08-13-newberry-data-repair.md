# Newberry (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script (first-appearance order after Orange Park) was **Newberry**. DATA is a SmartGov portal payload (`Build Status` + nested `My Project` dates), same family as Redington Shores / Longwood. Upstream left STATUS_NORMALIZED null on 835/1,593 rows (mostly null Build Status with recoverable Submitted/Issued/Closed), mislabeled 98 Closed permits as Active, and omitted FINAL_DATE on Closed shells still tagged Active. Repair filled/fixed status from Build Status with Closed/Issued overrides and date inference; set FILE_DATE from Submitted, PERMIT_DATE from Issued (fallback Approved), FINAL_DATE from Closed. After repair: STATUS null 13/1,593 (empty shells); FILE_DATE 100% on non-empty; Active/Final PERMIT_DATE 1,152/1,153 (99.9%); Final FINAL_DATE 601/606 (99.2%); date-order violations 0.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` and walked `(JURISDICTION, STATE)` pairs in first-appearance order. Newberry was the first pair without `agent/scripts/fl/data_repair_fl_newberry.py` (Sewalls Point and Orange Park already had scripts; South Palm Beach and Orchid remain later).

## DATA shape

1,593 rows. All share the SmartGov shell; key-set variants add `ProjectDescription` and/or `Parcel Number`:

| Schema | n |
| --- | ---: |
| `smartgov_full` | 790 |
| `smartgov_no_desc` | 789 |
| `smartgov_empty` | 13 |
| `smartgov_minimal` | 1 |

Canonical sources:

| Field | DATA source |
| --- | --- |
| STATUS_NORMALIZED | `Build Status` (Expired*/Cancelled/Withdrawn → Inactive; Closed / Certificate of Completion\|Occupancy → Final; Active/Approved/Issued → Active; review-family → In Review) with Closed-date / Issued-date overrides; null Build Status → date inference |
| FILE_DATE | `My Project.Submitted` (fallback `Created`) |
| PERMIT_DATE | `My Project.Issued` (fallback `Approved`) |
| FINAL_DATE | `My Project.Closed` (fallback latest passed Building Final / COO inspection) |

## Field assessments

### STATUS_NORMALIZED

Before: 835 null; 360 Final; 277 Active; 118 In Review; 3 Inactive.

Root causes:

1. **Null scrape (801 rows):** `Build Status` and `STATUS_ORIGINAL` both null while `My Project` still carried Submitted / Issued / Closed → inferred Final (140), Active (343), or In Review (326); plus Expired* and other explicit statuses among the remaining nulls.
2. **Closed lag (98 Active + 4 In Review + 1 null):** Build Status `Closed` with a Closed date, but STATUS_ORIGINAL still `active`/`approved`/`routed for review` → Fixed to Final.
3. **Expired* mislabels:** left null or tagged In Review/Active → Inactive (26 Expired + Cancelled/Withdrawn).
4. **Certificate of Completion/Occupancy:** 4 COC + 2 COO → Final (were Active / In Review / mixed).
5. **Issued-but-In-Review:** Active/Approved Build Status (or Issued date) still labeled In Review → Fixed to Active.

After: Final 606, Active 547, In Review 398, Inactive 29, null 13 (empty shells). FILLED 822, FIXED 150.

### FILE_DATE

Before: 14 missing. Existing values already matched `Submitted` on 1,579/1,579 comparable rows (0 mismatches). Filled 1 from Submitted (`Active` commercial roof). After: 13 missing — all `smartgov_empty` shells with blank My Project.

### PERMIT_DATE

Before: 481 missing. When present, always equaled `Issued` (0 mismatches). Filled 54 after status repair (Issued present on In Review→Active/Final transitions and null-status Issued shells; Approved fallback where Issued blank). Active/Final still missing PERMIT_DATE: **1** — Final with Closed date but blank Issued and blank Approved. In Review correctly has 0 PERMIT_DATE.

### FINAL_DATE

Before: 1,096 missing; 497 present all matched Closed. Filled 104 (mostly Closed shells previously labeled Active). Final still missing FINAL_DATE: **5** — Certificate of Completion/Occupancy with blank Closed and no usable passed Building Final / COO inspection. Non-Final statuses keep FINAL_DATE null after repair.

## Repair performance

Script: `agent/scripts/fl/data_repair_fl_newberry.py` (`data_repair`).

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 822 | 150 | 835 → 13 |
| FILE_DATE | 1 | 0 | 14 → 13 |
| PERMIT_DATE | 54 | 0 | 481 → 427 |
| FINAL_DATE | 104 | 0 | 1,096 → 992 |

Post-repair coverage:

- STATUS_NORMALIZED null: 13/1,593 (0.8%) — empty shells only
- FILE_DATE overall: 1,580/1,593 (99.2%); 100% for Active / Final / In Review / Inactive
- Active/Final PERMIT_DATE: 1,152/1,153 (99.9%)
- Final FINAL_DATE: 601/606 (99.2%)
- Date order violations (FILE>PERMIT, PERMIT>FINAL, FILE>FINAL): 0

## Artifacts

- Script: `agent/scripts/fl/data_repair_fl_newberry.py`
- Repaired sample: `AGENT_DATA_PATH/repaired/permits_fl_newberry_repaired.parquet`

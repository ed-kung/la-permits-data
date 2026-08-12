# Sunrise (FL) data repair — STATUS_NORMALIZED and date fields

**Summary:** Among Florida sample jurisdictions missing a repair script, Sunrise was first. Its DATA is a uniform Tyler EnerGov payload. STATUS_NORMALIZED was wrong on 18 rows (stale Active labels vs Closed / To Be Issued / Withdrawn). FILE_DATE was already complete and correct. PERMIT_DATE matched IssueDate whenever present; only 1 missing Active/Final IssueDate could be filled, while ~750 Active/Final rows have no IssueDate in DATA. FINAL_DATE was the main gap: 205 fills (11 from FinalDate, 194 from Approved final inspections) plus 54 clears of non-Final void/close stamps, leaving FINAL_DATE on 98.6% of Final rows.

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_fl_sample.parquet`
- Jurisdiction: **Sunrise, FL** (1,999 rows) — first `(JURISDICTION, STATE)` pair without `agent/scripts/{state}/data_repair_{state}_{city}.py`
- Script: `agent/scripts/fl/data_repair_fl_sunrise.py` (`data_repair`)

## DATA schema

All records are EnerGov-shaped (`entity`, `details`, `contacts`, `processing_status`). Variants:

| INFERRED_SCHEMA prefix | n | Notes |
| --- | ---: | --- |
| `energov` | 1,760 | + `fees` |
| `energov_basic` | 198 | no fees |
| `energov_full` | 41 | + reviews/holds/attachments/more_info |

Content suffixes (`_issued_finaled`, `_issued`, `_finaled`, `_applied`, `_status_only`) reflect which of ApplyDate / IssueDate / FinalDate are populated. `processing_status` is often a list of inspections (Approved / Disapproved / …), used as a FINAL_DATE fallback.

Canonical mappings:

| Field | Source |
| --- | --- |
| STATUS_NORMALIZED | `entity.CaseStatus` (fallback `details.PermitStatus`) |
| FILE_DATE | `ApplyDate` |
| PERMIT_DATE | `IssueDate` |
| FINAL_DATE | `FinalDate` / `FinalizeDate`, else latest Approved final-ish inspection |

## Field assessments

### STATUS_NORMALIZED

No missing values. Most rows already matched CaseStatus. **18 FIXED:**

| Before → After | CaseStatus | n |
| --- | --- | ---: |
| Active → Final | Closed | 9 |
| Active → In Review | To Be Issued (Awaiting Payment) | 5 |
| Active → In Review | To Be Issued (Paid) | 3 |
| Active → Inactive | Withdrawn | 1 |

Cause: `STATUS_ORIGINAL` / upstream normalization lagged CaseStatus (e.g. original `issued` while DATA already says Closed or Withdrawn). After repair: Final 1,660; Inactive 167; Active 96; In Review 76.

### FILE_DATE

Ideal: populated for all records. **Already correct** — 0 missing; every FILE_DATE matches ApplyDate at day resolution. No FILLED/FIXED.

### PERMIT_DATE

Ideal: populated for Active and Final.

- When present, always equaled IssueDate (no incorrect values to overwrite).
- **1 FILLED** (Active with IssueDate but missing PERMIT_DATE).
- **2 FIXED** (cleared on rows remapped to In Review that carried a permit date).
- Remaining gap: **750 Active/Final** still missing PERMIT_DATE because IssueDate is null and `details.Issued` is false despite CaseStatus Issued/Closed/CO (common on legacy / shell permits). Not inventable from DATA.

Coverage after repair: Active 45/96 (46.9%); Final 961/1,660 (57.9%); In Review 0/76; Inactive 107/167.

### FINAL_DATE

Ideal: populated for Final; absent otherwise.

- Before: 220 Final rows missing FINAL_DATE; 54 non-Final rows had FINAL_DATE (Voided / Voided (Error) / Withdrawn / On Hold) equal to FinalDate void/close stamps.
- **205 FILLED** (11 from entity FinalDate after status fix or rare CO FinalDate; 194 from Approved final inspections when FinalDate null).
- **54 FIXED** (cleared non-Final FINAL_DATE).
- Remaining: **24 Final** rows, all Certificate of Occupancy, with neither FinalDate nor an Approved final inspection.

Coverage after repair: Final 1,636/1,660 (98.6%); Active / In Review / Inactive 0%.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 0 | 18 | 0 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 1 | 2 | 885 → 886 |
| FINAL_DATE | 205 | 54 | 514 → 363 |

Post-repair consistency checks (status vs CaseStatus map; FILE vs ApplyDate; PERMIT vs IssueDate / cleared on In Review; FINAL only on Final and equal to FinalDate or inspection date): **0 violations**.

## Artifacts

- Repair function: `agent/scripts/fl/data_repair_fl_sunrise.py`

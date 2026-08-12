# Pembroke Pines (FL) data repair — STATUS_NORMALIZED and date fields

**Summary:** Among Florida sample jurisdictions missing a repair script, Pembroke Pines was first. Its DATA is a uniform Tyler EnerGov payload. STATUS_NORMALIZED was wrong on 7 rows (stale Active vs Complete, or In Review vs Issued). FILE_DATE was already complete and correct. PERMIT_DATE matched IssueDate whenever present; 2 missing Active IssueDates were filled and 19 spurious In Review permit dates cleared. FINAL_DATE was the main gap: 714 fills (4 from FinalDate, 710 from Passed final inspections) plus 5 clears of non-Final stamps, leaving FINAL_DATE on 57.5% of Final rows (Legacy Sub Application stubs account for most of the remainder).

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_fl_sample.parquet`
- Jurisdiction: **Pembroke Pines, FL** (2,001 rows) — first `(JURISDICTION, STATE)` pair without `agent/scripts/{state}/data_repair_{state}_{city}.py`
- Script: `agent/scripts/fl/data_repair_fl_pembroke_pines.py` (`data_repair`)

## DATA schema

All records are EnerGov-shaped (`entity`, `details`, `contacts`, `fees`, `processing_status`). Variants:

| INFERRED_SCHEMA prefix | n | Notes |
| --- | ---: | --- |
| `energov` | 1,957 | + `fees` |
| `energov_full` | 44 | + reviews/holds/attachments/more_info |

Content suffixes (`_issued_finaled`, `_issued`, `_finaled`, `_applied`, `_status_only`) reflect which of ApplyDate / IssueDate / FinalDate are populated. `processing_status` is a list of inspections with result strings such as `Passed.` / `Partial Pass` / `Failed: …` / `Canceled.` — used as a FINAL_DATE fallback when `FinalDate` is null.

Canonical mappings:

| Field | Source |
| --- | --- |
| STATUS_NORMALIZED | `entity.CaseStatus` (fallback `details.PermitStatus`) |
| FILE_DATE | `ApplyDate` |
| PERMIT_DATE | `IssueDate` |
| FINAL_DATE | `FinalDate` / `FinalizeDate`, else latest Passed final-ish inspection |

CaseStatus → STATUS_NORMALIZED: Complete / Legacy Sub Application → Final; Issued → Active; Void / Expired / Denied → Inactive; In Review / Submitted / Submitted - Online / Applied / Fees Paid / Fees Due → In Review.

## Field assessments

### STATUS_NORMALIZED

No missing values. Most rows already matched CaseStatus. **7 FIXED:**

| Before → After | CaseStatus | n |
| --- | --- | ---: |
| Active → Final | Complete | 4 |
| In Review → Active | Issued | 3 |

Cause: `STATUS_ORIGINAL` / upstream normalization lagged CaseStatus (e.g. original `issued` while DATA already says Complete; or `submitted - online` / `stop work order` while CaseStatus is Issued). After repair: Final 1,695; In Review 148; Inactive 88; Active 70.

### FILE_DATE

Ideal: populated for all records. **Already correct** — 0 missing; every FILE_DATE matches ApplyDate at day resolution. No FILLED/FIXED.

### PERMIT_DATE

Ideal: populated for Active and Final.

- When present, always equaled IssueDate (no incorrect values to overwrite).
- **2 FILLED** (Issued rows mislabeled In Review that had IssueDate but missing PERMIT_DATE; status remapped to Active).
- **19 FIXED** (cleared PERMIT_DATE on In Review rows that still carried an issue stamp — Fees Due / In Review / Submitted* etc.).
- Remaining gap: **828 Final** still missing PERMIT_DATE — 671 Legacy Sub Application (no IssueDate in DATA) plus ~157 Complete without IssueDate. Not inventable from DATA.

Coverage after repair: Active 70/70 (100%); Final 867/1,695 (51.2%); In Review 0/148; Inactive 34/88.

### FINAL_DATE

Ideal: populated for Final; absent otherwise.

- Before: 1,431 Final rows missing FINAL_DATE; 5 non-Final rows had FINAL_DATE equal to FinalDate (Issued / Fees Due / In Review / Void).
- **714 FILLED** (4 from entity FinalDate after Complete→Final status fix; 710 from Passed final-ish inspections when FinalDate null). Prefer FinalDate over inspections when both exist — FinalDate is often the administrative close day after the last Passed final inspection.
- **5 FIXED** (cleared non-Final FINAL_DATE).
- Remaining: **721 Final** rows — 670 Legacy Sub Application (empty processing_status, no FinalDate) and 51 Complete with neither FinalDate nor a Passed final inspection (empty or non-final inspections only).

Coverage after repair: Final 974/1,695 (57.5%); Active / In Review / Inactive 0%.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 0 | 7 | 0 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 2 | 19 | 1,013 → 1,030 |
| FINAL_DATE | 714 | 5 | 1,736 → 1,027 |

Post-repair consistency checks (status vs CaseStatus map; FILE vs ApplyDate; PERMIT vs IssueDate / cleared on In Review; FINAL only on Final and equal to FinalDate or Passed inspection date): **0 violations**.

## Artifacts

- Repair function: `agent/scripts/fl/data_repair_fl_pembroke_pines.py`

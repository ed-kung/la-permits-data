# Ponce Inlet (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script (in parquet appearance order) was **Ponce Inlet**. DATA is a uniform Tyler EnerGov payload (`entity` / `details` / `fees` / `processing_status` / `holds`). Upstream left 48 `No Longer Renting` statuses null and incorrectly mapped 60 rental `Sold` rows to Final. Repair filled/fixed all statuses (including 2 Issued→Complete entity lags → Final), cleared 3 spurious In Review `PERMIT_DATE` values and 187 non-Final `FINAL_DATE` stamps, and filled 2 Final dates from `FinalizeDate`. `FILE_DATE` already matched `ApplyDate` on every row. After repair: STATUS 100%; FILE_DATE 100%; Active/Final PERMIT_DATE 1,507/1,519 (99.2%); Final FINAL_DATE 1,377/1,377 (100%).

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` and walked `(JURISDICTION, STATE)` pairs in file order. Ponce Inlet was the first pair without `agent/scripts/fl/data_repair_fl_ponce_inlet.py`.

## DATA shape

| Schema | n |
| --- | ---: |
| `energov_full_issued_finaled` | 1,546 |
| `energov_full_issued` | 329 |
| `energov_full_applied` | 92 |
| `energov_full_finaled` | 33 |

All 2,000 rows share the same top-level key set. `reviews` is always empty; `processing_status` is non-null on 1,528 rows; `holds` on 560.

Canonical sources:

| Field | DATA source |
| --- | --- |
| STATUS_NORMALIZED | `entity.CaseStatus` (fallback `details.PermitStatus`); Issued + Complete/Final + final date → Final |
| FILE_DATE | `entity.ApplyDate` (fallback `details.ApplyDate`) |
| PERMIT_DATE | `entity.IssueDate` (fallback `details.IssueDate`) for Active/Final/Inactive |
| FINAL_DATE | `entity.FinalDate` / `details.FinalizeDate`; else passed FINAL-ish `processing_status` inspection |

## Field assessments

### STATUS_NORMALIZED

Before: Final 1,435; Inactive 306; Active 144; In Review 67; null 48.

After: Final 1,377; Inactive 414; Active 142; In Review 67; **0 null**.

| Issue | n | Cause |
| --- | ---: | --- |
| null → Inactive | 48 | `No Longer Renting` rental licenses never mapped |
| Final → Inactive | 60 | `Sold` rental licenses incorrectly treated as Final |
| Active → Final | 2 | `CaseStatus=Issued` while `PermitStatus=Complete` + `FinalizeDate` (entity lag) |

Flags: **48 FILLED, 62 FIXED**.

Already-correct mappings left unchanged: Complete→Final, Issued→Active, In Review/Submitted→In Review, Expired/Void/Denied→Inactive.

### FILE_DATE

Missing on 0/2,000 before and after. Every row matches `entity.ApplyDate` at UTC calendar-day resolution. Flags: **0 FILLED, 0 FIXED**.

Note: 20 rental renewals have FILE_DATE > PERMIT_DATE because `ApplyDate` is after a license-period `IssueDate` (often Oct 1). Source chronology retained.

### PERMIT_DATE

Missing before: 127. After: 130 (net +3 from clearing In Review stamps).

- **FILLED 0:** Every Active/Final/Inactive row with a parseable `IssueDate` already matched `PERMIT_DATE` (1,873/1,873 calendar-day matches). The two upgraded Issued→Final rows already carried issuance stamps.
- **FIXED 3:** Cleared issuance stamps on In Review rows (`CaseStatus` In Review with `IssueDate` / Issued=True portal lag).

Active/Final coverage after repair: **1,507 / 1,519 (99.2%)**. Remaining 12 gaps are `Complete` administrative shells (`Issued=False`, blank `IssueDate`) — mostly Other / Tree Removal / Milestone Inspection / Special Events.

### FINAL_DATE

Missing before: 438. After: 623 (net clears of non-Final stamps outweigh 2 fills).

- **FILLED 2:** Issued→Complete entity-lag upgrades, from `details.FinalizeDate`.
- **FIXED 187:** Cleared FINAL stamps on rows that are not Final after repair — Sold→Inactive (60), No Longer Renting (48), Void (61), Active Issued with prior-cycle FinalDate (15), Expired (2), In Review (1).

Final coverage after repair: **1,377 / 1,377 (100%)**. Two Final rows retain PERMIT_DATE > FINAL_DATE from source chronology (rental / tree-removal shells); left as-is.

Issued rentals that still show `PermitStatus=Issued` but carry a prior-cycle `FinalDate` stay Active; their FINAL stamps are cleared rather than promoting status.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 48 | 62 | 48 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 0 | 3 | 127 → 130 |
| FINAL_DATE | 2 | 187 | 438 → 623 |

## Artifacts

- Repair script: `agent/scripts/fl/data_repair_fl_ponce_inlet.py`
- Repaired sample: `$AGENT_DATA_PATH/repaired/permits_fl_ponce_inlet_repaired.parquet`

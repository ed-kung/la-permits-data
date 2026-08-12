# West Palm Beach (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script (after Coral Springs in list order) was **West Palm Beach**. DATA mixes Tyler EnerGov JSON (`entity` / `details` / `processing_status`) with a smaller legacy `permit_info` portal. STATUS_NORMALIZED was filled on 8 unmapped review statuses and fixed on 15 rows where portal status lagged (`Open`+issued→Active; `Issued`/`Complete` with FinalDate→Active/Final). FILE_DATE was already complete and correct. PERMIT_DATE gained 6 fills from `IssueDate` on rows whose upstream status still said In Review. FINAL_DATE gained 1,195 fills, mostly from passed final inspections.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` and walked unique `(JURISDICTION, STATE)` pairs in file order. Existing FL repair scripts covered Jacksonville through Coral Springs. **West Palm Beach** was the first without `agent/scripts/fl/data_repair_fl_west_palm_beach.py`.

Sample size: **2,004** records.

## DATA schemas

Two portal families, further split by which dates are populated:

| INFERRED_SCHEMA           | Count |
| ------------------------- | ----: |
| `energov_issued`          | 1,264 |
| `legacy_issued`           |   279 |
| `energov_applied`         |   230 |
| `energov_issued_finaled`  |   171 |
| `legacy_applied`          |    33 |
| `legacy_issued_finaled`   |    19 |
| `energov_finaled`         |     8 |

Canonical source fields:

| Target field      | DATA source                                                                 |
| ----------------- | --------------------------------------------------------------------------- |
| STATUS_NORMALIZED | EnerGov `CaseStatus` / legacy `permit_info.Status`; FinalDate / C.O. Issued → Final; Open+Issued → Active |
| FILE_DATE         | `ApplyDate` / `Application Date`                                            |
| PERMIT_DATE       | `IssueDate` / `Issued Date`                                                 |
| FINAL_DATE        | `FinalDate` / `C.O. Issued`, else latest passed final-ish inspection, else latest passed inspection |

## Field assessments

### STATUS_NORMALIZED

Before: Final 1,591 · Inactive 275 · In Review 78 · Active 52 · missing 8.

- Most `STATUS_ORIGINAL` mappings were already correct (`complete`/`closed`→Final; `issued`/`approved`→Active; review-like→In Review; expired/void/canceled/revoked→Inactive).
- **8** missing rows had CaseStatus in {Requires Resubmit for Prescreen, Requires Resubmit for ROW Permits, Plan Rev Fees Pd} with no prior normalize mapping → **FILLED** as In Review.
- **7** legacy `Open` rows with a non-null Issued Date were labeled In Review → **FIXED** to Active (open issued permits).
- **6** rows had stale `STATUS_ORIGINAL` in {requires resubmit, in review, submitted - online} while EnerGov `CaseStatus=Issued` (and IssueDate set) → **FIXED** to Active.
- **2** rows had `STATUS_ORIGINAL=issued` / Active while DATA showed `CaseStatus=Complete` plus `FinalDate` → **FIXED** to Final.

After: Final 1,593 · Inactive 275 · In Review 73 · Active 63 · missing 0.  
Flags: **FILLED 8 · FIXED 15**.

### FILE_DATE

Before: 0 missing. Ideal: populated for all records.

- Upstream FILE_DATE matched ApplyDate / Application Date on every row (**0** day mismatches, **0** fills/fixes).
- Coverage remains **100%** for all statuses.

After: 0 missing.  
Flags: **FILLED 0 · FIXED 0**.

### PERMIT_DATE

Before: 277 missing (86 of Active/Final). Ideal: populated for Active and Final.

- When present, PERMIT_DATE already matched IssueDate / Issued Date (**0** mismatches).
- **6** rows with IssueDate but null PERMIT_DATE (the same stale In Review→Active cases) → **FILLED**.
- **86** Active/Final rows still lack IssueDate / Issued Date (mostly `complete` shells with `Issued=False`) → not repairable from DATA.
- 8 rows have IssueDate on a calendar day before ApplyDate (agency chronology quirks, often ROW / reissue); left as-is since IssueDate is the correct PERMIT_DATE source.

After: 271 missing. Coverage: Active **98.4%**; Final **94.7%**.  
Flags: **FILLED 6 · FIXED 0**.

### FINAL_DATE

Before: 1,808 missing (1,395 of Final); 0 non-Final rows carried FINAL_DATE. Ideal: populated for Final.

- When present, FINAL_DATE already matched EnerGov FinalDate (**0** mismatches); legacy C.O. Issued was unused upstream on missing Finals.
- Status repair moved 2 Active+finaled rows into Final; FINAL_DATE on those was then **FILLED** from FinalDate (upstream had left FINAL_DATE null despite FinalDate).
- Among Final rows still missing FINAL_DATE, filled from inspections: **1,141** from passed final-ish types, **52** from latest other passed inspection (guarded so inspection date does not predate IssueDate).
- **202** Final rows remain without FINAL_DATE (empty / non-passing inspection history and blank FinalDate / C.O. Issued).

After: 613 missing. Coverage: Final **87.3%**; Active/In Review/Inactive **0%**.  
Flags: **FILLED 1,195 · FIXED 0**  
Fill sources: energov final insp 931 · legacy final insp 210 · energov any-pass 37 · legacy any-pass 15 · FinalDate stamp 2.

## Repair script

`agent/scripts/fl/data_repair_fl_west_palm_beach.py` — function `data_repair(df)`.

Adds columns: `INFERRED_SCHEMA`, `STATUS_NORMALIZED_FLAG`, `FILE_DATE_FLAG`, `PERMIT_DATE_FLAG`, `FINAL_DATE_FLAG`.

### Artifact

`AGENT_DATA_PATH/west_palm_beach_repaired_sample.parquet` (repaired sample preview from CLI).

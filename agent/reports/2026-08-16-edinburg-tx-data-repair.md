# Edinburg (TX) data repair

**Summary:** Edinburg was the first TX jurisdiction in `permits_tx_sample.parquet` without a repair script (2,001 rows). DATA is a CivicPlus/EnerGov payload (`entity_core` / `entity_rich`). STATUS_NORMALIZED had no nulls but 17 stale mappings vs `entity.CaseStatus` (STATUS_ORIGINAL lagged). FILE_DATE was already complete and matched `ApplyDate`. PERMIT_DATE gained 2 fills from `IssueDate` and cleared 4 SQL `1753-01-01` sentinels. FINAL_DATE filled 5 Complete rows that had `FinalDate` but no FINAL_DATE, and cleared 58 spurious values on Issued/Void rows. After repair, Final FINAL_DATE coverage is 100%; Active/Final PERMIT_DATE coverage is 97.2% / 95.8%.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_tx_sample.parquet` and walked unique `(JURISDICTION, STATE)` pairs in appearance order. Existing TX scripts covered through Arlington; **Edinburg** was the first missing pair → `agent/scripts/tx/data_repair_tx_edinburg.py`.

## DATA schema

All 2,001 rows parse. Two top-level key-set variants (same repair fields):

| Schema | n | Top-level keys |
| --- | ---: | --- |
| `entity_core` | 1,912 | contacts, details, entity, fees, processing_status |
| `entity_rich` | 89 | core + attachments, holds, more_info, reviews |

Canonical sources:

- `entity.CaseStatus` → STATUS_NORMALIZED
- `entity.ApplyDate` → FILE_DATE
- `entity.IssueDate` (years outside 1900–2035 rejected) → PERMIT_DATE
- `entity.FinalDate` / `details.FinalizeDate` → FINAL_DATE (Final only)

`details.FinalizeDate` matches `entity.FinalDate` on all 489 rows where either is set. `processing_status` is null on every sample row (no inspection fallback).

## Field assessment

### STATUS_NORMALIZED

Before: Inactive 1,265 / Final 426 / Active 221 / In Review 89 / missing 0.

`entity.CaseStatus` categories: Expired (1,245), Complete (431), Issued (205), Submitted (32), In Review (30), Submitted - Online (20), Void (13), Expired - No Activity (11), Approved (6), Plan Approval Expired (3), Stop Work Order (3), Incomplete Submission (2).

Issues (17 FIXED; all STATUS_ORIGINAL lag vs portal CaseStatus):

1. **Complete still `issued` → Active (5):** should be Final; all five already had `FinalDate` in DATA.
2. **Expired / Expired - No Activity still `issued` → Active (4 + 3):** should be Inactive.
3. **Issued still `in review` (2):** should be Active; both have `IssueDate` and were missing PERMIT_DATE.
4. **Stop Work Order coded In Review (3):** remapped to Inactive.

Repair map (CaseStatus → normalized): Complete → Final; Issued / Approved → Active; In Review / Submitted / Submitted - Online / Incomplete Submission → In Review; Expired / Expired - No Activity / Void / Plan Approval Expired / Stop Work Order → Inactive.

After repair: Inactive 1,275 / Final 431 / Active 211 / In Review 84 / missing 0.

### FILE_DATE

Already 2,001 / 2,001 populated; all match `entity.ApplyDate` at UTC calendar-day resolution. No FILLED/FIXED changes.

### PERMIT_DATE

When both present and IssueDate is a real year, PERMIT_DATE always matched IssueDate (1,848 / 1,848). Four rows carried the SQL sentinel `1753-01-01` in both IssueDate and PERMIT_DATE (Expired/Void legacy shells) → FIXED (cleared).

Two Issued rows still labeled In Review had IssueDate but missing PERMIT_DATE → FILLED after status repair.

Remaining Active/Final gaps have null IssueDate in DATA:
- 6 Approved (Active, never issued)
- 18 Complete Certificate of Occupancy / similar shells (Final) with FinalDate but no IssueDate

After repair by status: Active 205/211 (97.2%); Final 413/431 (95.8%); Inactive 1,227/1,275 (96.2%); In Review 1/84 (1.2%).

### FINAL_DATE

All 426 already-Final rows had FINAL_DATE matching FinalDate/FinalizeDate. Five Complete rows wrongly labeled Active had FinalDate in DATA but null FINAL_DATE → FILLED after status → Final.

58 non-Final rows carried spurious FINAL_DATE → cleared (FIXED):
- 52 Issued Active (FinalDate/FinalizeDate present while CaseStatus still Issued; only 1/52 equals ExpireDate, so these are not simple expire-stamps, but CaseStatus remains Issued so FINAL_DATE is cleared)
- 6 Void Inactive

After repair: Final 431/431 (100%); other statuses 0%.

## Repair performance

Script: `agent/scripts/tx/data_repair_tx_edinburg.py`  
Artifact: `AGENT_DATA_PATH/repaired/permits_tx_edinburg_repaired.parquet`

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 0 | 17 | 0 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 2 | 4 | 153 → 155 |
| FINAL_DATE | 5 | 58 | 1,517 → 1,570 |

(Missing PERMIT_DATE / FINAL_DATE rise slightly because clearing sentinels and spurious non-Final dates outweighs the fills.)

After repair by STATUS_NORMALIZED:

| Status | n | FILE_DATE | PERMIT_DATE | FINAL_DATE |
| --- | ---: | ---: | ---: | ---: |
| Active | 211 | 100% | 205 / 211 (97.2%) | 0 / 211 |
| Final | 431 | 100% | 413 / 431 (95.8%) | 431 / 431 (100%) |
| In Review | 84 | 100% | 1 / 84 (1.2%) | 0 / 84 |
| Inactive | 1,275 | 100% | 1,227 / 1,275 (96.2%) | 0 / 1,275 |

## Remaining gaps

- **PERMIT_DATE:** 6 Approved Active rows and 18 Complete Final rows have null `IssueDate` in DATA (not fillable).
- **FINAL_DATE:** none remaining on Final rows. Issued rows with FinalDate are intentionally left Active without FINAL_DATE because CaseStatus is still Issued.

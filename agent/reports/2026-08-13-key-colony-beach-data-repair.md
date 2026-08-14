# Key Colony Beach (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script was **Key Colony Beach**. DATA is a CitizenServe-style portal payload (`Status:`, `Permit Details`, `Reviews`, `Inspections`). Upstream `FILE_DATE` often stored latest Review Completion instead of Application Intake / earliest Review Start; repair fixes 1,175 of those and fills 61 gaps. `FINAL_DATE` was missing on every row and is filled from passed Final* inspections for Closed / upgraded-Final rows. Stale statuses are corrected (96 In Review→Active when Issue Date present; 28 Active→Final when `FINAL BUILDING` passed). After repair: STATUS 1 null remains (empty shell); FILE_DATE 89.3%; Active/Final PERMIT_DATE 1,441/1,592 (90.5%); Final FINAL_DATE 473/794 (59.6%).

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` and walked `(JURISDICTION, STATE)` pairs in sorted order. Key Colony Beach was the first pair without `agent/scripts/fl/data_repair_fl_key_colony_beach.py`.

## DATA shape

All 1,807 rows share the same portal shell. Form extras vary; inferred schema prefixes:

| Schema prefix | Role |
| --- | --- |
| `portal_res` | Residential form extras (rental / owner questions) |
| `portal_pp` | Private-provider extras |
| `portal_owner` | Property-owner contact extras |
| `portal_core` | Minimal colon-key shell |

Suffixes (`_issued_finaled`, `_issued`, `_finaled`, `_applied`, `_status_only`) mark which canonical dates are recoverable.

Canonical sources:

| Field | DATA source |
| --- | --- |
| STATUS_NORMALIZED | `Status:`; Issued/Approved → Final when `FINAL BUILDING` passed; In Review → Active when Issue Date present |
| FILE_DATE | Application Intake Start/Completion ≤ Issue; else earliest Review Start/Completion ≤ Issue |
| PERMIT_DATE | `Permit Details["Issue Date:"]` (top-level `Issue Date` null/polluted) |
| FINAL_DATE | Latest passed Final* / CO inspection |

## Field assessments

### STATUS_NORMALIZED

Before: Final 766; Active 730; In Review 226; Inactive 84; null 1.

| Issue | n | Repair |
| --- | ---: | --- |
| Online Application Received (etc.) with Issue Date still In Review | 96 | FIXED → Active |
| Issued/Approved with passed `FINAL BUILDING` still Active | 28 | FIXED → Final |
| Blank `Status:` shell, empty Reviews/Inspections/Issue | 1 | not repairable (stays null) |

Other mapped statuses already matched (`Closed`→Final, `Issued`/`Approved`→Active, `Under Review`/`Payment Required`/`Resubmittal Required`/`Online Application Received`→In Review, `Canceled`/`Denied`→Inactive). Five rows had lagged `STATUS_ORIGINAL` vs current `Status:`, but `STATUS_NORMALIZED` already matched the current portal status for those In Review variants.

Flags: **0 FILLED, 124 FIXED**; 1 null after repair.

After: Active 798; Final 794; In Review 130; Inactive 84; null 1.

### FILE_DATE

Missing on 245/1,807 before. When present, calendar day often matched latest Review Completion (964/1,562), not Application Intake / earliest Review Start (only 388 matched earliest Start).

| Repair action | n |
| --- | ---: |
| FIXED to Application Intake / earliest Review Start/Completion (≤ Issue) | 1,166 |
| Cleared post-issue FILE with no application source | 9 |
| FILLED from Reviews | 61 |
| Still missing (empty / undated Reviews) | 193 |

After: **1,614/1,807 (89.3%)** populated; 0 `FILE_DATE > PERMIT_DATE` inversions.

### PERMIT_DATE

Missing on 344/1,807 before. Every populated `PERMIT_DATE` already matched `Permit Details["Issue Date:"]` (top-level `Issue Date` is null except one polluted work-description string).

Repairs:

- **2** Active/Final shells → FILLED from `Permit Details["Issue Date:"]`

Still missing after repair: 342 rows — remaining In Review (correctly blank), plus 150 Closed and 1 Approved with blank Issue Date in DATA, and Inactive without Issue Date. Active/Final coverage: **1,441/1,592 (90.5%)**. Flags: **2 FILLED, 0 FIXED**.

### FINAL_DATE

Missing on 1,807/1,807 before.

| Repair action | n |
| --- | ---: |
| FILLED from passed Final* inspections (Closed + upgraded Final) | 473 |

Final rows still missing FINAL_DATE (321): Closed shells with empty Inspections or only non-final types (rough-in, framing, canceled finals, etc.). Ideal Final coverage: **473/794 (59.6%)**. Non-Final rows keep FINAL_DATE cleared. Two rare `PERMIT_DATE > FINAL_DATE` cases remain where Issue Date is later than the latest passed Final* stamp.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 0 | 124 | 1 → 1 |
| FILE_DATE | 61 | 1,175 | 245 → 193 |
| PERMIT_DATE | 2 | 0 | 344 → 342 |
| FINAL_DATE | 473 | 0 | 1,807 → 1,334 |

## Artifacts

- Repair script: `agent/scripts/fl/data_repair_fl_key_colony_beach.py` (`data_repair`)
- Repaired sample parquet: `$AGENT_DATA_PATH/repaired/permits_fl_key_colony_beach_repaired.parquet`

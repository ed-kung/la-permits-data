# Putnam County (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script was **Putnam County**. DATA is a CitizenServe-style portal payload (`Status:`, `Permit Details`, `Reviews`, `Inspections`). Upstream `FILE_DATE` often stored Final Review Completion or a later resubmittal cycle instead of earliest Review Start; repair fixes 1,086 of those and fills 9 gaps. `FINAL_DATE` was missing on every row and is filled from passed `Admin. Final` / `Inspector Final` / other Final* inspections. `Revise and Resubmit` null statuses are filled; Issued rows with a primary final inspection are upgraded to Final. After repair: STATUS fully populated; FILE_DATE 71.2%; Active/Final PERMIT_DATE 1,926/1,929 (99.8%); Final FINAL_DATE 1,291/1,437 (89.8%).

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` and walked `(JURISDICTION, STATE)` pairs in first-appearance order. Putnam County was the first pair without `agent/scripts/fl/data_repair_fl_putnam_county.py`.

## DATA shape

All 2,000 rows share the same portal shell. Form extras vary; inferred schema prefixes:

| Schema prefix | Approx. role |
| --- | --- |
| `portal_building` | Residential / commercial project-type forms |
| `portal_roof` | Re-roof / product-approval extras |
| `portal_utility` | Utility clearance extras |
| `portal_planning` | Rezoning / variance / FLUM extras |
| `portal_core` / `portal_form` | Minimal or other form shells |

Suffixes (`_issued_finaled`, `_issued`, `_finaled`, `_applied`, `_status_only`) mark which canonical dates are recoverable.

Canonical sources:

| Field | DATA source |
| --- | --- |
| STATUS_NORMALIZED | `Status:`; Issued → Final when Admin./Inspector Final passed; In Review → Active when Issue Date present |
| FILE_DATE | Earliest Review Start ≤ Issue Date; else earliest Review Completion ≤ Issue |
| PERMIT_DATE | `Permit Details["Issue Date:"]` (top-level `Issue Date` always null) |
| FINAL_DATE | Latest passed Admin. Final; else Inspector Final; else other Final* / CO / Close Out / finished elevation certificate |

## Field assessments

### STATUS_NORMALIZED

Before: Final 1,248; Active 678; In Review 52; null 12; Inactive 10.

| Issue | n | Repair |
| --- | ---: | --- |
| Null on Revise and Resubmit | 12 | FILLED → In Review |
| Issued with passed Admin./Inspector Final still Active | 189 | FIXED → Final |
| In Review / Open / Online Application Received with Issue Date | 3 | FIXED → Active |

Flags: **12 FILLED, 192 FIXED**; 0 null after repair.

After: Final 1,437; Active 492; In Review 61; Inactive 10.

### FILE_DATE

Missing on 585/2,000 before. When present, calendar day often matched Final Review Completion or a later Initial Review cycle (1,085 mismatches vs earliest Review Start), not the application/submittal date.

| Repair action | n |
| --- | ---: |
| FIXED to earliest Review Start/Completion (≤ Issue) | 1,086 |
| FILLED from Reviews | 9 |
| Cleared post-issue FILE with no application source | 1 |
| Still missing (empty / undated Reviews) | 577 |

After: **1,423/2,000 (71.2%)** populated; 0 `FILE_DATE > PERMIT_DATE` inversions.

### PERMIT_DATE

Missing on 67/2,000 before. Every populated `PERMIT_DATE` already matched `Permit Details["Issue Date:"]` (top-level `Issue Date` is always null). No value corrections needed.

Still missing after repair: 67 rows — mostly In Review / pre-issue statuses (correctly blank), plus 3 Closed shells with blank Issue Date and 3 Denied/Cancelled without Issue Date. Active/Final coverage: **1,926/1,929 (99.8%)**. Flags: **0 FILLED, 0 FIXED**.

### FINAL_DATE

Missing on 2,000/2,000 before.

| Repair action | n |
| --- | ---: |
| FILLED from passed final-ish inspections | 1,291 |

Final rows still missing FINAL_DATE (146): 64 with empty Inspections; 81 with only non-final types (Expired Permit, Courtesy Letter, Rope Off, NOC, etc.). Mid-construction `Elevation Certificate (FEMA)` is excluded so it does not create `PERMIT_DATE > FINAL_DATE` inversions. Ideal Final coverage: **1,291/1,437 (89.8%)**. Non-Final rows keep FINAL_DATE cleared.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 12 | 192 | 12 → 0 |
| FILE_DATE | 9 | 1,086 | 585 → 577 |
| PERMIT_DATE | 0 | 0 | 67 → 67 |
| FINAL_DATE | 1,291 | 0 | 2,000 → 709 |

## Artifacts

- Repair script: `agent/scripts/fl/data_repair_fl_putnam_county.py` (`data_repair`)
- Repaired sample parquet: `$AGENT_DATA_PATH/putnam_county_fl_repaired_sample.parquet`

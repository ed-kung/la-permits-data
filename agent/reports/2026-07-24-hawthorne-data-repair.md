# Hawthorne CA data repair

**Summary:** Hawthorne’s 1,899 sample records are Tyler EnerGov payloads (`entity` / `details` / `fees`, with an optional reviews bundle). Upstream dates already match `entity` when present: `FILE_DATE` is complete, Active/Final already have `PERMIT_DATE` and Final rows already have `FINAL_DATE`. The only material defects are (1) one stale `STATUS_ORIGINAL='submitted - online'` row whose `entity.CaseStatus` is Issued → remapped to Active and `PERMIT_DATE` filled from `IssueDate`; (2) 19 non-Final rows with spurious `FINAL_DATE` copied from `entity.FinalDate` → cleared. Script: `agent/scripts/data_repair_ca_hawthorne.py`.

## Data & schema

| Item | Value |
| --- | --- |
| Source | `MY_DATA_PATH/processed_data/permits_la_sample.parquet` |
| Filter | `JURISDICTION == "Hawthorne"`, `STATE == "CA"` |
| N | 1,899 |
| First jurisdiction without an existing `data_repair_{state}_{city}.py` | Hawthorne, CA (after Alhambra … Glendora) |

| INFERRED_SCHEMA | n |
| --- | --- |
| `entity_fees` | 1,615 |
| `entity_fees_reviews` | 284 |

Canonical fields under `entity` (details used as fallback):

| Target field | DATA source |
| --- | --- |
| `STATUS_NORMALIZED` | `entity.CaseStatus` (fallback `details.PermitStatus`) |
| `FILE_DATE` | `entity.ApplyDate` |
| `PERMIT_DATE` | `entity.IssueDate` |
| `FINAL_DATE` | `entity.FinalDate` (fallback `details.FinalizeDate`, Final status only) |

`ExpireDate` is a validity window, not a completion date. `details.PermitStatus=Complete` with `FinalizeDate` but `CaseStatus` not Complete (41 rows: In Review×17, Issued×16, Plan Approval Expired×8) is treated as a stale details label — `CaseStatus` is authoritative and those `FinalizeDate` values are not used as finaling dates.

Status map: Complete → Final; Issued → Active; Expired / Plan Approval Expired / Void / Denied → Inactive; In Review / Fees Due / Fees Paid / Submitted / Submitted - Online / Stop Work Order → In Review.

## Field assessment

### STATUS_NORMALIZED — 0 missing; 1 incorrect

Upstream mapped `STATUS_ORIGINAL` (lowercased portal label) → normalized status. That label agrees with `entity.CaseStatus` on all but one row:

| CaseStatus | Was | Should be | n | Flag |
| --- | --- | --- | --- | --- |
| Issued | In Review (`STATUS_ORIGINAL` = submitted - online) | Active | 1 | FIXED |

All other CaseStatus values already map to the correct `STATUS_NORMALIZED`. After repair: In Review 848, Inactive 379, Final 366, Active 306 (**0 missing**).

### FILE_DATE — complete and correct

- Ideal: application / submittal date for all records.
- 1,899 / 1,899 match the UTC calendar day of `entity.ApplyDate` (0 mismatches, 0 missing).
- No FILLED / FIXED.

### PERMIT_DATE — correct when present; 1 fillable after status fix

- Ideal: populated for Active and Final.
- Where both `PERMIT_DATE` and `IssueDate` exist, UTC day always matches (0 mismatches).
- Pre-repair Active 305/305 and Final 366/366 already complete.
- The one Issued→Active remap had `IssueDate=2024-11-22` and null `PERMIT_DATE` → **FILLED 1**.

After repair: Active 306/306 (100%), Final 366/366 (100%). Remaining missing dates are on In Review / Inactive rows (optional).

### FINAL_DATE — all Final rows correct; 19 spurious on non-Final

- Ideal: populated for Final.
- All 366 CaseStatus=Complete rows have `FINAL_DATE` equal to `entity.FinalDate` (= `details.FinalizeDate` when both present).
- 19 non-Final rows carried `FINAL_DATE` from `entity.FinalDate` (Plan Approval Expired×14, Issued×2, In Review×2, Void×1). Cleared as FIXED — same convention as Glendale.

After repair: Final 366/366 (100%); Active / In Review / Inactive have none.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | --- | --- | --- |
| `STATUS_NORMALIZED` | 0 | 1 | 0 → 0 |
| `FILE_DATE` | 0 | 0 | 0 → 0 |
| `PERMIT_DATE` | 1 | 0 | 861 → 860 |
| `FINAL_DATE` | 0 | 19 | 1,514 → 1,533 |

Missing `FINAL_DATE` rises because 19 non-Final spurious values are cleared; among Final rows coverage remains 366 / 366 (100%).

| STATUS_NORMALIZED | Before | After |
| --- | --- | --- |
| In Review | 849 | 848 |
| Inactive | 379 | 379 |
| Final | 366 | 366 |
| Active | 305 | 306 |

Post-repair date coverage by status:

| Status | PERMIT_DATE | FINAL_DATE |
| --- | --- | --- |
| Active | 306 / 306 (100%) | 0 / 306 |
| Final | 366 / 366 (100%) | 366 / 366 (100%) |
| In Review | 100 / 848 (11.8%) | 0 / 848 |
| Inactive | 267 / 379 (70.4%) | 0 / 379 |

## Artifacts

- Script: `agent/scripts/data_repair_ca_hawthorne.py` (`data_repair`)
- Report: `agent/reports/2026-07-24-hawthorne-data-repair.md`
- No derived datasets written under `AGENT_DATA_PATH`

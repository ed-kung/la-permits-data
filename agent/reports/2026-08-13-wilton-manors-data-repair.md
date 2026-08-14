# Wilton Manors (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script was **Wilton Manors**. DATA is a CitizenServe-style portal payload (`Status:`, `Permit Details`, `Reviews`, `Inspections`). `STATUS_NORMALIZED` already matched portal `Status:` on every row. Upstream `FILE_DATE` usually stored the latest Review Completion instead of the earliest Review Start; repair rewrites 851 of those, fills 3 gaps, and clears 4 post-issue values. `PERMIT_DATE` incorrectly used the legacy placeholder Issue Date `01/01/2000` on 437 rows (cleared) and was missing on one Issued row with a real Issue Date (filled). `FINAL_DATE` was missing on every row; filled from latest Approved/Passed inspection for Final rows (portal has no Final*/CO inspection types). After repair: STATUS 0 null; FILE_DATE 48.3%; Active/Final PERMIT_DATE 1,381/1,819 (75.9%); Final FINAL_DATE 677/1,426 (47.5%).

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` and walked `(JURISDICTION, STATE)` pairs in file order. Wilton Manors was the first pair without `agent/scripts/fl/data_repair_fl_wilton_manors.py`.

## DATA shape

All 2,000 rows share the same CitizenServe portal shell. Form extras vary; inferred schema prefixes:

| Schema prefix | n | Role |
| --- | ---: | --- |
| `portal_form_checklist` | 1,201 | Form extras + Permit Checklist |
| `portal_core` | 547 | Minimal colon-key shell |
| `portal_form` | 243 | Form extras, no checklist |
| `portal_core_sqft` | 5 | Core + Square Footage / dwelling units |
| `portal_form_window` | 4 | Form + window/door openings |

Suffixes (`_issued_finaled`, `_issued`, `_finaled`, `_applied`, `_status_only`) mark which canonical dates are recoverable.

Canonical sources:

| Field | DATA source |
| --- | --- |
| STATUS_NORMALIZED | `Status:` (`Finaled`/`Closed`→Final, `Issued`/`Approved`→Active, `Under Review`/`Online Application Received`/`Ready for pickup`→In Review, `Void`/`Expired`/`Denied`/`Withdrawn`→Inactive) |
| FILE_DATE | Earliest Review Start ≤ Issue; else earliest Review Completion ≤ Issue (no Application Intake tasks in sample) |
| PERMIT_DATE | `Permit Details["Issue Date:"]` (top-level `Issue Date` always null; reject `01/01/2000`) |
| FINAL_DATE | Latest Approved/Passed inspection date (any trade type), floored at Issue when present |

## Field assessments

### STATUS_NORMALIZED

Before/after: Final 1,426; Active 393; Inactive 166; In Review 15; **0 null**.

| Status: | n | Upstream STATUS_NORMALIZED | Assessment |
| --- | ---: | --- | --- |
| Finaled | 1,193 | Final | Correct |
| Issued | 326 | Active | Correct |
| Closed | 233 | Final | Correct |
| Void | 120 | Inactive | Correct |
| Approved | 67 | Active | Correct |
| Expired | 38 | Inactive | Correct |
| Under Review | 7 | In Review | Correct |
| Online Application Received | 5 | In Review | Correct |
| Denied / Withdrawn | 4 / 4 | Inactive | Correct |
| Ready for pickup | 3 | In Review | Correct |

`STATUS_ORIGINAL` matches live `Status:` on all 2,000 rows. No Issued→Final upgrade is possible: inspection types are only trade labels (`Structural`, `Electrical`, `Plumbing`, …) with no `FINAL BUILDING` / CO types. Flags: **0 FILLED, 0 FIXED**.

### FILE_DATE

Missing on 1,034/2,000 before. When present, calendar day usually matched latest Review Completion (896/966), not earliest Review Start (112/966). No Application Intake review tasks exist.

| Repair action | n |
| --- | ---: |
| FIXED to earliest Review Start/Completion (≤ Issue) | 851 |
| Cleared post-issue FILE with no application source | 4 |
| FILLED from Reviews | 3 |
| Still missing (empty / undated Reviews) | 1,035 |

After: **965/2,000 (48.3%)** populated; 0 `FILE_DATE > PERMIT_DATE` inversions. Coverage is low because many legacy Closed/Finaled shells have empty Reviews.

### PERMIT_DATE

Missing on 111/2,000 before. Every non-sentinel populated `PERMIT_DATE` already matched `Permit Details["Issue Date:"]`. Top-level `Issue Date` is null on all rows.

| Issue | n | Repair |
| --- | ---: | --- |
| `Issue Date:` = `01/01/2000` copied into PERMIT_DATE (216 Finaled, 201 Closed, 16 Void, 4 Approved) | 437 | FIXED (cleared as migration placeholder) |
| Active Issued missing PERMIT_DATE despite real Issue Date | 1 | FILLED |

Still missing after repair: 547 rows — mostly Finaled/Closed shells with `01/01/2000` or blank Issue Date, plus Approved shells with blank Issue Date, plus In Review (correctly blank). Active/Final coverage: **1,381/1,819 (75.9%)**. Flags: **1 FILLED, 437 FIXED**.

### FINAL_DATE

Missing on 2,000/2,000 before. Portal inspection types never include Final*/CO labels; Finaled rows with inspections use ordinary trade types that end in Approved.

| Repair action | n |
| --- | ---: |
| FILLED from latest Approved/Passed inspection (Final only; floored at Issue) | 677 |

Final rows still missing FINAL_DATE (749): mostly Finaled (518) and Closed (231) shells with empty Inspections or no Approved/Passed stamp. Ideal Final coverage: **677/1,426 (47.5%)**. Non-Final rows keep FINAL_DATE cleared. 0 `PERMIT_DATE > FINAL_DATE` inversions.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 0 | 0 | 0 → 0 |
| FILE_DATE | 3 | 855 | 1,034 → 1,035 |
| PERMIT_DATE | 1 | 437 | 111 → 547 |
| FINAL_DATE | 677 | 0 | 2,000 → 1,323 |

Coverage after repair: FILE_DATE 48.3% all statuses; Active/Final PERMIT_DATE 1,381/1,819 (75.9%); Final FINAL_DATE 677/1,426 (47.5%). Missing PERMIT_DATE increased because incorrect `01/01/2000` placeholders were cleared.

## Artifacts

- Repair script: `agent/scripts/fl/data_repair_fl_wilton_manors.py` (`data_repair`)
- Repaired sample parquet: `$AGENT_DATA_PATH/repaired/permits_fl_wilton_manors_repaired.parquet`

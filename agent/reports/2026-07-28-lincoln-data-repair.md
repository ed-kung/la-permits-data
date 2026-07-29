# Lincoln (CA) data repair

**Summary:** Assessed Lincoln's 2,000-row sample and wrote `agent/scripts/ca/data_repair_ca_lincoln.py`. Lincoln uses an Accela Citizen Access portal payload. Status mapping is already correct. The repair advances 101 FILE_DATEs to earlier Application Acceptance marks, fills 36 missing FINAL_DATEs from Passed Final*/Final Solar inspections, and clears 4 spurious FINAL_DATEs on Active Issued / Inactive Expired shells. After repair, FILE_DATE is 100% populated, Final has 99.6% FINAL_DATE, Active has 97.6% PERMIT_DATE, and Final has 98.5% PERMIT_DATE.

## Jurisdiction selection

First `(JURISDICTION, STATE)` in `permits_ca_sample.parquet` without an existing `agent/scripts/{state}/data_repair_{state}_{city}.py`: **Lincoln, CA**.

## DATA schema

All 2,000 rows have DATA and share the same top-level key set (`date`, `status`, `tasks`, `inspections`, `search_data`, `more_details`, etc.). Content-based `INFERRED_SCHEMA`:

| Schema | N | Notes |
| --- | --- | --- |
| `portal_issued_finaled` | 1,576 | Permit Issuance Issued + finaling evidence |
| `portal_issued` | 331 | Issued present, no finaling date |
| `portal_application_only` | 69 | Application / top-level date only |
| `portal_final_insp_only` | 24 | Final evidence present, no Issued |

Canonical mappings from DATA:

- `DATA.status` / `search_data.Status` (+ Issued workflow upgrade) → `STATUS_NORMALIZED`
- Earliest of `DATA.date` / `search_data.Date` / Application Submittal·Acceptance Accepted* → `FILE_DATE`
- Earliest Permit Issuance `Issued` / `Permit Issued` → `PERMIT_DATE`
- Earliest Inspection `Final Inspection Complete` / `Inspections Complete` (fallbacks: Final CO Issued, Pass/Passed Final* inspection including Final Solar) → `FINAL_DATE`

## Findings by field

### STATUS_NORMALIZED

Before: Final 1,599 / Inactive 192 / Active 170 / In Review 39 / missing 0.

`STATUS_ORIGINAL` (lowercased) matches live `DATA.status` on every row — no stale listing-snapshot lag. Mapping is already correct:

| DATA.status | N | STATUS_NORMALIZED |
| --- | --- | --- |
| Finaled | 1,375 | Final |
| Closed | 221 | Final |
| Expired | 178 | Inactive |
| Issued | 170 | Active |
| Submitted | 26 | In Review |
| Application Expired | 13 | Inactive |
| Plan Review | 9 | In Review |
| Ready to Issue | 4 | In Review |
| CofO Issued | 3 | Final |
| Void | 1 | Inactive |

Passed Final inspections on still-Issued shells are **not** treated as status promotions (agency CaseStatus lag), matching Eastvale/Perris conventions.

Repair performance: **0 FILLED, 0 FIXED**; missing after: **0**.

### FILE_DATE

Before: 0 missing. All 2,000 values match top-level `DATA.date` (and `search_data.Date`).

101 rows have an Application Acceptance Accepted* mark earlier than `DATA.date` (median 4 days; 15 exceed 30 days). Large deltas are typically model-home / master-plan shells whose workflow Acceptance/Issued stamps predate a later Accela open date — bringing FILE forward also restores FILE ≤ PERMIT chronology on those rows.

Repair: **0 FILLED, 101 FIXED**. Coverage remains 100%.

### PERMIT_DATE

Before: 93 missing. Where both present, PERMIT_DATE matches Permit Issuance `Issued` exactly (1,907/1,907).

Repair: **0 FILLED, 0 FIXED** — the 28 Active/Final gaps (24 Finaled, 4 Issued) have only TBD/empty Permit Issuance events, so nothing fillable in DATA.

Remaining Active/Final gap: **28**. Active coverage after repair: **166 / 170 (97.6%)**; Final: **1,575 / 1,599 (98.5%)**.

### FINAL_DATE

Before: 440 missing. When both present, FINAL_DATE matches earliest `Final Inspection Complete` for all overlapping rows.

43 Finaled rows lacked FINAL_DATE; 36 of those have a Passed inspection titled Final* / Final Solar while the workflow Inspection task is still TBD. Seven Finaled shells have no Final Inspection Complete, Inspections Complete, Final CO Issued, or Final*-titled Pass inspection → unfillable.

Four non-Final rows carried FINAL_DATE (2 Active Issued with Inspections Complete / Final Inspection Complete; 2 Inactive Expired) → cleared as spurious.

Repair: **36 FILLED**, **4 FIXED** (cleared).

Final coverage after repair: **1,592 / 1,599 (99.6%)**. No spurious FINAL_DATE remains on Active / In Review / Inactive.

## Repair script

`agent/scripts/ca/data_repair_ca_lincoln.py` — `data_repair(df)` overwrites incorrect/missing fields, adds `{FIELD}_FLAG` (`FILLED` / `FIXED`) and `INFERRED_SCHEMA`.

Status logic: Inactive labels sticky (Expired / Application Expired / Void); Finaled / Closed / CofO Issued → Final; Issued → Active; dated Permit Issuance Issued promotes In Review → Active; final-inspection evidence alone does not promote Issued → Final.

### Performance (n=2,000)

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | --- | --- | --- | --- |
| STATUS_NORMALIZED | 0 | 0 | 0 | 0 |
| FILE_DATE | 0 | 101 | 0 | 0 |
| PERMIT_DATE | 0 | 0 | 93 | 93 |
| FINAL_DATE | 36 | 4 | 440 | 408 |

### Coverage after repair

| Status | PERMIT_DATE | FINAL_DATE |
| --- | --- | --- |
| Active | 166 / 170 (97.6%) | 0 / 170 (0%) |
| Final | 1,575 / 1,599 (98.5%) | 1,592 / 1,599 (99.6%) |
| In Review | 0 / 39 (0%) | 0 / 39 (0%) |
| Inactive | 166 / 192 (86.5%) | 0 / 192 (0%) |

FILE_DATE: 2,000 / 2,000 (100%). Chronology: 2 PERMIT &lt; FILE and 3 FINAL &lt; PERMIT (all pre-existing Accela workflow inversions; not introduced by repair).

## Artifact

- Repaired sample: `/Users/ekung/Dropbox/projects/la-permits-data-bot/repaired/permits_ca_lincoln_repaired.parquet`

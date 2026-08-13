# Islamorada (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script was Islamorada. Its DATA is an EnerGov/Civic `Summary` + `Inspections` payload (same family as Westlake). `FILE_DATE` already matched `Application Date` on all 2,000 rows. `STATUS_NORMALIZED` had 150 nulls (unmapped terminal/review statuses) and 39 stale labels vs `Application Status`. `FINAL_DATE` was missing on every row despite `Date Finalled` on 1,247 rows; repair filled 1,512 Final rows (summary + approved Final* inspections). `PERMIT_DATE` gained 16 fills after status correction; 440 Closed/Final legacy shells still lack `Issued Date`.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` and walked `(JURISDICTION, STATE)` in first-appearance order. Islamorada was the first pair without `agent/scripts/fl/data_repair_fl_islamorada.py`.

## DATA shape

All 2,000 rows have a top-level `Summary` dict. Common companions: `Inspections`, `Locations`, `Contacts`, `Reviews`, plus either `Permits` (list) or `Permit Info` (dict); a small minority also have `project_id` / `Submittals`.

Canonical sources:

| Field | DATA source |
| --- | --- |
| STATUS_NORMALIZED | `Summary["Application Status"]` (+ Issued / Date Finalled overrides) |
| FILE_DATE | `Summary["Application Date"]` |
| PERMIT_DATE | `Summary["Issued Date"]` |
| FINAL_DATE | `Summary["Date Finalled"]`, else latest approved Final* `Inspections[].DateCompleted` |

`INFERRED_SCHEMA` prefixes: `energov_permits*`, `energov_permit_info*`, `energov_permits_project*`, with content suffixes `_issued_finaled` / `_issued` / `_finaled` / `_app_date`.

## Field assessments

### STATUS_NORMALIZED

Before: Final 1,585; null 150; Inactive 104; In Review 96; Active 65.

Root causes of errors:

1. **Unmapped statuses left null** — `Voided/Cancelled` (68), `Withdrawn/Abandoned` (45), `Assigned in Error` (17), `Returned for Correction`, `In BPAS`, `Allocated`, etc.
2. **Stale `STATUS_ORIGINAL`** — 51 rows where lowercased `STATUS_ORIGINAL` ≠ `Application Status` (e.g. `issued`/`in plan check`/`expired` while DATA already says `Closed`). Normalized status followed the stale original → Active/In Review/Inactive instead of Final.

After repair: Final 1,612; Inactive 237; In Review 91; Active 60; **0 null**. Flags: **150 FILLED, 39 FIXED**.

### FILE_DATE

Already populated for all 2,000 rows and identical to `Application Date`. No fills/fixes. Ideal coverage: 100%.

### PERMIT_DATE

Before: 700 missing. When present, values already matched `Issued Date` (no wrong dates).

Issues:

- 16 rows had `Issued Date` but null `PERMIT_DATE`, mostly because status was still In Review from a stale original while DATA said Issued/Closed.
- After status repair, Active has 100% `PERMIT_DATE`; Final has 72.7% (1,172 / 1,612).
- **440 Closed/Final rows** have blank `Issued Date` (mostly legacy shells) → not recoverable from DATA.

Flags: **16 FILLED, 0 FIXED**. Spurious In Review issuance stamps were cleared when present after reclassification.

### FINAL_DATE

Before: **all 2,000 missing**, even though 1,247 rows had nonempty `Date Finalled`. Upstream pipeline never mapped that key (Islamorada spelling uses double-L `Finalled`, vs Westlake’s `Finaled`).

Repair:

- Filled from `Date Finalled` for Final rows.
- For Closed rows without `Date Finalled`, used latest approved inspection whose `Activity` matches Final/CO (`FINAL TO CLOSE`, `BUILDING: FINAL`, etc.) → recovered most of the remaining Closed gap.

After: Final FINAL_DATE coverage **1,512 / 1,612 (93.8%)**. **100 Closed** rows still lack both `Date Finalled` and an approved Final* inspection. Non-Final statuses correctly have null FINAL_DATE (including a handful of Voided/Abandoned shells that carry a leftover `Date Finalled`).

Flags: **1,512 FILLED, 0 FIXED**.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | --- | --- | --- |
| STATUS_NORMALIZED | 150 | 39 | 150 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 16 | 0 | 700 → 684 |
| FINAL_DATE | 1,512 | 0 | 2,000 → 488 |

Ideal-coverage gaps remaining:

- Active/Final missing PERMIT_DATE: **440** (blank `Issued Date`)
- Final missing FINAL_DATE: **100** (no finalled stamp / Final inspection)
- FILE_DATE / STATUS_NORMALIZED: **none**

Chronology: 12 rows with `PERMIT_DATE` > `FINAL_DATE` and 1 with `FILE_DATE` > `FINAL_DATE` — source quirks in agency `Date Finalled` / re-issue timelines, not introduced by the repair logic.

## Artifacts

- Script: `agent/scripts/fl/data_repair_fl_islamorada.py` (`data_repair`)
- Repaired sample: `AGENT_DATA_PATH/repaired/permits_fl_islamorada_repaired.parquet`

# Westlake (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script after Belleair was Westlake (2,000 rows). DATA is EnerGov / Civic community-development JSON (`Summary` with Application/Issued/Date Finaled stamps, plus `Permits` or `Permit Info`). Upstream STATUS_NORMALIZED left **34** rows missing (`Returned for Correction`, `Submittals Incomplete`) and had **29** mismatches vs Application Status / date stamps — all repaired (FILLED 34 · FIXED 29). FILE_DATE already matched `Application Date` for all 2,000 rows. PERMIT_DATE matched `Issued Date` when present; **81** spurious stamps cleared on Inactive. FINAL_DATE matched `Date Finaled` when present, but **1,278 / 1,582 (80.8%)** Final rows have no finaled stamp in DATA and cannot be filled.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` and walked unique `(JURISDICTION, STATE)` pairs in first-appearance order. Existing FL repair scripts covered through Belleair. **Westlake** was the first without `agent/scripts/fl/data_repair_fl_westlake.py`.

Sample size: **2,000** records.

## DATA schemas

EnerGov / Civic community-development portal payload. Top-level keys include `Summary`, `Contacts`, `Locations`, `Related Permit & Planning Applications`, plus either `Permits` (list) or `Permit Info` (dict), and optionally `project_id`.

| INFERRED_SCHEMA prefix | Meaning |
| ---------------------- | ------- |
| `energov_permits_project_*` | Has `Permits` list + `project_id` |
| `energov_permits_*` | Has `Permits` list, no `project_id` |
| `energov_permit_info_*` | Has `Permit Info` dict |

Content suffixes: `_issued_finaled`, `_issued`, `_finaled`, `_app_date`, `_minimal`.

Largest buckets: `energov_permits_issued` 665 · `energov_permit_info_issued` 579 · `energov_permit_info_issued_finaled` 225 · `energov_permit_info_app_date` 190 · `energov_permits_app_date` 163.

Canonical source fields:

| Target field | DATA source |
| --- | --- |
| STATUS_NORMALIZED | `Summary["Application Status"]`, with Inactive terminal statuses first; `Date Finaled` or Finaled/Closed → Final; `Issued Date` or Issued statuses → Active |
| FILE_DATE | `Summary["Application Date"]` |
| PERMIT_DATE | `Summary["Issued Date"]` |
| FINAL_DATE | `Summary["Date Finaled"]` (`Expiration Date` is not a completion stamp) |

## Field assessments

### STATUS_NORMALIZED

Before: Final 1,580 · Active 144 · Inactive 142 · In Review 100 · missing 34.  
After: Final 1,582 · Active 169 · Inactive 142 · In Review 107 · missing 0.

- Upstream mapped from `STATUS_ORIGINAL` (lowercased Application Status) but omitted `Returned for Correction` and `Submittals Incomplete`.
- Two records had `STATUS_ORIGINAL` out of sync with `Summary["Application Status"]` (stale `permit(s) issued` vs Closed; stale `expired` vs Permit(s) Issued).
- Date overrides remapped In Review rows that already carried Issued / Date Finaled stamps.

Flags: **FILLED 34 · FIXED 29**.

| Transition | n | Reason |
| --- | ---: | --- |
| missing → In Review | 34 | Returned for Correction (24), Submittals Incomplete (10) |
| In Review → Active | 25 | Ready for Issuance (20), On Hold (3), In Plan Check (1), In Progress (1) with Issued Date |
| In Review → Final | 1 | In Progress with Date Finaled |
| In Review → Inactive | 1 | Recalled |
| Inactive → Active | 1 | Application Status Permit(s) Issued; STATUS_ORIGINAL was expired |
| Active → Final | 1 | Application Status Closed; STATUS_ORIGINAL was permit(s) issued |

### FILE_DATE

Before/after: **0 missing**. Ideal: populated for all records.

- `Summary["Application Date"]` present on all 2,000 rows; FILE_DATE matches at day resolution — no FILLED/FIXED needed.
- No incorrect non-null FILE_DATE values found.

Flags: **FILLED 0 · FIXED 0**.

### PERMIT_DATE

Before: **404 missing**. After: **485 missing** (cleared spurious values). Ideal: populated for Active and Final.

- When `Issued Date` is present (1,596 rows), upstream PERMIT_DATE matched it exactly.
- After status repair: Active **130 / 169 (76.9%)**; Final **1,385 / 1,582 (87.5%)**.
- Active gaps (**39**): Permit(s) Issued / Issued with blank `Issued Date`.
- Final gaps (**197**): Finaled (193) / Closed (4) with blank `Issued Date`.
- **81 FIXED** clears of PERMIT_DATE on Inactive (Expired / Canceled / Abandoned / Withdrawn / Denied / Recalled).
- In Review correctly ends with **0** PERMIT_DATE (issued In Review rows were reclassified to Active/Final).

Flags: **FILLED 0 · FIXED 81**.

### FINAL_DATE

Before/after: **1,696 missing**. Ideal: populated for Final.

- When `Date Finaled` is present (304 rows), upstream FINAL_DATE matched it exactly.
- After status repair: Final **304 / 1,582 (19.2%)**.
- **1,278** Final gaps: Finaled 1,266 · Closed 12 — no alternate completion date in DATA (`Expiration Date` differs from `Date Finaled` whenever both exist; never used as FINAL_DATE).
- The one In Progress row that carried `Date Finaled` was remapped to Final, so its FINAL_DATE was retained without a flag change.
- No spurious FINAL_DATE remained on non-Final statuses after the status override.

Flags: **FILLED 0 · FIXED 0**.

## Repair performance

Script: `agent/scripts/fl/data_repair_fl_westlake.py` (`data_repair`).

Artifact: `AGENT_DATA_PATH/repaired/permits_fl_westlake_repaired.parquet`.

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 34 | 29 | 34 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 0 | 81 | 404 → 485 |
| FINAL_DATE | 0 | 0 | 1,696 → 1,696 |

Post-repair ideal-coverage gaps (not fillable from DATA): Active/Final missing PERMIT_DATE **236**; Final missing FINAL_DATE **1,278**; FILE_DATE / STATUS_NORMALIZED fully populated. Chronology inversions: FILE>PERMIT **0**, PERMIT>FINAL **0**.

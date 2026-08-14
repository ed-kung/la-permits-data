# Mascotte (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script (in parquet appearance order) was **Mascotte**. DATA is a city-portal payload (`Status`, `Permit Date`, nested `reviews` / `plan_reviews` / `inspections`). Upstream left 74 non-blank Status values unmapped and ~1,054 blank-Status shells null; `FILE_DATE` already matched `Permit Date` whenever present. Repair filled/fixed status on 128 rows, filled 18 missing `PERMIT_DATE` values and cleared/corrected 119 issuance stamps, and filled 63 `FINAL_DATE` values from passed FINAL-ish inspections. After repair: FILE_DATE 1,586/2,000 (79.3%); Active/Final PERMIT_DATE 516/745 (69.3%); Final FINAL_DATE 204/417 (48.9%). Remaining gaps are mostly blank-Status shells with no dated final inspection and Issued/Final rows lacking review completion stamps.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` and walked `(JURISDICTION, STATE)` pairs in first-appearance order. Mascotte was the first pair without `agent/scripts/fl/data_repair_fl_mascotte.py`.

## DATA shape

| Schema | n |
| --- | ---: |
| `city_portal_applied` | 904 |
| `city_portal_issued` | 414 |
| `city_portal_status_only` | 400 |
| `city_portal_issued_finaled` | 133 |
| `city_portal_finaled` | 68 |
| `city_portal_record_type_issued` | 51 |
| `city_portal_plan_reviews_issued` | 20 |
| `city_portal_record_type_applied` | 6 |
| `city_portal_record_type_issued_finaled` | 3 |
| `city_portal_plan_reviews_applied` | 1 |

Canonical sources:

| Field | DATA source |
| --- | --- |
| STATUS_NORMALIZED | `Status`, with `Final Inspection Date` / passed FINAL-ish inspection overrides; blank `Status` → Final only when a dated passed FINAL-ish inspection exists |
| FILE_DATE | `Permit Date` (application / open stamp — not issuance) |
| PERMIT_DATE | Latest approved `reviews` / `plan_reviews` `completed_date` (Building* preferred; else non-payment; fallback `date` / `review_date`) |
| FINAL_DATE | `Final Inspection Date`, else latest passed FINAL-ish inspection `completed_date` |

## Field assessments

### STATUS_NORMALIZED

Before: null 1,128; Final 359; Active 319; In Review 148; Inactive 46.

After: null 1,007; Final 417; Active 328; In Review 202; Inactive 46.

| Issue | n | Cause |
| --- | ---: | --- |
| null → In Review | 56 | Unmapped `Waiting Payment` (41), `Needs Additional Info` (13), `Intake / Applied for` (2) |
| null → Final | 53 | Unmapped `Final / Completed` (6) + blank-Status shells with dated passed FINAL-ish inspections (47) |
| null → Active | 12 | Unmapped `Issued / Work started` (11), `PRIVATE PROVIDER` (1) |
| Active → Final | 5 | `Issued` with `Final Inspection Date` or passed FINAL-ish inspection |
| In Review → Active | 2 | `APPROVED WITH CONDITIONS` previously kept as In Review |

Flags: **121 FILLED, 7 FIXED**.

Not repairable: 1,007 blank-`Status` shells without a dated passed FINAL-ish inspection (many are empty shells or undated Pass rows only).

### FILE_DATE

Missing on 414/2,000. Calendar day matches `Permit Date` on every populated row; the 414 gaps are exactly the rows with blank `Permit Date` (empty shells). Inspection schedule/completion dates were not treated as application dates. Flags: **0 FILLED, 0 FIXED**.

After repair, FILE_DATE coverage among non-null statuses is essentially complete (Active/In Review/Inactive 100%; Final 403/417 = 96.6% — the 14 gaps are blank-Status→Final promotions that still lack `Permit Date`).

### PERMIT_DATE

Missing before: 1,398. After: 1,484 (net increase from clearing spurious stamps).

- **FILLED 18:** Active/Final rows with approved review completion (or approved `date` / `review_date` fallback) but blank `PERMIT_DATE`.
- **FIXED 119:** 104 cleared (In Review 72, null→In Review 19, Inactive 13 — ideal rule keeps issuance only on Active/Final); 15 overwritten to the Building-preferred / non-payment approved review completion on `plan_reviews` shells where upstream used an earlier Intake stamp.

Active/Final coverage after repair: **516 / 745 (69.3%)**. Remaining gaps are Issued/Final/Complete rows with empty review `completed_date` (payment dates are a poor proxy — they disagree with review completions on 166/172 dual-source rows).

### FINAL_DATE

Missing before: 1,859. After: 1,796.

- **FILLED 63:** all from passed FINAL-ish inspection `completed_date` (rows already carrying `Final Inspection Date` already had matching `FINAL_DATE`).
- **FIXED 0.**

Final coverage after repair: **204 / 417 (48.9%)**. Remaining Final/Complete rows lack both `Final Inspection Date` and a dated passed FINAL-ish inspection.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 121 | 7 | 1,128 → 1,007 |
| FILE_DATE | 0 | 0 | 414 → 414 |
| PERMIT_DATE | 18 | 119 | 1,398 → 1,484 |
| FINAL_DATE | 63 | 0 | 1,859 → 1,796 |

Ideal-rule coverage after repair:

| Rule | Coverage |
| --- | --- |
| FILE_DATE populated (all rows) | 1,586 / 2,000 (79.3%) |
| PERMIT_DATE on Active/Final | 516 / 745 (69.3%) |
| FINAL_DATE on Final | 204 / 417 (48.9%) |

## Artifacts

- Repair script: `agent/scripts/fl/data_repair_fl_mascotte.py` (`data_repair`)
- Repaired sample: `AGENT_DATA_PATH/mascotte_repaired_sample.parquet`

# Weston (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script was **Weston**. DATA is an Accela Citizen Access payload (`status` / `date` / `tasks` / `search_data` / `inspections`; 23 rows are basic shells without contacts/fees/inspections extras). Upstream left 42 `STATUS_NORMALIZED` nulls and often mapped from stale `STATUS_ORIGINAL` (workflow task label) instead of current `DATA.status` — e.g. Closed kept as Active, Issued kept as In Review, 207 Sub Application shells kept as Active despite no issuance. Present `FILE_DATE` / `PERMIT_DATE` already matched `DATA.date` / Permit Issuance `Issued` wherever set; `FINAL_DATE` usually matched Final Inspection Complete but was missing on many Final rows that only had passed Final* inspections. The repair filled 42 statuses and fixed 225, filled 9 `PERMIT_DATE` values, filled 702 `FINAL_DATE` values, and fixed 6 `FINAL_DATE` values (5 late Final Inspection Complete corrections + 1 Expired clear). After repair: STATUS 100%; FILE_DATE 100%; Active/Final PERMIT_DATE 98.4%/42.4%; Final FINAL_DATE 87.1%.

## Jurisdiction selection

`(JURISDICTION, STATE)` pairs in `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` (first-appearance order) were checked against `agent/scripts/{state}/data_repair_{state}_{city}.py`. First missing: **Weston, FL** → `agent/scripts/fl/data_repair_fl_weston.py` (2,000 sample rows).

## DATA schemas (`INFERRED_SCHEMA`)

Almost all rows share Accela top-level keys `address`, `date`, `details`, `more_details`, `record_type`, `search_data`, `status`, `tasks`, `total_fees`, `valuation`, `job_value`. The common “full” variant also carries `inspections`, `contacts`, `conditions`, `fees_details`, `address_lines`, `related_records` (sometimes empty lists). Content suffixes split by which canonical dates are recoverable:

| Schema | n | Notes |
| --- | ---: | --- |
| `accela_full_finaled` | 670 | Final date recoverable, no Issued event |
| `accela_full_issued_finaled` | 631 | Issued + final |
| `accela_full_applied` | 551 | Neither issued nor final |
| `accela_full_issued` | 125 | Issued, no usable final |
| `accela_basic_applied` | 22 | Shell without extras |
| `accela_basic_issued` | 1 | Shell with Issued only |

Canonical fields:

| Target field | Source in DATA |
| --- | --- |
| STATUS_NORMALIZED | `DATA.status` (fallback `search_data.Status`); In Review upgraded to Active when Permit Issuance `Issued` exists |
| FILE_DATE | `search_data.Date` else `DATA.date` else Application Submittal Accepted |
| PERMIT_DATE | Earliest Permit Issuance task marked `Issued` |
| FINAL_DATE | Latest of Inspection `Final Inspection Complete`, Certificate of Occupancy Final CO/CC Issued, passed Final* inspections; else Plans Coordination `Revision Approved` on `Closed - Revision Approved` |

## Field assessments

### STATUS_NORMALIZED

| DATA.status | n | Upstream STATUS_NORMALIZED | Assessment |
| --- | ---: | --- | --- |
| Closed | 819 | Final (9 Active, 2 null) | Fix Active/null → Final |
| Permit Complete | 563 | Final | Correct |
| Sub Application | 207 | Active | Fix → In Review (subordinate shells, no Issued) |
| Issued | 124 | Active (3 In Review, 3 null) | Fix In Review/null → Active |
| Closed - Revision Approved | 95 | Final (1 Inactive) | Fix Inactive → Final |
| In Review / Response Received | 34 / 34 | In Review / **null** | Fill nulls → In Review |
| Waiting On/on Applicant | 19 / 19 | In Review (1 null) | Fill null → In Review |
| Canceled Permit / Closed-Withdrawn / Expired / Voided | 20 / 14 / 9 / 7 | Inactive | Correct |
| Submitted / Application / Incomplete / Plan Review | 13 / 9 / 3 / 2 | In Review | Correct |
| Issuance | 5 | Active (4) / In Review (1) | Fix Active→In Review unless Issued event (1 upgraded to Active) |
| File Validation Issues | 2 | **null** | Fill → In Review |
| Permit Renewal | 1 | **null** | Fill → Active (has Issued) |
| Finaled | 1 | Final | Correct |

**Root causes:**
1. Upstream often used stale `STATUS_ORIGINAL` (e.g. `issued`, `response received`, `sub application`) instead of current `DATA.status`.
2. Mapper omitted `Response Received`, `File Validation Issues`, `Permit Renewal`, and some `Waiting on Applicant` / `Issued` / `Closed` rows → null `STATUS_NORMALIZED`.
3. `Sub Application` and ready-to-issue `Issuance` were labeled Active despite no Permit Issuance `Issued` event.

**Repair performance:** FILLED 42, FIXED 225; missing 42 → 0.

### FILE_DATE

- Before: missing on **0 / 2,000**. Every value matches `DATA.date` at calendar-day resolution (1,996 also match `search_data.Date`; 4 lack search_data Date but keep `DATA.date`).
- Ideal coverage already 100% for every status class.

**Repair performance:** FILLED 0, FIXED 0; missing 0 → 0 (100% coverage).

### PERMIT_DATE

- Before: NaN on **1,252 / 2,000**. All 748 present values matched Permit Issuance `Issued` (0 calendar mismatches).
- 9 rows had an Issued event but missing `PERMIT_DATE` (null/In Review status shells) → FILLED.
- After status repair, Active coverage is 124 / 126 (98.4%); the 2 gaps are `Issued` records with an empty Permit Issuance task (no date in DATA).
- Final coverage remains low (626 / 1,478 = 42.4%): `Permit Complete` (563), older `Closed` (195), and `Closed - Revision Approved` (93) typically never recorded an Issued event in the scraped task history.

**Repair performance:** FILLED 9, FIXED 0; missing 1,252 → 1,243. Active 98.4%; Final 42.4%; In Review 0%.

### FINAL_DATE

- Before: NaN on **1,413 / 2,000**; Final had 586 / 1,466 present; 1 Expired/Inactive row carried a spurious final date.
- Present values usually matched Inspection `Final Inspection Complete` (4 were earlier than the task mark → FIXED to the later FIC/CO date).
- Large Final gap was fillable from passed Final* inspections on `Permit Complete` / `Closed` rows that lack the Inspection workflow mark; `Closed - Revision Approved` filled from Plans Coordination `Revision Approved`.
- Pass Partial on Final* inspections is ignored (not a close-out); that also removes a Permit>Final inversion where Pass Partial Final Electrical preceded issuance.

**Repair performance:** FILLED 702, FIXED 6 (5 date corrections + 1 Inactive clear). Final coverage 87.1% (1,288 / 1,478). Active / In Review / Inactive FINAL_DATE all 0% after cleanup.

## Artifacts

- Repair script: `agent/scripts/fl/data_repair_fl_weston.py` (`data_repair`)
- Repaired sample parquet: `$AGENT_DATA_PATH/repaired/permits_fl_weston_repaired.parquet`

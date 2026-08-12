# Marco Island (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script was **Marco Island**. DATA is a Tyler EnerGov payload (`entity` / `details` / `fees` / `contacts`; `processing_status` always null). Upstream left 102 `STATUS_NORMALIZED` null (unmapped Estoppel/WWP/Ready/Hold labels) and misclassified 17 rows against current `entity.CaseStatus`. `FILE_DATE` already matched `ApplyDate` on all 2,000 rows. Repairs filled/fixed status fully (0 nulls), filled 5 missing `PERMIT_DATE` values, cleared 2 spurious In Review issuance dates, filled 4 Final `FINAL_DATE` values, and cleared 53 non-Final void/cancel `FinalDate` stamps. After repair: STATUS 100%; FILE_DATE 100%; Active/Final PERMIT_DATE 92.1%/96.4%; Final FINAL_DATE 97.2%.

## Jurisdiction selection

Ordered `(JURISDICTION, STATE)` pairs in `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` were checked against `agent/scripts/{state}/data_repair_{state}_{city}.py`. First missing: **Marco Island, FL** → `agent/scripts/fl/data_repair_fl_marco_island.py` (2,000 sample rows).

## DATA schemas (`INFERRED_SCHEMA`)

Two key-set variants share the same EnerGov shape:

| Key-set | n | Notes |
| --- | ---: | --- |
| `contacts`, `details`, `entity`, `fees`, `processing_status` | 1,957 | Standard |
| + `reviews`, `holds`, `attachments`, `more_info` | 43 | `energov_full_*` |

Content suffixes split by which canonical dates are populated:

| Schema | n |
| --- | ---: |
| `energov_issued_finaled` | 1,573 |
| `energov_issued` | 184 |
| `energov_applied` | 139 |
| `energov_finaled` | 61 |
| `energov_full_applied` | 26 |
| `energov_full_issued` | 13 |
| `energov_full_finaled` | 2 |
| `energov_full_issued_finaled` | 2 |

Canonical fields:

| Target field | Source in DATA |
| --- | --- |
| STATUS_NORMALIZED | `entity.CaseStatus` (fallback `details.PermitStatus`) |
| FILE_DATE | `entity.ApplyDate` (fallback `details.ApplyDate`) |
| PERMIT_DATE | `entity.IssueDate` (fallback `details.IssueDate`) |
| FINAL_DATE | `entity.FinalDate` (fallback `details.FinalizeDate`) |

`processing_status` is null on every sample row, so there is no inspection-based FINAL_DATE fallback.

## Field assessments

### STATUS_NORMALIZED

| CaseStatus | n | Upstream STATUS_NORMALIZED | Assessment |
| --- | ---: | --- | --- |
| Permit Complete | 861 | Final (857); Active (2); Inactive (1); null (1) | Mostly correct; 4 FIXED/FILLED |
| Permit Closed | 712 | Final | Correct |
| Permit Expired | 123 | Inactive (122); Active (1) | 1 FIXED |
| Permit Active | 60 | Active (57); In Review (2); null (1) | 3 FIXED/FILLED |
| Application Review | 52 | In Review | Correct |
| Application Voided | 49 | Inactive | Correct |
| Estoppel Closed | 48 | **null** | Fill → Final |
| Permit Void | 19 | Inactive (18); Active (1) | 1 FIXED |
| Book Permit - UNISSUED | 19 | **null** | Fill → In Review |
| Application Approved | 10 | In Review | **FIXED → Active** (all have IssueDate) |
| Request in Process / Internet Submit - PENDING | 14 | In Review | Correct |
| WWP Resolved | 7 | **null** | Fill → Final |
| Ready - Contractor Notified (+ Digital) | 11 | **null** | Fill → In Review |
| WWP Permit Needed | 5 | **null** | Fill → Active |
| APP HOLD / Application Hold | 6 | **null** | Fill → In Review |
| MS - PHASE 1 - REPORT RECEIVED | 3 | **null** | Fill → In Review |
| SWO Issued | 1 | **null** | Fill → Active |

**Root cause of nulls / mismatches:** upstream mapper did not cover Estoppel, Book Permit, WWP, Ready-to-issue, hold, milestone, or SWO labels. A handful of rows have stale `STATUS_ORIGINAL` that disagrees with current `entity.CaseStatus` (e.g. `permit active` while CaseStatus is `Permit Complete`). Application Approved was treated as In Review despite always carrying `IssueDate` in this city.

**Repair performance:** FILLED 102, FIXED 17; missing 102 → 0.

### FILE_DATE

- Before: missing on **0 / 2,000**. Present values always matched `entity.ApplyDate` at calendar-day resolution.
- No fills or fixes needed.

**Repair performance:** FILLED 0, FIXED 0; missing 0 → 0 (100% coverage).

### PERMIT_DATE

- Before: missing on **234 / 2,000**; present values always matched `IssueDate`.
- Filled 5 rows that gained Active/Final status (or were null) while carrying `IssueDate`.
- Cleared 2 In Review rows that incorrectly retained issuance (`APP HOLD` with IssueDate; `Application Review` with IssueDate).
- Remaining Active/Final gaps (65): Estoppel Closed (48), WWP Resolved (7), WWP Permit Needed (5), SWO Issued (1), and 4 Permit Complete/Closed shells with blank IssueDate — no issuance field in DATA.

**Repair performance:** FILLED 5, FIXED 2; missing 234 → 231. Active coverage 92.1%; Final coverage 96.4%.

### FINAL_DATE

- Before: missing on **368 / 2,000**, including 4 Final rows; 53 non-Final rows (mostly Application Voided / Permit Void, plus 1 Active) incorrectly carried `FinalDate` (void/close stamps).
- Filled 4 rows reclassified to Final that already had `FinalDate`.
- Cleared all 53 spurious non-Final finals (FIXED).
- Remaining Final gaps (45): Estoppel Closed (41), Permit Closed (3), Permit Complete (1) — the Complete case has `FinalDate` year **2916**, rejected as out-of-range. No inspection fallback available.

**Repair performance:** FILLED 4, FIXED 53; missing 368 → 417 (count rises because void stamps are cleared). Final coverage: 97.2% (1,583 / 1,628).

## Ideal-field checklist (after repair)

| Rule | Result |
| --- | --- |
| FILE_DATE populated for all records | Yes (100%) |
| PERMIT_DATE for Active and Final | Mostly (92.1% / 96.4%; gaps are non-issued Estoppel/WWP/SWO or blank IssueDate shells) |
| FINAL_DATE for Final | Mostly (97.2%; Estoppel/Closed shells lack FinalDate) |

Status distribution after repair: Final 1,628; Inactive 191; In Review 105; Active 76; null 0.

## Artifacts

- Script: `agent/scripts/fl/data_repair_fl_marco_island.py`
- Repaired sample: `$AGENT_DATA_PATH/marco_island_repaired_sample.parquet`

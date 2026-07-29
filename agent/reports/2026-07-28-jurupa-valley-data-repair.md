# Jurupa Valley (CA) data repair — 2026-07-28

Jurupa Valley was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. Accela Citizen Access JSON under `DATA` supports correcting 58 wrong statuses (39 plans-`Approved` previously Active → In Review; 7 Issued originals already Finaled/C of O in DATA → Final; 9 Applied/Ready-to-Issue/In-Review lagging Issued → Active; 2 In Review already Closed-Revisions-Approved/Finaled → Final; 1 Applied already Closed-Expired → Inactive), filling 81 missing statuses (mostly See MA planning placeholders), fixing 2 `FILE_DATE` values where Accela re-open bumped the top-level date past Application Submittal Accepted, filling 745 missing `PERMIT_DATE` values (mostly historical Open/Issued shells without a Permit Issuance task), filling 647 previously blank `FINAL_DATE` values (mostly Closed-Final shells whose Inspection task is marked Closed rather than Finaled), and clearing 5 spurious `FINAL_DATE` stamps on non-Final rows.

## Jurisdiction selection

Walked `(JURISDICTION, STATE)` pairs in sample order and compared against `agent/scripts/{state}/data_repair_{state}_{city}.py`. First missing: **Jurupa Valley, CA** → `agent/scripts/ca/data_repair_ca_jurupa_valley.py` (n=2,001).

## DATA schema

All 2,001 rows share Accela portal JSON with the same top-level keys (`address`, `date`, `status`, `tasks`, `search_data`, …). Optional blocks (`inspections`, `fees_details`, `contacts`, …) are sometimes absent. Events use the Chino-style `Marked as` / `on` pair (HTML fallback). Content variants:

| Schema | n | Description |
| --- | ---: | --- |
| `portal_issued_finaled` | 1,150 | Issued* + final-date evidence |
| `portal_application_only` | 413 | Top-level / application dates only (incl. See MA null-task shells) |
| `portal_issued` | 405 | Issued present, no final date |
| `portal_final_only` | 33 | Final date present, no Issued |

Canonical fields:

| Source | Field |
| --- | --- |
| `DATA.status` / `search_data.Status` (+ Issued / strong final workflow upgrades) | `STATUS_NORMALIZED` |
| Earliest of `DATA.date`, `search_data.Date`, Application Submittal Accepted*, Open Applied | `FILE_DATE` |
| Earliest Permit Issuance Issued* (fallback: Open Issued) | `PERMIT_DATE` |
| Earliest Inspection Finaled (fallback: Inspection C of O, Closed Closed-Final*, Inspection Closed, final-titled inspection Approved/Pass*) | `FINAL_DATE` |

## Field assessment

### STATUS_NORMALIZED

- Missing on 81 / 2,001 before repair: See MA (64), null `DATA.status` (10), To Applicant (4), Holding for Applicant (1), Pending ACA Account (1), plus one status-lag To Applicant → In Review - 2nd Submittal. All fillable as In Review from portal status / application evidence.
- Upstream mostly mapped from lagged `STATUS_ORIGINAL` while `DATA.status` already advanced on 37 rows.
- Mis-mapping: `Approved` (plans / admin approval, not permit issuance) was stored as Active (39). None have a dated Issued event → In Review.
- Status lag FIXED: 7 Issued → Finaled/C of O stayed Active → Final; 9 Applied / Ready to Issue / In Review already Issued → Active; 2 In Review already Closed - Revisions Approved / Finaled → Final; 1 Applied already Closed - Expired → Inactive.
- Issued portal status is **not** promoted to Final solely because an Inspection Finaled mark exists. Bare Closed-task `Closed` is also excluded from status promotion (Accela stamps it on still-open In Review shells).
- **Repair:** 81 FILLED, 58 FIXED. Missing after: 0.

### FILE_DATE

- Present on all 2,001; every value matched `DATA.date` before repair.
- 2 rows had Accela re-open / later bump of `DATA.date` after an earlier Application Submittal Accepted (2019-10-09 vs FILE 2019-10-14; 2019-08-15 vs FILE 2019-08-19).
- **Repair:** 0 FILLED, 2 FIXED. Coverage 2,001 / 2,001 (100%).
- Residual: 8 rows still have `PERMIT_DATE` one or more days before `FILE_DATE` (Accela Open Issued stamped before Applied / Accepted on historical or same-day shells). Left as-is.

### PERMIT_DATE

- Missing on 1,295 / 2,001 (64.7%). When Permit Issuance Issued* exists, all 706 present values already matched (0 mismatches).
- Historical shells (932 Historical* record types) use Open / Issued instead of Permit Issuance → 745 Active/Final fills from Open Issued (and modern Permit Issuance when previously blank after status upgrades).
- Active coverage after repair: 374/374 (100%). Final: 1,069/1,106 (96.7%). Remaining 37 Final without issuance are mostly Closed - Approved / Complete planning / Master Application shells with no Issued event.
- **Repair:** 745 FILLED, 0 FIXED. Missing after: 550.

### FINAL_DATE

- Missing on 1,551 / 2,001 before repair. Existing values almost all matched Inspection Finaled (448); 2 spurious stamps on In Review (Complete Application / Accepted dates) and 2 on Active Issued / 1 on Inactive Closed-Expired → cleared.
- Final fillable: 647 — primarily Inspection Closed on Closed - Final historical shells (no Finaled mark), plus Inspection C of O / Closed-task Closed-Final* / Finaled / final-titled inspections.
- Remaining 14 Final rows (empty historical shells) stay missing.
- **Repair:** 647 FILLED, 5 FIXED. Missing after: 909.
- Post-repair Final FINAL coverage: 1,092/1,106 (98.7%); Active / In Review / Inactive: 0% by design.

## Repair performance

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | ---: | ---: | ---: | ---: |
| STATUS_NORMALIZED | 81 | 58 | 81 | 0 |
| FILE_DATE | 0 | 2 | 0 | 0 |
| PERMIT_DATE | 745 | 0 | 1,295 | 550 |
| FINAL_DATE | 647 | 5 | 1,551 | 909 |

Status distribution:

| | Before | After |
| --- | ---: | ---: |
| Final | 1,097 | 1,106 |
| Active | 411 | 374 |
| In Review | 258 | 366 |
| Inactive | 154 | 155 |
| (null) | 81 | 0 |

## Artifacts

- Script: `agent/scripts/ca/data_repair_ca_jurupa_valley.py`
- Repaired sample: `AGENT_DATA_PATH/repaired/permits_ca_jurupa_valley_repaired.parquet`

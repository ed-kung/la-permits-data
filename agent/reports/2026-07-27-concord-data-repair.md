# Concord (CA) data repair

**Summary:** Concord was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. Assessed and repaired `STATUS_NORMALIZED`, `FILE_DATE`, `PERMIT_DATE`, and `FINAL_DATE` from the Accela Citizen Access `DATA` JSON. Status is now fully populated (**FILLED 12 · FIXED 83**): unmapped planning statuses were filled, and Accepted+Issued rows wrongly labeled In Review/Inactive were corrected to Active. `FILE_DATE` already matched `DATA.date` for all 2,001 rows (no changes). `PERMIT_DATE` saw modest gains (**FILLED 3 · FIXED 15**)—upstream already captured most Issued events, but 15 rows used Pending Issue instead of Issued. `FINAL_DATE` missingness fell from **1,485 → 878** (**FILLED 610 · FIXED 172**): Inspection Complete proxies were replaced with Closed/Finaled, and 515 shell Finaled rows were filled from Passed FINAL* inspection Status Dates. Remaining gaps are mostly Accela shells without task events or final inspections, plus Active Approved rows still pending issuance.

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_ca_sample.parquet`
- Jurisdiction: **Concord, CA** (n=2,001)
- Script: `agent/scripts/ca/data_repair_ca_concord.py` (`data_repair`)

## DATA schema (`INFERRED_SCHEMA`)

All records are Accela Civic Access scrapes with top-level keys `status`, `date`, `tasks`, `inspections`, `more_details`, `search_data`, etc. Sub-schemas reflect which date sources are populated:

| Schema | n | Description |
| --- | ---: | --- |
| `accela_tasks` | 1,097 | Dated workflow events under `tasks` |
| `accela_shell_inspections` | 521 | Empty task shells; usable Passed FINAL* inspection Status Dates |
| `accela_shell` | 383 | No dated task events and no usable FINAL inspection dates |

Canonical fields:

| Field | Source |
| --- | --- |
| `STATUS_NORMALIZED` | `DATA.status` (Accepted without Issued → In Review; Accepted with Issued → Active) |
| `FILE_DATE` | `DATA.date` (fallback: `search_data['Date Submitted']`) |
| `PERMIT_DATE` | `Permit Issuance` / `Issuance` → Issued\|Reissued\|Annual Issued (not Pending Issue) |
| `FINAL_DATE` | `Closed` / Finaled\|Closed; `Close` / Completed; `Permit Issuance`\|CBO\|BIS / Closed; else Passed FINAL* insp Status Date; else `Inspection` / Complete |

## Field assessment

### STATUS_NORMALIZED

**Before:** Final 1,277 · Inactive 356 · In Review 183 · Active 173 · missing 12

Issues:
1. **12 null statuses** from unmapped planning values: Project Approved (6), Incomple (4), Project Denied (1), Project Closeout (1).
2. **83 mis-normalized rows** relative to `DATA.status` / Issued evidence:
   - Accepted + Issued → In Review (74) or Inactive (3) → Active
   - Expired / Canceled → Active (3) → Inactive
   - Finaled → Active (2) → Final
   - Issued → In Review (1) → Active

When present, `DATA.status` maps as:

| `DATA.status` | `STATUS_NORMALIZED` |
| --- | --- |
| Finaled, Closed, Completed, Project Closed, Project Closeout | Final |
| Issued, Approved, Active, Renewed, Reissued, PreFinaled, Project Approved, Accepted (+ Issued) | Active |
| Applied, Submitted, Opened, Created, Completeness Review, Incomplete, Incomple, Corrections Required, Accepted (no Issued) | In Review |
| Canceled, Cancel, Expired, Permit Withdrawn, Voided, Void, ApplCanceled, Inactive, Application Withdrawn, Revoked, ApprExpired, ApplExpired, Withdrawn, Project Denied | Inactive |

**After:** Final 1,280 · Inactive 357 · Active 252 · In Review 112 · missing 0  
Flags: **FILLED 12 · FIXED 83**

### FILE_DATE

**Before:** 0 missing (100%).

- Every row’s `FILE_DATE` equals `DATA.date`.
- `search_data['Date Submitted']` matches the same calendar day when present (1,996 / 2,001).

**After:** still 0 missing.  
Flags: **FILLED 0 · FIXED 0**

### PERMIT_DATE

**Before:** 1,042 missing (52.1%). Among Active/Final: ~739 / 1,450 missing.

Root cause: upstream already populated issuance for nearly all rows with an Issued event (944 matches). Gaps are mostly Finaled/Closed shells with empty task events (no issuance history in Accela). A smaller set of Active Approved / planning rows never reached Permit Issuance.

Repairs:
1. Prefer earliest `Permit Issuance` / `Issuance` → Issued\|Reissued\|Annual Issued.
2. If existing `PERMIT_DATE` equals Pending Issue but an Issued date exists → FIXED to Issued.
3. Fill missing Active/Final when an Issued mark exists.

**After:** missing 1,039 (−3). Active: 203/252 (80.6%) have PERMIT_DATE; Final: 585/1,280 (45.7%).  
Flags: **FILLED 3 · FIXED 15**

Remaining Active gaps (49): Approved (23), Active (13), Issued shells (7), Project Approved (6)—no Issued mark available.

### FINAL_DATE

**Before:** 1,485 missing (74.2%). Among Final: 764 / 1,277 missing. Also 3 spurious finals on non-Final rows.

Root causes:
1. Upstream often stored **Inspection / Complete** as `FINAL_DATE` even when a later **Closed / Finaled** event existed (~138–169 rows).
2. Pre-~2013 Finaled shells had empty tasks but Passed FINAL* inspections with Status Date (515 recoverable).
3. Annual / levy / enforcement “Closed” records use `Permit Issuance` / Closed or CBO/BIS Closed instead of the Closed/Finaled workflow.

Repairs (Final only):
1. Prefer latest Closed / Finaled, then Closed\|Close / Closed\|Completed, then Project Closeout / Closed.
2. Else Permit Issuance\|CBO\|BIS / Closed, or Investigation / Completed.
3. Else latest Passed FINAL* inspection Status Date.
4. Else Inspection / Complete (fill only when missing).
5. Clear `FINAL_DATE` on non-Final rows (FIXED).

**After:** missing 878 (−607). Final: 1,123 / 1,280 (87.7%) have FINAL_DATE; Active/In Review/Inactive: 0 with FINAL.  
Flags: **FILLED 610 · FIXED 172**

Remaining Final gaps (157): mostly `accela_shell` Finaled/Closed with no inspections, plus planning Closed rows whose tasks end at Project Implementation without a closeout date.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 12 | 83 | 12 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 3 | 15 | 1,042 → 1,039 |
| FINAL_DATE | 610 | 172 | 1,485 → 878 |

## Artifacts

- Repair script: `agent/scripts/ca/data_repair_ca_concord.py`

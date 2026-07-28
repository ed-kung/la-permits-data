# Rancho Cucamonga (CA) data repair

**Summary:** Rancho Cucamonga was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. Assessed and repaired `STATUS_NORMALIZED`, `FILE_DATE`, `PERMIT_DATE`, and `FINAL_DATE` from the Accela Citizen Access `DATA` JSON. Status is now fully populated (**FILLED 11 · FIXED 19**): lagged `STATUS_ORIGINAL` mismatches against live `DATA.status` were corrected, and previously unmapped statuses (BPR Review, Released, typos, etc.) were filled. `FILE_DATE` was already complete and matched Accela sources (**0 changes**). `PERMIT_DATE` gained **17 FILLED · 4 FIXED** from `Permit Issuance` / Issued and KEY DATES `Permit Issued`. `FINAL_DATE` missingness fell from **1,246 → 920** (**FILLED 332 · FIXED 13**); Final-record coverage rose from **64.9% → 93.3%**.

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_ca_sample.parquet`
- Jurisdiction: **Rancho Cucamonga, CA** (n=1,999)
- Script: `agent/scripts/ca/data_repair_ca_rancho_cucamonga.py` (`data_repair`)

## DATA schema (`INFERRED_SCHEMA`)

All records are Accela Civic Access scrapes with top-level keys `status`, `tasks`, `search_data`, `more_details`, `inspections`, etc. Sub-schemas reflect which date sources are populated:

| Schema | n | Description |
| --- | ---: | --- |
| `accela_tasks` | 1,846 | Dated workflow events under `tasks` |
| `accela_shell` | 109 | Task shells present but no dated events |
| `accela_search_only` | 44 | No tasks; dates in `search_data` / `more_details` / `DATA.date` |

Canonical fields:

| Field | Source |
| --- | --- |
| `STATUS_NORMALIZED` | `DATA.status` (fallback: task event marks) |
| `FILE_DATE` | `search_data['Date']`; else `DATA.date`; else earliest Application Submittal event |
| `PERMIT_DATE` | `Permit Issuance` → Issued; else `more_details` KEY DATES `Permit Issued` |
| `FINAL_DATE` | `Inspections` → Final Inspection Complete; else `Closed` / `Permit Closure` finaling marks; else KEY DATES `Permit Final` / `Final`; else approved final inspection `Status Date` |

## Field assessment

### STATUS_NORMALIZED

**Before:** Final 1,147 · Active 424 · Inactive 225 · In Review 192 · missing 11

`DATA.status` maps cleanly for the bulk of rows. Main mappings:

| `DATA.status` | `STATUS_NORMALIZED` |
| --- | --- |
| Finalized, Finaled, Closed, Final Inspection Complete, Recorded at County, Temp C of O Issued, Complete, Released, 1-YR Maint. Period | Final |
| Issued, Approved, Inspection Phase, Pre-Inspection | Active |
| In Review, Pending, Incomplete, Invoiced, Ready to Issue, Out for Corrections, BPR Review, Fee Paid, RTI Pending, … | In Review |
| Expired, Withdrawn, Void, Inactive, Withdrawn-Closed | Inactive |

Issues:
1. **19 mis-normalized rows** where `STATUS_ORIGINAL` lagged live Accela `DATA.status` (e.g. `ready to issue` / `invoiced` / `in review` while `DATA.status=Issued`; `inspection phase` while Finalized or Expired).
2. **11 null `STATUS_NORMALIZED`:** unmapped originals — BPR Review (4), Released (2), In Reivew typo (1), Withdrwan typo (1), Fee Paid (1), RTI Pending (1), 1-YR Maint. Period (1).

**After:** Final 1,156 · Active 427 · Inactive 228 · In Review 188 · missing 0  
Flags: **FILLED 11 · FIXED 19**

### FILE_DATE

**Before:** 0 missing (100% populated).

`search_data['Date']` (RC’s Accela list date) plus `DATA.date` already match the existing `FILE_DATE` for all 1,999 rows. No fill or fix needed.

**After:** 0 missing.  
Flags: **FILLED 0 · FIXED 0**

### PERMIT_DATE

**Before:** 525 missing (26.3%). Among Active/Final: 228 / 1,571 missing.

When a `Permit Issuance` / Issued event exists, existing `PERMIT_DATE` usually matched; 4 rows had a different (incorrect) date vs the Issued event → FIXED. KEY DATES `Permit Issued` agrees with the task event in 1,108 / 1,123 dual-source rows (task date preferred when they disagree).

Gaps after repair are dominated by:
- **Approved** Active rows (72) with no Issued event or Permit Issued field (plan/entitlement approval without issuance).
- **Issued** / **Pre-Inspection** Active shells (17) lacking dated issuance sources.
- Final / Inactive historical rows without issuance events.

Repairs (Active / Final only for fills): earliest `Permit Issuance` → Issued, else KEY DATES `Permit Issued`.

**After:** missing 508 overall; Active 338/427 (79.2%) · Final 1,023/1,156 (88.5%) have `PERMIT_DATE`.  
Flags: **FILLED 17 · FIXED 4**

### FINAL_DATE

**Before:** 1,246 missing (62.3%). Among Final: 403 / 1,147 missing (35.1%).

Root causes for Final gaps:
1. Upstream often missed `Closed` / `Permit Closure` closure marks and KEY DATES `Permit Final`.
2. A minority of Closed records are empty shells (`accela_search_only` / `accela_shell`) with no finaling source.
3. 6+ non-Final rows carried spurious `FINAL_DATE` values (cleared when status remains non-Final).

Repairs:
1. Prefer `Inspections` → Final Inspection Complete.
2. Else `Closed` → Finalized / Finalize Permit; `Permit Closure` → Closed; then `Closed` → Closed.
3. Else KEY DATES `Permit Final` / `Final` (avoid LCP `Completion Date`, which is often a proposed date).
4. Else approved final inspection `Status Date`.
5. Clear `FINAL_DATE` on non-Final records.

**After:** missing 920 overall; Final 1,079/1,156 (93.3%) have `FINAL_DATE`. Remaining Final gaps are mostly Closed shells without dated events (44 search-only + 25 shell + 4 tasks) plus a few Recorded at County / Complete stubs.  
Flags: **FILLED 332 · FIXED 13**

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| `STATUS_NORMALIZED` | 11 | 19 | 11 → 0 |
| `FILE_DATE` | 0 | 0 | 0 → 0 |
| `PERMIT_DATE` | 17 | 4 | 525 → 508 |
| `FINAL_DATE` | 332 | 13 | 1,246 → 920 |

Post-repair coverage by status:

| Status | PERMIT_DATE | FINAL_DATE |
| --- | --- | --- |
| Active | 338 / 427 (79.2%) | 0 / 427 (0.0%) |
| Final | 1,023 / 1,156 (88.5%) | 1,079 / 1,156 (93.3%) |
| In Review | 1 / 188 (0.5%) | 0 / 188 (0.0%) |
| Inactive | 129 / 228 (56.6%) | 0 / 228 (0.0%) |

## Artifacts

- Repair script: `agent/scripts/ca/data_repair_ca_rancho_cucamonga.py`

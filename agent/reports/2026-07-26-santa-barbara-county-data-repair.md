# Santa Barbara County (CA) data repair

**Summary:** Santa Barbara County was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. Assessed and repaired `STATUS_NORMALIZED`, `FILE_DATE`, `PERMIT_DATE`, and `FINAL_DATE` from the Accela Citizen Access `DATA` JSON. Status is now fully populated (**FILLED 14 · FIXED 10**): unmapped payment/document/awaiting statuses were filled as In Review, and stale `STATUS_ORIGINAL`-based mappings (Closed→Active/In Review, Expired→In Review, Monitoring→In Review) were corrected from `DATA.status`. `FILE_DATE` already matched `DATA.date` for all 2,003 rows (no changes). `PERMIT_DATE` was corrected on **413** rows where the stored date matched Approved to Issue / FILE_DATE rather than `Permit Issuance` / Issued (**FIXED 413 · FILLED 0**); remaining Active/Final gaps are mostly parent Building General Application cases with no Issued event. `FINAL_DATE` was the main defect: missingness fell from **1,788 → 513** (**FILLED 1,352 · FIXED 215**), filling Closed / Finaled rows from `Follow-up and Close` / Closed (or Final*Inspection Clearance Approved), correcting wrongly sourced finals (often Initial Site Inspection), and clearing spurious finals on non-Final rows. After repair, **100% of Final rows have FINAL_DATE** and **100% of Active rows have PERMIT_DATE**.

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_ca_sample.parquet`
- Jurisdiction: **Santa Barbara County, CA** (n=2,003)
- Script: `agent/scripts/ca/data_repair_ca_santa_barbara_county.py` (`data_repair`)

## DATA schema (`INFERRED_SCHEMA`)

All records are Accela Citizen Access scrapes with top-level keys `status`, `date`, `tasks`, `more_details`, `search_data`, etc. Sub-schemas reflect which optional Accela blocks are present and whether dated workflow events exist:

| Schema | n | Description |
| --- | ---: | --- |
| `accela_full` | 828 | Has `inspections` / `conditions` / `fees_details` |
| `accela_minimal` | 591 | Core keys only (no contacts / inspections) |
| `accela_contacts` | 566 | Has `contacts` / `address_lines` but no inspections block |
| `accela_shell` | 18 | Tasks present but no dated events |

Canonical fields:

| Field | Source |
| --- | --- |
| `STATUS_NORMALIZED` | `DATA.status` |
| `FILE_DATE` | `DATA.date` (fallback: `search_data['Date']`) |
| `PERMIT_DATE` | `Permit Issuance` / Issued; else any Issued mark; else Approved to Issue |
| `FINAL_DATE` | `Follow-up and Close` / Closed; else Final*Inspection / Clearance Approved |

`more_details` does not carry usable Permit Master issue/status dates (unlike Stockton).

## Field assessment

### STATUS_NORMALIZED

**Before:** Final 1,486 · Active 230 · Inactive 171 · In Review 102 · missing 14

Issues:
1. **14 null `STATUS_NORMALIZED`** rows whose `DATA.status` values were never mapped upstream (Document or Payment Pending, Updated Documents Added, Payment Pending Only, Awaiting*, Case(s) Created, etc.) → **FILLED** as In Review.
2. **10 mis-normalized rows** relative to current `DATA.status` (upstream appears to have used stale `STATUS_ORIGINAL`):
   - Monitoring In Progress → In Review (5) → **Active** (post-issuance petroleum monitoring)
   - Closed → Active (3) / In Review (1) → **Final**
   - Expired → In Review (1) → **Inactive**

When present, `DATA.status` maps cleanly:

| `DATA.status` | `STATUS_NORMALIZED` |
| --- | --- |
| Closed, Finaled | Final |
| Issued, Permit Active, Account Active, Final Processing, Monitoring In Progress | Active |
| Expired, Void, Withdrawn | Inactive |
| In Review, Open, Accepted, Submitted, Submittal*, Payment/Document Pending*, Awaiting*, Approved to Issue, Case(s) Created, … | In Review |

**After:** Final 1,490 · Active 232 · Inactive 172 · In Review 109 · missing 0  
Flags: **FILLED 14 · FIXED 10**

### FILE_DATE

**Before:** 0 missing (100%).

- Every row’s `FILE_DATE` equals `DATA.date`.
- `search_data['Date']` mirrors the same calendar day when present.

**After:** still 0 missing.  
Flags: **FILLED 0 · FIXED 0**

### PERMIT_DATE

**Before:** 246 missing (12.3%). Among Active/Final: 80 / 1,716 missing (all on Final; Active already 100%).

Root cause for incorrect values: all **413** mismatched `PERMIT_DATE` values matched `Permit Issuance` / Approved to Issue rather than the later Issued event.

Repairs:
1. Prefer earliest `Permit Issuance` → Issued as canonical (**FIXED** when present and different).
2. Else any Issued mark; else Approved to Issue (fill-only fallback).
3. **FILL** only for Active / Final when missing and a source date exists.

**After:** still 246 missing overall. Active 100% · Final 94.6% populated.  
Flags: **FILLED 0 · FIXED 413**

Not repairable: 81 Final rows lack an Issued event — mostly **Building General Application** parent cases that close after spawning related child permits (`related_records`), plus a handful of legacy Closed shells.

### FINAL_DATE

**Before:** 1,788 missing (89.3%). Among Final: 1,349 / 1,486 missing. Existing non-null finals (215) were largely **wrong**: they matched Initial Site Inspection / Complete, Zoning / plan-review clearances, or PERMIT_DATE — almost never `Follow-up and Close` / Closed. 77+ non-Final rows also carried a FINAL_DATE.

Root cause: upstream never used the Accela closure task; Finaled / solar rows without a Closed mark still have Final*Inspection Clearance Approved available.

Repairs:
1. Fill / correct from latest `Follow-up and Close` / Closed.
2. Else latest Final*Inspection (name contains Final + Inspection) / Clearance Approved (covers Finaled and SolarApp Closed shells).
3. Clear FINAL_DATE when effective status is not Final (**FIXED** to null).

**After:** 513 missing (25.6%) — all on non-Final rows. **Final 100% populated** · Active / In Review / Inactive 0%.  
Flags: **FILLED 1,352 · FIXED 215** (77 clears on non-Final + 138 date corrections on Final)

## Repair performance (sample)

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | ---: | ---: | ---: | ---: |
| STATUS_NORMALIZED | 14 | 10 | 14 | 0 |
| FILE_DATE | 0 | 0 | 0 | 0 |
| PERMIT_DATE | 0 | 413 | 246 | 246 |
| FINAL_DATE | 1,352 | 215 | 1,788 | 513 |

## Artifacts

- Repair script: `agent/scripts/ca/data_repair_ca_santa_barbara_county.py`
- Summary parquet: `AGENT_DATA_PATH/santa_barbara_county_repair/repair_summary.parquet`

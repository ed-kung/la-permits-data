# Stanislaus County data repair

**Summary:** Assessed and repaired STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for 2,000 Stanislaus County (CA) sample rows. DATA is an Accela Citizen Access scrape (`status` / `date` / `tasks` / `inspections`). Status gaps were mostly ACA Issued left as In Review and a handful of unmapped / stale labels. FILE_DATE was already complete. PERMIT_DATE gained 611 fills from Issue Permit / Issued workflow events (Active coverage 44%→97%). FINAL_DATE gained 62 fills from Inspection Finaled / Project Close Out Closed and Filed / passed Final* inspections; 3 spurious Active finals were cleared. Remaining Final gaps are mostly Closed planning shells with empty tasks.

## Jurisdiction selection

First `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` appearance order without `agent/scripts/{state}/data_repair_{state}_{city}.py`: **Stanislaus County, CA**.

## DATA schema

Accela portal payload. Top-level keys on nearly all rows: `date`, `status`, `tasks`, `inspections`, `details`, `more_details`, `search_data`, `fees_details`, `contacts`, `conditions`, `related_records`, etc. Two sparse rows omit contacts/inspections/fees.

`INFERRED_SCHEMA` content variants:

| Schema | n |
| --- | ---: |
| accela_full_issued_finaled | 825 |
| accela_full_empty_tasks | 605 |
| accela_full_other_events | 302 |
| accela_full_issued | 251 |
| accela_full_finaled_only | 15 |
| accela_partial_issued | 1 |
| accela_partial_empty_tasks | 1 |

Canonical sources:
- **STATUS_NORMALIZED** ← `DATA.status`
- **FILE_DATE** ← `DATA.date` (fallback: `search_data.Date`, earliest fee Date)
- **PERMIT_DATE** ← earliest `Issue Permit` / `Re-Issue Permit`, else `Issued`/`ACA Issued`/`TMHP Issued` on Application Submittal / Ready to Issue / Permit Issuance, else any Issued, else Ready to Issue mark
- **FINAL_DATE** ← latest Inspection(s)/Finaled `Finaled` mark; else Project Close Out `Closed and Filed`; else passed Final* inspection `Status Date`

## Field assessment

### STATUS_NORMALIZED

Before: Final 1,538 / In Review 227 / Active 132 / Inactive 98 / missing 5.

Issues:
- **ACA Issued** (48) mapped to In Review → should be Active
- **TMHP Issued** (2) missing → Active
- **CEQA** (2), **Loan Documents** (1) missing → In Review
- Stale `STATUS_ORIGINAL`: Finaled still Active (2), Expired still Active (1), Issued still In Review (1)

After repair: Final 1,540 / Active 180 / In Review 181 / Inactive 99 / missing 0.  
Flags: **FILLED 5, FIXED 52**.

### FILE_DATE

Already populated for all 2,000 rows and equal to `DATA.date`. No changes (**FILLED 0, FIXED 0**).

### PERMIT_DATE

Before: missing 1,569 (78.4%). Active had only 58/132 (44%); Final 362/1,538 (23.5%).

Root cause: upstream often captured Ready to Issue / Issue Permit only when that workflow task existed; over-the-counter / ACA rows store issuance as Application Submittal marked `Issued`, which was left blank.

After repair: missing 958. Active 174/180 (96.7%); Final 857/1,540 (55.6%).  
Flags: **FILLED 611, FIXED 0**.

Remaining Active/Final gaps are Closed planning / PFF / empty-task shells with no Issue*/Issued event.

### FINAL_DATE

Before: missing 1,162. Present on 835/1,538 Final; 3 spurious dates on Active (Issued status with an Inspection `Finaled` mark while live status remained Issued).

After repair: missing 1,103. Final 897/1,540 (58.2%); Active/In Review/Inactive all 0.  
Flags: **FILLED 62, FIXED 8** (5 date corrections to latest Finaled mark + 3 Active clears).

Unfilled Final rows are overwhelmingly `Closed` Projects / Public Facility Fee shells with empty tasks and no Final* inspection (~640).

## Repair performance

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | ---: | ---: | ---: | ---: |
| STATUS_NORMALIZED | 5 | 52 | 5 | 0 |
| FILE_DATE | 0 | 0 | 0 | 0 |
| PERMIT_DATE | 611 | 0 | 1,569 | 958 |
| FINAL_DATE | 62 | 8 | 1,162 | 1,103 |

Chronology after repair: PERMIT &lt; FILE = 0; FINAL &lt; PERMIT = 0.

## Artifacts

- Script: `agent/scripts/ca/data_repair_ca_stanislaus_county.py` (`data_repair`)
- Repaired parquet: `$AGENT_DATA_PATH/repaired/permits_ca_stanislaus_county_repaired.parquet`

# San Bernardino County (CA) data repair

**Summary:** Assessed and repaired `STATUS_NORMALIZED`, `FILE_DATE`, `PERMIT_DATE`, and `FINAL_DATE` for San Bernardino County — the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. All 2,000 sample rows share one Accela Citizen Access DATA schema (`tasks`). Status gaps and stale `STATUS_ORIGINAL`-derived labels were corrected from `DATA.status` (FILLED 35 · FIXED 14; missing → 0). `FILE_DATE` already matched `DATA.date` on every row. `PERMIT_DATE` was wrong on 70 rows that used Permit Issuance intermediate dates (especially Ready to Issue) instead of Issued, and 5 Active/Final gaps with an Issued event were filled. `FINAL_DATE` gained 132 fills from inspection / closure / recordation events, and 13 spurious finals on Active (Issued) rows were cleared. After repair: Final has 76.0% `PERMIT_DATE` and 78.0% `FINAL_DATE`; Active has 62.7% `PERMIT_DATE`; non-Final rows have 0% `FINAL_DATE`. Remaining Active/Final date gaps are mostly Approved/Active/Complete/Closed/Recorded records with no Issued or finaling event in DATA.

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_ca_sample.parquet`
- Jurisdiction: **San Bernardino County, CA** (n=2,000)
- Script: `agent/scripts/ca/data_repair_ca_san_bernardino_county.py` (`data_repair`)
- Artifact: `AGENT_DATA_PATH/repairs/permits_ca_san_bernardino_county_repaired.parquet`

## DATA schema (`INFERRED_SCHEMA`)

| Schema | n | Description |
| --- | ---: | --- |
| `tasks` | 2,000 | Accela portal payload: `date`, `status`, `tasks`, `inspections`, `search_data`, `details`, `contacts`, `fees_details`, etc. |

Task event keys have leading/trailing spaces (`Marked as `, ` on `), same as Downey and other Accela cities.

Canonical fields:

| Field | Source |
| --- | --- |
| `STATUS_NORMALIZED` | `DATA.status` |
| `FILE_DATE` | `DATA.date` |
| `PERMIT_DATE` | Permit Issuance / Issued (fallback: Application Review / Issued) |
| `FINAL_DATE` | Inspections/Inspection Final or Complete; else inspection Status Date (Final / Pass); else Closure / Project Closure / Job Closure / Recordation |

## Field assessment

### STATUS_NORMALIZED

**Before:** Final 642 · Active 637 · Inactive 378 · In Review 308 · missing 35

Issues:
1. **35 missing** — unmapped `STATUS_ORIGINAL` values: Part 1/2 Approved (25), blank status (3), Contractor Info Required (3), Approved with Comments (2), Waiver Denied (1), plus one Issued row whose original status was null. Filled from `DATA.status` (Part approvals / conditional approvals → In Review; Waiver Denied → Inactive; Issued → Active; blank → In Review).
2. **Stale original vs current portal status (14)** — `STATUS_NORMALIZED` was derived from `STATUS_ORIGINAL` while `DATA.status` had moved on:
   - Active → Final (5): `STATUS_ORIGINAL=issued` but `DATA.status=Final` (electrical/plumbing/pool/etc. with Final inspections).
   - In Review → Active (6): Issued or Approved still labeled In Review.
   - Final → Active (2): Fire Special Event `Inspection Required` wrongly labeled Final (inspection still TBD).
   - In Review → Final (1): Complete labeled In Review.

**After:** Final 646 · Active 641 · In Review 334 · Inactive 379 · missing 0  
Flags: **FILLED 35 · FIXED 14**

### FILE_DATE

**Before:** 0 missing (100%).

- `FILE_DATE` matches `DATA.date` at calendar-day resolution for all 2,000 rows. No alternate application date needed.

**After:** still 0 missing.  
Flags: **FILLED 0 · FIXED 0**

### PERMIT_DATE

**Before:** 1,074 missing (53.7%). By then-current status: Active 236/637 missing (37.0%); Final 156/642 missing (24.3%).

Where both `PERMIT_DATE` and Permit Issuance / Issued existed (923 rows), 853 matched exactly and **70 mismatched**. Mismatches almost always equaled an earlier Permit Issuance intermediate date — especially Ready to Issue — rather than Issued.

Repairs:
- Overwrite mismatched dates with earliest Permit Issuance / Issued (**70 FIXED**).
- Fill Active/Final gaps that have an Issued event (**5 FILLED**; includes rows whose status was corrected to Active).

Remaining Active/Final gaps after repair:
- **Active 239:** mostly `Approved` (132) and `Active` (92) with no Issued task event; also 11 `Issued` shells with empty Permit Issuance events.
- **Final 155:** `Complete` (92), `Closed` (46), `Recorded` (17) — administrative / addressing / fire-annual / recordation types that never record a building-permit issuance.

No reliable Accela proxy (OTC Approval, etc.) exists for these gaps in this sample, so they are left missing.

**After:** missing 1,069. Active 402/641 (62.7%) · Final 491/646 (76.0%).  
Flags: **FILLED 5 · FIXED 70**

### FINAL_DATE

**Before:** 1,615 missing; Final missing 270/642 (42.1%); **13 Active rows** carried `FINAL_DATE` (12 Issued + 1 Inspection Complete) despite `DATA.status` still Active/Issued.

Existing Final `FINAL_DATE` values overwhelmingly match Inspections/Inspection Final or Complete task events plus Final/Pass inspection Status Dates (360/362 agree with the preferred inspection-task Final source).

Repairs:
- Fill Final gaps from inspection Final/Complete, Final/Pass inspection Status Dates, or Closure / Project Closure / Job Closure / Recordation (**132 FILLED**).
- Clear spurious `FINAL_DATE` on non-Final rows (**13 FIXED** clears).
- Correct 2 Final rows whose stored date disagreed with the preferred finaling source (**2 FIXED** overwrites).

Remaining Final gaps (142): `Complete` (80), `Closed` (41), `Final` (21) — typically Addressing-New, fire annual, CDWMP, or issued permits with empty Inspections tasks and no Final/Pass inspections.

**After:** missing 1,496 overall (net drop reflects fills minus clears). Final 504/646 (78.0%); Active / In Review / Inactive 0%.  
Flags: **FILLED 132 · FIXED 15**

## Repair performance

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | ---: | ---: | ---: | ---: |
| `STATUS_NORMALIZED` | 35 | 14 | 35 | 0 |
| `FILE_DATE` | 0 | 0 | 0 | 0 |
| `PERMIT_DATE` | 5 | 70 | 1,074 | 1,069 |
| `FINAL_DATE` | 132 | 15 | 1,615 | 1,496 |

Post-repair coverage by status:

| Status | n | `PERMIT_DATE` | `FINAL_DATE` |
| --- | ---: | ---: | ---: |
| Active | 641 | 62.7% | 0.0% |
| Final | 646 | 76.0% | 78.0% |
| In Review | 334 | 2.4% | 0.0% |
| Inactive | 379 | 7.9% | 0.0% |

## Files

- `agent/scripts/ca/data_repair_ca_san_bernardino_county.py`
- `AGENT_DATA_PATH/repairs/permits_ca_san_bernardino_county_repaired.parquet`
- `agent/reports/2026-07-25-san-bernardino-county-data-repair.md`

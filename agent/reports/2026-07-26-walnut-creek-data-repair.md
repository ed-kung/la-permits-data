# Walnut Creek (CA) data repair

**Summary:** Walnut Creek was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. Assessed and repaired `STATUS_NORMALIZED`, `FILE_DATE`, `PERMIT_DATE`, and `FINAL_DATE` from the Accela Citizen Access `DATA` JSON. Status is nearly complete (**FILLED 2 · FIXED 57**; 3 Administrative Documentation shells remain null). `FILE_DATE` already matched `DATA.date` for all 2,000 rows (no changes). `PERMIT_DATE` missingness fell from **1,582 → 1,423** (**FILLED 159**) by picking up `Online Permit` / Issued events that upstream ignored. `FINAL_DATE` missingness fell from **1,585 → 784** (**FILLED 801**), mainly from Approved `050 PROJECT FINAL` inspections on legacy rows plus Inspections / Final Admin Finaled task events. Remaining gaps are mostly pre-~2016 Accela shells with empty task events and no Issued mark.

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_ca_sample.parquet`
- Jurisdiction: **Walnut Creek, CA** (n=2,000)
- Script: `agent/scripts/ca/data_repair_ca_walnut_creek.py` (`data_repair`)

## DATA schema (`INFERRED_SCHEMA`)

All records are Accela Civic Access scrapes with top-level keys `status`, `date`, `tasks`, `inspections`, `more_details`, `search_data`, etc. Sub-schemas reflect which date sources are populated:

| Schema | n | Description |
| --- | ---: | --- |
| `accela_inspections` | 785 | No dated task events; usable dates from Approved PROJECT / BUILDING FINAL inspections |
| `accela_shell` | 549 | No dated task events and no usable final inspection dates |
| `accela_tasks_and_inspections` | 419 | Both dated task events and Approved final inspections |
| `accela_tasks` | 247 | Dated workflow events under `tasks` only |

Canonical fields:

| Field | Source |
| --- | --- |
| `STATUS_NORMALIZED` | `DATA.status` |
| `FILE_DATE` | `DATA.date` (fallback: `search_data['Date']`) |
| `PERMIT_DATE` | `Ready to Issue` → Issued\|Re-Issued; else `Online Permit` → Issued; else any Issued mark |
| `FINAL_DATE` | Inspections / Finaled; Final Admin Processing / Finaled (`min(on, due)`); Closed; else Approved `PROJECT FINAL` / BUILDING FINAL inspection Status Date |

## Field assessment

### STATUS_NORMALIZED

**Before:** Final 1,347 · In Review 386 · Inactive 171 · Active 91 · missing 5

Issues:
1. **57 mis-normalized rows** relative to `DATA.status`:
   - Revision Issued → In Review (52) — revision was issued → Active
   - Finaled → Active (3) → Final (also unlocked FINAL_DATE fill)
   - Issued → In Review (2) → Active
2. **2 null `STATUS_NORMALIZED`** with usable `DATA.status`: Revision Issued → Active; Admin OTC Consolidation → In Review.
3. **3 Administrative Documentation** rows (`AD-00053`, `AD-00013`, `AD-00070`) have null `DATA.status` and empty task shells → left missing.

When present, `DATA.status` maps cleanly:

| `DATA.status` | `STATUS_NORMALIZED` |
| --- | --- |
| Finaled, FINAL, COMPLETE, Closed | Final |
| Issued, Revision Issued, Approved, Final Pending, Renewed | Active |
| PENDING, Received, In Review, Ready to Issue, Conditionally Approved, With Customer for Response, Routed, Resubmittal Required, Research, Affidavit, Admin OTC Consolidation | In Review |
| Expired, Cancelled, Void/void, Withdrawn, Plan Check Expired, Dropped, Application Voided | Inactive |

**After:** Final 1,350 · In Review 333 · Inactive 171 · Active 143 · missing 3  
Flags: **FILLED 2 · FIXED 57**

### FILE_DATE

**Before:** 0 missing (100%).

- Every row’s `FILE_DATE` equals `DATA.date`.
- `search_data['Date']` mirrors the same calendar day when present.

**After:** still 0 missing.  
Flags: **FILLED 0 · FIXED 0**

### PERMIT_DATE

**Before:** 1,582 missing (79.1%). Among Active/Final: 1,119 / 1,438 missing.

Root cause: upstream only populated issuance from `Ready to Issue` / Issued (~318 rows). Another ~152 Active/Final rows have `Online Permit` / Issued (common for OTC / online MEP permits) that were ignored. Most pre-~2016 Finaled shells have empty task event lists and no Issued mark at all.

Repairs (Active / Final only):
1. Prefer earliest `Ready to Issue` → Issued\|Re-Issued.
2. Else earliest `Online Permit` → Issued\|Re-Issued.
3. Else any other Issued\|Re-Issued mark.

**After:** missing 1,423 overall. Active: **125 / 143 (87.4%)** populated; Final: **405 / 1,350 (30.0%)**.  
Flags: **FILLED 159 · FIXED 0**

Not repairable: ~945 Final + 18 Active rows with no Issued task event (almost all `accela_inspections` / `accela_shell`).

### FINAL_DATE

**Before:** 1,585 missing (79.2%). Among Final: 932 / 1,347 missing. No spurious FINAL_DATE on non-Final rows.

Root cause: upstream used Inspections / Finaled when present (~415 rows) but ignored (1) Final Admin Processing / Finaled and (2) the inspections list, where legacy Finaled records almost always have Approved `050 PROJECT FINAL` with a Status Date.

Repairs (Final only):
1. Earliest Inspections / Finaled `on` date.
2. Final Admin Processing / Finaled using `min(on, due)` (handles Accela’s mixed Due-on vs stamp-on patterns).
3. Closed task marks.
4. If still missing: Approved `PROJECT FINAL` Status Date, else Approved BUILDING / POOL FINAL (FILL only; never overwrite an existing FINAL_DATE with these weaker sources).

**After:** missing 784 overall. Final: **1,216 / 1,350 (90.1%)** populated.  
Flags: **FILLED 801 · FIXED 0**

Not repairable: 134 Final rows with no Finaled/Closed event and no Approved final inspection.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 2 | 57 | 5 → 3 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 159 | 0 | 1,582 → 1,423 |
| FINAL_DATE | 801 | 0 | 1,585 → 784 |

## Artifacts

- Repair script: `agent/scripts/ca/data_repair_ca_walnut_creek.py`

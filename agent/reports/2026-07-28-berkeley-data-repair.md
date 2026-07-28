# Berkeley (CA) data repair

**Summary:** Berkeley was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. Assessed and repaired `STATUS_NORMALIZED`, `FILE_DATE`, `PERMIT_DATE`, and `FINAL_DATE` from the Accela Citizen Access `DATA` JSON (`status` / `date` / `tasks` / `inspections`). Status: **0 missing before/after**; **FIXED 15** (Finaled mislabeled Active/Inactive; Issued mislabeled In Review; Closed Expired mislabeled In Review; Active/In Review upgraded to Final on Finaled inspection signal). `FILE_DATE` already matched `DATA.date` for all 1,999 rows (**FILLED 0 · FIXED 0**). `PERMIT_DATE` missingness fell **1,133 → 1,128** (**FILLED 5**) after correcting Issued → Active. `FINAL_DATE` missingness fell **1,458 → 1,428** (**FILLED 32 · FIXED 4**); Final coverage is **571 / 1,060 (53.9%)**, with Active / In Review / Inactive at 0 final dates. No chronology inversions remain (**FILE>PERMIT=0**, **PERMIT>FINAL=0**).

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_ca_sample.parquet`
- Jurisdiction: **Berkeley, CA** (n=1,999) — first pair lacking `agent/scripts/{state}/data_repair_{state}_{city}.py`
- Script: `agent/scripts/ca/data_repair_ca_berkeley.py` (`data_repair`)
- Artifact: `AGENT_DATA_PATH/repaired/permits_ca_berkeley_repaired.parquet`

## DATA schema (`INFERRED_SCHEMA`)

All records are Accela Citizen Access scrapes with top-level keys including `status`, `date`, `tasks`, `search_data`, `details`, `more_details`, `record_type`, and (when present) `inspections` / `contacts` / `conditions` / `fees_details`. Sub-schemas reflect workflow richness:

| Schema | n | Description |
| --- | ---: | --- |
| `tasks_only` | 1,195 | Tasks present; inspections key missing or empty (includes 447 Closed Complete lean shells with empty Issuance/Inspection events) |
| `tasks_inspections` | 804 | Non-empty `tasks` and non-empty `inspections` |

Canonical fields:

| Field | Source |
| --- | --- |
| `STATUS_NORMALIZED` | `DATA.status` (= `search_data.Status`); upgrade Active/In Review → Final when Inspection is Finaled or a Final\* inspection is Approved |
| `FILE_DATE` | `DATA.date` (fallback: `search_data.Date`) |
| `PERMIT_DATE` | earliest `Issuance` task event Marked as Issued/Issue |
| `FINAL_DATE` | latest `Inspection` task event Marked as Finaled/Final; else latest Final\* inspection `Status Date` with Approved / Approve / Approved with Conditions |

`PermitExpirationDate` is not present. Certificate of Occupancy task events are almost always TBD and are not used.

## Field assessment

### STATUS_NORMALIZED

**Before:** Final 1,051 · Inactive 620 · Active 194 · In Review 134 · missing 0

`DATA.status` → expected mapping:

| `DATA.status` | `STATUS_NORMALIZED` |
| --- | --- |
| Finaled, Closed Complete, Closed | Final |
| Issued | Active |
| Documents Required, Corrections List Issued, Under Review, Waiting for Review, Approved w/Conditions, Ready to Issue, Open, Received, Pending Payment, Documents Uploaded | In Review |
| Closed Expired, Closed Error, Closed Cancelled, Denied | Inactive |

Issues:
1. **Stale labels vs `DATA.status` (13 FIXED):**
   - Finaled → Active (6) / Inactive (1) → Final
   - Issued → In Review (5) → Active
   - Closed Expired → In Review (1) → Inactive
2. **Finaled inspection override (2 FIXED):** Issued (1) and Under Review (1) with a dated Inspection/Finaled (or approved Final\* inspection) → Final. Closed Expired rows with a Finaled signal stay Inactive (expired terminal status takes precedence).

**After:** Final 1,060 · Inactive 620 · Active 192 · In Review 127 · missing 0  
Flags: **FILLED 0 · FIXED 15**

### FILE_DATE

**Before:** 0 missing (100%).

- `FILE_DATE` equals `DATA.date` (and `search_data.Date`) for all 1,999 rows.
- Application Submittal task dates sometimes differ (later workflow stamps); Accela header date is treated as canonical.

**After:** still 0 missing.  
Flags: **FILLED 0 · FIXED 0**

Coverage after: **100%**.

### PERMIT_DATE

**Before:** 1,133 missing (56.7%). Among Active/Final: 520 / 1,245 missing (all on Final).

- When an Issuance/Issued|Issue date exists, `PERMIT_DATE` always matched it (865 agree, 0 disagree).
- **FILLED 5:** Issued rows previously labeled In Review; after status → Active, Issuance date populated.
- Large residual gap: 447 Closed Complete lean shells have empty Issuance events; 46 Finaled + 27 Closed also lack dated Issuance → not fillable from DATA.

**After:** 1,128 missing. Active coverage **192 / 192 (100%)**; Final **540 / 1,060 (50.9%)**.  
Flags: **FILLED 5 · FIXED 0**

### FINAL_DATE

**Before:** 1,458 missing (72.9%). Among Final: 513 / 1,051 missing.

- Inspection/Finaled task dates mostly agreed with `FINAL_DATE` (538 agree); 2 rows used the first of multiple Finaled events instead of the latest → **FIXED**.
- **FILLED 32:** 26 already-Final rows from approved Final\* inspections; 5 Active→Final and 1 Inactive→Final after status repair from Inspection/Finaled.
- **FIXED 2 clears:** spurious `FINAL_DATE` on Active (no final signal) and Inactive Closed Expired.
- Residual: 447 Closed Complete + 27 Closed + 15 Finaled lack both Inspection/Finaled and an approved Final\* inspection.

**After:** 1,428 missing. Final coverage **571 / 1,060 (53.9%)**; Active / In Review / Inactive at 0.  
Flags: **FILLED 32 · FIXED 4**

## Performance summary

| Field | Missing before | Missing after | FILLED | FIXED |
| --- | ---: | ---: | ---: | ---: |
| STATUS_NORMALIZED | 0 | 0 | 0 | 15 |
| FILE_DATE | 0 | 0 | 0 | 0 |
| PERMIT_DATE | 1,133 | 1,128 | 5 | 0 |
| FINAL_DATE | 1,458 | 1,428 | 32 | 4 |

Chronology after repair: **FILE>PERMIT=0**, **PERMIT>FINAL=0**.

Main limitation: Closed Complete lean shells (`tasks_only`, empty workflow events, no inspections) are correctly labeled Final but cannot recover issuance or finaling dates from `DATA`.

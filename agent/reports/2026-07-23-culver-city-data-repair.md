# Culver City Data Repair Assessment

## Summary

Assessed the correctness of STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for 2,000 Culver City permit records from `permits_la_sample.parquet`. Found issues in three of the four fields: 4 missing STATUS_NORMALIZED values, 5 incorrect PERMIT_DATE values (populated with CO Issuance date instead of Permit Issuance date), and widespread missing PERMIT_DATE and FINAL_DATE values that can be partially filled from the raw DATA JSON. FILE_DATE required no repairs. A `data_repair` function was written to fix these issues.

## Data Structure

The Culver City DATA column contains two distinct schemas:

- **Tasks schema** (873 records): Rich workflow data with a `tasks` list containing events (e.g., "Application Submittal", "Permit Issuance", "Inspection", "Closed"). Also includes `date` and `status` fields.
- **Flat schema** (1,122 records): Structured record with `RecordStatus`, `DateOpened`, `StatusDate`, `PermitType`, etc. Many flat records have empty `StatusDate`, limiting repair potential.
- **Search-data-only** (4 records): Minimal metadata with no status or date information.
- **Empty tasks** (1 record): Has the tasks structure but with empty event lists.

## Findings by Field

### STATUS_NORMALIZED

**8 missing values**, 4 of which were fillable:

| Root cause | Count | Resolution |
|---|---|---|
| `DATA.status = "Corrections Sent - EDR"` | 4 | FILLED → "In Review" |
| No status data at all (search-data-only schema) | 4 | Cannot fill |

All other 1,992 records had correct STATUS_NORMALIZED values. Cross-tabulation of `STATUS_ORIGINAL` and `DATA.status` against STATUS_NORMALIZED confirmed accurate mappings across all status values (Finaled → Final, Issued → Active, Void → Inactive, etc.).

**Note:** 12 records have `STATUS_ORIGINAL = "not approved"` mapped to "In Review". This mapping is debatable — "Not Approved" could mean "denied" (Inactive) or "not yet approved" (In Review). One record (row 19969) has review activity as recent as July 2025, supporting "In Review". The current mapping was left unchanged.

### FILE_DATE

**No issues found.** All 2,000 records have FILE_DATE populated. Where `DATA.date` was available (874 records), FILE_DATE matched perfectly.

### PERMIT_DATE

**1,385 missing values** before repair. 5 incorrect values found.

| Issue | Count | Resolution |
|---|---|---|
| PERMIT_DATE set to CO Issuance date instead of Permit Issuance date | 5 | FIXED to actual Permit Issuance/Issued date |
| Missing, fillable from tasks "Permit Issuance / Issued" event | 274 | FILLED |
| Missing, fillable from flat schema StatusDate (Approved records) | 5 | FILLED |
| Missing, no data available | 1,101 | Cannot fill |

The 5 FIXED records (rows 18333, 18343, 18396, 18505, 18511) had their PERMIT_DATE set to the Certificate of Occupancy issuance date rather than the building permit issuance date. The CO Issuance events occurred years after the actual permit was issued. For the 3 records where FINAL_DATE was also missing, the CO date was repurposed as FINAL_DATE (see below).

After repair: **1,106 still missing** (primarily flat-schema records with empty `StatusDate`).

### FINAL_DATE

**1,227 missing values** before repair, including 853 for "Final" status records.

| Issue | Count | Resolution |
|---|---|---|
| Missing, fillable from tasks "Closed / Finaled" event | 264 | FILLED |
| Missing, fillable from tasks "CO Issuance" event | 3 | FILLED |
| Missing, tasks exist but no finaled event | 7 | Cannot fill |
| Missing, no tasks data available (flat/search-data-only) | 579 | Cannot fill |

All 773 pre-existing FINAL_DATE values were verified correct against task data (zero mismatches).

After repair: **960 still missing** (586 Final records without source data).

## Repair Summary

| Field | FILLED | FIXED | Still Missing |
|---|---|---|---|
| STATUS_NORMALIZED | 4 | 0 | 4 |
| FILE_DATE | 0 | 0 | 0 |
| PERMIT_DATE | 279 | 5 | 1,106 |
| FINAL_DATE | 267 | 0 | 960 |

## Artifacts

- Repair script: `agent/scripts/culver_city_data_repair.py`

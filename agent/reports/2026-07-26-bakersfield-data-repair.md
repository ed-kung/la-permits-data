# Bakersfield (CA) data repair

**Summary:** Assessed and repaired `STATUS_NORMALIZED`, `FILE_DATE`, `PERMIT_DATE`, and `FINAL_DATE` for Bakersfield — the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. DATA is a city permit-portal scrape with two schemas (`permit_status` 1,978 · `detail_only` 22). Status is now fully populated (FILLED 22 · FIXED 49): the main corrections were Application Status `REVOKED`/`EXPIRED` rows still labeled Active/In Review from a lagging `Status for Permit Number`. `FILE_DATE` already matched `Application Date` on every row. The largest repair was `PERMIT_DATE`: 1,088 Final rows used `Permit Date`, which is frequently overwritten to the finalization date (828 rows had `PERMIT_DATE == FINAL_DATE` before; 4 after) — corrected to `Issue Date`. Spurious `PERMIT_DATE` on In Review / never-issued Inactive shells was cleared (107). `FINAL_DATE` gained 2 fills on temporary C.O. rows; Final coverage is 1,375 / 1,404 (97.9%).

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_ca_sample.parquet`
- Jurisdiction: **Bakersfield, CA** (n=2,000)
- Script: `agent/scripts/ca/data_repair_ca_bakersfield.py` (`data_repair`)
- Artifact: `AGENT_DATA_PATH/bakersfield_repaired_sample.parquet`

## DATA schema (`INFERRED_SCHEMA`)

| Schema | n | Description |
| --- | ---: | --- |
| `permit_status` | 1,978 | `detail` + `permit_status_detail` + `insp_status_detail` (+ fee/status headers) |
| `detail_only` | 22 | `detail` / fees only — no permit or inspection blocks |

Canonical fields:

| Field | Source |
| --- | --- |
| `STATUS_NORMALIZED` | `Status for Permit Number`; Application Status `REVOKED`/`EXPIRED` override; detail_only uses Application Status |
| `FILE_DATE` | `detail['Application Date']` |
| `PERMIT_DATE` | `Issue Date` (fallback `Permit Date`) for Active/Final / permit-revoked Inactive |
| `FINAL_DATE` | Latest APPROVED `FINAL*` / `CERTIFICATE OF OCCUPANCY` on/after `FILE_DATE`; else latest APPROVED inspection |

## Field assessment

### STATUS_NORMALIZED

**Before:** Final 1,405 · Active 437 · In Review 107 · Inactive 29 · missing 22

Issues:
1. **22 `detail_only` rows** with null `STATUS_ORIGINAL` / `STATUS_NORMALIZED` (PENDING VERIFICATION, APPROVED, REVOKED, etc.).
2. **Application Status `REVOKED` (48) / `EXPIRED` (7)** still mapped from lagging permit status → Active (25), In Review (23), or Final (1).

**After:** Final 1,404 · Active 412 · In Review 100 · Inactive 84 · missing 0  
Flags: **FILLED 22 · FIXED 49**

### FILE_DATE

**Before:** 0 missing (100%).

- Every row’s `FILE_DATE` equals `detail['Application Date']` at calendar-day resolution.
- No fills or fixes.

**After:** still 0 missing.  
Flags: **FILLED 0 · FIXED 0**

### PERMIT_DATE

**Before:** 22 missing (all `detail_only`). Where present on Final rows, values matched `Permit Date`, not `Issue Date`.

Root cause: on finaled permits, `Permit Date` is often overwritten to the finalization date (`PERMIT_DATE == FINAL_DATE` on 828 rows). `Issue Date` is the true first-issuance date (empty on only 85 rows, mostly In Review). In Review `plan check` / `to be issued` rows carried placeholder `Permit Date` values (often equal to `FILE_DATE`).

Repairs:
- Prefer `Issue Date` over `Permit Date` for Active/Final (**1,088 FIXED** on Final; Active already had Issue == Permit).
- Clear spurious dates on In Review and never-issued Inactive (**107 FIXED** clears).
- Keep `Issue Date` on Inactive rows that were issued then revoked.

**After:** missing 129. Active 412/412 (100%) · Final 1,404/1,404 (100%) · In Review 0/100 · Inactive 55/84.  
`PERMIT_DATE == FINAL_DATE`: 828 → 4.  
Flags: **FILLED 0 · FIXED 1,197**

### FINAL_DATE

**Before:** 626 missing; 1,374/1,405 Final rows had `FINAL_DATE` (97.8%); 0 non-Final rows carried a final date.

Existing finals already track the latest APPROVED inspection on/after `FILE_DATE` (filters out stale prior-job `FINAL INSPECTION` rows, e.g. shared 2012 dates on 2014 solar permits).

Repairs:
- Fill 2 temporary C.O. Finals from latest APPROVED inspection (**2 FILLED**).
- Clear final date on the one Final→Inactive (`REVOKED`) row (**1 FIXED**).

Remaining Final gaps (29): empty `insp_status_detail` (28 `final inspection complete`, 1 `c.o. issued`).

**After:** missing 625 overall. Final 1,375/1,404 (97.9%); Active / In Review / Inactive 0%.  
Flags: **FILLED 2 · FIXED 1**

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| `STATUS_NORMALIZED` | 22 | 49 | 22 → 0 |
| `FILE_DATE` | 0 | 0 | 0 → 0 |
| `PERMIT_DATE` | 0 | 1,197 | 22 → 129 |
| `FINAL_DATE` | 2 | 1 | 626 → 625 |

Post-repair coverage targets:

| Status | n | `PERMIT_DATE` | `FINAL_DATE` |
| --- | ---: | ---: | ---: |
| Active | 412 | 100% | 0% |
| Final | 1,404 | 100% | 97.9% |
| In Review | 100 | 0% | 0% |
| Inactive | 84 | 65.5% | 0% |

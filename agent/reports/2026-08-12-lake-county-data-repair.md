# Lake County (FL) data repair

**Summary:** Lake County (`2,000` sample rows) uses a flat county-portal DATA payload. `STATUS_NORMALIZED` was already correct for mapped portal statuses; 3 unmapped `CLOSED_NI` / `closed_ni` rows were filled as Inactive. `FILE_DATE` already matched `Application Date` on every row (0 missing). `PERMIT_DATE` already matched `Issued Date` wherever present; Active/Final coverage is 100%, and remaining gaps are true nulls on never-issued In Review / Inactive shells. The main data gap is `FINAL_DATE`: it is missing on all 2,000 rows, including 1,637 Final records, and cannot be recovered because `Certificate of Occupancy` and `Permit History` are null on every sample row.

## Jurisdiction selection

First `(JURISDICTION, STATE)` pair in `permits_fl_sample.parquet` without an existing `agent/scripts/{state}/data_repair_{state}_{city}.py`: **Lake County, FL** (index 60 after Palm Coast).

Script: `agent/scripts/fl/data_repair_fl_lake_county.py`  
Artifact: `$AGENT_DATA_PATH/lake_county_repaired_sample.parquet`

## DATA schemas (`INFERRED_SCHEMA`)

Three layout variants, further split by portal `Status`:

| Schema family | n | Notes |
| --- | ---: | --- |
| `lake_portal_*` | 1,575 | Base key set (no Permit Description) |
| `lake_portal_desc_*` | 380 | Adds `Permit Description` |
| `lake_portal_underscore_*` | 45 | Also has `Job_Value` / `Job_Description` / `Permit_Description` duplicates |

Largest slices: `lake_portal_coed` (1,361), `lake_portal_desc_coed` (230), `lake_portal_desc_issued` (75), `lake_portal_cancel` (57).

Canonical fields: `Status`, `Application Date`, `Issued Date`, `Certificate Number`, `Certificate of Occupancy` (always null), `Permit History` (always null).

## Field assessments

### STATUS_NORMALIZED

| Portal `Status` | Prior mapping | Assessment |
| --- | --- | --- |
| COED, FINAL | Final | Correct |
| ISSUED, INSPECT | Active | Correct |
| APPLY, READY, CITY | In Review | Correct (CITY kept as In Review per Leon/upstream convention; 8/9 have Issued Date) |
| CANCEL, EXPIRED, VOID | Inactive | Correct |
| CLOSED_NI / closed_ni (3) | null | Filled → Inactive (closed without inspection / final) |

No incorrect non-null statuses found (`STATUS_ORIGINAL` == `DATA.Status` for all rows, case aside).

**Repair performance:** FILLED 3, FIXED 0; missing 3 → 0.

### FILE_DATE

- Before: missing on **0 / 2,000** rows.
- Source: `Application Date` — exact calendar-day match on all 2,000 rows.
- After: still 0 missing; no fills or fixes.

**Repair performance:** FILLED 0, FIXED 0; missing 0 → 0.

### PERMIT_DATE

- When present, matched `Issued Date` on **1,902 / 1,902** (100%).
- Active/Final already fully populated (183 + 1,637).
- Remaining 98 missings: APPLY (24), READY (19), CANCEL (40), EXPIRED (8), VOID (6), CITY (1) — appropriate (no Issued Date in DATA).
- In Review retains Issued stamps on 8 CITY/similar rows; not cleared.

**Repair performance:** FILLED 0, FIXED 0; missing 98 → 98.

### FINAL_DATE

- Before: missing on **all 2,000** rows, including every Final (`COED`/`FINAL`) record.
- Candidate fields `Certificate of Occupancy` and `Permit History` are `None` on every row.
- `Certificate Number` is often populated on COED rows (1,485 / 1,634) but carries no date.
- No inspection / review history arrays exist in this extract.

**Repair performance:** FILLED 0, FIXED 0; missing 2,000 → 2,000.

After repair by status:

| Status | FINAL_DATE present |
| --- | --- |
| Final | 0 / 1,637 (0%) |
| Active / In Review / Inactive | 0% (as expected) |

## Ideal-field checklist (after repair)

| Rule | Result |
| --- | --- |
| FILE_DATE populated for all records | Yes (100%) |
| PERMIT_DATE for Active and Final | Yes (100%) |
| FINAL_DATE for Final | No — not present in DATA |
| STATUS_NORMALIZED in {Active, Final, In Review, Inactive} | Yes (0 null) |

## Conclusion

Lake County’s application and issuance dates were already correctly ingested. The only actionable repair in this sample is mapping unmapped `CLOSED_NI` statuses to Inactive. Completing Final records with `FINAL_DATE` would require a richer source extract (CO issue dates or inspection history); the current DATA payload does not contain those timestamps.

# Soledad (CA) data repair

Repaired all 2,000 Soledad sample rows: every missing `STATUS_NORMALIZED` was filled from `My Project` date presence, and 9 Final rows missing `PERMIT_DATE` were filled from `Approved` when `Issued` was blank. Ideal coverage is complete after repair (100% `FILE_DATE`; 100% `PERMIT_DATE` on Active/Final; 100% `FINAL_DATE` on Final).

## Jurisdiction selection

First `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing `agent/scripts/{state}/data_repair_{state}_{city}.py` (accent-normalized slug): **Soledad, CA**.

## DATA schema

SmartGov portal payload. Two key-set variants:

| Schema | n | Notes |
| --- | ---: | --- |
| `my_project_with_parcel` | 1,940 | core keys + top-level `Parcel Number` |
| `my_project_basic` | 60 | core keys without `Parcel Number` |

`Build Status`, `Permit Number`, `Application Number`, `Permit Details`, and `Permit Inspections` are null/empty on every row. Usable signal is entirely under `My Project`: `Submitted`, `Created`, `Approved`, `Issued`, `Closed` (plus address/parcel fields). Blank portal dates appear as `" - -"`.

Canonical mapping:

- `Closed` / `Issued` / `Approved`/`Submitted`/`Created` presence → `STATUS_NORMALIZED`
- `Submitted` (fallback `Created`) → `FILE_DATE`
- `Issued` (fallback `Approved`) → `PERMIT_DATE`
- `Closed` → `FINAL_DATE`

## Findings by field

### STATUS_NORMALIZED

- **Before:** missing on all 2,000 rows (`STATUS_ORIGINAL` also entirely null). Root cause: no upstream status mapping; `Build Status` is always null.
- **Repair:** fill from date presence — `Closed` → Final (1,525); `Issued` without `Closed` → Active (357); `Approved`/`Submitted`/`Created` only → In Review (118).
- **After:** 0 missing. No Inactive rows (no cancel/expire Build Status; `Application Expires` is a validity window, not a status).

### FILE_DATE

- Already populated for all 2,000 rows and matches `My Project.Submitted` at calendar-day resolution.
- No FILLED/FIXED changes.

### PERMIT_DATE

- **Before:** 127 missing. Of those, 118 are pre-issuance (In Review); 9 are Final shells with `Closed` but blank `Issued` (mostly fee / planning-style records that still have `Approved`).
- When present, `PERMIT_DATE` always matched `Issued`.
- **Repair:** FILLED 9 from `Approved`. Remaining 118 missing are all In Review (correct by design).
- **After:** Active 357/357 (100%); Final 1,525/1,525 (100%); In Review 0/118.

### FINAL_DATE

- **Before:** 475 missing — exactly the non-Closed rows. When present, always matched `Closed`. No spurious `FINAL_DATE` on non-Closed rows.
- **After status fill:** Final 1,525/1,525 (100%); Active/In Review 0%. No FILLED/FIXED needed.

### Other notes

- 8 portal chronology inversions where `Issued` precedes `Submitted`, and 3 where `Closed` precedes `Issued`. Dates were left as-is because they match `My Project`.
- `Approved` without `Issued` is treated as plan approval (In Review), not issuance — consistent with Delano’s SmartGov date fallback.

## Repair performance

Script: `agent/scripts/ca/data_repair_ca_soledad.py`  
Artifact: `AGENT_DATA_PATH/repaired/permits_ca_soledad_repaired.parquet`

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 2,000 | 0 | 2,000 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 9 | 0 | 127 → 118 |
| FINAL_DATE | 0 | 0 | 475 → 475 |

Remaining missing dates are intentional: 118 In Review rows without issuance/completion. Ideal-coverage gaps after repair: **0**.

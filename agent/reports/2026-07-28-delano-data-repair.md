# Delano (CA) data repair

**Summary:** Assessed Delano's 2,000-row sample and wrote `agent/scripts/ca/data_repair_ca_delano.py`. Delano uses a SmartGov portal payload (`Build Status` + `My Project` dates). The repair fills 179 missing statuses and fixes 17 stale ones, fills 9 FILE_DATEs, 46 PERMIT_DATEs, and 9 FINAL_DATEs, and corrects 3 stale FINAL_DATEs. After repair, FILE_DATE is complete for all typed statuses; Active has 100% PERMIT_DATE; Final has 98.3% FINAL_DATE. Remaining gaps are empty `My Project` shells and historical Closed/Finaled rows that lack Issued/Closed dates in DATA.

## Jurisdiction selection

First `(JURISDICTION, STATE)` in `permits_ca_sample.parquet` without an existing `agent/scripts/{state}/data_repair_{state}_{city}.py`: **Delano, CA**.

## DATA schema

All 2,000 rows have DATA. Inferred schemas:

| Schema | N | Notes |
| --- | --- | --- |
| `smartgov_full` | 1,398 | Has `ProjectDescription` + `Parcel Number` |
| `smartgov_no_desc` | 523 | Has `Parcel Number`, no description |
| `smartgov_minimal` | 65 | Neither description nor parcel |
| `empty_my_project` | 14 | Empty `My Project` dict; no date fields |

Canonical mappings from DATA:

- `Build Status` → `STATUS_NORMALIZED` (date inference when Build Status is null)
- `My Project.Submitted` (fallback `Created`) → `FILE_DATE`
- `My Project.Issued` (fallback `Approved`) → `PERMIT_DATE`
- `My Project.Closed` (fallback passed Final inspection) → `FINAL_DATE`

## Findings by field

### STATUS_NORMALIZED

Before: Final 1,363 / Inactive 271 / missing 192 / In Review 133 / Active 41.

Issues:

1. **Missing (192):** Mostly `Expired: <date>` labels that were never mapped (~95), null Build Status on recent scrapes (~70), plus unmapped review labels (`Plans returned…`, `Review process has started`) and a handful of Closed / Certificate of Occupancy shells with null `STATUS_ORIGINAL`.
2. **Incorrect (17 after repair):** Closed/Finaled still coded Active; Issued still In Review; Expired still Active; Ready To Issue / Pending / Under Review rows that already had Issued dates in My Project.

Repair performance: **179 FILLED, 17 FIXED**; missing after: **13** (all `empty_my_project` with no dates; one retains `STATUS_ORIGINAL` but no Build Status/dates to validate).

After: Final 1,374 / Inactive 368 / In Review 162 / Active 83 / missing 13.

### FILE_DATE

Before: 21 missing. Values that exist match `My Project.Submitted` exactly (1,977/1,977).

Repair: **9 FILLED** from Submitted. Remaining **12** missing are empty-`My Project` shells with no Submitted/Created.

After repair, FILE_DATE is populated for 100% of Active / Final / In Review / Inactive rows.

### PERMIT_DATE

Before: 946 missing. Where both present, PERMIT_DATE matches Issued exactly (1,053/1,053).

Repair: **46 FILLED** from Issued or Approved for Active/Final after status repair.

Remaining Final gap (~675) is historical Closed records with neither Issued nor Approved in DATA (Closed-only shells). Active has **100%** PERMIT_DATE after repair.

### FINAL_DATE

Before: 659 missing. Most Final rows already matched Closed; **3 mismatches** had an older FINAL_DATE while Closed was `7/28/2024` (DATA authoritative → FIXED).

Repair: **9 FILLED** (Closed on status-promoted rows + 1 Finaled via passed Final inspection), **3 FIXED**.

Remaining Final missing FINAL_DATE: **24**, all `Finaled` with blank Closed and no usable Final inspection. Final coverage after repair: **1,350 / 1,374 (98.3%)**. No spurious FINAL_DATE remains on non-Final statuses.

## Repair script

`agent/scripts/ca/data_repair_ca_delano.py` — `data_repair(df)` overwrites incorrect/missing fields, adds `{FIELD}_FLAG` (`FILLED` / `FIXED`) and `INFERRED_SCHEMA`.

### Performance (n=2,000)

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | --- | --- | --- | --- |
| STATUS_NORMALIZED | 179 | 17 | 192 | 13 |
| FILE_DATE | 9 | 0 | 21 | 12 |
| PERMIT_DATE | 46 | 0 | 946 | 900 |
| FINAL_DATE | 9 | 3 | 659 | 650 |

Post-repair coverage by status:

| Status | FILE_DATE | PERMIT_DATE | FINAL_DATE |
| --- | --- | --- | --- |
| Active (83) | 100% | 100% | 0% (expected) |
| Final (1,374) | 100% | 50.9% | 98.3% |
| In Review (162) | 100% | 0% | 0% (expected) |
| Inactive (368) | 100% | 86.4% | 0% (expected) |

## Not repairable from DATA

- 13 empty-`My Project` shells (no status/dates in JSON).
- ~675 Final Closed-only historical rows without Issued/Approved → PERMIT_DATE stays missing.
- 24 Finaled rows without Closed or a passed Final inspection → FINAL_DATE stays missing.
- `Technically Completed` (11) kept as In Review (no Issued/Closed dates to support Final).

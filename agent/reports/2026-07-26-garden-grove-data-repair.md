# Garden Grove (CA) data repair

**Summary:** Garden Grove was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. Assessed and repaired `STATUS_NORMALIZED`, `FILE_DATE`, `PERMIT_DATE`, and `FINAL_DATE` from the city permit-portal `DATA` JSON. Status is now fully populated (**FILLED 53 · FIXED 12**): 52 recent `project_status` rows and 1 empty-`permit status` row were filled, and 12 Suspended rows previously labeled In Review were corrected to Inactive. `FILE_DATE` missingness fell from **1,267 → 40** (**FILLED 1,227**) using `created on`, with `issued on` as fallback when create is blank. `PERMIT_DATE` gained **52 FILLED** values on Active/Final `project_status` rows (Active/Final coverage **99.4% / 99.6%**). `FINAL_DATE` improved modestly (**FILLED 18 · FIXED 20**); most Finaled shells have empty inspections and remain unfillable.

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_ca_sample.parquet`
- Jurisdiction: **Garden Grove, CA** (n=2,000)
- Script: `agent/scripts/ca/data_repair_ca_garden_grove.py` (`data_repair`)

## DATA schema (`INFERRED_SCHEMA`)

Two top-level JSON shapes:

| Schema | n | Description |
| --- | ---: | --- |
| `permit_status` | 1,948 | Keys: `permit#`, `permit status`, `inspection status`, `location`, `created on`, `issued on`, `inspections`, … |
| `project_status` | 52 | Keys: `Project`, `status`, `address`, `created on`, `issued on`, `inspections`, … (recent scrapes) |

Canonical fields:

| Field | Source |
| --- | --- |
| `STATUS_NORMALIZED` | `DATA['permit status']` or `DATA['status']`; else first line of `inspection status` |
| `FILE_DATE` | `created on`; fallback `issued on` when create is blank |
| `PERMIT_DATE` | `issued on` |
| `FINAL_DATE` | Latest dated inspection whose type contains "Final" (skip Canceled / Final Application Evaluation) |

## Field assessment

### STATUS_NORMALIZED

**Before:** Final 1,419 · Active 413 · In Review 88 · Inactive 27 · missing 53

Issues:
1. **52 `project_status` rows** had null `STATUS_NORMALIZED` / `STATUS_ORIGINAL`. Raw `DATA.status` maps cleanly: Inspections (26) / Issued (23) → Active; Finaled (3) → Final.
2. **1 `permit_status` row** (`18-0884`) has empty `permit status` but `inspection status` starts with `Expired` → Inactive.
3. **12 Suspended** rows were normalized as In Review. Suspended + Expired inspection status is Inactive, not under review → FIXED.

When present, `permit status` / `status` maps as:

| Raw status | `STATUS_NORMALIZED` |
| --- | --- |
| Finaled, Closed | Final |
| Inspections, Issued | Active |
| Plan Check, Plan Check Final, Payment Check, Applicaion, Undefined | In Review |
| Cancelled, Suspended, Expired | Inactive |

**After:** Final 1,422 · Active 462 · In Review 76 · Inactive 40 · missing 0  
Flags: **FILLED 53 · FIXED 12**

### FILE_DATE

**Before:** 1,267 missing (63.4%).

- When both present, `FILE_DATE` already matched `created on` for all compared rows (0 mismatches).
- `created on` is blank on most legacy `permit_status` shells (1,215 both-missing before repair).
- All 52 `project_status` rows had `created on` available but `FILE_DATE` null.

Repairs:
1. Prefer `created on` (**52 FILLED**, all `project_status`).
2. Else `issued on` as application-date proxy (**1,175 FILLED**).

**After:** 40 missing (2.0%). Remaining gaps have neither usable `created on` nor `issued on`.  
Flags: **FILLED 1,227 · FIXED 0**

### PERMIT_DATE

**Before:** 163 missing (8.2%). Among Active/Final: 8 missing; among null-status rows: 52 missing with `issued on` present.

Root cause: upstream did not parse the `project_status` schema, so those 52 Active/Final-equivalent rows lack `PERMIT_DATE` despite `issued on`.

Repairs (Active / Final only): fill from `issued on` → **FILLED 52**.

**After:** 111 missing overall; Active **459 / 462 (99.4%)**, Final **1,417 / 1,422 (99.6%)**. The 8 remaining Active/Final gaps have blank `issued on` in DATA.  
Flags: **FILLED 52 · FIXED 0**

### FINAL_DATE

**Before:** 1,592 missing. Among Final: 1,011 / 1,419 missing (71.2%). Present values usually equal the latest final-type inspection (344) or, when no final-type insp exists, the latest any inspection (53).

Issues:
1. **18 Final rows** (including 3 newly filled Finaled `project_status` rows) have a usable final inspection but null `FINAL_DATE` → FILLED.
2. **20 rows** had `FINAL_DATE` set to a non-final or intermediate inspection date that disagrees with the latest final-type inspection → FIXED (e.g. `22-3492`: 2022-08-25 Pre-Inspection → 2022-08-30 Reroof Final).
3. **~996 Finaled shells** report "No inspections in System" → not repairable from DATA.

**After:** Final **426 / 1,422 (30.0%)** have `FINAL_DATE`; no non-Final rows retain a final date.  
Flags: **FILLED 18 · FIXED 20**

## Repair performance

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | ---: | ---: | ---: | ---: |
| `STATUS_NORMALIZED` | 53 | 12 | 53 | 0 |
| `FILE_DATE` | 1,227 | 0 | 1,267 | 40 |
| `PERMIT_DATE` | 52 | 0 | 163 | 111 |
| `FINAL_DATE` | 18 | 20 | 1,592 | 1,574 |

## Artifacts

- Script: `agent/scripts/ca/data_repair_ca_garden_grove.py`
- Report: `agent/reports/2026-07-26-garden-grove-data-repair.md`

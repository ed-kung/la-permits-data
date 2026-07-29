# Yolo County (CA) data repair — 2026-07-28

Yolo County was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. Civic-portal `permit_info` JSON already has near-complete `FILE_DATE` (from `PermitAppliedDate`) and mostly correct `STATUS_NORMALIZED` from `PermitStatus`, but four `ESTIMATE` shells were labeled Final, four Issued/Approved rows with `PermitFinaledDate` were left Active, 39 Active/Final rows were missing `PERMIT_DATE` despite Issued/Approved dates, one Final row had a usable final inspection with blank `PermitFinaledDate`, and one Expired row carried a spurious `FINAL_DATE`. Repair fixes 8 statuses, fills 39 permit dates and 1 final date, and clears 1 spurious final date. One VOID shell still lacks all dates.

## Jurisdiction selection

Walked `(JURISDICTION, STATE)` pairs in sample order and compared against `agent/scripts/{state}/data_repair_{state}_{city}.py`. First missing: **Yolo County, CA** → `agent/scripts/ca/data_repair_ca_yolo_county.py` (n=2,000).

## DATA schema

All rows share civic portal top-level keys (`fees`, `contacts`, `site_info`, `inspections`, `permit_info`, `search_data`). Canonical lifecycle fields live under `permit_info`. `inspections` is a list-of-lists (`[title, result, date, time, date2, …]`), not dicts. Variants recorded in `INFERRED_SCHEMA`:

| Schema | n | Description |
| --- | ---: | --- |
| `permit_info_issued_finaled` | 1,561 | Issued + Finaled present |
| `permit_info_applied_only` | 197 | only Applied populated |
| `permit_info_issued` | 185 | Issued present, Finaled blank |
| `permit_info_approved_only` | 43 | Approved present, Issued/Finaled blank |
| `permit_info_finaled_only` | 13 | Finaled present, Issued blank |
| `permit_info_empty_dates` | 1 | VOID shell with status only |

## Field assessment

### STATUS_NORMALIZED

- Fully populated (0 missing). Upstream mapped `STATUS_ORIGINAL` / `PermitStatus` into the four normalized buckets for most labels (`FINALED` / `Yes (finaled)` / `YES (FINALED)` / `HISTORIC RECORD` → Final; `ISSUED` / `APPROVED` / `NEW (ACTIVE)` → Active; `UNDER REVIEW` / `PENDING PAYMENT` → In Review; `EXPIRED` / `VOID` / `CANCELLED` / `ABANDONED` / `WITHDRAWN` → Inactive).
- **Incorrect vs DATA:**
  - `ESTIMATE` (4) labeled Final despite empty Issued / Approved / Finaled → FIXED to In Review.
  - `ISSUED` / `APPROVED` (4) carrying `PermitFinaledDate` left Active → FIXED to Final.
- `EXPIRED` keeps Inactive even when `PermitFinaledDate` is a close stamp (not treated as Final).
- **Repair:** 0 FILLED, 8 FIXED. Missing after: 0.

### FILE_DATE

- 1,999 / 2,000 populated; every populated value matches `PermitAppliedDate` calendar day (0 mismatches).
- One VOID encroachment (`PW2017-0133`) has empty Applied / Issued / Approved / Finaled and no fees/inspections → not fillable.
- Historic-record Applied dates are often a migration stamp (e.g. 2004-05-17) while Issued/Finaled are earlier; left as Applied (canonical source). That drives many `PERMIT < FILE` chronology flags and is not corrected.
- **Repair:** 0 FILLED, 0 FIXED. Coverage 1,999 / 2,000 (99.95%).

### PERMIT_DATE

- When present, always matched `PermitIssuedDate` (Approved used only when Issued blank).
- Missing fillable: Active 29 + Final 10 with Approved (no Issued), mostly FSA / floodplain `APPROVED` shells → FILLED.
- Unfillable after repair: 4 Active (`APPROVED`/`ISSUED` with blank Issued and Approved) and 30 Final shells with neither Issued nor Approved.
- **Repair:** 39 FILLED, 0 FIXED. Missing after: 215.
- Post-repair Active+Final PERMIT coverage: 1,646 / 1,680 (98.0%).

### FINAL_DATE

- When present on Final rows, always matched `PermitFinaledDate` (0 mismatches).
- Fillable: 1 Final (`BP2019-0401`) with blank Finaled but passed `FINAL BUILDING` inspection → FILLED 2019-04-30.
- Spurious: 1 Inactive `EXPIRED` row with Finaled close stamp → FINAL_DATE cleared (FIXED). The 4 Active→Final upgrades already carried correct Finaled dates (kept).
- Unfillable: 36 Final (`FINALED` 34 / `Yes (finaled)` 1 / `Historic record` 1) lack Finaled and a dated final inspection.
- **Repair:** 1 FILLED, 1 FIXED. Missing after: 426 (same count; fill and clear cancel).
- Post-repair Final FINAL coverage: 1,574 / 1,610 (97.8%). Active / In Review / Inactive: 0% by design.

## Repair performance

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | ---: | ---: | ---: | ---: |
| STATUS_NORMALIZED | 0 | 8 | 0 | 0 |
| FILE_DATE | 0 | 0 | 1 | 1 |
| PERMIT_DATE | 39 | 0 | 254 | 215 |
| FINAL_DATE | 1 | 1 | 426 | 426 |

Status distribution:

| | Before | After |
| --- | ---: | ---: |
| Final | 1,610 | 1,610 |
| Inactive | 196 | 196 |
| In Review | 120 | 124 |
| Active | 74 | 70 |

Status transitions (FIXED): Active→Final 4; Final→In Review 4.

## Artifacts

- Repair script: `agent/scripts/ca/data_repair_ca_yolo_county.py`
- Repaired sample parquet: `$AGENT_DATA_PATH/repaired/permits_ca_yolo_county_repaired.parquet`

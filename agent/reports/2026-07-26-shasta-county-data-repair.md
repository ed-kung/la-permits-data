# Shasta County (CA) data repair

**Summary:** Shasta County was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. Assessed and repaired `STATUS_NORMALIZED`, `FILE_DATE`, `PERMIT_DATE`, and `FINAL_DATE` from the GIS / open-data `permit_info` JSON. Status corrections (**FIXED 520**): 502 `HISTORY` archive rows mis-labeled Inactive were remapped to Final (they carry Finaled and/or Issued dates), and 18 `APPROVED SEPTIC/WELL*` waivers were remapped In Review → Active. `FILE_DATE` already matched `PermitAppliedDate` for all 1,999 rows (no changes). `PERMIT_DATE` missingness fell from **430 → 411** (**FILLED 19**) via `PermitApprovedDate` when Issued was empty. `FINAL_DATE` (**FILLED 5 · FIXED 8**): five COMP CARD NEEDED / well-seal finals were filled from inspections; eight spurious finals on CANCELED rows were cleared. After repair, Final rows are **99.7%** final-dated; remaining Active/Final permit-date gaps are mostly empty ACTIVE MISCELLANEOUS and legacy HISTORY/FINALED shells with no Issued/Approved in DATA.

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_ca_sample.parquet`
- Jurisdiction: **Shasta County, CA** (n=1,999)
- Script: `agent/scripts/ca/data_repair_ca_shasta_county.py` (`data_repair`)
- Artifact: `AGENT_DATA_PATH/shasta_county_repaired_sample.parquet`

## DATA schema (`INFERRED_SCHEMA`)

All records share top-level keys `contacts`, `fees`, `inspections`, `permit_info`, `search_data`, `site_info`. Content variants:

| Schema | n | Description |
| --- | ---: | --- |
| `permit_info_dates_only` | 874 | Empty inspections; Issued / Approved / Finaled present |
| `permit_info_with_inspections` | 815 | Non-empty `inspections` list |
| `permit_info_applied_only` | 310 | Only `PermitAppliedDate` (other dates blank) |

Canonical fields:

| Field | Source |
| --- | --- |
| `STATUS_NORMALIZED` | `permit_info.PermitStatus` (Finaled date overrides to Final except inactive-keep labels) |
| `FILE_DATE` | `PermitAppliedDate` |
| `PERMIT_DATE` | `PermitIssuedDate`, else `PermitApprovedDate` |
| `FINAL_DATE` | `PermitFinaledDate`, else latest passed BUILDING FINAL / FINAL** / WELL SEAL / similar inspection `Completed` |

## Field assessment

### STATUS_NORMALIZED

**Before:** Final 950 · Inactive 720 · Active 225 · In Review 104 · missing 0

Upstream mapping of `PermitStatus` → `STATUS_ORIGINAL` (lowercased) was consistent, but two groups were mis-normalized relative to permit lifecycle:

1. **HISTORY (510)** labeled Inactive. These are `HISTORICAL PERMITS` archive rows; **501 have `PermitFinaledDate`** and **461 have `PermitIssuedDate`**. Completed historical permits should be Final. Empty HISTORY shells (no Issued/Finaled, n=8 after remap rules) stay Inactive.
2. **APPROVED SEPTIC/WELL* (18)** labeled In Review. These waivers carry `PermitApprovedDate` and no issuance workflow — they are approved decisions → Active.

Other statuses map cleanly:

| `PermitStatus` | `STATUS_NORMALIZED` |
| --- | --- |
| FINALED, COMPLETE, COMP CARD NEEDED, HISTORY (with dates) | Final |
| ACTIVE, ISSUED, APPROVED SEPTIC/WELL* | Active |
| APPLIED, READY TO ISSUE/PAY, UNDER REVIEW, REVISION SUBMITTED | In Review |
| CANCELED/CANCELLED, DENIED, EXPIRED, VOID, NON COMPLIANCE | Inactive |

**After:** Final 1,452 · Active 243 · Inactive 218 · In Review 86 · missing 0  
Flags: **FILLED 0 · FIXED 520** (502 HISTORY, 18 APPROVED*)

### FILE_DATE

**Before:** 0 missing (100%).

- Every row’s `FILE_DATE` equals `PermitAppliedDate` at calendar-day resolution.
- No alternate file-date source needed (`search_data` has no Date field).

**After:** still 0 missing.  
Flags: **FILLED 0 · FIXED 0**

### PERMIT_DATE

**Before:** 430 missing (21.5%). Among Active/Final: 170 / 1,175 missing.

Upstream only copied `PermitIssuedDate`. Gaps:

1. **APPROVED* waivers** (and one FINALED pool/spa) have Approved but empty Issued → fillable.
2. **155 ACTIVE MISCELLANEOUS** shells have neither Issued nor Approved → not fillable from DATA.
3. Legacy **HISTORY / FINALED** rows with Finaled but blank Issued/Approved → not fillable.

Repairs (Active / Final only): prefer Issued, else Approved.

**After:** 411 missing. Active/Final with PERMIT: Active 88/243 (36.2%); Final 1,397/1,452 (96.2%).  
Flags: **FILLED 19 · FIXED 0**

### FINAL_DATE

**Before:** 549 missing (27.5%). Final missing FINAL: 9. Non-Final with FINAL: 509 (all HISTORY) + 8 CANCELED.

Issues:

1. **HISTORY→Inactive** left 501 completed finals sitting on Inactive (values matched `PermitFinaledDate` correctly; status was wrong).
2. **9 Final** lacked `PermitFinaledDate`; **5 COMP CARD NEEDED** water wells had `WELL SEAL` / PASS inspections usable as final proxies.
3. **8 CANCELED** rows carried `PermitFinaledDate` / `FINAL_DATE` (cancel/close stamps) — cleared once status stays Inactive.

**After:** Final with FINAL_DATE **1,447 / 1,452 (99.7%)**; no non-Final rows retain FINAL_DATE. Remaining 5 Final gaps: 2 COMP CARD (no inspections), 2 FINALED (no Finaled date / no final-titled insp), 1 HISTORY with Issued only.  
Flags: **FILLED 5 · FIXED 8**

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 0 | 520 | 0 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 19 | 0 | 430 → 411 |
| FINAL_DATE | 5 | 8 | 549 → 552 |

`FINAL_DATE` missingness rises slightly because 8 cancel stamps were cleared while only 5 finals were newly filled; coverage among true Final rows improves substantially after the HISTORY remap.

## Not repairable from DATA

- 155 ACTIVE MISCELLANEOUS records with no Issued/Approved dates and no inspections.
- Sparse HISTORY / FINALED / COMP CARD shells without Finaled dates or final-titled inspections.
- Inactive rows that retain Issued dates (canceled/expired after issuance) by design.

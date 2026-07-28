# Redwood City (CA) data repair

**Summary:** Redwood City was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. Assessed and repaired `STATUS_NORMALIZED`, `FILE_DATE`, `PERMIT_DATE`, and `FINAL_DATE` from the civic-portal `DATA` JSON (`permit_info` / `search_data`). Status missingness fell from **637 → 188** (**FILLED 449 · FIXED 11**): blank-`PermitStatus` legacy rows inferred from dates, plus remaps of `NO PMT REQ` / `NOT APPROVED` (In Review → Inactive) and finaled-but-still-Issued/Investigate rows → Final. `FILE_DATE` already matched `PermitAppliedDate` / `search_data.APPLIED` wherever either source exists (**FILLED/FIXED 0**); 197 shells have neither. `PERMIT_DATE` missingness fell from **350 → 341** (**FILLED 9**), using Issued and Approved for Active/Final. `FINAL_DATE` gained no fills (Final rows lacking `PermitFinaledDate` also lack usable final inspections) but **FIXED 50** by clearing spurious close timestamps on Inactive/Active/In Review rows.

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_ca_sample.parquet`
- Jurisdiction: **Redwood City, CA** (n=2,000)
- Script: `agent/scripts/ca/data_repair_ca_redwood_city.py` (`data_repair`)
- Artifact: `AGENT_DATA_PATH/redwood_city_repaired_sample.parquet`

## DATA schema (`INFERRED_SCHEMA`)

All records share top-level keys `fees`, `contacts`, `site_info`, `inspections`, `permit_info`, `search_data`. Sub-schemas reflect which `permit_info` fields are populated:

| Schema | n | Description |
| --- | ---: | --- |
| `permit_info_issued_finaled` | 895 | Issued + Finaled present |
| `legacy_no_status` | 449 | Blank `PermitStatus` but dates present (mostly 1980s–2000s) |
| `permit_info_issued` | 315 | Issued present, Finaled blank |
| `permit_info_empty` | 182 | Blank `permit_info` shell |
| `permit_info_applied_only` | 123 | Only Applied populated |
| `permit_info_empty_dates` | 13 | Status/desc text, no usable dates |
| `permit_info_approved_only` | 13 | Approved present, Issued/Finaled blank |
| `permit_info_finaled_only` | 10 | Finaled present, Issued blank |

Canonical fields:

| Field | Source |
| --- | --- |
| `STATUS_NORMALIZED` | `permit_info.PermitStatus` (prefer Final when non-inactive and `PermitFinaledDate` present; blank status inferred from dates) |
| `FILE_DATE` | `PermitAppliedDate`; else `search_data.APPLIED` |
| `PERMIT_DATE` | `PermitIssuedDate`; else `search_data.ISSUED`; else `PermitApprovedDate` / `search_data.APPROVED` |
| `FINAL_DATE` | `PermitFinaledDate`; else latest passed FINAL inspection `Completed` |

## Field assessment

### STATUS_NORMALIZED

**Before:** Final 907 · Active 277 · Inactive 92 · In Review 87 · missing 637

`PermitStatus` and `search_data.STATUS` agree whenever either is set. Two problem classes:

1. **Blank status (637 rows).** Empty `PermitStatus` with no search STATUS. Of these, 449 have application/issuance/final dates (legacy shells, mostly pre-2002); 188 are empty shells with no dates at all.
2. **Incorrect mappings / lag (11 rows).** Upstream mapped `NO PMT REQ` and `NOT APPROVED` to In Review; a few ISSUED/INVESTIGATE rows already carry `PermitFinaledDate` but stayed Active/In Review.

| Change | n | Reason |
| --- | ---: | --- |
| null → Active | 438 | Blank status + Issued/Approved date |
| null → In Review | 9 | Blank status + Applied only |
| null → Final | 2 | Blank status + Finaled date |
| In Review → Inactive | 8 | `NO PMT REQ` (5) / `NOT APPROVED` (3) |
| Active → Final | 2 | `ISSUED` with `PermitFinaledDate` |
| In Review → Final | 1 | `INVESTIGATE` with `PermitFinaledDate` |

**After:** Final 912 · Active 713 · Inactive 100 · In Review 87 · missing 188  
Flags: **FILLED 449 · FIXED 11**

Not repairable: 188 empty shells with no status or dates in DATA.

### FILE_DATE

**Before:** 197 missing (9.9%).

- Where present (1,803), `FILE_DATE` always equals `PermitAppliedDate` / `search_data.APPLIED` (day match).
- All 197 missing rows also lack Applied in both `permit_info` and `search_data` (188 empty shells + 9 Under Review / Final / Approved with blank Applied).

**After:** still 197 missing.  
Flags: **FILLED 0 · FIXED 0**

### PERMIT_DATE

**Before:** 350 missing (17.5%). Among Active/Final: 51 / 1,184 missing.

Root cause: upstream left `PERMIT_DATE` null when `PermitIssuedDate` was blank even if `PermitApprovedDate` (or SD ISSUED) was available. After status repair, most newly Active legacy rows already carried an Issued-based `PERMIT_DATE`.

Repairs (Active / Final only):
1. Prefer `PermitIssuedDate` / `search_data.ISSUED`.
2. Else `PermitApprovedDate` / `search_data.APPROVED`.

**After:** 341 missing. Active 708/713 (99.3%); Final 875/912 (95.9%).  
Flags: **FILLED 9 · FIXED 0**

Not repairable: 5 Active + 37 Final with neither Issued nor Approved in DATA.

### FINAL_DATE

**Before:** 1,093 missing. Among Final: 55 / 907 missing. 53 non-Final rows carried a `FINAL_DATE` that matched `PermitFinaledDate` (mostly `CANCEL - NFR` close timestamps; also 2 ISSUED and 1 INVESTIGATE later remapped to Final).

Repairs:
1. For Final: set from `PermitFinaledDate`, else passed FINAL inspection.
2. For non-Final: clear spurious `FINAL_DATE` (Inactive keep labels treat Finaled as close/void, not completion).

**After:** 1,143 missing (increase from clearing 50 spurious non-Final dates). Final 857/912 (94.0%); Active/In Review/Inactive all 0%.  
Flags: **FILLED 0 · FIXED 50**

Not repairable: 55 Final FINALED/CLOSED rows with blank `PermitFinaledDate` and no inspections list (none of the Final-missing-FINAL subset has inspections).

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| `STATUS_NORMALIZED` | 449 | 11 | 637 → 188 |
| `FILE_DATE` | 0 | 0 | 197 → 197 |
| `PERMIT_DATE` | 9 | 0 | 350 → 341 |
| `FINAL_DATE` | 0 | 50 | 1,093 → 1,143 |

Post-repair coverage by status:

| Status | PERMIT_DATE | FINAL_DATE |
| --- | --- | --- |
| Active | 708 / 713 (99.3%) | 0 / 713 (0%) |
| Final | 875 / 912 (95.9%) | 857 / 912 (94.0%) |
| In Review | 3 / 87 (3.4%) | 0 / 87 (0%) |
| Inactive | 73 / 100 (73.0%) | 0 / 100 (0%) |

`FILE_DATE` overall: 1,803 / 2,000 (90.1%).

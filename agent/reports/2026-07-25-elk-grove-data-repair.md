# Elk Grove (CA) data repair

**Summary:** Elk Grove (1,998 sample rows) uses a single civic-portal DATA schema under `permit_info`. STATUS_NORMALIZED was almost complete (2 NaNs filled; 2 stale non-Final labels with a `PermitFinaledDate` fixed to Final). FILE_DATE already matched `PermitAppliedDate` for 1,995/1,998 rows (3 blanks unfillable). PERMIT_DATE gained 46 fills from `PermitApprovedDate` when Issued was blank. FINAL_DATE gained 152 fills from APPROVED inspections whose Type contains `FINAL`. Large gaps remain on older CLOSED / CERT OF OCCUPANCY / COMPLETED rows with no issued, approved, or finaled source dates in DATA.

## Jurisdiction selection

First `(JURISDICTION, STATE)` in `permits_ca_sample.parquet` lacking `agent/scripts/{state}/data_repair_{state}_{city}.py` was **Elk Grove, CA**.

## DATA schema

All 1,998 rows share top-level keys: `fees`, `contacts`, `site_info`, `inspections`, `permit_info`, `search_data`.

| INFERRED_SCHEMA | n | Notes |
| --- | ---: | --- |
| `permit_info` | 1,997 | `PermitAppliedDate` present |
| `permit_info_no_applied` | 1 | Issued present, Applied blank (legacy CLOSED pool) |

Canonical mappings:

| Field | Source |
| --- | --- |
| STATUS_NORMALIZED | `permit_info.PermitStatus` (+ Final override if `PermitFinaledDate` set) |
| FILE_DATE | `PermitAppliedDate` |
| PERMIT_DATE | `PermitIssuedDate`, else `PermitApprovedDate` |
| FINAL_DATE | `PermitFinaledDate`, else latest APPROVED inspection with `FINAL` in Type |

## Field assessment

### STATUS_NORMALIZED

| Before | n |
| --- | ---: |
| Final | 1,578 |
| Active | 243 |
| Inactive | 109 |
| In Review | 66 |
| NaN | 2 |

- Existing labels matched `PermitStatus` for all mapped statuses (CLOSED/COMPLETED/CERT OF OCCUPANCY → Final; ISSUED/APPROVED → Active; EXPIRED/WITHDRAWN → Inactive; review-pipeline statuses → In Review).
- **Incorrect / missing:** 2 NaNs (`ACTIVE - NEED PRECON`, `INACTIVE MASTER PLAN`); 2 rows with `PermitFinaledDate` still labeled Active (ISSUED) or In Review (COMMENTS OUT).
- **Repair:** FILLED 2, FIXED 2 → no remaining NaNs. After: Final 1,580 / Active 243 / Inactive 110 / In Review 65.

### FILE_DATE

- 1,995/1,998 already equal `PermitAppliedDate` (day resolution).
- 3 missing: 2 WITHDRAWN and 1 CLOSED legacy with blank Applied (and no usable proxy under project conventions that avoid treating Issued as FILE_DATE).
- **Repair:** 0 FILLED / 0 FIXED. Coverage 99.8%.

### PERMIT_DATE

Ideal: populated for Active and Final.

| Status (before) | Missing PERMIT_DATE |
| --- | ---: |
| Final | 652 / 1,578 |
| Active | 70 / 243 |

- When present, PERMIT_DATE always matched `PermitIssuedDate`.
- Missing Issued but present Approved → fillable (mostly Active APPROVED / ISSUED over-the-counter style rows).
- **Repair:** FILLED 46 (all from Approved); FIXED 0. Missing 885 → 839.
- After repair: Active 210/243 (86.4%); Final 936/1,580 (59.2%).
- **Not fillable:** 33 Active ISSUED/ISSUED MASTER PLAN and 644 Final CLOSED/CERT OF OCCUPANCY/COMPLETED with neither Issued nor Approved in DATA.

### FINAL_DATE

Ideal: populated for Final.

- When present, FINAL_DATE always matched `PermitFinaledDate`.
- 265 Final rows missing FINAL_DATE also had blank `PermitFinaledDate`; 152 of those had an APPROVED inspection with `FINAL` in Type.
- 2 non-Final rows carried a FINAL_DATE (same as `PermitFinaledDate`); status remapped to Final instead of clearing the date.
- **Repair:** FILLED 152 (inspection fallback); FIXED 0. Missing 683 → 531.
- After repair: Final FINAL_DATE coverage 1,467/1,580 (92.8%); 0 non-Final rows retain FINAL_DATE.
- **Not fillable:** 113 Final rows (CERT OF OCCUPANCY 44, COMPLETED 15, CLOSED 54) with no finaled date and no usable FINAL inspection.

## Repair performance

Script: `agent/scripts/ca/data_repair_ca_elk_grove.py`  
Artifact: `$AGENT_DATA_PATH/elk_grove_repaired_sample.parquet`

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 2 | 2 | 2 → 0 |
| FILE_DATE | 0 | 0 | 3 → 3 |
| PERMIT_DATE | 46 | 0 | 885 → 839 |
| FINAL_DATE | 152 | 0 | 683 → 531 |

Integrity checks after repair: FILE_DATE matches Applied when Applied present; PERMIT_DATE matches Issued when Issued present; FINAL_DATE matches Finaled when Finaled present; no STATUS NaNs; no FINAL_DATE on non-Final rows.

# Folsom (CA) data repair

**Summary:** Folsom was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. Assessed and repaired `STATUS_NORMALIZED`, `FILE_DATE`, `PERMIT_DATE`, and `FINAL_DATE` from the civic-portal `DATA` JSON (`permit_info` / `search_data`). Status: **FIXED 9** (stale `STATUS_ORIGINAL` behind newer `PermitStatus`, plus three `ISSUED` rows that already had `PermitFinaledDate` → Final). `FILE_DATE` already matched `PermitAppliedDate` on all 2,001 rows. `PERMIT_DATE` missingness fell from **323 → 284** (**FILLED 39**) using Issued, then Approved. `FINAL_DATE`: **FILLED 7 · FIXED 6** — filled from `PermitFinaledDate` after status upgrades and from FINAL PASS inspections; cleared spurious finals on CANCELLED rows. Remaining gaps are mostly `permit_info_applied_only` shells (no Issued/Approved) and Final rows with blank `PermitFinaledDate` and no FINAL PASS inspection.

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_ca_sample.parquet`
- Jurisdiction: **Folsom, CA** (n=2,001)
- Script: `agent/scripts/ca/data_repair_ca_folsom.py` (`data_repair`)
- Artifact: `AGENT_DATA_PATH/folsom_repaired_sample.parquet`

## DATA schema (`INFERRED_SCHEMA`)

All records share top-level keys `fees`, `contacts`, `site_info`, `inspections`, `permit_info`, `search_data`. Sub-schemas reflect which `permit_info` dates are populated:

| Schema | n | Description |
| --- | ---: | --- |
| `permit_info_issued_finaled` | 1,134 | Applied + Issued + Finaled |
| `permit_info_issued` | 547 | Applied + Issued, no Finaled |
| `permit_info_applied_only` | 204 | Applied only |
| `permit_info_approved` | 110 | Applied + Approved, no Issued |
| `permit_info` | 6 | Other date combinations |

Canonical fields:

| Field | Source |
| --- | --- |
| `STATUS_NORMALIZED` | `permit_info.PermitStatus`; if `PermitFinaledDate` present and status is not cancelled/expired/withdrawn → Final |
| `FILE_DATE` | `PermitAppliedDate` (fallback: `search_data.Application`) |
| `PERMIT_DATE` | `PermitIssuedDate` / `search_data.Issued`; else `PermitApprovedDate` |
| `FINAL_DATE` | `PermitFinaledDate`; else latest PASS inspection with `FINAL` in Type |

## Field assessment

### STATUS_NORMALIZED

**Before:** Final 1,236 · Active 457 · In Review 182 · Inactive 126 · missing 0

Upstream normalized from `STATUS_ORIGINAL`, which is usually the lowercased `PermitStatus`. Issues:
1. **5 rows** with `PermitStatus=FINALED` still carried `STATUS_ORIGINAL` issued/approved → Active.
2. **3 rows** with `PermitStatus=ISSUED` but a populated `PermitFinaledDate` (and FINAL PASS inspections) → upgraded to Final (status lag).
3. **1 row** with `PermitStatus=ISSUED` still carried `STATUS_ORIGINAL=in review` → In Review → Active.

`CANCELLED` rows that store a close-out in `PermitFinaledDate` are **not** upgraded to Final.

When present, `PermitStatus` maps cleanly:

| `PermitStatus` | `STATUS_NORMALIZED` |
| --- | --- |
| FINALED, BUILDING FINAL, CLOSED, CERTIFICATE ISSUED | Final |
| ISSUED, APPROVED | Active |
| PAID, INITIAL SUBMITTAL, IN REVIEW, PROJECTDOX, PLAN CHECK, INCOMPLETE, READY TO ISSUE, OUTSTANDING ITEMS, HOLD, INITIAL FEES DUE, STAFF REVIEW | In Review |
| EXPIRED, CANCELLED, EXPIRED APPLICATION, WITHDRAWN | Inactive |

**After:** Final 1,244 · Active 450 · In Review 181 · Inactive 126 · missing 0  
Flags: **FILLED 0 · FIXED 9**

### FILE_DATE

**Before:** 0 missing (100%).

- Every row’s `FILE_DATE` equals `PermitAppliedDate`.
- `search_data.Application` mirrors the same calendar day on all rows.

**After:** still 0 missing.  
Flags: **FILLED 0 · FIXED 0**

### PERMIT_DATE

**Before:** 323 missing (16.1%). Among Active/Final: 122 / 1,693 missing.

When `PermitIssuedDate` is present, existing `PERMIT_DATE` already matched it (1,678 rows). Gaps were Active/Final rows with blank Issued but a usable Approved date, plus two ISSUED rows whose dates were skipped because status was wrong upstream.

Repairs (Active / Final only):
1. Prefer `PermitIssuedDate` / `search_data.Issued`.
2. Else `PermitApprovedDate`.

**After:** 284 missing (14.2%). Active 84.9% populated · Final 98.7%.  
Flags: **FILLED 39 · FIXED 0**

Not repairable: 84 Active/Final rows (mostly `APPROVED` / `FINALED` `permit_info_applied_only`) have neither Issued nor Approved.

### FINAL_DATE

**Before:** 866 missing (43.3%). Among Final: 110 / 1,236 missing. Nine non-Final rows incorrectly carried a FINAL_DATE (3 Active ISSUED with Finaled; 6 Inactive CANCELLED).

Root cause: upstream copied `PermitFinaledDate` when present, including onto CANCELLED close-outs, and did not use FINAL PASS inspections when Finaled was blank. Three ISSUED+Finaled rows kept Active status.

Repairs:
1. After status correction, fill from `PermitFinaledDate` (5 upgraded FINALED rows).
2. Fill from latest PASS inspection with `FINAL` in Type when Finaled is blank (2 rows).
3. Clear FINAL_DATE on CANCELLED (**FIXED** to null). The 3 ISSUED+Finaled rows become Final and keep their Finaled date.

**After:** 865 missing (43.2%). Final 91.3% populated · Active/In Review/Inactive 0%.  
Flags: **FILLED 7 · FIXED 6**

Not repairable: 108 Final rows (mostly `permit_info_issued` / `applied_only` / `approved` with blank Finaled and no FINAL PASS inspection).

## Repair performance (sample)

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | ---: | ---: | ---: | ---: |
| STATUS_NORMALIZED | 0 | 9 | 0 | 0 |
| FILE_DATE | 0 | 0 | 0 | 0 |
| PERMIT_DATE | 39 | 0 | 323 | 284 |
| FINAL_DATE | 7 | 6 | 866 | 865 |

## Artifacts

- Repair script: `agent/scripts/ca/data_repair_ca_folsom.py`
- Repaired sample: `AGENT_DATA_PATH/folsom_repaired_sample.parquet`

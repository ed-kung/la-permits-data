# Mendocino County (CA) data repair

**Summary:** Mendocino County was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. Assessed and repaired `STATUS_NORMALIZED`, `FILE_DATE`, `PERMIT_DATE`, and `FINAL_DATE` from the civic-portal `DATA` JSON (`permit_info` + `inspections`). Status missingness fell from **64 → 0** (**FILLED 64 · FIXED 21**): blank-Status legacy conversions inferred Active/In Review; `READY FOR APPLICANT` filled; Finaled/Issued/Expired/Superseded/Satisfactory mismatches corrected. `FILE_DATE` already matched `PermitAppliedDate` wherever Applied exists (**FILLED 0 · FIXED 0**); 7 rows lack Applied in DATA. `PERMIT_DATE` gained **FILLED 63** (mostly Approved fallback on TRANSPORTATION/ENCROACHMENT Issued shells). `FINAL_DATE` gained **FILLED 269 · FIXED 2** (legacy type-33 finals + status-fixed Finaled rows; cleared spurious finals on Inactive). Final coverage is **1,231 / 1,265 (97.3%)**. Active PERMIT coverage is **190 / 190 (100%)**.

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_ca_sample.parquet`
- Jurisdiction: **Mendocino County, CA** (n=2,000) — first pair lacking `agent/scripts/{state}/data_repair_{state}_{city}.py` (index 87 after Palo Alto)
- Script: `agent/scripts/ca/data_repair_ca_mendocino_county.py` (`data_repair`)
- Artifact: `AGENT_DATA_PATH/repaired/permits_ca_mendocino_county_repaired.parquet`

## DATA schema (`INFERRED_SCHEMA`)

All records share top-level keys: `fees`, `contacts`, `site_info`, `inspections`, `permit_info`, `search_data`. Canonical dates/status live under `permit_info`; `search_data` only mirrors Address / RECORDID / Permit Number. Sub-schemas reflect which `permit_info` dates are populated:

| Schema | n | Description |
| --- | ---: | --- |
| `permit_info_issued_finaled` | 952 | Issued + Finaled present |
| `permit_info_issued` | 766 | Issued present, Finaled blank |
| `permit_info_applied_only` | 125 | Only Applied populated |
| `permit_info_approved_only` | 76 | Approved present, Issued/Finaled blank |
| `legacy_no_status` | 61 | Blank PermitStatus but dates present |
| `permit_info_finaled_only` | 18 | Finaled present, Issued blank |
| `permit_info_empty_dates` | 2 | Status text, no usable dates |

Canonical fields:

| Field | Source |
| --- | --- |
| `STATUS_NORMALIZED` | `permit_info.PermitStatus`; else FinaledDate → Final; else blank-status date inference |
| `FILE_DATE` | `PermitAppliedDate` only (do not backfill from Issued) |
| `PERMIT_DATE` | `PermitIssuedDate`; else `PermitApprovedDate` |
| `FINAL_DATE` | `PermitFinaledDate`; else latest final / legacy Type `33`+Result `1` inspection |

## Field assessment

### STATUS_NORMALIZED

**Before:** Final 1,259 · Inactive 469 · Active 136 · In Review 72 · missing 64

`PermitStatus` → expected mapping (selected):

| `PermitStatus` | `STATUS_NORMALIZED` |
| --- | --- |
| FINALED, COMPLETED, COMPLETED SA, SATISFACTORY | Final |
| ISSUED | Active |
| UNDER REVIEW, HOLD, WAITING ON APPLICANT, CORRECTION LETTER, READY FOR APPLICANT, READY, IN PROGRESS, REVISION, BOND REQUIRE | In Review |
| EXPIRED BY DATE, EXPIRED, VOID, CANCELLED*, SUPERSEDED, ABANDONED, DENIED, UNSATISFACTORY | Inactive |

Issues:
1. **61 blank `PermitStatus`:** legacy conversions with dates but empty status → **FILLED** Active (55, Issued/Approved present) or In Review (6, Applied only).
2. **3 null with `READY FOR APPLICANT`:** unmapped upstream → **FILLED** In Review.
3. **21 mismatches vs `PermitStatus` (FIXED):**
   - FINALED labeled Active (4) or Inactive (2) — STATUS_ORIGINAL lagged (`issued` / `expired`)
   - ISSUED labeled Inactive (3) or In Review (1)
   - EXPIRED / CANCELLED / UNSATISFACTORY labeled In Review (6); EXPIRED BY DATE labeled Active (1)
   - SUPERSEDED labeled Final (2)
   - SATISFACTORY labeled In Review (2)

**After:** Final 1,265 · Inactive 473 · Active 190 · In Review 72 · missing 0  
Flags: **FILLED 64 · FIXED 21**

### FILE_DATE

**Before:** 7 missing (0.4%).

- Wherever `PermitAppliedDate` exists (1,993 rows), `FILE_DATE` matches exactly — 0 disagreements.
- The 7 missing rows all have blank Applied in DATA (4 have Issued only; 2 VOID/HOLD shells with no dates; 1 Issued-only blank status). Not backfilled from Issued (application date is absent, not mis-copied).

**After:** still 7 missing.  
Flags: **FILLED 0 · FIXED 0**  
Coverage: **99.7%**.

### PERMIT_DATE

**Before:** 230 missing (11.5%). Among Active/Final: 65 / 1,395 missing (Active 46/136 · Final 19/1,259).

- When set, `PERMIT_DATE` always matched `PermitIssuedDate` (1,770/1,770) — 0 incorrect values to fix against Issued.
- **FILLED 63:** 62 from `PermitApprovedDate` when Issued blank (TRANSPORTATION trip/annual and ENCROACHMENT Issued shells); 1 from Issued on an ISSUED row previously labeled In Review.
- Remaining Active/Final gaps: **5 Final** with neither Issued nor Approved (4 finaled-only shells + 1 applied-only FINALED).

**After:** missing 167.  
Flags: **FILLED 63 · FIXED 0**  
Active coverage: **190 / 190 (100%)** · Final coverage: **1,260 / 1,265 (99.6%)**

### FINAL_DATE

**Before:** 1,036 missing (51.8%); Final missing 297 / 1,259. When present, always matched `PermitFinaledDate` (964/964).

- **FILLED 269:** 6 from `PermitFinaledDate` on status-fixed Final rows; **263** from inspections — almost all legacy `Type=33` / `Result=1` finals that upstream never mapped when `PermitFinaledDate` was blank.
- **FIXED 2:** cleared spurious `FINAL_DATE` on Inactive (`EXPIRED` / `EXPIRED BY DATE`) rows that still carried `PermitFinaledDate`.
- Remaining Final gaps: **34** (`permit_info_issued` FINALED/COMPLETED/SATISFACTORY) with blank FinaledDate and no usable final inspection.

**After:** missing 769; Final coverage **1,231 / 1,265 (97.3%)**.  
Flags: **FILLED 269 · FIXED 2**

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| `STATUS_NORMALIZED` | 64 | 21 | 64 → 0 |
| `FILE_DATE` | 0 | 0 | 7 → 7 |
| `PERMIT_DATE` | 63 | 0 | 230 → 167 |
| `FINAL_DATE` | 269 | 2 | 1,036 → 769 |

Coverage after repair:

| Metric | Value |
| --- | --- |
| Active with `PERMIT_DATE` | 190 / 190 (100%) |
| Final with `PERMIT_DATE` | 1,260 / 1,265 (99.6%) |
| Final with `FINAL_DATE` | 1,231 / 1,265 (97.3%) |
| All with `FILE_DATE` | 1,993 / 2,000 (99.7%) |

Chronology notes (source DATA, not introduced by repair): 9 rows with `PERMIT_DATE` < `FILE_DATE` (Approved fallback earlier than Applied, often annual/trip permits); 6 with `FINAL_DATE` < `PERMIT_DATE` (legacy inspection/finaled timestamps).

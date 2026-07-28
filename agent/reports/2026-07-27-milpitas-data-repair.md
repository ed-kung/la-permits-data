# Milpitas (CA) data repair

**Summary:** Milpitas was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. Assessed and repaired `STATUS_NORMALIZED`, `FILE_DATE`, `PERMIT_DATE`, and `FINAL_DATE` from the portal `DATA` JSON (`permit_info` / inspections). Status is now fully populated (**FILLED 2 · FIXED 15**): stale FINALED / CLOSED / ISSUED / APPROVED labels and empty-status CONV shells were corrected, and rows with `PermitFinaledDate` were forced to Final. `FILE_DATE` already matched `PermitAppliedDate` for all 1,991 rows with an Applied date (8 shells remain missing; no changes). `PERMIT_DATE` missingness fell from **166 → 149** (**FILLED 17**) via Issued (preferred) and Approved fallback after status remaps. `FINAL_DATE` missingness fell from **554 → 542** (**FILLED 12**) from `PermitFinaledDate` and finaling inspections; legacy CLOSED rows with only late FOLLOW UP / Complete sweeps stay missing by design.

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_ca_sample.parquet`
- Jurisdiction: **Milpitas, CA** (n=1,999)
- Script: `agent/scripts/ca/data_repair_ca_milpitas.py` (`data_repair`)
- Artifact: `AGENT_DATA_PATH/milpitas_repaired_sample.parquet`

## DATA schema (`INFERRED_SCHEMA`)

All records share the same top-level keys: `contacts`, `fees`, `inspections`, `permit_info`, `search_data`, `site_info`. Sub-schemas reflect which `permit_info` dates are populated:

| Schema | n | Description |
| --- | ---: | --- |
| `permit_info_full` | 1,412 | Applied + Issued + Finaled |
| `permit_info_issued` | 423 | Applied + Issued (no Finaled) |
| `permit_info_applied_only` | 136 | Applied only |
| `permit_info_approved` | 20 | Applied + Approved (no Issued/Finaled) |
| `permit_info_shell` | 8 | No usable Applied/Issued/Approved/Finaled |

Canonical fields:

| Field | Source |
| --- | --- |
| `STATUS_NORMALIZED` | `permit_info.PermitStatus`; override to Final when `PermitFinaledDate` present; else infer from dates if status empty |
| `FILE_DATE` | `PermitAppliedDate` |
| `PERMIT_DATE` | `PermitIssuedDate`, else `PermitApprovedDate` |
| `FINAL_DATE` | `PermitFinaledDate`; else latest finaling inspection `Completed` (Type contains FINAL / Fin, Result PASS/PASSED/…; Result FINALED). FOLLOW UP admin sweeps ignored |

`PermitExpirationDate` is a validity window, not a completion date. `search_data` has identifiers only.

## Field assessment

### STATUS_NORMALIZED

**Before:** Final 1,656 · Inactive 150 · Active 110 · In Review 81 · missing 2

`PermitStatus` → expected mapping (case-insensitive):

| `PermitStatus` | `STATUS_NORMALIZED` |
| --- | --- |
| FINALED, CLOSED, COMPLETE | Final |
| ISSUED, RENEWED, APPROVED | Active |
| PLAN CHECK, UNDER REVIEW, PENDING, Appr w/ Cond | In Review |
| EXPIRED, CANCELED, WITHDRAWN, DENIED | Inactive |

Issues:
1. **11 mis-normalized rows** vs portal status / finaled date:
   - FINALED → Active (4) → Final (also had `PermitFinaledDate`)
   - CLOSED → Active (1) / Inactive (2) → Final
   - ISSUED → In Review (1) → Active; ISSUED with `PermitFinaledDate` → Final (1)
   - APPROVED → In Review (1) → Active
2. **5 cancel/withdraw rows** with `PermitFinaledDate` were Inactive → Final (portal closed them with a finaled stamp; matches sibling `permit_info` repair convention).
3. **2 empty `PermitStatus`** CONV_PLANNING / CONV_BUILDING shells with Applied-only dates and null status → In Review (FILLED).

**After:** Final 1,669 · Inactive 143 · Active 106 · In Review 81 · missing 0  
Flags: **FILLED 2 · FIXED 15**

### FILE_DATE

**Before:** 8 missing (0.4%).

- When `PermitAppliedDate` is present, `FILE_DATE` matches it for all 1,991 rows (0 mismatches).
- The 8 missing rows are shells with empty Applied/Issued/Approved/Finaled — not fillable from DATA.

**After:** still 8 missing.  
Flags: **FILLED 0 · FIXED 0**

### PERMIT_DATE

**Before:** 166 missing (8.3%). Among Active/Final: 54 / 1,766 missing.

Root cause: upstream only copied `PermitIssuedDate`. Active/Final rows with Issued empty but `PermitApprovedDate` present (APPROVED / COMPLETE / some FINALED), plus ISSUED rows remapped from In Review, were left blank.

Repairs (Active / Final only):
1. Prefer `PermitIssuedDate`.
2. Else `PermitApprovedDate`.

**After:** 149 missing. Active 103/106 (97.2%); Final 1,629/1,669 (97.6%).  
Flags: **FILLED 17 · FIXED 0**

Remaining Active/Final gaps: 3 legacy `Approved` with no Issued/Approved dates; 40 Final (mostly CLOSED / FINALED / cancel-closure) with neither Issued nor Approved in DATA.

### FINAL_DATE

**Before:** 554 missing (27.7%). Among Final: 217 / 1,656 missing.

Root cause: upstream copied `PermitFinaledDate` only. Four FINALED rows mislabeled Active had finaled dates but no `FINAL_DATE`. A few FINALED / CLOSED Final rows lack `PermitFinaledDate` but have contemporaneous finaling inspections. Most CLOSED Final rows (~207 remaining) only have FOLLOW UP / Complete inspections ~20–28 years after issuance (administrative cleanup) — not used.

Repairs (Final only):
1. Prefer `PermitFinaledDate`.
2. Else latest finaling inspection `Completed` (FINAL / Fin in Type with PASS/PASSED/…, or Result FINALED). Exclude FOLLOW UP.

**After:** 542 missing. Final 1,457/1,669 (87.3%); Active / In Review / Inactive have 0 final dates.  
Flags: **FILLED 12 · FIXED 0**

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| `STATUS_NORMALIZED` | 2 | 15 | 2 → 0 |
| `FILE_DATE` | 0 | 0 | 8 → 8 |
| `PERMIT_DATE` | 17 | 0 | 166 → 149 |
| `FINAL_DATE` | 12 | 0 | 554 → 542 |

## Not repairable / left as-is

- 8 Applied-empty shells: no FILE_DATE source.
- ~40 Active/Final without Issued or Approved: no PERMIT_DATE source.
- ~207 CLOSED Final without `PermitFinaledDate` or a finaling inspection: FINAL_DATE left missing (FOLLOW UP Complete is not a completion date).
- 5 FINALED Final still lacking both `PermitFinaledDate` and a usable finaling inspection.

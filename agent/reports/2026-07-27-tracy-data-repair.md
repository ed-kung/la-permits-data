# Tracy (CA) data repair

**Summary:** Tracy was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. Assessed and repaired `STATUS_NORMALIZED`, `FILE_DATE`, `PERMIT_DATE`, and `FINAL_DATE` from the portal `DATA` JSON (`permit_info` / inspections / `search_data`). Status missingness fell from **335 → 5** (**FILLED 330 · FIXED 56**): empty CRW shells inferred from dates, stale FINALED/ISSUED/CANCELLED labels corrected, and rows with `PermitFinaledDate` forced to Final (including 31 INACTIVE close-outs). `FILE_DATE` already matched `PermitAppliedDate` whenever Applied was present (**FILLED 0 · FIXED 0**; 17 shells remain missing). `PERMIT_DATE` missingness fell **230 → 191** (**FILLED 39**) via Issued (preferred) and Approved fallback after status remaps (one implausible `1/1/2819` Issued rejected). `FINAL_DATE` missingness fell **832 → 817** (**FILLED 15**); Final coverage is **1,184 / 1,198 (98.8%)**, with Active / In Review / Inactive at 0 final dates. Chronology inversions remaining are source-data quirks (**FILE>PERMIT=6**, **PERMIT>FINAL=3**).

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_ca_sample.parquet`
- Jurisdiction: **Tracy, CA** (n=2,001)
- Script: `agent/scripts/ca/data_repair_ca_tracy.py` (`data_repair`)
- Artifact: `AGENT_DATA_PATH/repaired/permits_ca_tracy_repaired.parquet`

## DATA schema (`INFERRED_SCHEMA`)

All records share the same top-level keys: `contacts`, `fees`, `inspections`, `permit_info`, `search_data`, `site_info`. Sub-schemas reflect which `permit_info` dates are populated:

| Schema | n | Description |
| --- | ---: | --- |
| `permit_info_full` | 1,163 | Applied + Issued + Finaled |
| `permit_info_issued` | 614 | Applied + Issued (no Finaled) |
| `permit_info_applied_only` | 137 | Applied only |
| `permit_info_approved` | 70 | Applied + Approved (no Issued/Finaled) |
| `permit_info_shell` | 13 | No usable Applied/Issued/Approved/Finaled |
| `permit_info_partial` | 4 | Issued/Approved/Finaled without Applied |

Canonical fields:

| Field | Source |
| --- | --- |
| `STATUS_NORMALIZED` | `permit_info.PermitStatus`; override to Final when `PermitFinaledDate` present; else infer from dates if status empty |
| `FILE_DATE` | `PermitAppliedDate`; else `search_data['Application']` |
| `PERMIT_DATE` | `PermitIssuedDate`, else `PermitApprovedDate`, else `search_data['Issued']` |
| `FINAL_DATE` | `PermitFinaledDate`; else latest finaling inspection `Completed` (Type contains FINAL with Result APPROVED/PASSED/…, or Result FINALED). FOLLOW UP sweeps ignored |

`PermitExpirationDate` is a validity window, not a completion date.

## Field assessment

### STATUS_NORMALIZED

**Before:** Final 1,034 · Active 285 · Inactive 212 · In Review 135 · missing 335

`PermitStatus` → expected mapping (case-insensitive):

| `PermitStatus` | `STATUS_NORMALIZED` |
| --- | --- |
| FINALED, COUNTY RELEASED | Final |
| ISSUED, ACTIVE, APPROVED | Active |
| PENDING REVIEW, PENDING, READY TO ISSUE, E Payment, COUNCIL PENDING, CIP DESIGN, ROUTING FORM-… | In Review |
| EXPIRED, CANCELLED, INACTIVE, VOID, NOT REQUIRED | Inactive |

Issues:
1. **Stale labels vs `PermitStatus` / finaled date (56 FIXED):**
   - FINALED → Active (11) / In Review (1) → Final (also had `PermitFinaledDate`)
   - ISSUED → In Review (8) → Active (`STATUS_ORIGINAL` lag: hold / pending review / ready to issue)
   - CANCELLED → In Review (1) → Inactive
   - INACTIVE with `PermitFinaledDate` (31) → Final
   - NOT REQUIRED → Final (2) → Inactive
   - Plus 2 Active rows with finaled date already stamped as Active
2. **Empty / `<none>` `PermitStatus` (330 FILLED):** mostly legacy CRW shells. Inferred from dates: Issued → Active (203), Finaled → Final (121), Applied-only / CIP DESIGN / COUNCIL PENDING → In Review (6).
3. **5 remaining nulls (unrepairable):** empty shells with no status and no usable dates.

**After:** Final 1,198 · Active 483 · Inactive 184 · In Review 131 · missing 5  
Flags: **FILLED 330 · FIXED 56**

### FILE_DATE

**Before:** 17 missing (0.8%).

- When `PermitAppliedDate` is present, `FILE_DATE` matches it for all 1,984 rows (0 mismatches).
- `search_data['Application']` (158 rows) always agrees with FILE when both present; none of the 17 gaps have Application.
- The 17 missing rows are shells with empty Applied/Issued/Approved/Finaled — not fillable from DATA.

**After:** still 17 missing.  
Flags: **FILLED 0 · FIXED 0**

Coverage after: **99.2%**.

### PERMIT_DATE

**Before:** 230 missing (11.5%). Among Active/Final: 47 / 1,319 missing.

Root cause: upstream copied `PermitIssuedDate` only. Active/Final rows with Issued empty (or the one implausible `1/1/2819`) but `PermitApprovedDate` present, plus ISSUED rows remapped from In Review and empty-status shells remapped to Active/Final, were left blank.

Repairs (Active / Final only):
1. Prefer `PermitIssuedDate` (reject years outside 1980–2035).
2. Else `PermitApprovedDate`.
3. Else `search_data['Issued']`.

**After:** 191 missing. Active **477/483 (98.8%)**; Final **1,187/1,198 (99.1%)**.  
Flags: **FILLED 39 · FIXED 0**

Remaining Active/Final gaps: 6 ISSUED shells with no Issued/Approved; 11 Final (FINALED / empty-status with finaled only) with neither Issued nor Approved.

### FINAL_DATE

**Before:** 832 missing (41.6%). Among Final: 19 / 1,034 missing. Also 11 Active FINALED rows had `PermitFinaledDate` but no `FINAL_DATE` because status was wrong.

Root cause: upstream copied `PermitFinaledDate` only when status was already Final; status lag hid finaled dates on Active/In Review rows. Some Final COUNTY RELEASED / FINALED rows lack `PermitFinaledDate` but have finaling inspections (FIRE FINAL BP).

Repairs (Final only):
1. Prefer `PermitFinaledDate`.
2. Else latest finaling inspection `Completed` (FINAL in Type with APPROVED/PASSED/…, or Result FINALED). Exclude FOLLOW UP / non-final Types (e.g. VISUAL INSPECTION).

**After:** 817 missing. Final **1,184/1,198 (98.8%)**; Active / In Review / Inactive have **0** final dates.  
Flags: **FILLED 15 · FIXED 0**

Remaining Final gaps (14): FINALED / COUNTY RELEASED shells with empty `PermitFinaledDate` and no usable finaling inspection.

## Repair performance

| Field | Missing before | Missing after | FILLED | FIXED |
| --- | ---: | ---: | ---: | ---: |
| `STATUS_NORMALIZED` | 335 | 5 | 330 | 56 |
| `FILE_DATE` | 17 | 17 | 0 | 0 |
| `PERMIT_DATE` | 230 | 191 | 39 | 0 |
| `FINAL_DATE` | 832 | 817 | 15 | 0 |

Ideal coverage after repair:

| Rule | Result |
| --- | --- |
| FILE_DATE for all records | 99.2% (17 unrepairable shells) |
| PERMIT_DATE for Active + Final | 98.9% (1,664 / 1,681) |
| FINAL_DATE for Final | 98.8% (1,184 / 1,198) |

Chronology (source-data inversions left as-is): FILE > PERMIT on 6 rows; PERMIT > FINAL on 3 rows.

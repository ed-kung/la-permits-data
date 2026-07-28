# South San Francisco (CA) data repair

**Summary:** South San Francisco was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. Assessed and repaired `STATUS_NORMALIZED`, `FILE_DATE`, `PERMIT_DATE`, and `FINAL_DATE` from the portal `DATA` JSON (`permit_info` / inspections). Status missingness fell from **97 → 1** (**FILLED 96 · FIXED 20**): empty CRW shells inferred from dates/finaling inspections, stale FINALED/ISSUED/CANCELLED/ACTIVE labels corrected, and rows with `PermitFinaledDate` forced to Final. `FILE_DATE` already matched `PermitAppliedDate` whenever Applied was present (**FILLED 0 · FIXED 0**; 2 shells remain missing). `PERMIT_DATE` missingness fell **782 → 631** (**FILLED 151**) via Issued (preferred) and Approved fallback on Active/Final rows. `FINAL_DATE` missingness fell **1,289 → 1,224** (**FILLED 65**); Final coverage is **776 / 1,002 (77.4%)**, with Active / In Review / Inactive at 0 final dates. Chronology inversions remaining are source-data quirks (**FILE>PERMIT=20**, **PERMIT>FINAL=2**).

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_ca_sample.parquet`
- Jurisdiction: **South San Francisco, CA** (n=2,000) — first pair lacking `agent/scripts/{state}/data_repair_{state}_{city}.py`
- Script: `agent/scripts/ca/data_repair_ca_south_san_francisco.py` (`data_repair`)
- Artifact: `AGENT_DATA_PATH/repaired/permits_ca_south_san_francisco_repaired.parquet`

## DATA schema (`INFERRED_SCHEMA`)

All records share the same top-level keys: `contacts`, `fees`, `inspections`, `permit_info`, `search_data`, `site_info`. Sub-schemas reflect which `permit_info` dates are populated:

| Schema | n | Description |
| --- | ---: | --- |
| `permit_info_full` | 619 | Applied + Issued + Finaled |
| `permit_info_issued` | 600 | Applied + Issued (no Finaled) |
| `permit_info_applied_only` | 600 | Applied only |
| `permit_info_approved` | 179 | Applied + Approved (no Issued/Finaled) |
| `permit_info_shell` | 2 | No usable Applied/Issued/Approved/Finaled |

Canonical fields:

| Field | Source |
| --- | --- |
| `STATUS_NORMALIZED` | `permit_info.PermitStatus`; override to Final when `PermitFinaledDate` present; else infer from finaling inspection / Issued / Approved / Applied if status empty |
| `FILE_DATE` | `PermitAppliedDate` (SSF `search_data` has no Application key) |
| `PERMIT_DATE` | `PermitIssuedDate`, else `PermitApprovedDate` |
| `FINAL_DATE` | `PermitFinaledDate`; else latest finaling inspection `Completed` (Type contains FINAL with Result APPROVED/PASSED/…, or Result FINALED) |

`PermitExpirationDate` is a validity window, not a completion date. SSF `search_data` carries only Address / RECORDID / Permit Number (plus occasional SITE_APN / SITE_STREETNAME).

## Field assessment

### STATUS_NORMALIZED

**Before:** Final 971 · Active 547 · Inactive 274 · In Review 111 · missing 97

`PermitStatus` → expected mapping (case-insensitive):

| `PermitStatus` | `STATUS_NORMALIZED` |
| --- | --- |
| FINALED, COMPLIANT | Final |
| ISSUED, ACTIVE, APPROVED | Active |
| PENDING, READY TO ISSUE, PLAN CHECK, UNDER REVIEW, CORRECTIONS, DEPOSIT RFND, BALANCE DUE | In Review |
| EXPIRED, CANCELLED, NON COMPLIANT, NOT APPROVED | Inactive |

Issues:
1. **Stale labels vs `PermitStatus` / finaled date (20 FIXED):**
   - FINALED → Active (3) / In Review (1) → Final
   - ISSUED / READY TO ISSUE / DEPOSIT RFND / CANCELLED / NON COMPLIANT with `PermitFinaledDate` (12) → Final
   - CANCELLED → Active (1) → Inactive
   - ACTIVE / ISSUED → In Review (2) → Active
   - NOT APPROVED → In Review (2) → Inactive
2. **Empty `PermitStatus` (96 FILLED):** legacy CRW shells with null `STATUS_NORMALIZED`. Inferred from: Finaled date or successful finaling inspection → Final (16), Issued/Approved → Active (7), Applied-only → In Review (73).
3. **1 remaining null (unrepairable):** empty FIRE PROTECTION shell with no status and no usable dates.

**After:** Final 1,002 · Active 550 · Inactive 275 · In Review 172 · missing 1  
Flags: **FILLED 96 · FIXED 20**

### FILE_DATE

**Before:** 2 missing (0.1%).

- When `PermitAppliedDate` is present, `FILE_DATE` matches it for all 1,998 rows (0 mismatches).
- The 2 missing rows are shells with empty Applied (one ISSUED R1 occupancy inspection with only Expiration; one empty FIRE PROTECTION shell) — not fillable from DATA.

**After:** still 2 missing.  
Flags: **FILLED 0 · FIXED 0**

Coverage after: **99.9%**.

### PERMIT_DATE

**Before:** 782 missing (39.1%). Among Active/Final: 418 / 1,518 missing.

- When `PermitIssuedDate` is present, `PERMIT_DATE` always matches it (0 disagreements on 1,218 overlapping rows).
- Primary fillable gap: Active/Final rows with empty Issued but populated `PermitApprovedDate` → **FILLED 151** (Approved used as issuance proxy).
- Remaining Active/Final gaps (73 Active + 218 Final) have neither Issued nor Approved — largely COMPLIANT fire/occupancy inspections and FINALED/ISSUED shells with blank date fields.

**After:** 631 missing. Active coverage **477 / 550 (86.7%)**; Final **784 / 1,002 (78.2%)**.  
Flags: **FILLED 151 · FIXED 0**

### FINAL_DATE

**Before:** 1,289 missing (64.5%). Among Final: 272 / 971 missing.

- When `PermitFinaledDate` is present, `FINAL_DATE` always matches it (0 disagreements on 711 overlapping rows).
- 12 non-Final rows carried `FINAL_DATE` because they also had `PermitFinaledDate`; status repair remaps them to Final, so no spurious finals remain after repair.
- **FILLED 65** from successful finaling inspections on Final rows (and empty-status encroachment rows remapped to Final via PUBLIC WORKS FINAL / ENGINEER FINAL APPROVED).
- Remaining Final gaps (226): mostly COMPLIANT (207) and FINALED (19) with neither Finaled date nor a usable finaling inspection.

**After:** 1,224 missing. Final coverage **776 / 1,002 (77.4%)**; Active / In Review / Inactive **0%**.  
Flags: **FILLED 65 · FIXED 0**

## Repair performance

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | ---: | ---: | ---: | ---: |
| STATUS_NORMALIZED | 96 | 20 | 97 | 1 |
| FILE_DATE | 0 | 0 | 2 | 2 |
| PERMIT_DATE | 151 | 0 | 782 | 631 |
| FINAL_DATE | 65 | 0 | 1,289 | 1,224 |

Ideal-date coverage after repair:

| Rule | Coverage |
| --- | --- |
| FILE_DATE populated (all records) | 1,998 / 2,000 (99.9%) |
| PERMIT_DATE on Active | 477 / 550 (86.7%) |
| PERMIT_DATE on Final | 784 / 1,002 (78.2%) |
| FINAL_DATE on Final | 776 / 1,002 (77.4%) |

Chronology (source quirks, not introduced by repair): **FILE>PERMIT=20** (Applied after Issued/Approved in portal), **PERMIT>FINAL=2** (Issued/Approved after Finaled by one day to a week).

## Artifacts

- Script: `agent/scripts/ca/data_repair_ca_south_san_francisco.py`
- Repaired sample: `AGENT_DATA_PATH/repaired/permits_ca_south_san_francisco_repaired.parquet`

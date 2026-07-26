# Vallejo (CA) data repair

**Summary:** Assessed and repaired `STATUS_NORMALIZED`, `FILE_DATE`, `PERMIT_DATE`, and `FINAL_DATE` for Vallejo — the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. All 2,000 sample rows share one DATA schema (`permit_info` + `search_data`), the same portal layout as Richmond. The main status defect was 137 `COMPLIED` weed-abatement rows wrongly labeled In Review (should be Final), plus 13 `APPROVED` rows with a true `PermitFinaledDate` still labeled Active, and 61 unmapped statuses (`COMPLANT`, `LETR1BCK`, `REF-*`, etc.). Status is now fully populated (FILLED 61 · FIXED 150). `FILE_DATE` already matched `PermitAppliedDate` everywhere present (10 unfillable gaps). `PERMIT_DATE` gained 15 Approved-date fills for Active/Final. Spurious `FINAL_DATE` on non-Final rows was cleared (45 FIXED) and 17 Final gaps were filled from inspections. After repair: Final has 80.4% `PERMIT_DATE` and 96.8% `FINAL_DATE`; Active has 91.9% `PERMIT_DATE`; non-Final rows have 0% `FINAL_DATE`.

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_ca_sample.parquet`
- Jurisdiction: **Vallejo, CA** (n=2,000)
- Script: `agent/scripts/ca/data_repair_ca_vallejo.py` (`data_repair`)
- Artifact: `AGENT_DATA_PATH/vallejo_repaired_sample.parquet`

## DATA schema (`INFERRED_SCHEMA`)

| Schema | n | Description |
| --- | ---: | --- |
| `permit_info_search_data` | 2,000 | Flat portal payload: `contacts`, `fees`, `inspections`, `permit_info`, `search_data`, `site_info` |

Canonical fields under `permit_info`:

| Field | Source |
| --- | --- |
| `STATUS_NORMALIZED` | `PermitStatus` (infer from dates when blank/unmapped) |
| `FILE_DATE` | `PermitAppliedDate` |
| `PERMIT_DATE` | `PermitIssuedDate` (fallback: `PermitApprovedDate`) |
| `FINAL_DATE` | `PermitFinaledDate` (fallback: finaling / PUBLIC WORKS inspection `Completed`) |

Unlike Richmond, Vallejo does not use `PermitFinaledDate == PermitExpirationDate` as an expire-close stamp pattern (0 such rows among Inactive-like statuses).

## Field assessment

### STATUS_NORMALIZED

**Before:** Final 938 · Inactive 543 · In Review 234 · Active 224 · missing 61

Issues:
1. **`COMPLIED` → In Review (137 rows)** — almost all `WEED-IMPA` abatement cases with `PermitFinaledDate` present (136/137). Past-tense completion should be **Final**. This was the largest incorrect mapping.
2. **`APPROVED` with `PermitFinaledDate` still Active (13)** — legacy SFR / remodel / reroof rows that were finaled but left on an Approved portal label → **Final**.
3. **61 unmapped `PermitStatus` values** left `STATUS_NORMALIZED` null: `COMPLANT` (21; open complaint, not COMPLIED), `LETR1BCK` (11), `WORKORDR` (6), `REF-ABVH`/`REF-BLDG`/`REF-FIRE`/`REFMAINT` (13), `TOWED`/`UNCLAIMD`/`STOPWORK`/`1ST CIT`/`LETTER1`, plus one blank status. Filled via an explicit map and date inference (`WORKORDR` / `1ST CIT` / `REF-BLDG` with FinaledDate → Final; Inactive labels for TOWED/UNCLAIMD/STOPWORK; In Review for open referrals/complaints).
4. **Inactive labels** (`EXPIRED`, `VOID`, `ABATED`, `WITHDRAWN`, etc.) stay Inactive even when `PermitFinaledDate` is set (ABATED close dates are code-enforcement closures, not building-permit sign-offs).

**After:** Final 1,096 · Inactive 549 · Active 211 · In Review 144 · missing 0  
Flags: **FILLED 61 · FIXED 150**

### FILE_DATE

**Before:** 10 missing (0.5%).

- Where present (1,990), `FILE_DATE` always matches `PermitAppliedDate` at calendar-day resolution. No fixes.
- All 10 gaps also lack `PermitAppliedDate` (mostly VOID / ERROR / EXPIRED shells with no dates at all). No alternate application date is used.

**After:** still 10 missing (99.5% coverage).  
Flags: **FILLED 0 · FIXED 0**

### PERMIT_DATE

**Before:** 463 missing (23.2%). Where both present, `PERMIT_DATE` matches `PermitIssuedDate` at day resolution (9 apparent mismatches were Issued timestamps with a time component; dates agree).

Repairs:
- Fill Active/Final gaps from `PermitApprovedDate` when Issued is empty (**15 FILLED**: 11 Active + 4 Final).

Remaining Active/Final gaps (~17 Active ACTIVE/ISSUED/APPROVED; ~215 Final, mostly legacy `FINAL` without Issued/Approved) have neither Issued nor Approved in DATA. Many older Final records only carry Applied + Finaled.

**After:** missing 448. Active 194/211 (91.9%) · Final 881/1,096 (80.4%).  
Flags: **FILLED 15 · FIXED 0**

### FINAL_DATE

**Before:** 911 missing; 51 Final rows lacked `FINAL_DATE`; **192 non-Final rows** carried `FINAL_DATE` (136 COMPLIED — correct once remapped to Final; 13 APPROVED — remapped to Final; 35 ABATED + 3 EXPIRED + 2 VOID + 1 WITHDRAW + 1 APPLIED + 1 HOLD — spurious on Inactive/In Review).

Repairs:
- Clear `FINAL_DATE` on all non-Final rows (**45 FIXED** after COMPLIED/APPROVED remaps absorb their prior finals into Final).
- Fill Final gaps from finaling / PUBLIC WORKS inspection `Completed` when `PermitFinaledDate` is empty (**17 FILLED**).

Remaining Final gaps (34): 23 `FINALED` (mostly excavation/encroachment with empty or non-finaling inspections), 10 `CLOSED` investigations with no dates, 1 `COMPLIED`, 1 `COMPLETED`.

**After:** missing 939 overall (driven by clearing non-Final spurious dates). Final 1,061/1,096 (96.8%); Active / In Review / Inactive 0%.  
Flags: **FILLED 17 · FIXED 45**

## Repair performance

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | ---: | ---: | ---: | ---: |
| `STATUS_NORMALIZED` | 61 | 150 | 61 | 0 |
| `FILE_DATE` | 0 | 0 | 10 | 10 |
| `PERMIT_DATE` | 15 | 0 | 463 | 448 |
| `FINAL_DATE` | 17 | 45 | 911 | 939 |

Ideal-population coverage after repair:

| Status | n | FILE_DATE | PERMIT_DATE | FINAL_DATE |
| --- | ---: | ---: | ---: | ---: |
| Active | 211 | 210 (99.5%) | 194 (91.9%) | 0 (0%) |
| Final | 1,096 | 1,096 (100%) | 881 (80.4%) | 1,061 (96.8%) |
| In Review | 144 | 144 (100%) | 36 (25.0%) | 0 (0%) |
| Inactive | 549 | 540 (98.4%) | 441 (80.3%) | 0 (0%) |

## Artifacts

- Repair script: `agent/scripts/ca/data_repair_ca_vallejo.py`
- Repaired sample: `AGENT_DATA_PATH/vallejo_repaired_sample.parquet`

# Richmond (CA) data repair

**Summary:** Assessed and repaired `STATUS_NORMALIZED`, `FILE_DATE`, `PERMIT_DATE`, and `FINAL_DATE` for Richmond — the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. All 2,002 sample rows share one DATA schema (`permit_info` + `search_data`). Status repair filled 114 of 117 missing values and fixed 5 mismatches; `FILE_DATE` already matched `PermitAppliedDate` wherever present (381 gaps remain unfillable); `PERMIT_DATE` gained 41 Approved-date fills for Active/Final; and 212 spurious `FINAL_DATE` values on non-Final rows (mostly EXPIRED close stamps) were cleared while 2 Final gaps were filled. After repair: Final has 96.9% `PERMIT_DATE` and 87.5% `FINAL_DATE`; Active has 82.7% `PERMIT_DATE`; non-Final rows have 0% `FINAL_DATE`.

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_ca_sample.parquet`
- Jurisdiction: **Richmond, CA** (n=2,002)
- Script: `agent/scripts/ca/data_repair_ca_richmond.py` (`data_repair`)
- Artifact: `AGENT_DATA_PATH/richmond_repaired_sample.parquet`

## DATA schema (`INFERRED_SCHEMA`)

| Schema | n | Description |
| --- | ---: | --- |
| `permit_info_search_data` | 2,002 | Flat portal payload: `contacts`, `fees`, `inspections`, `permit_info`, `search_data`, `site_info` |

Canonical fields under `permit_info`:

| Field | Source |
| --- | --- |
| `STATUS_NORMALIZED` | `PermitStatus` (infer from dates when blank) |
| `FILE_DATE` | `PermitAppliedDate` |
| `PERMIT_DATE` | `PermitIssuedDate` (fallback: `PermitApprovedDate`) |
| `FINAL_DATE` | `PermitFinaledDate` (fallback: finaling inspection `Completed`) |

`PermitExpirationDate` is a validity window, not a sign-off date.

## Field assessment

### STATUS_NORMALIZED

**Before:** Active 561 · Inactive 540 · Final 444 · In Review 340 · missing 117

Issues:
1. **117 empty `PermitStatus`** (and null `STATUS_ORIGINAL` / `STATUS_NORMALIZED`), mostly legacy `SAP CONV` rows. 110 have `PermitIssuedDate` → **Active**; 2 have Approved-only → **Active**; 3 have Applied-only → **In Review**; 3 tracking stubs (`RC-PC1`, `ENG-HM`, `22010590`) have no dates → left missing.
2. **5 status mismatches** vs `PermitStatus` / FinaledDate:
   - `B22-00013`, `B24-00600`: `FINALED` labeled Active → **Final**
   - `B23-02695`: `ISSUED` labeled In Review (`STATUS_ORIGINAL` = application incomp) → **Active**
   - `B23-01668`: `EXPIRED` labeled Active → **Inactive**
   - `13-03701`: `ISSUED` with a true `PermitFinaledDate` → **Final**
3. **EXPIRED / VOID / CANCELLED** stay **Inactive** even when `PermitFinaledDate` is populated (on ~177 EXPIRED rows that date equals `PermitExpirationDate` — a close stamp, not a completion).
4. **In Review** (including BLD PLAN CHECK rows where FinaledDate equals Approved) stay In Review — plan-check completion is not a permit sign-off.

**After:** Active 669 · Inactive 541 · Final 447 · In Review 342 · missing 3  
Flags: **FILLED 114 · FIXED 5**

### FILE_DATE

**Before:** 381 missing (19.0%).

- Where present (1,621), `FILE_DATE` always matches `PermitAppliedDate` at calendar-day resolution. No fixes.
- All 381 gaps also lack `PermitAppliedDate`. Alternates exist (`PermitIssuedDate` on 160; fee Paid Date on 179) but are not used as application-date proxies (same convention as Gardena / Fontana / Modesto).

**After:** still 381 missing.  
Flags: **FILLED 0 · FIXED 0**

### PERMIT_DATE

**Before:** 625 missing (31.2%). Where present, always matches `PermitIssuedDate`.

Repairs:
- Fill Active/Final gaps from `PermitApprovedDate` when Issued is empty (**41 FILLED**: 37 Active + 4 Final).
- Empty-status → Active rows that already carried Issued-based `PERMIT_DATE` needed no change.

Remaining Active/Final gaps (~116 Active ISSUED/PRINT PTO/ACTIVE/APPROVED; ~14 Final) have neither Issued nor Approved in DATA.

**After:** missing 584. Active 553/669 (82.7%) · Final 433/447 (96.9%).  
Flags: **FILLED 41 · FIXED 0**

### FINAL_DATE

**Before:** 1,401 missing; 57 Final rows lacked `FINAL_DATE`; **214 non-Final rows** carried `FINAL_DATE` (191 EXPIRED, 13 APPLIED, 5 UNDER REVIEW, plus VOID / NON-APPLICABLE / ISSUED).

Root causes of spurious finals:
- On EXPIRED rows, `PermitFinaledDate` often equals `PermitExpirationDate` (177/191) — expire/close stamp copied into FINAL.
- On BLD PLAN CHECK APPLIED / UNDER REVIEW rows, FinaledDate equals Approved — plan-check completion, not permit finaling.

Repairs:
- Clear `FINAL_DATE` on all non-Final rows (**212 FIXED**).
- Fill Final gaps from FinaledDate after status remap, or from inspection `Result=FINALED` Completed (**2 FILLED**: `B24-00600` after remap; `09-00821` via inspection).

Remaining Final gaps: 56 (46 COMPLETELY PROCESSED legacy with Issued only; 7 FINALED + 3 CLOSEDBY PERMIT with empty FinaledDate and no usable finaling inspection).

**After:** Final 391/447 (87.5%) have `FINAL_DATE`; Active / In Review / Inactive have 0.  
Flags: **FILLED 2 · FIXED 212**

## Repair performance (sample)

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 114 | 5 | 117 → 3 |
| FILE_DATE | 0 | 0 | 381 → 381 |
| PERMIT_DATE | 41 | 0 | 625 → 584 |
| FINAL_DATE | 2 | 212 | 1,401 → 1,611 |

Missing `FINAL_DATE` rises because 212 incorrect non-Final finals were cleared; among Final rows, coverage improved (387 → 391 with dates, and status composition cleaned).

### Coverage by status (after repair)

| Status | n | FILE_DATE | PERMIT_DATE | FINAL_DATE |
| --- | ---: | ---: | ---: | ---: |
| Active | 669 | — | 553 (82.7%) | 0 (0%) |
| Final | 447 | — | 433 (96.9%) | 391 (87.5%) |
| In Review | 342 | — | 15 (4.4%) | 0 (0%) |
| Inactive | 541 | — | 417 (77.1%) | 0 (0%) |
| (all) | 2,002 | 1,621 (81.0%) | — | — |

## Artifacts

- `agent/scripts/ca/data_repair_ca_richmond.py`
- `AGENT_DATA_PATH/richmond_repaired_sample.parquet`

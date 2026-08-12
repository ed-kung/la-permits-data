# Largo (FL) data repair — STATUS_NORMALIZED and date fields

**Summary:** Among Florida sample jurisdictions missing a repair script, **Largo** was first. Its DATA is the Accela / eTRAKiT family (`permit_info` + `search_data` + inspections). Upstream status was complete but **32** rows were wrong: all **31 HISTORICAL** labeled In Review (legacy issued/finaled archive) plus **1 ISSUED** row with a PermitFinaledDate still labeled Active. FILE_DATE already matched PermitAppliedDate on every row (**0** repairs; 100% coverage). PERMIT_DATE matched Issued whenever present; **14 FILLED** from Approved on Active/Final shells with blank Issued. FINAL_DATE already matched PermitFinaledDate whenever present; **63** Final rows remain without a finaled stamp or usable inspections. After repair: Final 1,691 · Active 60 · Inactive 231 · In Review 18; Active/Final PERMIT coverage 96.7% / 99.9%; Final FINAL coverage 96.3%.

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_fl_sample.parquet`
- Jurisdiction: **Largo, FL** (2,000 rows) — first `(JURISDICTION, STATE)` pair without `agent/scripts/{state}/data_repair_{state}_{city}.py`
- Script: `agent/scripts/fl/data_repair_fl_largo.py` (`data_repair`)
- Artifact: `AGENT_DATA_PATH/repaired/permits_fl_largo_repaired.parquet`

## DATA schema

All 2,000 rows share top-level keys `fees`, `contacts`, `site_info`, `inspections`, `permit_info`, `search_data`. INFERRED_SCHEMA is content-based:

| Family | n | Notes |
| --- | ---: | --- |
| `accela_issued_finaled` | 1,623 | Issued + Finaled |
| `accela_issued` | 253 | Issued, no Finaled |
| `accela_applied` | 78 | Applied only |
| `accela_approved` | 41 | Approved only |
| `accela_finaled` | 5 | Finaled, no Issued |

Canonical mappings:

| Field | Source |
| --- | --- |
| STATUS_NORMALIZED | `permit_info.PermitStatus` (+ Final when `PermitFinaledDate` set; HISTORICAL → Final/Active/Inactive by stamps) |
| FILE_DATE | `PermitAppliedDate` (else `search_data` Application Date) |
| PERMIT_DATE | `PermitIssuedDate`, else `PermitApprovedDate` for Active/Final |
| FINAL_DATE | `PermitFinaledDate`, else latest passed final-ish / any passed inspection on/after Issued |

## Field assessments

### STATUS_NORMALIZED

**0 missing** before repair. Upstream mapped `STATUS_ORIGINAL` 1:1 into the four normalized buckets, but two portal labels were wrong for lifecycle semantics:

| Portal status | Upstream | Issue |
| --- | --- | --- |
| HISTORICAL (31) | In Review | Legacy archive, not an open review. 7 have Finaled → Final; 23 have Issued only → Active; 1 CONV shell with neither → Inactive |
| ISSUED + Finaled (1) | Active | PermitFinaledDate 2019-08-26 on Golf Lakes condo unit → Final |

Other mappings were already correct: FINAL/FINALED/CLOSED/COED → Final; ISSUED/APPROVED → Active; APPLY/READY/READY FOR PICKUP/UNDER REVIEW → In Review; ABANDONED/CANCEL/EXPIRED → Inactive.

**0 FILLED / 32 FIXED.** After: Final 1,691; Active 60; Inactive 231; In Review 18; **0 null**.

### FILE_DATE

Ideal: populated for all records.

- All 2,000 rows have FILE_DATE; all equal `PermitAppliedDate` (**0 FIXED / 0 FILLED**).
- Coverage after repair: 100% across Active / Final / In Review / Inactive.
- **0** FILE_DATE > PERMIT_DATE inversions.

### PERMIT_DATE

Ideal: populated for Active and Final.

- Upstream already copied `PermitIssuedDate` when present (**1,876** matches; **0 FIXED**).
- **14 FILLED** from `PermitApprovedDate` on Active/Final rows with blank Issued (RIGHT OF WAY, TREE REMOVAL, REMODEL, TOWN OF BELLEAIR, APPROVED shells).
- Remaining Active/Final gap: **4** — 2 ISSUED COUNTY FIRE shells and 2 FINAL shells with neither Issued nor Approved.

Coverage after repair: Active 58/60 (96.7%); Final 1,689/1,691 (99.9%); In Review 1/18 (UNDER REVIEW with Issued kept); Inactive 142/231 (issued-then-abandoned/cancelled/expired). **0** PERMIT_DATE ≠ Issued among Active/Final/Inactive with Issued present.

### FINAL_DATE

Ideal: populated for Final; absent otherwise.

- Upstream used `PermitFinaledDate` when present (**1,628** matches; **0** value FIXED / FILLED).
- The 8 non-Final rows that previously carried FINAL_DATE were the HISTORICAL/ISSUED cases remapped to Final, so dates were retained rather than cleared.
- Inspection salvage found **0** usable passed inspections on Final rows still missing FINAL_DATE (empty `inspections` lists).
- Remaining Final gap: **63** — CLOSED (53), FINAL (8), COED (2) with blank PermitFinaledDate.
- Non-Final rows carry **0** FINAL_DATE after repair.

Coverage after repair: Final 1,628/1,691 (96.3%); Active / In Review / Inactive 0%. **0** PERMIT_DATE > FINAL_DATE inversions.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 0 | 32 | 0 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 14 | 0 | 124 → 110 |
| FINAL_DATE | 0 | 0 | 372 → 372 |

Sanity checks vs Accela sources after repair: FILE_DATE == Applied (when both present); Active/Final/Inactive PERMIT_DATE == Issued (when Issued present); Final FINAL_DATE == Finaled (when both present); no date-order inversions.

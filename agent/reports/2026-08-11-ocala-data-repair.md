# Ocala (FL) data repair — STATUS_NORMALIZED and date fields

**Summary:** Among Florida sample jurisdictions missing a repair script, Ocala was first. Its DATA is a uniform civic/eTRAKiT payload (`permit_info` / `search_data` / `inspections`). STATUS_NORMALIZED had 76 nulls from unmapped portal labels plus systematic mislabels (SUSPENDED as In Review, CLOSED-NO FINAL INSP / bare CLOSED without a final stamp as Final, unissued APPROVED as Active). FILE_DATE already matched `PermitAppliedDate` whenever present; 568 legacy blanks are not fillable from DATA. PERMIT_DATE matched `PermitIssuedDate` and gained 17 fills from Issued/Approved. FINAL_DATE gained 10 fills (mostly Approved final inspections / CO) and 9 clears of non-Final stamps; after remapping admin-closed rows without a final stamp to Inactive, Final FINAL_DATE coverage is 99.7%.

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_fl_sample.parquet`
- Jurisdiction: **Ocala, FL** (2,000 rows) — first `(JURISDICTION, STATE)` pair without `agent/scripts/{state}/data_repair_{state}_{city}.py`
- Script: `agent/scripts/fl/data_repair_fl_ocala.py` (`data_repair`)
- Artifact: `AGENT_DATA_PATH/ocala_repaired_sample.parquet`

## DATA schema

All 2,000 records share top-level keys `contacts`, `fees`, `inspections`, `permit_info`, `search_data`, `site_info`. Content variants:

| INFERRED_SCHEMA | n | Notes |
| --- | ---: | --- |
| `civic_issued` | 968 | IssuedDate present, no FinaledDate |
| `civic_issued_finaled` | 862 | both Issued and Finaled |
| `civic_applied` | 155 | Applied only |
| `civic_status_only` | 13 | no canonical dates |
| `civic_finaled` | 2 | Finaled without Issued |

Canonical mappings:

| Field | Source |
| --- | --- |
| STATUS_NORMALIZED | `permit_info.PermitStatus` (APPROVED gated on IssuedDate; empty status + IssuedDate → Active; CLOSED gated on resolvable final stamp) |
| FILE_DATE | `PermitAppliedDate` |
| PERMIT_DATE | `PermitIssuedDate`, else `PermitApprovedDate` |
| FINAL_DATE | `PermitFinaledDate`, else `search_data.FINALED` / `CO ISSUED`, else latest Approved/Completed final-ish inspection |

## Field assessments

### STATUS_NORMALIZED

76 missing before repair; remaining values mostly matched `PermitStatus`. Issues:

| Change | n | Reason |
| --- | ---: | --- |
| null → In Review | 47 | Unmapped labels (ON APPLICATION, IN REVIEW - EPLANS/INSPECT, E-APPLICATION, AWAITING FINAL PAY, PLAN CORRECTIONS NEEDED, …) |
| null → Active | 21 | Empty `PermitStatus` shells with `PermitIssuedDate` |
| null → Inactive | 1 | `EXPIRED REISSUED` |
| Final → Inactive | 73 | `CLOSED-NO FINAL INSP` (26) + `CLOSED` without finaled/CO/final inspection (47) |
| In Review → Inactive | 16 | `SUSPENDED` |
| Active → In Review | 9 | `APPROVED` with null IssuedDate |

After repair: Final 868; Active 748; Inactive 232; In Review 145; null 7 (empty-status shells with no dates at all — not inventable).

### FILE_DATE

Ideal: populated for all records.

- When present (1,432), always equaled `PermitAppliedDate` at day resolution — **0 FIXED**.
- **0 FILLED**: every missing FILE_DATE also has blank `PermitAppliedDate` (568 rows, mostly pre-2004 APPROVED / empty-status legacy shells). No alternate application date in DATA.

Coverage after repair unchanged: 1,432 / 2,000 (71.6%). Active FILE_DATE is especially sparse (30.5%) because legacy APPROVED rows dominate that class.

### PERMIT_DATE

Ideal: populated for Active and Final.

- When present, always equaled `PermitIssuedDate` (0 incorrect overwrites vs issued).
- **17 FILLED** from IssuedDate or ApprovedDate fallback on Active/Final/Inactive rows that were missing PERMIT_DATE.
- Active: **748 / 748 (100%)** after repair (unissued APPROVED remapped to In Review).
- Final: **867 / 868 (99.9%)** — one FINALED row has neither Issued nor Approved date.

### FINAL_DATE

Ideal: populated for Final; absent otherwise.

- Before: 864 rows had FINAL_DATE, all matching `PermitFinaledDate`; 86 Final rows missing; 9 non-Final rows carried a finaled stamp.
- **10 FILLED** on Final (FINALED) rows via Approved final inspections and/or `CO ISSUED` when `PermitFinaledDate` blank.
- **9 FIXED** cleared FINAL_DATE on non-Final rows (Active/In Review/Inactive with a stale finaled stamp).
- Remapping admin-closed rows without a final stamp to Inactive removed 73 former Final rows that could never get a honest FINAL_DATE.
- Remaining: **3 Final (FINALED)** with no FinaledDate, no CO, and no Approved final inspection.

Coverage after repair: Final 865 / 868 (99.7%); Active / In Review / Inactive 0%.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 69 | 98 | 76 → 7 |
| FILE_DATE | 0 | 0 | 568 → 568 |
| PERMIT_DATE | 17 | 0 | 170 → 153 |
| FINAL_DATE | 10 | 9 | 1,136 → 1,135 |

Net FINAL_DATE missing count barely moves because clears on non-Final offset fills, while the larger win is correctness: Final rows now almost all have FINAL_DATE, and non-Final no longer carry completion dates.

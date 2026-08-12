# Venice (FL) data repair — STATUS_NORMALIZED and date fields

**Summary:** Among Florida sample jurisdictions missing a repair script, Venice was first. Its DATA is a single Accela/eTRAKiT portal family (`permit_info` + `inspections` / `fees` / `search_data`) with clear applied / issued / approved / finaled stamps. Upstream status was nearly complete (only **5** NOC HOLD nulls) and FILE_DATE already matched PermitAppliedDate on all 2,000 rows. After repair: status complete (FILLED 5 · FIXED 3); FILE_DATE unchanged; PERMIT_DATE FILLED **22** from PermitApprovedDate when Issued blank (Active 100%; Final 96.4%); FINAL_DATE FILLED **20** / FIXED **4** (Final coverage 91.9%). Remaining Active/Final PERMIT gaps (**60**) and Final FINAL gaps (**137**) are mostly CLOSED shells with no issued/approved/finaled and empty inspections.

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_fl_sample.parquet`
- Jurisdiction: **Venice, FL** (2,000 rows) — first `(JURISDICTION, STATE)` pair without `agent/scripts/{state}/data_repair_{state}_{city}.py`
- Script: `agent/scripts/fl/data_repair_fl_venice.py` (`data_repair`)
- Artifact: `AGENT_DATA_PATH/repaired/permits_fl_venice_repaired.parquet`

## DATA schema

| Family | n | Notes |
| --- | ---: | --- |
| `accela_issued_finaled` | 1,518 | Issued + Finaled present |
| `accela_issued` | 298 | Issued, no Finaled |
| `accela_applied` | 144 | Applied only (many legacy CLOSED) |
| `accela_approved` | 27 | Approved only (mostly APPROVED Active) |
| `accela_finaled` | 13 | Finaled, no Issued |

INFERRED_SCHEMA is one of the `accela_*` labels above. RECORDID prefixes vary (`CONV`, `ECON`, staff initials) but share the same `permit_info` shape.

Canonical mappings:

| Field | Source |
| --- | --- |
| STATUS_NORMALIZED | `permit_info.PermitStatus` (finaled stamp forces Final) |
| FILE_DATE | `PermitAppliedDate` |
| PERMIT_DATE | `PermitIssuedDate`, else `PermitApprovedDate` for Active/Final |
| FINAL_DATE | `PermitFinaledDate`, else passed final-ish / any passed inspection; if finaled precedes issuance, prefer later passed inspection |

## Field assessments

### STATUS_NORMALIZED

Upstream distribution: Final 1,684 · Active 197 · Inactive 69 · In Review 45 · **null 5**.

The five nulls are all `PermitStatus = NOC HOLD` (Notice of Commencement hold) with Issued dates → **FILLED Active**.

Incorrect values (FIXED):

| n | Before → After | Reason |
| ---: | --- | --- |
| 2 | Active → Final | `STATUS_ORIGINAL` lagged (`issued`) while `PermitStatus` was CLOSED / FINALED (one also had PermitFinaledDate) |
| 1 | In Review → Final | `ON HOLD` carrying `PermitFinaledDate` 2003-12-04 |

Mapping used:

| STATUS_NORMALIZED | `PermitStatus` |
| --- | --- |
| Final | CLOSED, FINALED, C.O. ISSUED, CO ISSUED (+ any row with PermitFinaledDate) |
| Active | ISSUED, APPROVED, NOC HOLD |
| In Review | UNDER REVIEW, PROJECTDOX, PLAN CHECK, ETRAKIT, ON HOLD |
| Inactive | WITHDRAWN, WITHDRAWN APPLICATION, EXPIRED, REJECTED |

After: Final 1,687 · Active 200 · Inactive 69 · In Review 44 · null **0**.

### FILE_DATE

Ideal: populated for all records.

- All 2,000 rows already equal `PermitAppliedDate` at calendar-day resolution (**0 FILLED / 0 FIXED**).
- Includes 11 CONV shells with Jan-1 applied years in 1968–1979 (kept; Venice `_MIN_YEAR` is 1960).
- Coverage after repair: **100%** for every STATUS_NORMALIZED.

### PERMIT_DATE

Ideal: populated for Active and Final.

- Upstream PERMIT_DATE already matched `PermitIssuedDate` whenever Issued was present (1,816 rows); 184 missing mirrored blank Issued.
- **22 FILLED** from `PermitApprovedDate` when Issued blank: 19 APPROVED Active, 1 ISSUED Active, 2 FINALED Final.
- Active/Final still missing PERMIT_DATE: **60 / 1,887** — all CLOSED/FINALED with neither Issued nor Approved (mostly `accela_applied` / `accela_finaled` legacy shells). Not inventable from DATA without conflating fee paid dates with issuance.
- In Review correctly has **0** PERMIT_DATE after repair.

Coverage after repair: Active 200/200 (100%); Final 1,627/1,687 (96.4%); In Review 0%; Inactive 11/69 (15.9%, issued-then-withdrawn).

### FINAL_DATE

Ideal: populated for Final; absent otherwise.

- Upstream FINAL_DATE matched `PermitFinaledDate` on nearly all rows that had it; 155 Final rows lacked both.
- **20 FILLED**: 1 from PermitFinaledDate on a FINALED row previously labeled Active; remainder from passed final / any passed inspections on CLOSED / FINALED / CO ISSUED.
- **4 FIXED**: agency `PermitFinaledDate` preceded `PermitIssuedDate`; replaced with a later passed final inspection when available.
- **1** remaining PERMIT > FINAL inversion: Issued 2000-08-30 vs Finaled/inspection 2000-08-29 — no later inspection in DATA.
- Remaining Final gap: **137** — CLOSED/FINALED with blank Finaled and empty or non-final inspections (expired / closed-without-final notes common).
- Non-Final FINAL_DATE cleared via status remap (the ON HOLD → Final case keeps its finaled stamp).

Coverage after repair: Final 1,550/1,687 (91.9%); Active / In Review / Inactive 0%.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 5 | 3 | 5 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 22 | 0 | 184 → 162 |
| FINAL_DATE | 20 | 4 | 470 → 450 |

Date-order checks after repair: FILE_DATE > PERMIT_DATE inversions **0**; PERMIT_DATE > FINAL_DATE inversions **1** (unrepairable agency quirk).

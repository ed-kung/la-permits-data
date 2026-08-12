# Pompano Beach (FL) data repair — STATUS_NORMALIZED and date fields

**Summary:** Among Florida sample jurisdictions missing a repair script, Pompano Beach was first. Its DATA is the Margate / North Port city-portal family (`detail` / `fees`, optional `permit_status_detail` + inspections). Upstream left STATUS_NORMALIZED null on all 169 fees_detail-only rows and mislabeled 79 VOID / WITHDRAWN / SUPERSEDED / PERMIT EXPIRED rows as Final or Active because `Status for Permit Number` still said CLOSED or PERMIT PRINTED. FILE_DATE already matched Application Date for every row. PERMIT_DATE was 100% missing despite Issue Date on 1,742 permit_status rows — all filled. FINAL_DATE gained 21 fills and 5 inspection-based corrections on Final rows; 7 spurious finals were cleared when status moved to Inactive. After repair: no null statuses; Final FINAL_DATE coverage 98.9%; Active/Final PERMIT_DATE 87.8% / 99.5%.

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_fl_sample.parquet`
- Jurisdiction: **Pompano Beach, FL** (2,000 rows) — first `(JURISDICTION, STATE)` pair without `agent/scripts/{state}/data_repair_{state}_{city}.py`
- Script: `agent/scripts/fl/data_repair_fl_pompano_beach.py` (`data_repair`)
- Artifact: `AGENT_DATA_PATH/pompano_beach_repaired_sample.parquet`

## DATA schema

| INFERRED_SCHEMA (top) | n |
| --- | ---: |
| `permit_status_closed` | 1,535 |
| `permit_status_permit_printed` | 180 |
| `fees_detail_in_plan_check` | 89 |
| `permit_status_c_o_issued` | 43 |
| `fees_detail_void` | 40 |
| `permit_status_plan_check` | 36 |
| `permit_status_final_inspection_complete` | 18 |
| `fees_detail_withdrawn` | 16 |
| *(other SP / app variants)* | 43 |

Canonical mappings:

| Field | Source |
| --- | --- |
| STATUS_NORMALIZED | `Status for Permit Number`, overridden to Inactive when Application Status is VOID / WITHDRAWN / SUPERSEDED / PERMIT EXPIRED (unless SP is a true completion code and APP is only PERMIT EXPIRED); fees_detail uses Application Status alone |
| FILE_DATE | Application Date |
| PERMIT_DATE | Issue Date (`permit_status_detail`) |
| FINAL_DATE | Latest successful FINAL/FNL/CLOSEOUT inspection date; else latest non-NOC successful inspection (`APPROVED` / `APPROVED WITH EXCEPTION` / `SATISFACTORY`) |

## Field assessments

### STATUS_NORMALIZED

**169 missing** — all `fees_detail_*` rows (no `permit_status_detail`). Upstream STATUS_ORIGINAL is null whenever the permit-status block is absent. Filled from Application Status: IN PLAN CHECK / CLICK2GOV / APPROVED / REPAIRS REQUIRED → In Review; VOID / WITHDRAWN / SUPERSEDED / FAILED CONVERSION → Inactive; RECERTIFIED → Active; CLOSED / VIOLATION CASE COMPLIED → Final.

**79 incorrect** — Application Status terminal (VOID / WITHDRAWN / SUPERSEDED / PERMIT EXPIRED) while Status for Permit Number remained CLOSED or PERMIT PRINTED, so STATUS_ORIGINAL/`STATUS_NORMALIZED` stayed Final or Active. FIXED to Inactive (73 Final→Inactive, 6 Active→Inactive).

After repair: Final 1,527; Active 181; Inactive 152; In Review 140. **0 null / 0 unmapped.**

### FILE_DATE

Ideal: populated for all records.

- Before: **0 missing**. All 2,000 equal Application Date at day resolution.
- **0 FILLED / 0 FIXED.** Coverage remains 100% for every status.

### PERMIT_DATE

Ideal: populated for Active and Final.

- Before: **2,000 missing (100%)** — field never ingested despite `Issue Date` on 1,742 / 1,831 permit_status rows.
- **1,742 FILLED** from Issue Date; **0 FIXED**.
- Remaining **258 missing**: 169 fees_detail rows (no Issue Date) plus blank Issue Date on some PLAN CHECK / TO BE ISSUED / PERMIT PRINTED / PERMIT REVOKED rows.

Coverage after repair: Active 159/181 (87.8%); Final 1,520/1,527 (99.5%). Residual Active gaps are blank Issue Date or fees_detail RECERTIFIED shells.

Note: 50 rows have Issue Date a few days after the inspection-derived FINAL_DATE (source quirk; Reissue Date usually blank). PERMIT_DATE still uses Issue Date as the issuance stamp.

### FINAL_DATE

Ideal: populated for Final; absent otherwise.

- Before: 1,496 / 1,596 Final rows had FINAL_DATE (mostly matching APPROVED final inspections); 100 Final missing; non-Final had none.
- **21 FILLED** from successful final / non-NOC inspections (including APPROVED WITH EXCEPTION).
- **12 FIXED**: 5 drifted dates overwritten with inspection candidates; 7 cleared when status remapped Final→Inactive.
- After repair: Final 1,510/1,527 (98.9%); other statuses 0%.
- **17 Final still missing**: CLOSED / CLOSED BY REPORT / VIOLATION CASE COMPLIED with empty or only DISAPPROVED inspection history. `Last Maintained` is a maintenance stamp (often years later) and is not used.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 169 | 79 | 169 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 1,742 | 0 | 2,000 → 258 |
| FINAL_DATE | 21 | 12 | 504 → 490 |

Status transitions (changed only): NaN→In Review 97; Final→Inactive 73; NaN→Inactive 61; NaN→Active 7; Active→Inactive 6; NaN→Final 4.

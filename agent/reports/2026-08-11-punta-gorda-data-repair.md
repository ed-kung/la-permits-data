# Punta Gorda (FL) data repair — STATUS_NORMALIZED and date fields

**Summary:** Among Florida sample jurisdictions missing a repair script, Punta Gorda was first. Its DATA is the same city-portal family as Pompano Beach (`detail` / `permit_status_detail` / `insp_status_detail`, plus sparse `fees_detail` and `application` shells). STATUS_NORMALIZED was missing on 41 rows and was filled on 40 (1 empty `{}` left null). FILE_DATE already matched Application Date wherever present (31 application/empty shells remain empty). The main defect was PERMIT_DATE: upstream used portal **Permit Date**, a close/final-adjacent stamp, instead of **Issue Date** — 1,703 Active/Final/Inactive rows were FIXED to Issue Date, and all 60 In Review Permit-Date stamps were cleared. FINAL_DATE was filled on 35 Final rows and corrected on 2; Final coverage is 97.9% after repair.

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_fl_sample.parquet`
- Jurisdiction: **Punta Gorda, FL** (2,001 rows) — first `(JURISDICTION, STATE)` pair without `agent/scripts/{state}/data_repair_{state}_{city}.py`
- Script: `agent/scripts/fl/data_repair_fl_punta_gorda.py` (`data_repair`)
- Artifact: `AGENT_DATA_PATH/punta_gorda_repaired_sample.parquet`

## DATA schema

| INFERRED_SCHEMA prefix | n | Notes |
| --- | ---: | --- |
| `permit_status_*` | 1,960 | Full portal permit block (`Status for Permit Number`, Issue/Permit/Application dates, inspections) |
| `application_*` | 30 | Shell with `application_status` only — no dates |
| `fees_detail_*` | 10 | `detail` + `fees` only — Application Status/Date, no Issue/inspections |
| `empty` | 1 | `{}` |

Canonical mappings:

| Field | Source |
| --- | --- |
| STATUS_NORMALIZED | `Status for Permit Number` (else Application Status / `application_status`) |
| FILE_DATE | Application Date |
| PERMIT_DATE | Issue Date (never portal Permit Date) |
| FINAL_DATE | latest successful FINAL/CO inspection; else latest successful non-NOC inspection; else Permit Date when it differs from Issue Date on Final/CLOSED |

## Field assessments

### STATUS_NORMALIZED

Upstream mapping from `STATUS_ORIGINAL` was already consistent for non-null rows:

| Status for Permit Number / STATUS_ORIGINAL | STATUS_NORMALIZED |
| --- | --- |
| CLOSED / FINAL INSPECTION COMPLETE / C.O. ISSUED | Final |
| PERMIT PRINTED | Active |
| PLAN CHECK / TO BE ISSUED | In Review |
| PERMIT REVOKED | Inactive |

**40 FILLED** from Application Status on sparse shells (7 CLOSED + 3 IN PLAN CHECK on `fees_detail`; 25 CLOSED + 3 APPROVED + 1 IN PLAN CHECK + 1 CERT OF OCCUPANCY ISSUED on `application`). **0 FIXED.** Remaining: **1** empty `{}` with no status text.

After repair: Final 1,652; Active 265; In Review 67; Inactive 16; null 1.

Note: 51 Active (`PERMIT PRINTED`) rows carry an approved final-named inspection, and 113 have Application Status CLOSED while permit status remains PERMIT PRINTED. Status text is kept — the agency has not moved Status for Permit Number to a completion code.

### FILE_DATE

Ideal: populated for all records.

- Before: 31 missing. Among the 1,970 rows with Application Date, FILE_DATE already matched exactly (0 mismatches).
- **0 FILLED / 0 FIXED.**
- Remaining: **31** (`application` × 30 + `empty` × 1) with no Application Date in DATA.

Coverage after repair: Active 100%; Final 98.4%; In Review 94.0%; Inactive 100%.

### PERMIT_DATE

Ideal: populated for Active and Final.

- Upstream almost always copied portal **Permit Date**, not **Issue Date**. On Final rows those two dates differ in 1,612/1,619 cases; Permit Date is usually on or near FINAL_DATE (close stamp), so using it as issuance was incorrect.
- **1,703 FIXED** to Issue Date (Active/Final/Inactive).
- **60 FIXED** cleared on In Review (Permit Date equals Application Date; Issue Date blank).
- **10 FIXED** cleared on Final/Inactive with blank Issue Date (unsupported Permit Date stamps).
- Remaining gaps: 5 Final + 5 Inactive with blank Issue Date; plus new Finals from `fees_detail`/`application` shells with no Issue Date.

Coverage after repair: Active 100%; Final 97.7%; In Review 0%; Inactive 68.8%.

### FINAL_DATE

Ideal: populated for Final; absent otherwise.

- Before: missing on 36/1,619 Final rows; never present on non-Final.
- **35 FILLED** on Final: successful FINAL/CO or other approved inspections, else Permit Date when it differs from Issue Date (admin close).
- **2 FIXED** where an existing FINAL_DATE did not match the latest successful final/approved inspection (including WAIVED finals).
- Remaining Final gaps: **34** — 33 newly labeled Final shells (`application`/`fees_detail` with no inspections) + 1 CLOSED permit with Issue Date == Permit Date and empty inspection history.
- Non-Final rows stay without FINAL_DATE.

Coverage after repair: Final 97.9%; Active / In Review / Inactive 0%.

One residual `PERMIT_DATE > FINAL_DATE` inversion remains: Issue Date `10/21/05` after an approved BLD FINAL `10/12/05` (source-data quirk; Issue Date kept as PERMIT_DATE).

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 40 | 0 | 41 → 1 |
| FILE_DATE | 0 | 0 | 31 → 31 |
| PERMIT_DATE | 0 | 1,703 | 41 → 111 |
| FINAL_DATE | 35 | 2 | 418 → 383 |

PERMIT_DATE missing count rises because incorrect In Review / no-Issue stamps were cleared; Active/Final issuance coverage improves in quality (100% / 97.7% on Issue Date) even though some unsupported rows are now correctly null.

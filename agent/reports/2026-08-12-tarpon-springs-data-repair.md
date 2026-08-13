# Tarpon Springs (FL) data repair

Tarpon Springs was the first `(JURISDICTION, STATE)` pair in `permits_fl_sample.parquet` without an existing repair script. Its DATA JSON follows the same city-portal family as Winter Garden/Oviedo/Lake Mary (`permit_status` + `fees_detail`). FILE_DATE was already correct; the main defects were null STATUS on fees-only rows, seven Active rows that should be Final (`FINAL INSPECTION COMPLETE`), PERMIT_DATE taken from the portal "Permit Date" stamp instead of "Issue Date", and FINAL_DATE gaps that can be filled from successful inspections.

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_fl_sample.parquet`
- Jurisdiction: Tarpon Springs, FL (2,000 sample rows)
- Script: `agent/scripts/fl/data_repair_fl_tarpon_springs.py`
- Artifact: `AGENT_DATA_PATH/tarpon_springs_permits_repaired.parquet`

## DATA schemas

| Schema | n | Contents |
| --- | ---: | --- |
| `permit_status` | 1,979 | `detail` / fees plus `permit_status_detail` + `insp_status_detail` |
| `fees_detail` | 21 | `detail` + fees only (Application Date / Application Status) |

## Field assessment

### STATUS_NORMALIZED

- Before: Final 1,631; Active 261; In Review 61; Inactive 26; **null 21**.
- All 21 nulls were `fees_detail` rows (no `Status for Permit Number`).
- Canonical source: prefer `Status for Permit Number`, else `Application Status`.
- Upstream mapping was already correct for nearly all `permit_status` rows (CLOSED / C.O. ISSUED / PERMIT PRINTED / PLAN CHECK / TO BE ISSUED / PERMIT REVOKED / ON HOLD).
- Exception: **7 Active** rows have `Status for Permit Number = FINAL INSPECTION COMPLETE` (and approved final inspections) but stale `STATUS_ORIGINAL = permit printed` → FIXED to Final.

### FILE_DATE

- Populated for all 2,000 rows; 100% match to `Application Date`.
- No fill or fix needed.

### PERMIT_DATE

- Upstream used portal **Permit Date** (1,979 rows with the field), not **Issue Date**.
- Permit Date is typically a later admin/closeout stamp; 887 rows share the batch stamp `07/21/15`. Issue Date is the true issuance date.
- All 61 In Review rows had a spurious PERMIT_DATE from Permit Date (56 with blank Issue Date; 5 ON HOLD / PLAN CHECK / TO BE ISSUED with an Issue Date still treated as In Review).
- Active/Final with a real Issue Date can be corrected; fees_detail and blank-Issue CLOSED rows cannot.

### FINAL_DATE

- For Final rows, upstream mostly matched the latest APPROVED inspection result date.
- Repair uses the Winter Garden family rule: latest successful non-NOC inspection (APPROVED / APPROVED WITH EXCEPTION / PARTIALLY APPROVED / WAIVED), preferring result date over schedule date.
- 159 Final rows still lack a usable success inspection after repair (139 empty `insp_status_detail`, 18 non-success only, 2 fees_detail) → not fillable from DATA.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 21 | 7 | 21 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 0 | 1,757 | 21 → 128 |
| FINAL_DATE | 68 | 11 | 587 → 519 |

STATUS after repair: Final 1,640; Active 254; In Review 77; Inactive 29; null 0.

Null STATUS fills from Application Status: In Review 16 (PENDING VERIFICATION / APPROVED / IN PLAN CHECK / IN APPROVAL), Inactive 3 (VOID), Final 2 (CLOSED). Seven Active → Final fixes from `FINAL INSPECTION COMPLETE`.

PERMIT_DATE FIXED = 1,650 replacements to Issue Date + 107 clears of unsupported Permit Date stamps (In Review 61; Final blank-Issue 30; fees_detail Final 2; Inactive without Issue Date 16). Missing rose from 21 → 128 because incorrect stamps were removed when Issue Date was absent.

After repair:

- FILE_DATE present for 100% of rows; equals Application Date on 2,000 / 2,000.
- PERMIT_DATE: Active 100%; Final 98.0%; In Review 0%; Inactive 34.5% (10 of 26 PERMIT REVOKED that had Issue Date).
- FINAL_DATE: Final 90.3%; cleared on non-Final.
- PERMIT_DATE equals Issue Date whenever both are present (0 mismatches / 1,877).
- Ordering: FILE_DATE > PERMIT_DATE on 0 rows; PERMIT_DATE > FINAL_DATE on 7 rows (source inspection dated before issue).

## Not repairable from DATA

- 32 Final rows with no Issue Date in DATA (30 `permit_status` CLOSED with blank Issue Date + 2 fees_detail) → PERMIT_DATE stays missing.
- 159 Final rows without a successful non-NOC inspection → FINAL_DATE stays missing.
- In Review / VOID fees_detail rows have no issuance or inspection history → PERMIT_DATE / FINAL_DATE stay missing.

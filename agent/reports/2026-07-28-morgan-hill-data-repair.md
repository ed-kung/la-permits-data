# Morgan Hill (CA) data repair

Assessed STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for the 2,000-row Morgan Hill sample against the raw DATA JSON, then implemented `agent/scripts/ca/data_repair_ca_morgan_hill.py`. The portal schema is uniform (`permit_info` + `search_data` + fees/contacts/inspections/site_info). Repair fills or fixes status for blank-status shells and a handful of mis-maps, fills PERMIT_DATE from Approved when Issued is blank, and fills FINAL_DATE for FINALED rows previously left Active. FILE_DATE was already correct wherever `PermitAppliedDate` exists; remaining gaps are conversion shells with no usable application date.

## Jurisdiction selection

First `(JURISDICTION, STATE)` in `permits_ca_sample.parquet` order without an existing `agent/scripts/{state}/data_repair_{state}_{city}.py` was **Morgan Hill, CA**.

## DATA schema

All 2,000 rows share one top-level key set. `INFERRED_SCHEMA` further tags date/status content:

| Schema | n |
| --- | ---: |
| permit_info_issued_finaled | 1,101 |
| permit_info_issued | 405 |
| permit_info_empty_dates | 270 |
| permit_info_applied_only | 93 |
| legacy_no_status | 75 |
| permit_info_finaled_only | 32 |
| permit_info_approved_only | 24 |

Canonical mappings:

- `permit_info.PermitStatus` → STATUS_NORMALIZED
- `PermitAppliedDate` → FILE_DATE
- `PermitIssuedDate` (fallback `PermitApprovedDate`) → PERMIT_DATE
- `PermitFinaledDate` (fallback approved final inspection) → FINAL_DATE

`PermitExpirationDate` is a validity window, not a completion date. Leading dates in `PermitNotes` on blank-status archive rows are a **5/10/2016 migration stamp**, not application dates.

## Field assessment

### STATUS_NORMALIZED

Before repair: Final 1,151 / Active 224 / Inactive 248 / In Review 36 / missing 341.

Raw `PermitStatus` values map cleanly in most cases (`FINALED`→Final, `ISSUED`/`APPROVED`→Active, `RECEIVED`/`UNDER REVIEW`→In Review, `EXPIRED`/`CANCELED`/`VOID`/`DENIED`→Inactive).

Incorrect / fillable issues:

- **6** `FINALED` rows stored as Active (also missing FINAL_DATE despite `PermitFinaledDate`).
- **1** `ISSUED` and **1** `APPROVED` stored as In Review.
- **341** blank `PermitStatus` with missing STATUS_NORMALIZED: **70** have Issued → Active; **5** have Applied only → In Review; **266** have no dates (mostly `BLD ARCHIVE` / `OVERSIZE OVERWEIGHT` conversion shells) and cannot be inferred.

### FILE_DATE

1,726 / 2,000 populated; every populated FILE_DATE matches `PermitAppliedDate` at day resolution (0 mismatches). All 274 missing FILE_DATE rows also lack `PermitAppliedDate` (3 have Issued only; 1 has Finaled only). Notes-based fill was rejected because the stamp is a 2016 conversion date. **No FILE_DATE repairs.**

### PERMIT_DATE

Where both exist, PERMIT_DATE matches `PermitIssuedDate` exactly (0 mismatches). Gaps:

- Active `APPROVED` rows with Approved but no Issued → fillable from Approved.
- Some Final rows with Approved but no Issued → same.
- Final rows with neither Issued nor Approved (only Applied/Finaled) → not fillable without inventing an issuance date.

### FINAL_DATE

Where both exist, FINAL_DATE matches `PermitFinaledDate` exactly. No spurious FINAL_DATE on non-Final statuses. The 6 mis-mapped FINALED→Active rows had FinaledDate available. **24** Final rows still lack FinaledDate and have no usable final inspection — left missing.

## Repair performance

Script: `agent/scripts/ca/data_repair_ca_morgan_hill.py`  
Artifact: `$AGENT_DATA_PATH/repaired/permits_ca_morgan_hill_repaired.parquet`

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 75 | 8 | 341 → 266 |
| FILE_DATE | 0 | 0 | 274 → 274 |
| PERMIT_DATE | 23 | 0 | 426 → 403 |
| FINAL_DATE | 6 | 0 | 873 → 867 |

Status transitions:

- nan → Active: 70 (FILLED)
- nan → In Review: 5 (FILLED)
- Active → Final: 6 (FIXED)
- In Review → Active: 2 (FIXED)

After repair, date coverage by status:

| Status | n | PERMIT_DATE | FINAL_DATE |
| --- | ---: | --- | --- |
| Active | 290 | 288 / 290 (99.3%) | 0 / 290 |
| Final | 1,157 | 1,121 / 1,157 (96.9%) | 1,133 / 1,157 (97.9%) |
| In Review | 39 | 0 / 39 | 0 / 39 |
| Inactive | 248 | 188 / 248 (75.8%) | 0 / 248 |

FILE_DATE coverage remains 1,726 / 2,000 (86.3%). Chronology: 4 rows have FILE_DATE one day after PERMIT_DATE in source DATA (left as-is); 0 PERMIT > FINAL inversions.

## Remaining gaps (not repairable from DATA)

- 266 blank-status conversion shells with no status/date fields.
- 274 rows without `PermitAppliedDate` (FILE_DATE).
- 36 Final rows without Issued/Approved (PERMIT_DATE).
- 24 Final rows without FinaledDate or a passed final inspection (FINAL_DATE).
- 2 Active rows still missing PERMIT_DATE.

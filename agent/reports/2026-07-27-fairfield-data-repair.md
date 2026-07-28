# Fairfield (CA) data repair

**Summary:** Fairfield was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. All 2,000 sample rows use one portal schema (`permit_info` + `search_data`). The dominant issue is **864 ISSUED rows already carrying `PermitFinaledDate` but labeled Active** — these were fixed to Final. Status blanks on COMPLAINT shells were filled as In Review. `PERMIT_DATE` gaps on Active/Final were mostly fillable from `PermitApprovedDate`; all 5 Final rows missing `FINAL_DATE` were fillable from inspections. `FILE_DATE` cannot be improved: every missing value already has an empty `PermitAppliedDate`.

## Jurisdiction selection

Went down first-seen `(JURISDICTION, STATE)` pairs in `MY_DATA_PATH/processed_data/permits_ca_sample.parquet`. Existing scripts live under `agent/scripts/{state}/data_repair_{state}_{city}.py`. First missing pair: **Fairfield, CA** (`agent/scripts/ca/data_repair_ca_fairfield.py`).

## DATA schema

All 2,000 rows share top-level keys:
`contacts`, `fees`, `inspections`, `permit_info`, `search_data`, `site_info`.

Canonical sources in `permit_info`:

| Field | Source |
| --- | --- |
| STATUS_NORMALIZED | `PermitStatus` (+ date inference when blank / stale) |
| FILE_DATE | `PermitAppliedDate` |
| PERMIT_DATE | `PermitIssuedDate`, else `PermitApprovedDate` |
| FINAL_DATE | `PermitFinaledDate`, else finaling inspection `Completed` (last resort for FINALED: latest APPROVED inspection) |

`INFERRED_SCHEMA` is `permit_info_search_data` for every row. `search_data.ISSUED` mirrors `PermitIssuedDate` and is not used as an application-date substitute.

## Field assessment

### STATUS_NORMALIZED

Pre-repair: Active 1,285 / Final 588 / Inactive 86 / In Review 28 / missing 13.

`STATUS_ORIGINAL` matches `PermitStatus` (lowercased) on every row. Direct mapping was generally correct (`FINALED`/`COFO ISSUED`→Final, `ISSUED`/`APPROVED`→Active, review/pending variants→In Review, `EXPIRED`/`VOID`/`CANCELLED`/`WITHDRAWN`/`N/A`→Inactive).

Issues found:

1. **864 ISSUED rows with `PermitFinaledDate`** still labeled Active — status should be **Final**. These already had `FINAL_DATE` populated from the portal finaled stamp (0 mismatches vs `PermitFinaledDate`).
2. **13 blank `PermitStatus`**: 12 COMPLAINT investigations with Applied date only → fillable as **In Review**; 1 empty WEB shell (`WEB25-00168`) with no dates → not fillable.

No other remapping errors (e.g. `READY TO ISSUE` as In Review, `APPROVED` as Active) were incorrect relative to the portal fields.

### FILE_DATE

899 missing; every gap also has empty `PermitAppliedDate`. When present, `FILE_DATE` always equals `PermitAppliedDate` (0 mismatches). No alternate application/submittal date exists in DATA (`search_data` only exposes ISSUED). Coverage stays **55.0%** (1,101 / 2,000).

### PERMIT_DATE

When present, always equals `PermitIssuedDate` (0 mismatches). Ideal: populate for Active and Final.

Pre-repair gaps: 8 Active, 5 Final missing Issued. Of those, **5 Active + 4 Final** had `PermitApprovedDate` — fillable. Remaining unfillable: 3 Active APPROVED (no Issued/Approved) and 1 Final FIRE inspection shell with neither date.

### FINAL_DATE

When present, always equals `PermitFinaledDate`. Ideal: populate for Final only.

5 Final (`FINALED`) rows were missing `PermitFinaledDate` but had usable inspection Completeds (BUILDING FINAL\*\*, PUBLIC WORKS FINAL\*\*, etc.; one hood/fire shell used a last-resort latest APPROVED inspection because `FIRE FINAL**` itself had an empty Completed). After upgrading the 864 stale Active rows to Final, non-Final rows correctly carry **0** `FINAL_DATE` values.

## Repair performance

Script: `agent/scripts/ca/data_repair_ca_fairfield.py` (`data_repair`).

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | ---: | ---: | ---: | ---: |
| STATUS_NORMALIZED | 12 | 864 | 13 | 1 |
| FILE_DATE | 0 | 0 | 899 | 899 |
| PERMIT_DATE | 9 | 0 | 87 | 78 |
| FINAL_DATE | 5 | 0 | 553 | 548 |

Status after repair: Final 1,452 / Active 421 / Inactive 86 / In Review 40 / missing 1.

Coverage after repair:

- FILE_DATE: 1,101 / 2,000 (55.0%)
- PERMIT_DATE: Active 418/421 (99.3%); Final 1,451/1,452 (99.9%)
- FINAL_DATE: Final 1,452/1,452 (100.0%); 0 on non-Final

## Remaining gaps (not repairable from DATA)

- **FILE_DATE (899):** empty `PermitAppliedDate`; mostly older ISSUED/EXPIRED shells that only expose an Issued stamp.
- **PERMIT_DATE:** 3 Active APPROVED and 1 Final FINALED with neither Issued nor Approved.
- **STATUS:** 1 blank WEB shell with no dates (`WEB25-00168`).
- **FINAL_DATE:** none remaining on Final rows.

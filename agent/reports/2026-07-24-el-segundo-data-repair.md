# El Segundo CA data repair

**Summary:** El Segundo’s 2,000 sample records share one DATA schema (`permit_info_search_data`). Upstream dates already match `permit_info` when present. The main fixes are status: 4 null `APPLICATION GENERATED` rows → In Review, and 15 rows with `PermitFinaledDate` but Active/Inactive labels → Final. `PERMIT_DATE` gains 22 fills from `PermitApprovedDate` when Issued is empty on Active/Final. `FILE_DATE` and `FINAL_DATE` need no value changes on this sample (10 / 25 gaps remain unfillable from DATA). Script: `agent/scripts/data_repair_ca_el_segundo.py`.

## Data & schema

| Item | Value |
| --- | --- |
| Source | `MY_DATA_PATH/processed_data/permits_la_sample.parquet` |
| Filter | `JURISDICTION == "El Segundo"`, `STATE == "CA"` |
| N | 2,000 |
| First jurisdiction without an existing `data_repair_{state}_{city}.py` | El Segundo, CA (after Alhambra … Downey) |

| INFERRED_SCHEMA | n |
| --- | --- |
| `permit_info_search_data` | 2,000 |

All rows share top-level keys `contacts`, `fees`, `inspections`, `permit_info`, `search_data`, `site_info`. `inspections` is null for every sample row. Canonical fields:

| Target field | DATA source |
| --- | --- |
| `STATUS_NORMALIZED` | `permit_info.PermitStatus` (override to Final if `PermitFinaledDate` present) |
| `FILE_DATE` | `permit_info.PermitAppliedDate` (= `search_data.Application`) |
| `PERMIT_DATE` | `permit_info.PermitIssuedDate` (= `search_data.Issued`); fallback `PermitApprovedDate` |
| `FINAL_DATE` | `permit_info.PermitFinaledDate` |

`PermitExpirationDate` is a validity window, not a completion date.

## Field assessment

### STATUS_NORMALIZED — 4 missing + 15 stale labels

`STATUS_ORIGINAL` is the lowercased `PermitStatus` 1:1. Upstream mapping was correct except for unmapped / stale cases:

| PermitStatus | Upstream STATUS_NORMALIZED | n |
| --- | --- | --- |
| FINALED | Final | 1,137 |
| ISSUED | Active | 321 |
| APPROVED | Active | 17 |
| SUBMITTED | In Review | 62 |
| APPLIED | In Review | 4 |
| PC FEES DUE | In Review | 4 |
| APPLICATION GENERATED | **null** | 4 |
| EXPIRED / PERMIT EXP | Inactive | 365 |
| WITHDRAWN / CANCELLED | Inactive | 86 |

Repairs:

| Before | After | Reason | n | Flag |
| --- | --- | --- | --- | --- |
| null | In Review | `APPLICATION GENERATED` | 4 | FILLED |
| Active | Final | `PermitFinaledDate` present (ISSUED×4, APPROVED×1) | 5 | FIXED |
| Inactive | Final | `PermitFinaledDate` present (EXPIRED×9, WITHDRAWN×1) | 10 | FIXED |

After repair: Final 1,152, Inactive 441, Active 333, In Review 74 (0 missing).

### FILE_DATE — correct where DATA has an application date (0 FILLED / 0 FIXED)

- Ideal: application / submittal date for all records.
- 1,990 / 2,000 match `PermitAppliedDate` / `Application` exactly.
- **Not repairable:** 10 rows (6 SUBMITTED, 4 WITHDRAWN) have empty Applied and Application (and empty Issued/Approved/Finaled). No other date fields in fees/contacts/site_info.

### PERMIT_DATE — correct when Issued present; 22 fillable from Approved

- Ideal: populated for Active and Final.
- When both present, `PERMIT_DATE` always equals `PermitIssuedDate` / `Issued` (1,747 / 1,747).
- 253 rows have both null. Of those, Active/Final with `PermitApprovedDate` can be filled (approval as issuance proxy).

| Action | n |
| --- | --- |
| FILLED from `PermitApprovedDate` (Active/Final, Issued empty) | 22 |
| FIXED | 0 |

After repair coverage: Active 330/333 (99.1%), Final 1,136/1,152 (98.6%).

**Not repairable:** 3 Active and 16 Final rows lack both Issued and Approved (Applied only, or empty). `FILE_DATE` is not used as a proxy. Four In Review (`APPLIED`) rows already carry `PERMIT_DATE` matching Issued (including three `2022-01-01` values that look like sentinels); left unchanged.

### FINAL_DATE — correct when Finaled present (0 FILLED / 0 FIXED)

- Ideal: populated for Final.
- All 1,127 non-null `FINAL_DATE` values match `PermitFinaledDate`. None equal Expiration.
- Status remaps move the 15 finaled-but-mislabeled rows into Final; they already had matching `FINAL_DATE`, so no FINAL flags fire.
- After repair: Final 1,127/1,152 (97.8%) have `FINAL_DATE`; Active / In Review / Inactive have 0.
- **Not repairable:** 25 `FINALED` rows have empty `PermitFinaledDate`. Expiration is not used as a proxy.

## Repair function

`agent/scripts/data_repair_ca_el_segundo.py` → `data_repair(df)`

- Overwrites incorrect / missing fields from DATA
- Adds `{FIELD}_FLAG` ∈ {`FILLED`, `FIXED`} and `INFERRED_SCHEMA`
- CLI preview on the LA sample:

| Field | FILLED | FIXED | Missing before → after |
| --- | --- | --- | --- |
| STATUS_NORMALIZED | 4 | 15 | 4 → 0 |
| FILE_DATE | 0 | 0 | 10 → 10 |
| PERMIT_DATE | 22 | 0 | 253 → 231 |
| FINAL_DATE | 0 | 0 | 873 → 873 |

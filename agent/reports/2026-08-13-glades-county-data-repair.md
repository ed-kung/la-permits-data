# Glades County (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script (alphabetical `(JURISDICTION, STATE)` order) was **Glades County**. DATA is a city permit-portal payload (`Applied Date`, `Permit Date`, `Issued Date`, `Completed Date`, `inspections`, …) with near-total null `STATUS_NORMALIZED` / `STATUS_ORIGINAL`. Status was filled from the date/inspection lifecycle; `FILE_DATE` was realigned from `Permit Date` to `Applied Date` where they differed; spurious `PERMIT_DATE` values copied from review timestamps (and 1900-01-01 sentinels) were cleared; `FINAL_DATE` gaps were filled from `Completed Date` or passed Final/CO inspections. After repair: STATUS 99.5%; FILE_DATE 100% on labeled rows; Active/Final PERMIT_DATE 98.2%; Final FINAL_DATE 100%.

## Jurisdiction selection

`(JURISDICTION, STATE)` pairs in `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` were checked against `agent/scripts/{state}/data_repair_{state}_{city}.py`. First missing: **Glades County, FL** → `agent/scripts/fl/data_repair_fl_glades_county.py` (2,000 sample rows).

## DATA schemas (`INFERRED_SCHEMA`)

| Prefix | n | Notes |
| --- | ---: | --- |
| `portal_*` | 1,928 | Standard shells with `reviews` array |
| `contractor_box_*` | 58 | Also carry `record_type_from_contractor_box` (+ `plan_reviews`) |
| `legacy_*` | 11 | Blank `Status`, no `Permit Date` (older key-set) |
| `plan_reviews_*` | 3 | `plan_reviews` without contractor_box |

Suffix is a content slug from which lifecycle dates are present. Top values: `portal_completed_issued` 1,327; `portal_issued` 370; `portal_applied` 151; `portal_issued_final_insp` 50.

Canonical fields:

| Target field | Source in DATA |
| --- | --- |
| STATUS_NORMALIZED | `Completed Date` → Final; else passed Final/CO inspection → Final; else `Issued Date` → Active; else `Applied Date` / `Permit Date` → In Review |
| FILE_DATE | `Applied Date`; else `Permit Date` |
| PERMIT_DATE | `Issued Date` (not portal `Permit Date`, not review timestamps) |
| FINAL_DATE | `Completed Date`; else latest passed Final/CO inspection `completed_date` |

## Field assessments

### STATUS_NORMALIZED

| Upstream | n | Assessment |
| --- | ---: | --- |
| null | 2,000 | Fill from dates / inspections |

**Root cause:** Upstream left `STATUS_NORMALIZED` and `STATUS_ORIGINAL` entirely empty. The dominant portal schema has no usable `Status` string (only 11 legacy rows carry a blank `Status` key). Lifecycle is recoverable from `Completed Date` / `Issued Date` / `Applied Date` / `Permit Date` and from passed Final/CO inspections when `Completed Date` is blank or the `01/01/1900` sentinel.

**Repair performance:** FILLED 1,989; FIXED 0; missing 2,000 → 11. After: Final 1,416; Active 391; In Review 182; null 11 (empty / sentinel-only shells).

### FILE_DATE

Ideal: populated for all records (application / submittal).

- Before: present on **1,988 / 2,000**; **1,979** matched portal `Permit Date`, but only **1,657** matched `Applied Date`. **283** rows used `Permit Date` when `Applied Date` differed; **9** stored `1900-01-01` from the portal sentinel `Permit Date`.
- **10 FILLED** (legacy rows with `Applied Date` but no `Permit Date`); **292 FIXED** (Applied realignment + sentinel clears).
- After: missing **11** (same empty shells as null status). Labeled rows: Active / Final / In Review all **100%**.

### PERMIT_DATE

Ideal: populated for Active and Final.

- Before: **1,800 / 2,000** present; **1,775** matched `Issued Date`. **25** unissued rows carried a `PERMIT_DATE` copied from review `completed_date` (or similar), and **7** stored `1900-01-01` when `Issued Date` was the sentinel.
- **0 FILLED, 25 FIXED** (cleared spurious / sentinel values). Missing 200 → 225.
- After: Active **391 / 391 (100%)**; Final **1,384 / 1,416 (97.7%)** — remaining Final gaps have blank `Issued Date` (often completed via inspection or `Completed Date` alone). In Review **0%** (spurious stamps cleared).

### FINAL_DATE

Ideal: populated for Final; absent otherwise.

- Before: **1,376** matched `Completed Date`; **12** stored `1900-01-01` from sentinel `Completed Date`; **1** valid `Completed Date` was not ingested; **51** issued rows lacked `Completed Date` but had a passed Final/CO inspection.
- **52 FILLED** (1 Completed + 51 inspections); **12 FIXED** (sentinel clears / replacements). Missing 624 → 584.
- After: Final **1,416 / 1,416 (100%)**; non-Final **0%**.

**Note:** 10 Final rows have agency `Completed Date` earlier than `Issued Date` (source quirk); left as reported in DATA.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 1,989 | 0 | 2,000 → 11 |
| FILE_DATE | 10 | 292 | 12 → 11 |
| PERMIT_DATE | 0 | 25 | 200 → 225 |
| FINAL_DATE | 52 | 12 | 624 → 584 |

Coverage after repair (by effective status):

| Status | n | FILE_DATE | PERMIT_DATE | FINAL_DATE |
| --- | ---: | ---: | ---: | ---: |
| Final | 1,416 | 100% | 97.7% | 100% |
| Active | 391 | 100% | 100% | 0% |
| In Review | 182 | 100% | 0% | 0% |
| null | 11 | 0% | 0% | 0% |

## Artifacts

- Repair script: `agent/scripts/fl/data_repair_fl_glades_county.py`
- Repaired sample parquet: `$AGENT_DATA_PATH/glades_county_repaired_sample.parquet`

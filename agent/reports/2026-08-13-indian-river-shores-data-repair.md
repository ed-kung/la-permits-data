# Indian River Shores (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script (first-appearance order) was **Indian River Shores**. DATA is a city permit-portal payload (`Status`, `Permit Date`, `inspections`, `fees`, …) in the same family as St. Pete Beach / Daytona Beach Shores. Upstream left 491 `STATUS_NORMALIZED` nulls (blank Status + one Online Portal Application) and mapped all 160 `OPEN` rows to In Review instead of Active. `FILE_DATE` already matched `Permit Date` on every row. `PERMIT_DATE` and `FINAL_DATE` were entirely empty; there is no issuance field in DATA, so PERMIT_DATE stays missing, while FINAL_DATE was filled on 343 Final rows from successful inspections. After repair: STATUS 78.0% (441 blank shells remain); FILE_DATE 100%; Active/Final PERMIT_DATE 0%; Final FINAL_DATE 25.3%.

## Jurisdiction selection

`(JURISDICTION, STATE)` pairs in `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` (first-appearance order) were checked against `agent/scripts/{state}/data_repair_{state}_{city}.py`. First missing: **Indian River Shores, FL** → `agent/scripts/fl/data_repair_fl_indian_river_shores.py` (2,000 sample rows).

## DATA schemas (`INFERRED_SCHEMA`)

| Prefix | n | Notes |
| --- | ---: | --- |
| `portal_*` | 1,975 | Standard shells with `reviews` array |
| `contractor_box_*` | 17 | Also carry `record_type_from_contractor_box` (+ `plan_reviews`) |
| `plan_reviews_*` | 8 | `plan_reviews` instead of `reviews` |

Suffix is a slug of `DATA["Status"]` (or `blank`). Top values: `portal_closed` 1,092; `portal_blank` 490; `portal_co` 209; `portal_open` 143.

Canonical fields:

| Target field | Source in DATA |
| --- | --- |
| STATUS_NORMALIZED | `Status`; blank Status + passed inspection → Final |
| FILE_DATE | `Permit Date` (application / record stamp) |
| PERMIT_DATE | *(none — do not copy Permit Date)* |
| FINAL_DATE | Latest passed final-named / C/O inspection `completed_date`; else latest any passed inspection |

## Field assessments

### STATUS_NORMALIZED

| Status (DATA) | n | Upstream STATUS_NORMALIZED | Assessment |
| --- | ---: | --- | --- |
| Closed | 1,096 | Final | Correct |
| *(blank)* | 490 | **null** | Fill Final when passed insp (49); else leave null (441) |
| CO | 209 | Final | Correct |
| OPEN | 160 | **In Review** | Fix → Active |
| Expired | 18 | Inactive | Correct |
| Pending | 13 | In Review | Correct |
| Canceled | 13 | Inactive | Correct |
| On-line Portal Permit Application Request | 1 | **null** | Fill → In Review |

**Root cause:** Upstream mapped plain `STATUS_ORIGINAL` labels (`closed`/`co`→Final, `open`→In Review, `pending`→In Review, expired/canceled→Inactive) but (1) treated OPEN as pre-issuance even though this portal has separate Pending / On-line Portal Application statuses for unissued work, and (2) left blank Status and the Online Portal Application label unmapped. Blank shells are sparse historic records (often empty fees/inspections); only those with an `A (APPROVED)` inspection are inferable as Final.

**Repair performance:** FILLED 50, FIXED 160; missing 491 → 441. After: Final 1,354; Active 160; Inactive 31; In Review 14; null 441.

### FILE_DATE

Ideal: populated for all records.

- Before: present on **2,000 / 2,000**; every value matches `Permit Date` at day resolution (years 1988–2025, no sentinels).
- **0 FILLED, 0 FIXED.** Coverage remains 100% across all statuses.
- `Permit Date` also appears on Pending / Online Portal Application rows, confirming it is the file/application stamp rather than issuance.

### PERMIT_DATE

Ideal: populated for Active and Final.

- DATA has **no** Issued / Approved date. Nested date keys are only `Permit Date` and inspection `completed_date` / `scheduled_date`.
- Upstream PERMIT_DATE was empty for all 2,000 rows → **0 FILLED / 0 FIXED**.
- Active/Final still missing PERMIT_DATE: **1,514 / 1,514** (100%). Not repairable from DATA (copying Permit Date would falsely stamp In Review / Pending shells as issued).

### FINAL_DATE

Ideal: populated for Final; absent otherwise.

- Upstream FINAL_DATE was empty for all rows.
- **343 FILLED** from inspections: prefer latest passed inspection whose type matches `final` / `fnl` / `C/O` / `certificate` (portal statuses look like `A (APPROVED) - inspector`); else latest any passed `completed_date`.
- Remaining Final gap: **1,011** — mostly Closed/CO/blank-Final shells with empty `inspections` arrays (only 408 / 2,000 rows carry any inspections).
- Non-Final rows carry no FINAL_DATE after repair.

Coverage after repair: Final 343/1,354 (25.3%); Active / In Review / Inactive 0%.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 50 | 160 | 491 → 441 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 0 | 0 | 2,000 → 2,000 |
| FINAL_DATE | 343 | 0 | 2,000 → 1,657 |

## Artifacts

- Script: `agent/scripts/fl/data_repair_fl_indian_river_shores.py` (`data_repair`)
- Repaired sample: `AGENT_DATA_PATH/repaired/permits_fl_indian_river_shores_repaired.parquet`

Main residual gaps: no issuance date anywhere in DATA (PERMIT_DATE), blank-Status shells without a passed inspection (STATUS), and Final rows without a dated successful inspection (FINAL_DATE).

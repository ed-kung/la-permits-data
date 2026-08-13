# Nassau County (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script was **Nassau County**. DATA is a uniform city-portal payload (`app` / `permit` / `inspection_list` / `fees` / `init_info` / `permit_list`). Upstream left 477 `STATUS_NORMALIZED` nulls (mostly `ENTERED IN ERROR`, `DENIED`, `ACTIVE / PENDING`, etc.) and mislabeled 21 Active rows (unissued `REVIEWING` → should be In Review; `COMPLETED` → Final; one entered-in-error → Inactive). `FILE_DATE` already matched `Application Received Date` for every row. `FINAL_DATE` was entirely missing despite dated `PASSED*` inspections on most Final shells. The repair filled all 477 null statuses, fixed 21 statuses, filled 5 `PERMIT_DATE` values, and filled 849 `FINAL_DATE` values. After repair: STATUS 100% populated; FILE_DATE 100%; Active/Final PERMIT_DATE 100%; Final FINAL_DATE 81.4%.

## Jurisdiction selection

Ordered `(JURISDICTION, STATE)` pairs in `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` were checked against `agent/scripts/{state}/data_repair_{state}_{city}.py`. First missing: **Nassau County, FL** → `agent/scripts/fl/data_repair_fl_nassau_county.py` (1,999 sample rows).

## DATA schemas (`INFERRED_SCHEMA`)

All rows share the same top-level keys. Content variants split by whether `permit` carries a parseable Issued Date and whether `inspection_list` has any dated rows:

| Schema | n | Notes |
| --- | ---: | --- |
| `city_app_issued_insp` | 935 | Issued Date + dated inspection(s) |
| `city_app_app_only` | 478 | Empty `permit` object (often void / denied shells) |
| `city_app_issued` | 412 | Issued Date, no dated inspections |
| `city_app_permit_no_issued` | 174 | Permit object present, blank Issued Date |

Canonical fields:

| Target field | Source in DATA |
| --- | --- |
| STATUS_NORMALIZED | `app.Status` + `permit.Permit Status` (+ Issued Date overrides) |
| FILE_DATE | `app.Application Received Date` |
| PERMIT_DATE | `permit.Issued Date` |
| FINAL_DATE | latest inspection result starting with `PASS` (floored at Issued Date) |

## Field assessments

### STATUS_NORMALIZED

Before: Final 1,025 / null 477 / Active 281 / Inactive 216 / In Review 0.

| app.Status (main) | Permit Status | Upstream | Assessment |
| --- | --- | --- | --- |
| COMPLETE / COMPLETE | COMPLETED | Final (1,025); Active (6) | 6 → Final |
| ACTIVE / ACTIVE | ISSUED | Active (260); null (5) | Fill Active |
| ACTIVE / ACTIVE | REVIEWING | Active (12); null (1) | → In Review (no issue) |
| ACTIVE / ACTIVE | COMPLETED | Active (1) | → Final |
| ACTIVE / PENDING | REVIEWING | null (58) | → In Review |
| ACTIVE / PENDING | ISSUED | null (4) | → Active |
| ACTIVE / READY TO ISSUE | REVIEWING / ISSUED | null | In Review / Active |
| ACTIVE / COMPLETE | COMPLETED | null (11) | → Final |
| ACTIVE / COMPLETE | ISSUED | null (4) | → Active (still open) |
| ACTIVE / READY TO CLOSE | ISSUED | null (2) | → Active |
| HOLD / ACTIVE | ISSUED | null (2) | → Active |
| ENTERED IN ERROR / * | various | mostly null; 1 Active; 3 Inactive | → Inactive |
| WITHDRAWN / * | various | Inactive or null | → Inactive |
| DENIED / * | various | Inactive or null | → Inactive |
| EXPIRED / * | ISSUED / VOIDED / REVOKED | null | → Inactive |
| ACTIVE / VOID | — / WITHDRAWN / VOIDED | null | → Inactive |

**Root causes:**
1. Upstream mapper only covered `COMPLETE / COMPLETE` → Final, `ACTIVE / ACTIVE` → Active, and a subset of withdrawn/denied/void → Inactive; many terminal and in-review labels were left null.
2. Unissued `ACTIVE / ACTIVE` + `REVIEWING` was treated as Active despite blank Issued Date.
3. A handful of `COMPLETED` shells kept an Active label.

**Repair performance:** FILLED 477, FIXED 21; missing 477 → 0.

### FILE_DATE

- Before: missing on **0 / 1,999** rows. Present values always matched `Application Received Date` (0 mismatches).
- Ideal coverage already 100% for every status class.

**Repair performance:** FILLED 0, FIXED 0; missing 0 → 0.

### PERMIT_DATE

- Before: missing on **656 / 1,999**; present values always matched `Issued Date` (0 mismatches).
- Gaps concentrated in null-status (437) and Inactive (206); also 13 Active `REVIEWING` shells with blank Issued Date (reclassified to In Review).
- Filled 5 from Issued Date on previously null-status Active ISSUED rows.
- After repair: Active 100%, Final 100%, In Review 0% (correct), Inactive 4.5% (only shells that still carry Issued Date, e.g. EXPIRED / ISSUED).

**Repair performance:** FILLED 5, FIXED 0; missing 656 → 651. Remaining gaps are Inactive / app-only shells with no Issued Date.

### FINAL_DATE

- Before: missing on **all 1,999** rows (never ingested).
- Final shells often have `inspection_list` rows like `[owner/contractor, date, "PASSED - NO VIOLATION", ...]`.
- Filled 849 Final rows from the latest `PASS*` inspection date; floored at Issued Date when inspections predate issuance (eliminates 22 PERMIT > FINAL inversions that were 1-day portal quirks).
- Remaining 194 Final gaps have PASSED results but blank inspection dates (or empty inspection lists) → not fillable from DATA.

**Repair performance:** FILLED 849, FIXED 0; Final coverage 849 / 1,043 (81.4%). Non-Final statuses correctly have no FINAL_DATE.

## Repair script

- Script: `agent/scripts/fl/data_repair_fl_nassau_county.py`
- Entry point: `data_repair(df)`
- Artifact: `AGENT_DATA_PATH/nassau_county_repaired_sample.parquet`

## Post-repair coverage

| Field | Before missing | After missing | Notes |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 477 | 0 | FILLED 477, FIXED 21 |
| FILE_DATE | 0 | 0 | unchanged |
| PERMIT_DATE | 656 | 651 | Active/Final 100% |
| FINAL_DATE | 1,999 | 1,150 | Final 81.4%; rest lack dated PASS inspections |

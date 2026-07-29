# Desert Hot Springs data repair

**Summary:** Desert Hot Springs was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. CitizenServe `main`/`extra`/`location` JSON already has complete, correctly mapped `STATUS_NORMALIZED` from `main.status` and complete `FILE_DATE` from `dateCreated`, but `FILE_DATE` lags `dateSubmitted` on 41 rows, and `PERMIT_DATE` / `FINAL_DATE` are empty on all 2,000 rows. Repair fixes those 41 file dates and fills 21 final dates from CE `Compliance Date`. No issuance timestamps exist in DATA, so `PERMIT_DATE` stays missing.

## Jurisdiction

- **Desert Hot Springs, CA** — 2,000 sample rows
- Script: `agent/scripts/ca/data_repair_ca_desert_hot_springs.py`
- Artifact: `$AGENT_DATA_PATH/repaired/permits_ca_desert_hot_springs_repaired.parquet`

## DATA schema

All rows share CitizenServe top-level keys (`main`, `extra`, `location`). `main.status` codes map to `STATUS_ORIGINAL` (`0=draft`, `1=active`, `2=complete`, `-1=stopped`). Unlike Buena Park, DHS forms do **not** carry named `Status` / `Date Issued` / `Date Finaled`. Variants recorded in `INFERRED_SCHEMA`:

| Schema | n |
| --- | ---: |
| citizenserve_code_compliance | 820 |
| citizenserve_building | 270 |
| citizenserve_empty_extra | 268 |
| citizenserve_cannabis | 260 |
| citizenserve_business | 122 |
| citizenserve_vacation_rental | 58 |
| citizenserve_planning | 51 |
| citizenserve_encroachment | 50 |
| citizenserve_code_closed | 48 |
| citizenserve_form_other | 36 |
| citizenserve_temporary | 17 |

Canonical mappings: `main.status` → status; `dateSubmitted` else `dateCreated` → file; no permit source; `Compliance Date` → final (Final only).

## Field assessments

### STATUS_NORMALIZED

- Missing: 0 / 2,000.
- Upstream mapping from `STATUS_ORIGINAL` already matches live `main.status` on every row (`draft`→In Review, `active`→Active, `complete`→Final, `stopped`→Inactive).
- Extra field `20656` Active/Inactive on CE Archive rows describes violation state, not portal lifecycle — left alone.
- **Repair:** 0 FILLED, 0 FIXED.

### FILE_DATE

- Missing before: 0 / 2,000 (all matched `dateCreated` on the UTC calendar day).
- **Issue:** 41 rows have `dateSubmitted` on a later calendar day than `dateCreated` (lag 1–425 days, median 2). Application/submittal date should prefer submitted. Draft/`In Review` rows correctly lack `dateSubmitted` and keep `dateCreated`.
- **Repair:** prefer `dateSubmitted`, else `dateCreated` → **0 FILLED**, **41 FIXED**. Coverage remains 100%.

### PERMIT_DATE

- Missing: 2,000 / 2,000 (should be populated for Active + Final).
- No `Date Issued` / approval timestamp in `main` or `extra`. Candidate fields rejected:
  - Numeric `12678` on Building TEST rows — month-end values consistent with license / workers-comp expiration, not issuance.
  - `Permit Start Date` / event Start/End / Garage Sale dates — activity windows, not approval.
  - `expirationDate` / `lastUpdatedDate` — validity / admin touch, not issuance.
- **Repair:** 0 FILLED, 0 FIXED. Remains 0% on Active and Final.

### FINAL_DATE

- Missing before: 2,000 / 2,000 (should be populated for Final).
- **Repairable:** `extra['Compliance Date']` on Final code-enforcement rows (21) is a compliance / close-out date after file date (delta 0–113 days) → **21 FILLED**.
- `Case Closed=true` without `Compliance Date` (27 rows) has no usable close date — left missing.
- Building / cannabis / business Final shells have no finaling timestamp.
- **After repair:** Final coverage 21 / 1,384 (1.5%). Missing after: 1,979.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 0 | 0 | 0 → 0 |
| FILE_DATE | 0 | 41 | 0 → 0 |
| PERMIT_DATE | 0 | 0 | 2,000 → 2,000 |
| FINAL_DATE | 21 | 0 | 2,000 → 1,979 |

Chronology after repair: `PERMIT < FILE` = 0, `FINAL < PERMIT` = 0, `FINAL < FILE` = 0.

## Not repairable

- Vast majority of Active/Final rows lack issuance and finaling timestamps in the CitizenServe payload.
- Do not infer Expired/Inactive from `expirationDate` alone while `main.status` remains active/complete.

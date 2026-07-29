# San Luis Obispo (CA) data repair — 2026-07-28

San Luis Obispo was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` (first-appearance order) without an existing repair script. EnerGov `entity` / `details` JSON already has complete `FILE_DATE` (from `ApplyDate`) and mostly correct status/date fields, but upstream lagged `CaseStatus` on 18 rows (Finaled still Active, Issued still In Review, Estimate / Issued Legacy Only labeled Final), left `FINAL_DATE` blank on 8 Finaled shells that carry `FinalDate`, left `PERMIT_DATE` blank on 2 Issued shells, and copied closure-stamp `FinalDate` onto 10 non-Final rows. Repair fixes 18 statuses, fills 2 permit dates and 8 final dates, and clears 10 spurious final dates. Two Finaled shells still lack `IssueDate`.

## Jurisdiction selection

Walked `(JURISDICTION, STATE)` pairs in sample first-appearance order and compared against `agent/scripts/{state}/data_repair_{state}_{city}.py`. First missing: **San Luis Obispo, CA** → `agent/scripts/ca/data_repair_ca_san_luis_obispo.py` (n=2,001). (San Luis Obispo County already had a sibling EnerGov repair script.)

## DATA schema

All rows are Tyler EnerGov payloads with `entity` + `details` (+ `contacts`, `processing_status`). Variants recorded in `INFERRED_SCHEMA`:

| Schema | n | Description |
| --- | ---: | --- |
| `entity_fees` | 1,800 | entity + details + fees |
| `entity_basic` | 101 | entity + details, no fees |
| `entity_fees_reviews` | 100 | fees plus reviews/holds/attachments/more_info |

Canonical lifecycle fields: `entity.CaseStatus` / `details.PermitStatus`, `ApplyDate`, `IssueDate`, `FinalDate` (details fallback `FinalizeDate`). `ExpireDate` is a validity window, not a finaled date.

## Field assessment

### STATUS_NORMALIZED

- Fully populated (0 missing). Upstream mapped most `STATUS_ORIGINAL` labels into the four buckets (`finaled` → Final; `issued` → Active; `under review` / `on-line submission` / `ready for issuance` / `on hold` → In Review; `expired` / `void` / `withdrawn` → Inactive).
- **Incorrect vs DATA (`CaseStatus`):**
  - `Finaled` (8) still Active with `STATUS_ORIGINAL=issued` despite `FinalDate` present → FIXED to Final.
  - `Issued` (2) still In Review with `STATUS_ORIGINAL=on-line submission` despite `IssueDate` → FIXED to Active.
  - `Estimate` (5) labeled Final with empty Issue/Final dates → FIXED to In Review.
  - `Issued (Legacy Only)` (3) labeled Final with no `FinalDate` → FIXED to Active.
- **Repair:** 0 FILLED, 18 FIXED. Missing after: 0.

### FILE_DATE

- 2,001 / 2,001 populated; every value matches `entity.ApplyDate` calendar day (0 mismatches).
- **Repair:** 0 FILLED, 0 FIXED. Coverage 100%.

### PERMIT_DATE

- When present, always matched `entity.IssueDate` (0 mismatches).
- Missing fillable: 2 Issued shells mislabeled In Review → FILLED after status catch-up.
- Unfillable: 2 Finaled shells (`EPM-2687-2021` electrical service upgrade; `ENCR-0030-2018` right-of-way) with `Issued=False` and blank `IssueDate` but populated `FinalDate`.
- **Repair:** 2 FILLED, 0 FIXED. Missing after: 222.
- Post-repair Active PERMIT coverage: 459 / 459 (100%). Final: 1,219 / 1,221 (99.8%).

### FINAL_DATE

- When present on Final rows, always matched `entity.FinalDate` / `details.FinalizeDate` (0 mismatches).
- Fillable: 8 Finaled shells that were Active upstream (blank `FINAL_DATE` despite `FinalDate`) → FILLED after status catch-up.
- Spurious: 9 Active `Issued` + 1 Inactive `Expired` carrying `FinalDate` closure stamps → cleared (FIXED).
- After repair every Final row has `FINAL_DATE` (1,221 / 1,221). Non-Final: 0% by design.
- **Repair:** 8 FILLED, 10 FIXED. Missing after: 780 (net +2 from clearing spurious stamps).

## Repair performance

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | ---: | ---: | ---: | ---: |
| STATUS_NORMALIZED | 0 | 18 | 0 | 0 |
| FILE_DATE | 0 | 0 | 0 | 0 |
| PERMIT_DATE | 2 | 0 | 224 | 222 |
| FINAL_DATE | 8 | 10 | 778 | 780 |

Status distribution:

| | Before | After |
| --- | ---: | ---: |
| Final | 1,221 | 1,221 |
| Active | 462 | 459 |
| In Review | 171 | 174 |
| Inactive | 147 | 147 |

Status transitions (FIXED): Active→Final 8; Final→In Review 5; Final→Active 3; In Review→Active 2.

Chronology: 25 `FILE > PERMIT` and 2 `PERMIT > FINAL` day-order inversions remain in source Apply/Issue/Final stamps (often same-calendar-adjacent encroachment shells); left as-is.

## Artifacts

- Repair script: `agent/scripts/ca/data_repair_ca_san_luis_obispo.py`
- Repaired sample parquet: `$AGENT_DATA_PATH/repaired/permits_ca_san_luis_obispo_repaired.parquet`

# Hernando County (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script was **Hernando County**. DATA is a uniform county portal payload (`Parcel info` / `Permit info` / `Application Progress History` / `Inspection History` / `Payments`). Upstream `STATUS_NORMALIZED` and `FILE_DATE` were already correct for all 2,000 rows. The main defects were `PERMIT_DATE` (often copied from Application Date or IMPACT FEE instead of Parcel `Permit Date` / `PERMIT ISSUED`) and `FINAL_DATE` (often an early intermediate FINAL* inspection, missing despite a `FINALED` mark, or a bogus `Invalid Status` / `GENERAL FINAL` 1990-01-05 sentinel). The repair filled 10 and fixed 582 `PERMIT_DATE` values, filled 239 and fixed 754 `FINAL_DATE` values. After repair: STATUS 100%; FILE_DATE 100%; Final PERMIT_DATE 99.8%; Final FINAL_DATE 92.1%.

## Jurisdiction selection

`(JURISDICTION, STATE)` pairs in `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` (first-appearance order) were checked against `agent/scripts/{state}/data_repair_{state}_{city}.py`. First missing: **Hernando County, FL** → `agent/scripts/fl/data_repair_fl_hernando_county.py` (2,000 sample rows).

## DATA schemas (`INFERRED_SCHEMA`)

Every row shares the same top-level keys: `Notes`, `Charges`, `Payments`, `Documents`, `Parcel info`, `Permit info`, `Deficiencies`, `Contractors Listed`, `Inspection Details`, `Inspection History`, `Application Progress History`. Content suffixes split by which canonical dates are recoverable:

| Schema | n | Notes |
| --- | ---: | --- |
| `hernando_portal_issued_finaled` | 1,759 | Issuance + close-out recoverable |
| `hernando_portal_issued` | 174 | Issuance only |
| `hernando_portal_applied` | 65 | Neither |
| `hernando_portal_finaled` | 2 | Close-out only |

Canonical fields:

| Target field | Source in DATA |
| --- | --- |
| STATUS_NORMALIZED | `Permit info['Appl Status: ']` (`F ** FINALED *` / `C ** CLOSED *` → Final; `V ** VOIDED *` → Inactive) |
| FILE_DATE | `Parcel info['Application Date']` |
| PERMIT_DATE | `Parcel info['Permit Date']` else earliest `Application Progress History` `PERMIT ISSUED` else earliest `Payments` `PERMIT FEE` |
| FINAL_DATE | Latest `Inspection History` `Insp Date` among Status `FINALED` and FINAL* types with `COMPLETED OK` / `ELECTRICAL RELEASE` |

## Field assessments

### STATUS_NORMALIZED

| DATA Appl Status | n | Upstream STATUS_NORMALIZED | Assessment |
| --- | ---: | --- | --- |
| `F ** FINALED *` | 1,899 | Final | Correct |
| `V ** VOIDED *` | 91 | Inactive | Correct |
| `C ** CLOSED *` | 10 | Final | Correct |

No Active or In Review statuses appear in the sample. No nulls.

**Repair performance:** FILLED 0, FIXED 0; missing 0 → 0.

### FILE_DATE

- Before: missing on **0 / 2,000**. Every value matches `Parcel info['Application Date']` at calendar-day resolution.
- Ideal coverage already 100% for every status class.

**Repair performance:** FILLED 0, FIXED 0; missing 0 → 0 (100% coverage).

### PERMIT_DATE

- Before: NaN on **59 / 2,000**. Of 1,941 present values, only 1,330 matched Parcel `Permit Date`; 563 mismatched (389 equaled `FILE_DATE` / Application Date; most of the rest matched IMPACT FEE payment dates rather than issuance).
- Parcel `Permit Date` agrees with `PERMIT ISSUED` progress marks on 1,900 / 1,903 comparable rows — that is the canonical issuance stamp.
- 10 Final rows had Parcel `Permit Date` (or `PERMIT ISSUED`) but missing `PERMIT_DATE` → FILLED.
- 18 Voided / empty-issuance shells had spurious `PERMIT_DATE` (usually equal to Application Date from ADVANCE PAY / IMPACT FEE only) → cleared.
- After repair, Final coverage is 1,906 / 1,909 (99.8%). The 3 gaps are `PERMIT_NUMBER == 0` shells with no Parcel Permit Date, no `PERMIT ISSUED`, and no `PERMIT FEE` (only IMPACT FEE or no payments).
- Inactive coverage 27 / 91 (29.7%): only Voided rows with real issuance evidence keep a date.

**Repair performance:** FILLED 10, FIXED 582; missing 59 → 67 (net rise from clearing spurious Inactive stamps). Final 99.8%.

Nine remaining `FILE_DATE > PERMIT_DATE` inversions are present in the agency Parcel fields themselves (Application Date after Permit Date), not introduced by the repair.

### FINAL_DATE

- Before: NaN on **331 / 2,000**; Final had 1,661 / 1,909 present; 8 Voided/Inactive rows carried a spurious final date.
- Present values matched max `FINALED` Insp Date on only ~907 rows; 588 were earlier intermediate FINAL* marks (e.g. first plumbing/mechanical complete, paid red-tag dates).
- 239 Final rows had a `FINALED` inspection but missing `FINAL_DATE` → FILLED.
- 138 rows used a bogus `GENERAL FINAL` / `Invalid Status` date of 1990-01-05 with no real close-out → cleared.
- Closed / Final shells without `FINALED` or FINAL* pass inspections remain missing (150 after repair).

**Repair performance:** FILLED 239, FIXED 754 (531 moved later to true close-out, ~67 adjusted earlier including ELECTRICAL RELEASE union cases, 149 cleared). Final coverage 92.1% (1,759 / 1,909). Active / In Review / Inactive FINAL_DATE all 0% after cleanup.

Three remaining `PERMIT_DATE > FINAL_DATE` inversions are agency quirks where a `FINALED` inspection predates Parcel `Permit Date` (likely re-issue / data-entry artifacts).

## Artifacts

- Repair script: `agent/scripts/fl/data_repair_fl_hernando_county.py` (`data_repair`)
- Repaired sample parquet: `$AGENT_DATA_PATH/repaired/permits_fl_hernando_county_repaired.parquet`

# Alachua County (FL) data repair

Summary: Alachua County was the first FL sample jurisdiction without a repair script (Jacksonville and Lee County already had one). Portal DATA always exposes `Status:`, `Permit Details`, `Reviews`, and `Inspections`, but workflow depth varies (`pas` / `workflow` / `legacy`). The repair clears all missing `STATUS_NORMALIZED`, reclassifies Closed Administratively from Final → Inactive, corrects ~1.1k `FILE_DATE` values that had been copied from issue/late-review dates, and recovers Final `FINAL_DATE` for 97.5% of Final rows (0% before). Remaining gaps are almost entirely empty legacy shells with no dates in DATA.

## Jurisdiction selected

- Sample file: `MY_DATA_PATH/processed_data/permits_fl_sample.parquet`
- Existing FL repair scripts: Jacksonville, Lee County
- First `(JURISDICTION, STATE)` without `agent/scripts/{state}/data_repair_{state}_{city}.py`: **Alachua County, FL**
- Sample size: **1,999** records

## DATA schemas (`INFERRED_SCHEMA`)

| Schema | n | Notes |
| --- | ---: | --- |
| `workflow` | 1,186 | Dated `Reviews` and/or `Inspections` present |
| `pas` | 426 | `Permit Type == Pre-Application Screening` |
| `legacy` | 387 | No dated workflow (mostly old converted records) |

Canonical field sources:

| Field | Source |
| --- | --- |
| STATUS_NORMALIZED | `DATA['Status:']` |
| FILE_DATE | Application Intake / earliest Review `Start`, else earliest `Completion`, else `Permit Details['Issue Date:']` |
| PERMIT_DATE | `Permit Details['Issue Date:']`, else Review Complete / latest approved or latest review `Completion` |
| FINAL_DATE | Latest Pass/Approved final-like inspection (`Final`, trade finals, `7090 - CO Request`), else Review Complete / latest review `Completion` / Issue Date |

Top-level `Issue Date` is always null; the real issuance date lives under `Permit Details`.

## Findings by field

### STATUS_NORMALIZED

- Before: Final 750; Active 438; missing 416; Inactive 314; In Review 81.
- **416 missing** were almost all `PAS Approved` (415) plus one `Irrigation Resubmittal Required` — never mapped upstream → **FILLED** to Final / In Review.
- **132 FIXED**: `Closed Administratively` had been mapped to Final, but 131/132 have no final inspection and look like admin closures of old building permits → remapped to **Inactive**.
- Other statuses already matched DATA (`Closed`/`Complete`/`COED` → Final; `Issued`/`Approved` → Active; void/expired/withdrawn/denied → Inactive; under review / payment due / online application → In Review).

### FILE_DATE

- Before: 644 / 1,999 missing (32.2%).
- When present, `FILE_DATE` frequently equaled Issue Date or a late review Completion even though an earlier Review Start existed (**694** rows with FILE==issue and an earlier start). That is incorrect for an application/submittal date.
- Repair prefers intake/earliest Review Start → **582 FILLED**, **1,096 FIXED** (97.7% of fixes move the date earlier; median shift −5 days).
- After: 62 still missing — nearly all `legacy` shells (`Under Review` / `Closed` misc / `Expired` / `SUSPEND`) with empty Reviews and null Issue Date.

### PERMIT_DATE

- Before: 332 missing. Existing non-null values matched `Permit Details['Issue Date:']` at day resolution (**1,667 / 1,667**, 0 mismatches → no FIXED).
- Missing Active/Final rows filled from Issue Date when present, else Review Complete / review Completions (needed for PAS Approved without Issue Date and Closed lien-search desk work).
- After: **Active 438/438 (100%)**, **Final 1,007/1,033 (97.5%)**.
- Remaining 26 Final gaps are empty Closed misc / zoning shells with no Issue Date and no Reviews.

### FINAL_DATE

- Before: **1,999 / 1,999 missing (100%)** — upstream never populated this field.
- Inspection statuses include `Pass` (legacy) as well as `Approved`; both count as successful. Final-like types include `9000 - Final Inspection`, trade finals (`Electrical Final`, etc.), Driveway Final, and `7090 - CO Request`.
- PAS Approved / desk Closed rows without inspections use Review Complete or latest review Completion (or Issue Date).
- After: **Final 1,007/1,033 (97.5%)** with FINAL_DATE; the same 26 empty legacy Closed shells remain unfillable.

## Repair performance

Script: `agent/scripts/fl/data_repair_fl_alachua_county.py` (`data_repair`)

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | ---: | ---: | ---: | ---: |
| STATUS_NORMALIZED | 416 | 132 | 416 | 0 |
| FILE_DATE | 582 | 1,096 | 644 | 62 |
| PERMIT_DATE | 190 | 0 | 332 | 142 |
| FINAL_DATE | 1,007 | 0 | 1,999 | 992 |

Status distribution after repair: Final 1,033; Inactive 446; Active 438; In Review 82.

Ideal coverage after repair:

| Status | FILE_DATE | PERMIT_DATE | FINAL_DATE |
| --- | ---: | ---: | ---: |
| Active | 100% | 100% | 0% (expected) |
| Final | 97.5% | 97.5% | 97.5% |
| In Review | 62.2% | 6.1% | 0% (expected) |
| Inactive | 98.9% | 91.3% | 0% (expected) |

## Not repairable from DATA

- Legacy shells with empty `Reviews`, empty `Inspections`, and blank `Permit Details['Issue Date:']` (no application, issuance, or final signal).
- In Review rows that never progressed past an undated stub.
- Inactive / In Review `PERMIT_DATE` left missing when never issued (by design for fill rules; pre-existing issuance dates on Inactive rows are retained).

## Artifacts

- Repair script: `agent/scripts/fl/data_repair_fl_alachua_county.py`
- Repaired sample: `AGENT_DATA_PATH/processed_data/permits_fl_alachua_county_repaired.parquet`

# Orlando (FL) data repair

Summary: Orlando was the first FL sample jurisdiction without a repair script after Jacksonville, Lee County, Sarasota County, and Osceola County. Of 2,001 sample rows, 1,118 are empty DATA stubs with no recoverable fields; the remaining 883 are city-portal payloads keyed by `Application Status`, `Issued Date`, and `Finaled Date`. The repair remaps 62 Open+Issued rows from In Review → Active, fills 1 Hardhold status, overwrites 98 FINAL_DATE values to match agency `Finaled Date` (upstream had used Final Inspection schedule dates), fills 9 missing finals, and clears 11 spurious FINAL_DATE values on non-Final rows. FILE_DATE and PERMIT_DATE had no fillable gaps among portal rows that already expose those dates in DATA—FILE_DATE remains almost entirely missing because the portal payload has no application/submittal field for ordinary building permits.

## Jurisdiction selected

- Sample file: `MY_DATA_PATH/processed_data/permits_fl_sample.parquet`
- First `(JURISDICTION, STATE)` without `agent/scripts/{state}/data_repair_{state}_{city}.py`: **Orlando, FL**
- Sample size: **2,001** records

## DATA schemas (`INFERRED_SCHEMA`)

| Schema | n | Notes |
| --- | ---: | --- |
| `empty` | 1,118 | `{"empty": ""}` stubs — no status or dates |
| `permit_portal` | 883 | `Application Status` plus optional Issued / Finaled / Expiration, Plan Review[], Inspections[] |

Canonical field sources (`permit_portal`):

- `Application Status` (Open + Issued Date → Active) → `STATUS_NORMALIZED`
- Earliest Plan Review `Due Date` → `FILE_DATE`
- `Issued Date` → `PERMIT_DATE`
- `Finaled Date`; else approved Final inspection `Scheduled Date` → `FINAL_DATE`

## Findings by field

### STATUS_NORMALIZED

- Before: missing 1,119; Final 791; In Review 88; Active 3.
- Upstream follows `STATUS_ORIGINAL` / `Application Status` almost 1:1 (`finaled`→Final, `closed`→Final, `open`→In Review, `approved`→Active, etc.).
- Issues:
  - **62** `Open` rows already have `Issued Date` but were normalized to In Review. An issued, still-open permit is Active.
  - **1** `Hardhold` row left `STATUS_NORMALIZED` null (unmapped).
  - **1,118** `empty` stubs have null status with nothing in DATA to recover.
- Repair:
  - **62 FIXED** Open+Issued → Active
  - **1 FILLED** Hardhold → In Review
- After: missing **1,118**; Final 791; Active 65; In Review 27.

### FILE_DATE

- Before: 1,969 missing (98.4%). Only **32** portal rows have a non-null FILE_DATE; all are Closed/Approved zoning-style cases with a non-empty Plan Review list.
- Earliest Plan Review `Due Date` matches 30/32 existing FILE_DATE values at day resolution. The 2 disagreements look like Due Date sentinels earlier than the stored application date (e.g. 2020-12-25 vs FILE 2021-01-13) — existing FILE_DATE left unchanged.
- No portal row with missing FILE_DATE has a Plan Review Due Date to fill from. Building/trade permits expose Issued / Finaled but not an application date.
- Repair: **0 FILLED**, **0 FIXED**. Missing after: still 1,969.
- Remaining gaps: all `empty` rows; nearly all issued/finaled building permits in `permit_portal`.

### PERMIT_DATE

- Before: 1,221 missing. Among portal rows, every parseable `Issued Date` already matched `PERMIT_DATE` (780/780).
- After remapping Open+Issued → Active, those 62 already carried matching PERMIT_DATE values.
- Repair: **0 FILLED**, **0 FIXED**.
- After repair coverage: Active **62/65 (95.4%)**; Final **718/791 (90.8%)**. The 3 Active gaps are `Approved` appearance-review rows with no Issued Date; Final gaps are mostly Closed cases never issued.

### FINAL_DATE

- Before: 1,338 missing. Among Final rows, 139 missing (17.6%). Also **11** Open (In Review) rows incorrectly carried FINAL_DATE from cancelled/partial Final inspection schedule dates while `Finaled Date` was `00/00/0000`.
- Upstream FINAL_DATE usually equals the approved Final inspection `Scheduled Date`. Agency `Finaled Date` differs on **98** rows (median +1 day; often administrative closeout after inspection).
- Repair:
  - **98 FIXED** → overwrite to `Finaled Date`
  - **9 FILLED** → Final rows with Finaled Date but null FINAL_DATE
  - **11 FIXED** → clear spurious FINAL_DATE on rows reclassified (or remaining) as non-Final
- After: Final **661/791 (83.6%)** have FINAL_DATE; Active / In Review have **0**. Missing count rose slightly (1,338 → 1,340) because clears exceeded fills.
- Remaining Final gaps: 127 Closed + 2 Completed + 1 Finaled without a usable Finaled Date or approved Final inspection date.

## Repair performance

Script: `agent/scripts/fl/data_repair_fl_orlando.py` (`data_repair`)

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | ---: | ---: | ---: | ---: |
| STATUS_NORMALIZED | 1 | 62 | 1,119 | 1,118 |
| FILE_DATE | 0 | 0 | 1,969 | 1,969 |
| PERMIT_DATE | 0 | 0 | 1,221 | 1,221 |
| FINAL_DATE | 9 | 109 | 1,338 | 1,340 |

Coverage after repair (share non-null):

| Status | n | FILE_DATE | PERMIT_DATE | FINAL_DATE |
| --- | ---: | ---: | ---: | ---: |
| Active | 65 | 4.6% | 95.4% | 0% |
| Final | 791 | 3.7% | 90.8% | 83.6% |
| In Review | 27 | 0% | 0% | 0% |

## Artifacts

- Repair script: `agent/scripts/fl/data_repair_fl_orlando.py`
- Repaired sample parquet: `AGENT_DATA_PATH/orlando_repaired_sample.parquet`

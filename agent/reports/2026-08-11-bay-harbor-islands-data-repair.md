# Bay Harbor Islands (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script (after Bay County in list order) was **Bay Harbor Islands**. DATA is a single citizen-portal family (`Status:`, `Permit Details`, `Reviews`, `Inspections`) with form-field variation by permit type. Upstream status mapping covered common labels but missed `Application Abandoned` / a few uncommon labels; `PERMIT_DATE` already matched `Issue Date:` perfectly when present; `FINAL_DATE` was entirely missing. After repair: STATUS 99.9% populated; FILE_DATE 99.4% (most fills use Issue Date as application proxy); Active/Final PERMIT_DATE 100%; Final FINAL_DATE 100% (340 from final inspections, 209 from other passed inspections, 67 from reviews, 242 from Issue Date).

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` and walked unique `(JURISDICTION, STATE)` pairs in sort order. Existing FL repair scripts covered Alachua County through Bay County. **Bay Harbor Islands** was the first without `agent/scripts/fl/data_repair_fl_bay_harbor_islands.py`.

Sample size: **2,000** records.

## DATA schemas

| INFERRED_SCHEMA   | Count |
| ----------------- | ----: |
| `issued_insp`     |   749 |
| `issued`          |   662 |
| `issued_insp_rev` |   403 |
| `issued_rev`      |   121 |
| `rev`             |    45 |
| `minimal`         |    11 |
| `insp_rev`        |     7 |
| `insp`            |     2 |

Canonical source fields:

| Target field      | DATA source                                                                 |
| ----------------- | --------------------------------------------------------------------------- |
| STATUS_NORMALIZED | `Status:`                                                                   |
| FILE_DATE         | earliest Review `Start` (else `Completion`); else `Permit Details.Issue Date:` when FILE missing |
| PERMIT_DATE       | `Permit Details.Issue Date:` (else latest approved / latest review Completion) |
| FINAL_DATE        | last passed final-ish inspection else last passed inspection else latest review Completion else Issue Date (Closed only) |

`STATUS_ORIGINAL` matches live `Status:` on all 2,000 rows (case-normalized). Top-level `Issue Date` is always null; the usable issue date lives under `Permit Details`.

## Field assessments

### STATUS_NORMALIZED

Before: Active 1,051 · Final 858 · Inactive 52 · In Review 15 · missing 24.

- Upstream mapping already correct for `approved`→Active, `closed`→Final, `expired`/`withdrawn`/`denied`→Inactive, `pending`/`online application received`/`on hold`/`corrections`→In Review.
- **22 FILLED** nulls:
  - `Application Abandoned` (20) → Inactive
  - `Zoning Needed` (1) → In Review
  - `Partial Approval - Foundation Only` (1) → Active
- **3 FIXED**:
  - `Approved with Conditions` In Review → Active (1)
  - `Change of Contractor` In Review → Active (2)
- **2** blank `Status:` / null `STATUS_ORIGINAL` rows stay missing.

After: Active 1,055 · Final 858 · Inactive 72 · In Review 13 · missing 2.  
Flags: **FILLED 22 · FIXED 3**.

### FILE_DATE

Before: 1,426 missing (71.3%). Ideal: populated for all records.

- No dedicated Applied/Submit date in DATA. Reviews carry `Start` / `Completion`; when FILE was already present it often equaled a late Completion rather than the earliest Start.
- **5 FILLED** from earliest Review Start.
- **1,408 FILLED** from `Issue Date:` when no review dates exist (application-date proxy; equals PERMIT_DATE on those rows).
- **371 FIXED** to earlier Review Start/Completion (370 moved earlier; median shift 13 days) — upstream had stored a later review Completion as FILE_DATE.
- **13** remain missing: 11 `minimal` + 2 `insp` shells with no Reviews and no Issue Date (Inactive/In Review only).

After: 13 missing (99.4% overall). Active/Final FILE_DATE **100%**.  
Flags: **FILLED 1,413 · FIXED 371**.

### PERMIT_DATE

Before: 65 missing. Ideal: populated for Active and Final.

- When both present, PERMIT_DATE already matched `Permit Details.Issue Date:` on **1,935 / 1,935** rows (0 day mismatches).
- **7 FILLED** on Active/Final rows with blank Issue Date, using latest approved / latest review Completion (`rev` schema).
- Remaining missing PERMIT_DATE values are on In Review / Inactive only (not required).

After: 58 missing. Coverage: Active **100%** (1,055/1,055); Final **100%** (858/858).  
Flags: **FILLED 7 · FIXED 0**.

### FINAL_DATE

Before: 2,000 missing (0% Final coverage). Ideal: populated for Final.

- No Finaled/CO date field in DATA; only inspection `Date` + review `Completion`.
- **858 FILLED** on all Closed→Final rows:
  - 340 from last passed final-ish inspection (`Final`, `Final Electrical`, `Building Final`, etc.)
  - 209 from last other passed inspection
  - 67 from review Completion
  - 242 from Issue Date (Closed with no inspections/reviews — weak proxy)
- Non-Final FINAL_DATE remains 0 (none were spuriously set upstream).

After: 1,142 missing. Final coverage **100%** (858/858). Non-Final FINAL_DATE: **0**.  
Flags: **FILLED 858 · FIXED 0**.

## Repair script

`agent/scripts/fl/data_repair_fl_bay_harbor_islands.py` — `data_repair(df)`.

Outputs: repaired `STATUS_NORMALIZED`, `FILE_DATE`, `PERMIT_DATE`, `FINAL_DATE`; flags `*_FLAG` (`FILLED` / `FIXED`); `INFERRED_SCHEMA`.

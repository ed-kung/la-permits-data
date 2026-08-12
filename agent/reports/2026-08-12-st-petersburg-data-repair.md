# St. Petersburg (FL) data repair

Repaired STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for St. Petersburg using the city-portal `DATA` JSON (same family as Punta Gorda / Pompano Beach). Upstream had mapped portal **Permit Date** into PERMIT_DATE (a close-adjacent stamp on Final rows) and left 133 fees-only shells with null status; after repair, FILE_DATE remains complete, Active/Final issuance uses **Issue Date**, and Final coverage of FINAL_DATE is 99.9%.

## Scope

- Jurisdiction: **St. Petersburg, FL** (first `(JURISDICTION, STATE)` in `permits_fl_sample.parquet` without an existing `agent/scripts/{state}/data_repair_*.py`)
- Sample size: **1,999** records
- Script: `agent/scripts/fl/data_repair_fl_st_petersburg.py`
- Artifact: `$AGENT_DATA_PATH/st_petersburg_repaired_sample.parquet`

## DATA schema

Two key-set schemas; `INFERRED_SCHEMA` further splits by status slug:

| Schema family | n | Notes |
| --- | ---: | --- |
| `permit_status_*` | 1,866 | `detail` + `permit_status_detail` + inspection blocks |
| `fees_detail_*` | 133 | `detail` / fees only (no issue or inspection dates) |

Canonical fields:

| Target field | DATA source |
| --- | --- |
| STATUS_NORMALIZED | `Status for Permit Number`, overridden by terminal `Application Status` (VOID / ABANDONED / EXPIRED); fees_detail uses `Application Status` alone |
| FILE_DATE | `Application Date` |
| PERMIT_DATE | `Issue Date` (not portal `Permit Date`) |
| FINAL_DATE | Latest successful FINAL/CO inspection; else latest non-NOC success; else `Permit Date` when it differs from `Issue Date` |

Top `INFERRED_SCHEMA` values: `permit_status_closed` (1,391), `permit_status_permit_printed` (335), `fees_detail_in_process` (95), `permit_status_final_inspection_complete` (51), `permit_status_c_o_issued` (42), `fees_detail_void` (34).

## Findings by field

### STATUS_NORMALIZED

**Before:** Final 1,484 · Active 335 · null 133 · In Review 31 · Inactive 16

Upstream mapped `Status for Permit Number` (`closed`→Final, `permit printed`→Active, `plan check`/`on hold`/`to be issued`→In Review, `permit revoked`→Inactive). Problems:

- **133 fees_detail shells** had no permit-status block → null STATUS_NORMALIZED (`IN PROCESS` 95, `VOID` 34, `PENDING VERIFICATION` 2, `CLOSED` 2).
- **92 CLOSED rows** with Application Status VOID / ABANDONED / EXPIRED were labeled Final despite terminal admin outcomes.
- One `TO BE ISSUED` + `VOID` In Review row should be Inactive.

**After:** Final 1,394 · Active 335 · Inactive 143 · In Review 127 · null 0  
Flags: **FILLED 133 · FIXED 93**

### FILE_DATE

Already populated for all 1,999 rows and equal to `Application Date` on every record. **FILLED 0 · FIXED 0**.

### PERMIT_DATE

Upstream copied portal **Permit Date**, which matches issuance on many Active rows but is a later close-adjacent stamp on nearly all Final rows (only 7/1,484 Final PERMIT values equaled Issue Date).

Issues repaired:

- **1,466+ Final / Active / Inactive** PERMIT values FIXED to Issue Date.
- **58 Active** rows (mostly older `PERMIT PRINTED` with blank Permit Date) FILLED from Issue Date → Active now 335/335.
- **31 In Review** rows had spurious Permit-Date stamps with blank Issue Date → cleared.

**After:** Active 100% · Final 99.5% (7 missing) · In Review 0% · Inactive 67.8%  
Flags: **FILLED 58 · FIXED 1,539** · missing 191 → 180

Remaining Final PERMIT gaps: 5 CLOSED shells with blank Issue Date and 2 fees_detail `CLOSED` rows (no Issue Date in DATA). Inactive gaps are mostly fees_detail VOID (never issued) plus a few revoked/closed shells without Issue Date.

### FINAL_DATE

Upstream FINAL matched the latest successful inspection on nearly every populated Final row (1,373/1,375). Issues:

- **109 Final** rows missing FINAL_DATE — largely VOID/ABANDONED/EXPIRED/admin-closed shells that are no longer Final after status repair; remaining true Finals filled from inspections or Permit Date≠Issue Date (**FILLED 39**).
- **22** FINAL values cleared when status moved to Inactive (**FIXED** clears).
- **4** FINAL values adjusted to the preferred inspection / close stamp.

**After:** Final 1,392/1,394 (99.9%); other statuses 0.  
Flags: **FILLED 39 · FIXED 26** · missing 624 → 607

The two remaining Final gaps are fees_detail `CLOSED` shells with no inspections and no Permit Date.

Three PERMIT > FINAL inversions remain where Issue Date is after the last approved inspection (likely reissue / portal stamp quirks); Issue Date is still the correct issuance field.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 133 | 93 | 133 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 58 | 1,539 | 191 → 180 |
| FINAL_DATE | 39 | 26 | 624 → 607 |

Post-repair coverage vs target rules:

| Rule | Result |
| --- | --- |
| FILE_DATE for all | 1,999/1,999 (100%) |
| PERMIT_DATE for Active / Final | Active 335/335; Final 1,387/1,394 |
| FINAL_DATE for Final only | 1,392/1,394 Final; 0 on non-Final |
| Active/Final/Inactive PERMIT = Issue Date | 0 mismatches among 1,830 rows with Issue Date |

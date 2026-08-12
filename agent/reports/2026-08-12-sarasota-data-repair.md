# Sarasota (FL) data repair

Repaired STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE for Sarasota using the flat Accela MHC `DATA` JSON. The sample had **zero Final rows** despite ~1,492 closed MHC shells; after repair, status/date coverage matches the target rules (FILE for all, PERMIT for Active/Final, FINAL for Final only).

## Scope

- Jurisdiction: **Sarasota, FL** (first `(JURISDICTION, STATE)` in `permits_fl_sample.parquet` without an existing `agent/scripts/{state}/data_repair_*.py`)
- Sample size: **1,999** records
- Script: `agent/scripts/fl/data_repair_fl_sarasota.py`
- Artifact: `$AGENT_DATA_PATH/sarasota_repaired_sample.parquet`

## DATA schema

Every row shares the same 201-key flat MHC payload. Canonical fields:

| Target field | DATA source |
| --- | --- |
| STATUS_NORMALIZED | `admin_status`, overridden by `mhc_closedate` / `coissuedate` / `mhc_issuedate` |
| FILE_DATE | `mhc_applicationdate` |
| PERMIT_DATE | `mhc_issuedate` |
| FINAL_DATE | `mhc_closedate`, fallback `coissuedate` |

`INFERRED_SCHEMA` is content-based (identical key set for all rows):

| Schema | n |
| --- | ---: |
| `mhc_issued_closed` | 1,419 |
| `mhc_applied` | 257 |
| `mhc_issued` | 226 |
| `mhc_issued_closed_co` | 50 |
| `mhc_nostatus_issued_closed` | 24 |
| `mhc_nostatus_issued` | 20 |
| `mhc_nostatus_applied` | 3 |

## Findings by field

### STATUS_NORMALIZED

**Before:** Active 1,103 · In Review 834 · Inactive 13 · null 49 · **Final 0**

`admin_status` mapped cleanly onto the existing labels (`Permit Issued`→Active, `Plan Approved`/`Pending Plan Review`→In Review, `Cancel Record`→Inactive), but **closed permits were never labeled Final**. 1,091 Active `Permit Issued` rows and hundreds of `Plan Approved` / null-status rows already carried `mhc_closedate`.

Null status came from blank `admin_status` (47) and `Plan Conditionally Approved` (2).

**Repair rule (priority):** Cancel → Inactive; close/CO date → Final; issued / `Permit Issued` → Active; else mapped / blank → In Review.

**After:** Final 1,492 · In Review 260 · Active 234 · Inactive 13 · null 0  
Flags: **FILLED 49 · FIXED 1,668**

### FILE_DATE

Already populated for all 1,999 rows and equal to `mhc_applicationdate` on every record. **FILLED 0 · FIXED 0**.

### PERMIT_DATE

Matched `mhc_issuedate` wherever both were present. Issues:

- 577 In Review rows carried a permit date (including one orphan `2024-09-10` with no MHC issue stamp) — incorrect for In Review.
- One `Plan Approved` row had `mhc_issuedate` but a missing `PERMIT_DATE`.

After status repair + fill/clear: Active/Final/Inactive all have PERMIT_DATE; In Review has none.  
Flags: **FILLED 1 · FIXED 1** (net missing count unchanged at 260 = remaining In Review).

### FINAL_DATE

Matched `mhc_closedate` when both present. Issues:

- 1,091 Active and 371 In Review rows had FINAL_DATE while status was not Final.
- Four closed `Plan Approved` rows were missing FINAL_DATE despite `mhc_closedate`.
- One Cancel Record had a close stamp that should not remain as FINAL_DATE under Inactive.

After repair: Final 1,492/1,492 (100%) have FINAL_DATE; other statuses 0.  
Flags: **FILLED 4 · FIXED 1**.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 49 | 1,668 | 49 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 1 | 1 | 260 → 260 |
| FINAL_DATE | 4 | 1 | 510 → 507 |

Post-repair coverage:

- FILE_DATE: 100% all statuses
- PERMIT_DATE: 100% Active / Final / Inactive; 0% In Review
- FINAL_DATE: 100% Final; 0% otherwise
- STATUS_NORMALIZED: no nulls remaining

## Not repaired (by design)

- Cancel Record stays Inactive even with `mhc_closedate` (close stamp cleared from FINAL_DATE).
- In Review rows intentionally lack PERMIT_DATE / FINAL_DATE after cleanup.

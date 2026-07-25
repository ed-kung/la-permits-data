# Fontana (CA) data repair

**Summary:** Assessed and repaired `STATUS_NORMALIZED`, `FILE_DATE`, `PERMIT_DATE`, and `FINAL_DATE` for Fontana — the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. Across 1,999 sample rows and two DATA schemas, status is fully populated (1 filled, 2 fixed), `FILE_DATE` was already correct wherever DATA provides an application date (3 unfillable gaps remain), `PERMIT_DATE` gained 93 fills from Approved when Issued was empty plus 6 Issued-date corrections, and `FINAL_DATE` gained 56 fills from finaling workflow/inspections while 20 spurious finals on Inactive (VOID) rows were cleared. Large residual gaps remain on historical Closed / Closed - Complete rows that lack Issued and Finaled timestamps in DATA.

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_ca_sample.parquet`
- Jurisdiction: **Fontana, CA** (n=1,999)
- Script: `agent/scripts/data_repair_ca_fontana.py` (`data_repair`)
- Artifact: `AGENT_DATA_PATH/fontana_repaired_sample.parquet`

## DATA schemas (`INFERRED_SCHEMA`)

| Schema | n | Description |
| --- | ---: | --- |
| `permit_info_search_data` | 1,234 | Open-data / GIS feed: `permit_info`, `search_data`, `inspections`, `fees`, `site_info`, `contacts` |
| `legacy_portal` | 765 | Accela Citizen Access: `date`, `status`, `tasks`, `inspections`, `search_data`, `fees_details`, … |

## Field assessment

### STATUS_NORMALIZED

**Before:** Final 1,433 · Active 304 · Inactive 188 · In Review 73 · missing 1

Issues:
1. **1 `permit_info` row** with empty `PermitStatus` but `PermitIssuedDate` present (and null `STATUS_ORIGINAL`) → **Active**.
2. **2 `legacy_portal` rows** with `DATA.status = Closed - Complete` but `STATUS_NORMALIZED = Active` (stale `STATUS_ORIGINAL = issued`). Both have Final Inspection Complete / Permit Final inspections → **Final**.

Otherwise existing status maps already match portal labels (`FINALED`/`CLOSED`→Final, `ISSUED`/`ACT`/`APPROVED`→Active, `RECEIVED`/`PAID`/`PND`→In Review, `EXPIRED`/`VOID`/`CANCELLED`/`INA`→Inactive; legacy `Closed - Complete`/`Issued`/`Permit Expired`/etc. likewise).

VOID rows that carry `PermitFinaledDate` stay **Inactive** (that date is a close/void stamp, not a completion).

**After:** Final 1,435 · Active 303 · Inactive 188 · In Review 73 · missing 0  
Flags: **FILLED 1 · FIXED 2**

### FILE_DATE

**Before:** 3 missing (99.8% populated).

- `permit_info`: existing `FILE_DATE` matches `PermitAppliedDate` on all 1,231 rows where Applied is present (0 mismatches).
- `legacy_portal`: existing `FILE_DATE` matches `DATA.date` on all 765 rows.
- The 3 gaps have empty `PermitAppliedDate` and no alternate application date in `search_data` → not fillable.

Flags: **FILLED 0 · FIXED 0** · missing 3 → 3

### PERMIT_DATE

**Before:** 975 missing. Active 82.2% / Final 49.3% populated.

`permit_info`:
- When present, `PERMIT_DATE` already equals `PermitIssuedDate` (919/919).
- **93 Active/Final** rows had empty Issued but populated `PermitApprovedDate` → **FILLED** from Approved.
- Remaining Active/Final gaps (~128) have neither Issued nor Approved in DATA.

`legacy_portal`:
- Canonical issuance is Permit Issuance task marked **Issued** (exact match; “Issued Send …” is signature routing, not used alone).
- **6 rows** had an incorrect `PERMIT_DATE` earlier than the Issued event (often equal to `FILE_DATE`) → **FIXED**.
- Most historical Active/Final rows have empty task event lists → no Issued date available (~559 still missing after repair among pre-fix Active/Final).

**After:** missing 882. Active 275/303 (90.8%) · Final 776/1,435 (54.1%).  
Flags: **FILLED 93 · FIXED 6**

### FINAL_DATE

**Before:** 904 missing; Final 75.0% populated; 20 Inactive (VOID) rows carried `FINAL_DATE` matching `PermitFinaledDate`.

`permit_info`:
- When present, `FINAL_DATE` already equals `PermitFinaledDate` (676/676).
- **9 Final** rows with empty Finaled but a passed Permit Final / Building Final inspection (`Type`/`Result`/`Completed`) → **FILLED**.
- **20 Inactive VOID** rows with Finaled timestamps → **FIXED** (cleared); status remains Inactive.
- ~192 Final (`CLOSED`/`FINALED`) still lack Finaled and a usable finaling inspection.

`legacy_portal`:
- Existing finals match Inspection / Final Inspection Complete (or Final CO Issued) when present.
- **~47 Final** rows missing `FINAL_DATE` filled from Final Inspection Complete / Final CO / passed Permit Final inspection (combined with the 2 status remaps).
- ~112 Closed - Complete rows still have no finaling signal in tasks or inspections.

**After:** Final 1,131/1,435 (78.8%) have `FINAL_DATE`; Active / In Review / Inactive have 0.  
Flags: **FILLED 56 · FIXED 20**

## Repair performance (sample)

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 1 | 2 | 1 → 0 |
| FILE_DATE | 0 | 0 | 3 → 3 |
| PERMIT_DATE | 93 | 6 | 975 → 882 |
| FINAL_DATE | 56 | 20 | 904 → 868 |

Ideal coverage after repair:
- `FILE_DATE`: 1,996 / 1,999 (99.8%)
- `PERMIT_DATE` on Active/Final: 1,051 / 1,738 (60.5%)
- `FINAL_DATE` on Final: 1,131 / 1,435 (78.8%)

Residual PERMIT/FINAL gaps are concentrated in older converted records whose DATA JSON has empty issuance/finaling fields and sparse or empty workflow/inspection history — not recoverable without an external source.
